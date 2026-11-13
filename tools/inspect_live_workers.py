"""Inspect live PixelWorld run-case workers.

Read-only by default. With --kill-stale, only terminates workers that have a
parsed case path and match the explicit stale predicates. This also reports
orphaned codex and snapshot child processes under the PixelWorld run root,
because killed run-case parents can leave detached helpers alive.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import time


CONFIG_TO_GENERATION = {
    "physics_missing_full.json": "physics_iq",
    "physics_gpt_native_v2_full.json": "physics_iq_gpt_native_v2",
    "physics_iq_512w24fps_gpt_native_full.json": "physics_iq_512w24fps_gpt_native",
    "physics_seed21_native_v2_full.json": "physics_iq_seed21_native_v2",
    "robojudge_full_baseline100k.json": "robojudge",
    "robojudge_seed21_native_v2_full.json": "robojudge_seed21_native_v2",
    "vbench2_subset_full.json": "vbench2_subset_full",
    "phygenbench_full.json": "phygenbench_full",
    "pcve_smoke.json": "pcve_smoke",
    "pcve_full.json": "pcve_smoke",
}


def _arg(tokens: list[str], flag: str) -> str | None:
    try:
        return tokens[tokens.index(flag) + 1]
    except (ValueError, IndexError):
        return None


def _ps_rows() -> list[tuple[int, int, str, str, str]]:
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
        if parts[0] == "PID":
            continue
        rows.append((int(parts[0]), int(parts[1]), parts[2], parts[3], parts[4]))
    return rows


def _run_case_rows() -> list[tuple[int, int, str, str, str]]:
    rows = []
    for pid, ppid, stat, elapsed, command in _ps_rows():
        try:
            tokens = shlex.split(command)
        except ValueError:
            continue
        if "-m" not in tokens:
            continue
        module_index = tokens.index("-m")
        if tokens[module_index:module_index + 3] != ["-m", "pixelworld.cli", "run-case"]:
            continue
        rows.append((pid, ppid, stat, elapsed, command))
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


def _event_reason(age: float | None, event_type: str | None, message: str,
                  prefix: str = "") -> str:
    if age is None:
        return ""
    lowered = message.lower()
    if age > 900 and (
        "connection failed" in lowered
        or "reconnecting" in lowered
        or "network retry" in lowered
    ):
        return f"{prefix}network retry >900s"
    if age > 2400 and event_type not in {"turn.completed", "turn.failed", "turn.cancelled"}:
        return f"{prefix}{event_type or 'event'} >2400s"
    return ""


def _codex_orphan_workers(run_root: Path, now: float) -> list[dict]:
    workers = []
    generation_root = (run_root / "generations").resolve()
    for pid, ppid, stat, elapsed, command in _ps_rows():
        if ppid != 1 or "codex --ask-for-approval never exec" not in command:
            continue
        if str(generation_root) not in command:
            continue
        try:
            tokens = shlex.split(command)
        except ValueError:
            continue
        workspace = _arg(tokens, "-C")
        if not workspace:
            continue
        try:
            relative = Path(workspace).resolve().relative_to(generation_root)
        except (OSError, ValueError):
            continue
        if len(relative.parts) < 5:
            continue
        bench, model, track, run_name = relative.parts[:4]
        match = re.match(r"^case_(?P<case>.+)_attempt_(?P<attempt>\d+)$", run_name)
        case_id = match.group("case") if match else None
        attempt = str(int(match.group("attempt"))) if match else None
        event_path = generation_root / bench / model / track / run_name / "logs" / "events.jsonl"
        age = None
        event_type = None
        message = ""
        reason = ""
        if not event_path.exists():
            reason = "orphan codex no events"
        else:
            age = now - event_path.stat().st_mtime
            event_type, message = _last_json_event(event_path)
            reason = _event_reason(age, event_type, message, prefix="orphan codex ")
        workers.append({
            "kind": "orphan-codex",
            "pid": pid,
            "ppid": ppid,
            "stat": stat,
            "elapsed": elapsed,
            "bench": bench,
            "model": model,
            "track": track,
            "case": case_id,
            "attempt": attempt,
            "event_age_s": round(age, 1) if age is not None else None,
            "last_type": event_type,
            "reason": reason,
            "event_path": str(event_path.relative_to(run_root)) if event_path.exists() else None,
        })
    return workers


def _snapshot_orphan_workers(run_root: Path) -> list[dict]:
    workers = []
    generation_root = (run_root / "generations").resolve()
    for pid, ppid, stat, elapsed, command in _ps_rows():
        if ppid != 1 or "-m pixelworld.snapshot" not in command:
            continue
        if str(generation_root) not in command:
            continue
        try:
            tokens = shlex.split(command)
        except ValueError:
            continue
        workspace = _arg(tokens, "--workspace")
        stop_file = _arg(tokens, "--stop-file")
        if not workspace:
            continue
        try:
            relative = Path(workspace).resolve().relative_to(generation_root)
        except (OSError, ValueError):
            continue
        if len(relative.parts) < 4:
            continue
        bench, model, track, run_name = relative.parts[:4]
        match = re.match(r"^case_(?P<case>.+)_attempt_(?P<attempt>\d+)$", run_name)
        workers.append({
            "kind": "orphan-snapshot",
            "pid": pid,
            "ppid": ppid,
            "stat": stat,
            "elapsed": elapsed,
            "bench": bench,
            "model": model,
            "track": track,
            "case": match.group("case") if match else None,
            "attempt": str(int(match.group("attempt"))) if match else None,
            "event_age_s": None,
            "last_type": None,
            "reason": "orphan snapshot detached",
            "event_path": None,
            "stop_file": str(Path(stop_file).resolve().relative_to(run_root)) if stop_file else None,
            "stop_file_exists": Path(stop_file).exists() if stop_file else None,
        })
    return workers


def inspect_workers(run_root: Path) -> list[dict]:
    now = time.time()
    workers = []
    for pid, ppid, stat, elapsed, command in _run_case_rows():
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
                reason = _event_reason(age, event_type, message)
        workers.append({
            "kind": "run-case",
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
    workers.extend(_codex_orphan_workers(run_root, now))
    workers.extend(_snapshot_orphan_workers(run_root))
    return workers


def _is_killable(worker: dict) -> bool:
    reason = worker["reason"]
    return (
        reason == "network retry >900s"
        or reason.endswith("network retry >900s")
        or reason.endswith(" >2400s")
        or reason == "orphan snapshot detached"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", type=Path, default=Path("runs/bench_codex_20261109"))
    parser.add_argument("--kill-stale", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    run_root = args.run_root.resolve()
    workers = inspect_workers(run_root)
    killable = [worker for worker in workers if _is_killable(worker)]
    if args.kill_stale:
        for worker in killable:
            try:
                os.kill(worker["pid"], signal.SIGTERM)
                worker["terminated"] = True
            except ProcessLookupError:
                worker["terminated"] = False

    payload = {
        "run_cases": sum(1 for worker in workers if worker["kind"] == "run-case"),
        "orphan_codex": sum(1 for worker in workers if worker["kind"] == "orphan-codex"),
        "orphan_snapshot": sum(1 for worker in workers if worker["kind"] == "orphan-snapshot"),
        "killable_stale": len(killable),
        "unparsed_or_missing": sum(
            1 for worker in workers
            if worker["kind"] == "run-case" and worker["reason"] in {"unparsed command", "no events"}
        ),
        "orphan_unparsed_or_missing": sum(
            1 for worker in workers
            if worker["kind"] == "orphan-codex" and worker["reason"] == "orphan codex no events"
        ),
        "counts": {
            "/".join(str(part) for part in key): value
            for key, value in sorted(Counter(
                (worker["bench"], worker["model"], worker["track"])
                for worker in workers
                if worker["kind"] == "run-case"
            ).items(), key=lambda item: tuple(str(part) for part in item[0]))
        },
        "orphan_counts": {
            "/".join(str(part) for part in key): value
            for key, value in sorted(Counter(
                (worker["bench"], worker["model"], worker["track"])
                for worker in workers
                if worker["kind"] == "orphan-codex"
            ).items(), key=lambda item: tuple(str(part) for part in item[0]))
        },
        "orphan_snapshot_counts": {
            "/".join(str(part) for part in key): value
            for key, value in sorted(Counter(
                (worker["bench"], worker["model"], worker["track"])
                for worker in workers
                if worker["kind"] == "orphan-snapshot"
            ).items(), key=lambda item: tuple(str(part) for part in item[0]))
        },
        "unparsed_or_missing_workers": [
            worker for worker in workers
            if worker["kind"] == "run-case" and worker["reason"] in {"unparsed command", "no events"}
        ],
        "orphan_unparsed_or_missing_workers": [
            worker for worker in workers
            if worker["kind"] == "orphan-codex" and worker["reason"] == "orphan codex no events"
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
