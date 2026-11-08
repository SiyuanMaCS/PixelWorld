"""Persist API-reported token usage for each run, including failed attempts.

This module is stdlib-only so the experiment runner can use an identical copy.
It does not infer reasoning inclusion, estimate USD cost or call a model.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import time

SCHEMA_VERSION = 1
TOKEN_FIELDS = ("input_tokens", "cached_input_tokens", "cache_creation_input_tokens",
                "output_tokens", "reasoning_output_tokens", "total_tokens")
TERMINALS = {"turn.completed", "turn.failed", "turn.cancelled"}


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def collect_usage(events: Path, *, finished: bool = True) -> dict:
    totals = {key: None for key in TOKEN_FIELDS}
    counts = {key: 0 for key in TOKEN_FIELDS}
    raw = []
    terminal_count = malformed = 0
    if events.is_file():
        with events.open(encoding="utf-8", errors="replace") as source:
            for line in source:
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                    if not isinstance(event, dict):
                        raise ValueError("non-object event")
                except (ValueError, json.JSONDecodeError):
                    malformed += 1
                    continue
                if event.get("type") not in TERMINALS:
                    continue
                terminal_count += 1
                usage = event.get("usage")
                if not isinstance(usage, dict):
                    continue
                raw.append({"terminal_type": event["type"], "usage": usage})
                for key in TOKEN_FIELDS:
                    value = usage.get(key)
                    if key == "cache_creation_input_tokens" and value is None:
                        value = usage.get("cache_write_input_tokens")
                    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                        totals[key] = (totals[key] or 0) + value
                        counts[key] += 1
    for key in TOKEN_FIELDS:
        if not terminal_count or counts[key] != terminal_count:
            totals[key] = None
    if not finished:
        state = "pending"
    elif not raw:
        state = "missing"
    elif totals["input_tokens"] is None or totals["output_tokens"] is None:
        state = "partial"
    else:
        state = "recorded"
    stat = events.stat() if events.is_file() else None
    return {
        "schema_version": SCHEMA_VERSION, "status": state, **totals,
        "source": "logs/events.jsonl terminal-turn API usage",
        "terminal_events": terminal_count, "usage_events": len(raw),
        "malformed_jsonl_lines": malformed,
        "raw_turn_usages": raw,
        "source_size_bytes": stat.st_size if stat else None,
        "source_mtime_ns": stat.st_mtime_ns if stat else None,
        "reasoning_inclusion": "provider-reported; not assumed or added to output_tokens",
    }


def preserve_completed_request_bound(usage: dict, budget: dict | None) -> dict:
    """Retain exposed counters on any interruption without inventing final usage."""
    if usage.get('status')=='recorded' or not budget:
        return usage
    total=budget.get('reported_output_tokens')
    prior=budget.get('prior_output_tokens',0)
    if isinstance(total,int) and not isinstance(total,bool):
        usage.update(status='partial',reported_completed_request_output_tokens=max(0,total-prior),
                     inflight_usage_unknown=True,
                     source_note='Completed request counter is a lower bound; interrupted request usage was not reported.')
    return usage


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def record_run(run: Path) -> bool:
    """Backfill terminal runs; never overwrite an active runner's manifest."""
    manifest_path = run / "run_manifest.json"
    manifest = read_json(manifest_path)
    if manifest.get("status") not in ("complete", "failed"):
        return False
    events = run / "logs/events.jsonl"
    sidecar = run / "logs/token_usage.json"
    prior = read_json(sidecar)
    budget = read_json(run/'logs/token_budget.json')
    known=budget.get('reported_output_tokens')
    expected_bound=max(0,known-budget.get('prior_output_tokens',0)) if isinstance(known,int) else None
    bound_current=(prior.get('status')=='recorded' or expected_bound is None or
                   prior.get('reported_completed_request_output_tokens')==expected_bound)
    stat = events.stat() if events.is_file() else None
    if (prior.get("schema_version") == SCHEMA_VERSION
            and prior.get("source_size_bytes") == (stat.st_size if stat else None)
            and prior.get("source_mtime_ns") == (stat.st_mtime_ns if stat else None)
            and manifest.get("token_usage") == prior and bound_current):
        return False
    usage = collect_usage(events)
    usage = preserve_completed_request_bound(usage, budget)
    if manifest.get('stop_reason') == 'output_token_budget_exhausted' and usage['status'] != 'recorded':
        try:
            budget = json.loads((run/'logs/token_budget.json').read_text())
            known = budget.get('reported_output_tokens')
            prior_output = budget.get('prior_output_tokens', 0)
            if isinstance(known, int):
                usage.update({'status': 'partial',
                              'reported_completed_request_output_tokens': max(0, known-prior_output),
                              'inflight_usage_unknown': True})
        except (OSError, ValueError):
            pass
    atomic_json(sidecar, usage)
    # Reload so other finalized metadata is preserved if a writer just finished.
    manifest = read_json(manifest_path)
    if manifest.get("status") not in ("complete", "failed"):
        return False
    manifest["token_usage"] = usage
    atomic_json(manifest_path, manifest)
    return True


def iter_runs(root: Path, path_contains: str | None = None):
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if d not in (".git", ".venv", "__pycache__")]
        if "run_manifest.json" in files:
            dirs[:] = []
            run = Path(directory)
            if not path_contains or path_contains in str(run.relative_to(root)):
                yield run


def backfill(root: Path, output: Path, path_contains: str | None = None) -> dict:
    rows = []
    updated = 0
    for run in iter_runs(root, path_contains):
        changed = record_run(run)
        updated += int(changed)
        manifest = read_json(run / "run_manifest.json")
        usage = manifest.get("token_usage") or {}
        rows.append({
            "run": str(run.relative_to(root)), "model": manifest.get("model"),
            "track": manifest.get("track"),
            "case_id": manifest.get("case_id", manifest.get("case_id_external")),
            "attempt": manifest.get("attempt", run.name),
            "run_status": manifest.get("status"),
            "usage_status": usage.get("status", "pending" if manifest.get("status") == "running" else "missing"),
            "duration_seconds": manifest.get("duration_seconds"),
            **{key: usage.get(key) for key in TOKEN_FIELDS},
        })
        if changed and updated % 100 == 0:
            print(json.dumps({"updated_manifests": updated, "scanned_runs": len(rows)}), flush=True)
    rows.sort(key=lambda r: (r["model"] or "", r["track"] or "", str(r["case_id"]), r["run"]))
    output.mkdir(parents=True, exist_ok=True)
    temporary = output / f"per_run.csv.tmp.{os.getpid()}"
    fields = ("run", "model", "track", "case_id", "attempt", "run_status", "usage_status",
              "duration_seconds", *TOKEN_FIELDS)
    with temporary.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(output / "per_run.csv")
    summary = {
        "updated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "runs": len(rows), "updated_manifests": updated,
        "recorded": sum(r["usage_status"] == "recorded" for r in rows),
        "partial": sum(r["usage_status"] == "partial" for r in rows),
        "missing": sum(r["usage_status"] == "missing" for r in rows),
        "pending": sum(r["usage_status"] == "pending" for r in rows),
        "scope": "One row per run/attempt; API fields preserved without reasoning double-counting or cost estimation.",
    }
    atomic_json(output / "summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--path-contains")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval", type=float, default=60)
    args = parser.parse_args()
    if not args.runs_root.is_dir() or args.interval <= 0:
        parser.error("Existing runs root and positive interval are required")
    args.output.mkdir(parents=True, exist_ok=True)
    lock = (args.output / "usage_recording.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if args.watch:
        (args.output / "watcher.pid").write_text(str(os.getpid()) + "\n")
    while not (args.output / "STOP_TOKEN_WATCH").exists():
        print(json.dumps(backfill(args.runs_root, args.output, args.path_contains)), flush=True)
        if not args.watch:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
