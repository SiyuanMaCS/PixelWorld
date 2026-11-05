"""Read-only usage export from Codex/TRAE JSONL run logs; no API calls."""
from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
import statistics


FIELDS = ("input_tokens", "cached_input_tokens", "cache_creation_input_tokens",
          "output_tokens", "reasoning_output_tokens")


def read_usage(path: Path) -> dict:
    # Reuse the runner's accounting so retrospective exports cannot drift.
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from pixelworld.usage import collect_usage
    value = collect_usage(path)
    return {key: value[key] for key in (*FIELDS, "usage_events", "malformed_jsonl_lines")}


def scan(root: Path, case_id: str | None = None, path_contains: str | None = None):
    for directory, dirs, files in os.walk(root, followlinks=False):
        # Run workspaces, image frames and ephemeral homes can be huge. Once
        # a manifest is found, read only its associated events and stop descent.
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", ".venv")]
        if "run_manifest.json" not in files:
            continue
        dirs[:] = []
        run = Path(directory)
        relative = str(run.relative_to(root))
        if path_contains and path_contains not in relative:
            continue
        try:
            manifest = json.loads((run / "run_manifest.json").read_text())
        except (OSError, json.JSONDecodeError):
            continue
        case = str(manifest.get("case_id", manifest.get("case_id_external", "")))
        if case_id is not None and case != case_id:
            continue
        yield {
            "run": relative,
            "model": manifest.get("model", "unknown"),
            "track": manifest.get("track") or "legacy-unspecified",
            "case_id": case,
            "status": manifest.get("status", "unknown"),
            "duration_seconds": manifest.get("duration_seconds"),
            **read_usage(run / "logs" / "events.jsonl"),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case-id")
    parser.add_argument("--path-contains")
    args = parser.parse_args()
    if not args.runs_root.is_dir():
        parser.error("--runs-root must be an existing run directory")
    rows = sorted(scan(args.runs_root, args.case_id, args.path_contains),
                  key=lambda r: (r["model"], r["track"], r["case_id"], r["run"]))
    args.output.mkdir(parents=True, exist_ok=True)
    columns = ("run", "model", "track", "case_id", "status", "duration_seconds",
               *FIELDS, "usage_events", "malformed_jsonl_lines")
    with (args.output / "per_run.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    groups = []
    for model, track in sorted({(r["model"], r["track"]) for r in rows}):
        selected = [r for r in rows if (r["model"], r["track"]) == (model, track)]
        complete = [r for r in selected if r["status"] == "complete"]
        known = [r["output_tokens"] for r in complete if r["output_tokens"] is not None]
        groups.append({
            "model": model, "track": track, "run_count": len(selected),
            "complete_count": len(complete), "complete_with_output_usage": len(known),
            "complete_missing_output_usage": len(complete) - len(known),
            "complete_output_tokens_sum": sum(known) if known else None,
            "complete_output_tokens_mean": statistics.mean(known) if known else None,
            "complete_output_tokens_median": statistics.median(known) if known else None,
            "all_recorded_output_tokens_sum": (sum(r["output_tokens"] for r in selected
                                                    if r["output_tokens"] is not None)
                                                if any(r["output_tokens"] is not None for r in selected) else None),
        })
    report = {
        "run_count": len(rows), "groups": groups,
        "accounting": "API-reported terminal-turn usage summed per run. Output and reasoning fields are preserved separately; do not add them without verifying provider semantics. Missing usage is not zero. No USD estimate or token-budget enforcement.",
    }
    (args.output / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
