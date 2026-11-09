"""Inspect live PixelWorld run-case workers.

Read-only by default. With --kill-stale, only terminates workers that have a
parsed case path and match the explicit stale predicates.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import time


CONFIG_TO_GENERATION = {
    "physics_missing_full.json": "physics_iq",
    "physics_gpt_native_v2_full.json": "physics_iq_gpt_native_v2",
    "physics_seed21_native_v2_full.json": "physics_iq_seed21_native_v2",
    "robojudge_full_baseline100k.json": "robojudge",
    "robojudge_seed21_native_v2_full.json": "robojudge_seed21_native_v2",
    "vbench2_subset_full.json": "vbench2_subset_full",
    "phygenbench_full.json": "phygenbench_full",
}


def _arg(tokens: list[str], flag: str) -> str | None:
    try:
        return tokens[tokens.index(flag) + 1]
    except (ValueError, IndexError):
        return None


def _process_rows() -> list[tuple[int, int, str, str, str]]:
    result = subprocess.run(
        ["ps", "-eo", "pid,ppid,stat,etime,cmd"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    rows = []
    for line in result.stdout.splitlines():
        parts = line.strip().split(None, 4)
        if len(parts) < 5:
            continue
        try:
            tokens = shlex.split(parts[4])
        except ValueError:
            continue
        if "-m" not in tokens:
            continue
        module_index = tokens.index("-m")
        if tokens[module_index:module_index + 3] != ["-m", "pixelworld.cli", "run-case"]:
            continue
        rows.append((int(parts[0]), int(parts[1]), parts[2], parts[3], parts[4]))
    return rows


def _last_json_event(path: Path) -> tuple[str | None, str]:
    with path.open("rb") as handle:
        handle.seek(0, 2)
        size = handle.tell()
        handle.seek(max(0, size - 65536))
        lines = handle.readlines()
    last = ""
    for line in lines:
        if line.strip():
            last = line.decode("utf-8", "ignore")
    try:
        event = json.loads(last)
    except json.JSONDecodeError:
        return None, last
    event_type = event.get("type") or event.get("event") or event.get("name")
    message = event.get("message") or event.get("msg") or str(event)
    return event_type, message


def inspect_workers(run_root: Path) -> list[dict]:
    now = time.time()
    workers = []
    for pid, ppid, stat, elapsed, command in _process_rows():
        tokens = shlex.split(command)
        config = _arg(tokens, "--config")
        model = _arg(tokens, "--model")
        track = _arg(tokens, "--track")
        case_id = _arg(tokens, "--case")
        attempt = _arg(tokens, "--attempt") or "1"
        generation = CONFIG_TO_GENERATION.get(Path(config).name if config else "")
        age = None
        event_type = None
        message = ""
        reason = ""
        event_path = None
        if not (generation and model and track and case_id):
            reason = "unparsed command"
        else:
            try:
                attempt_num = int(attempt)
            except ValueError:
                attempt_num = 1
            event_path = (
                run_root / "generations" / generation / model / track
                / f"case_{case_id}_attempt_{attempt_num:02d}" / "logs" / "events.jsonl"
            )
            if not event_path.exists():
                reason = "no events"
            else:
                age = now - event_path.stat().st_mtime
                event_type, message = _last_json_event(event_path)
                lowered = message.lower()
                if age > 900 and (
                    "connection failed" in lowered
                    or "reconnecting" in lowered
                    or "network retry" in lowered
                ):
                    reason = "network retry >900s"
                elif age > 2400 and event_type == "turn.started":
                    reason = "turn.started >2400s"
        workers.append({
            "pid": pid,
            "ppid": ppid,
            "stat": stat,
            "elapsed": elapsed,
            "bench": generation,
            "model": model,
            "track": track,
            "case": case_id,
            "attempt": attempt,
            "event_age_s": round(age, 1) if age is not None else None,
            "last_type": event_type,
            "reason": reason,
            "event_path": str(event_path.relative_to(run_root)) if event_path else None,
        })
    return workers


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", type=Path, default=Path("runs/bench_codex_20261109"))
    parser.add_argument("--kill-stale", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    run_root = args.run_root.resolve()
    workers = inspect_workers(run_root)
    killable = [worker for worker in workers if worker["reason"] in {
        "network retry >900s",
        "turn.started >2400s",
    }]
    if args.kill_stale:
        for worker in killable:
            try:
                os.kill(worker["pid"], signal.SIGTERM)
                worker["terminated"] = True
            except ProcessLookupError:
                worker["terminated"] = False

    payload = {
        "run_cases": len(workers),
        "killable_stale": len(killable),
        "unparsed_or_missing": sum(
            1 for worker in workers
            if worker["reason"] in {"unparsed command", "no events"}
        ),
        "counts": {
            "/".join(str(part) for part in key): value
            for key, value in sorted(Counter(
                (worker["bench"], worker["model"], worker["track"])
                for worker in workers
            ).items(), key=lambda item: tuple(str(part) for part in item[0]))
        },
        "unparsed_or_missing_workers": [
            worker for worker in workers
            if worker["reason"] in {"unparsed command", "no events"}
        ],
        "stale": killable,
        "oldest": sorted(
            workers,
            key=lambda worker: -1 if worker["event_age_s"] is None else worker["event_age_s"],
            reverse=True,
        )[:12],
    }
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
