"""Quarantine retryable infrastructure failures so cases can be requeued.

This does not mark outputs as successful. It preserves failed attempt folders
under _quarantine and lets the matrix supervisor launch a fresh attempt.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
import shutil
import time


GENERATION_ROOTS = (
    "physics_iq",
    "physics_iq_gpt_native_v2",
    "physics_iq_seed21_native_v2",
    "robojudge",
    "robojudge_seed21_native_v2",
    "pcve_smoke",
    "vbench2_subset_full",
    "phygenbench_full",
)


def parse_utc(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = dt.datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def is_provider_infra_failure(case_dir: Path, manifest: dict) -> bool:
    if manifest.get("status") != "failed":
        return False
    if manifest.get("stop_reason") in {"provider_queue_exceeded", "provider_connection_failed"}:
        return True
    events = case_dir / "logs" / "events.jsonl"
    try:
        text = events.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return (
        "request queue size is exceed" in text
        or "Code 4050" in text
        or '"code": 4050' in text
        or "429 Too Many Requests" in text
        or "exceeded retry limit, last status: 429" in text
        or "Connection failed: error sending request" in text
        or "Missing environment variable: `PIXELWORLD_MUX_KEY`" in text
        or "Missing environment variable: `PIXELWORLD_API_KEY`" in text
        or "Invalid value at 'contents" in text
        or "Invalid JSON payload received" in text
    )


def iter_case_dirs(generations: Path):
    for root_name in GENERATION_ROOTS:
        root = generations / root_name
        if not root.is_dir():
            continue
        for model_dir in root.iterdir():
            if not model_dir.is_dir() or model_dir.name.startswith("_"):
                continue
            for track_dir in model_dir.iterdir():
                if not track_dir.is_dir():
                    continue
                for case_dir in track_dir.iterdir():
                    if case_dir.is_dir() and case_dir.name.startswith("case_"):
                        yield root_name, case_dir


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", type=Path, default=Path("runs/bench_codex_20261109"))
    parser.add_argument("--root-name", action="append",
                        help="Limit to one generation root; may be passed multiple times.")
    parser.add_argument("--since-utc")
    parser.add_argument("--until-utc")
    parser.add_argument("--tag", default=None)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    run_root = args.run_root.resolve()
    generations = run_root / "generations"
    allowed_roots = set(args.root_name or GENERATION_ROOTS)
    since, until = parse_utc(args.since_utc), parse_utc(args.until_utc)
    matches = []
    for root_name, case_dir in iter_case_dirs(generations):
        if root_name not in allowed_roots:
            continue
        manifest_path = case_dir / "run_manifest.json"
        if not manifest_path.exists():
            continue
        try:
            manifest = json.loads(manifest_path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        completed = parse_utc(manifest.get("completed_utc"))
        if since and (completed is None or completed < since):
            continue
        if until and (completed is None or completed > until):
            continue
        if not is_provider_infra_failure(case_dir, manifest):
            continue
        matches.append({
            "completed_utc": manifest.get("completed_utc"),
            "root": root_name,
            "model": manifest.get("model_key"),
            "track": manifest.get("track"),
            "case_id": manifest.get("case_id"),
            "attempt": manifest.get("attempt"),
            "path": str(case_dir),
        })

    moved = []
    quarantine = None
    if args.apply and matches:
        tag = args.tag or time.strftime("provider_queue_%Y%m%dT%H%M%SZ", time.gmtime())
        quarantine = run_root / "_quarantine" / tag
        quarantine.mkdir(parents=True, exist_ok=True)
        for item in matches:
            source = Path(item["path"])
            relative = source.relative_to(generations)
            target = quarantine / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            suffix = 1
            original_target = target
            while target.exists():
                target = original_target.with_name(f"{original_target.name}.dup{suffix}")
                suffix += 1
            shutil.move(str(source), str(target))
            moved.append({**item, "to": str(target)})
        (quarantine / "audit.json").write_text(json.dumps({
            "reason": "Provider queue/connection failures are infrastructure failures; attempts moved so cases can retry.",
            "since_utc": since.isoformat() if since else None,
            "until_utc": until.isoformat() if until else None,
            "count": len(moved),
            "items": moved,
        }, indent=2, ensure_ascii=False))

    print(json.dumps({
        "apply": args.apply,
        "matches": len(matches),
        "moved": len(moved),
        "quarantine": str(quarantine) if quarantine else None,
        "items": moved if args.apply else matches,
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
