from __future__ import annotations

from collections import Counter
from pathlib import Path
import json
import os
import signal
import subprocess
import sys
import time

from .config import Benchmark, Model
from .runner import run_path
from .util import atomic_json, utc_now


def case_ids(config: Benchmark) -> list[str]:
    if config.case_ids:
        return list(config.case_ids)
    manifest = config.inputs_root.parent / "manifest.json"
    values = json.loads(manifest.read_text())
    identifiers = [value["id"] for value in values["cases"]]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("Duplicate case IDs in input manifest")
    return identifiers


def configurations(config: Benchmark) -> list[tuple[Model, str]]:
    return [(model, track) for model in config.models for track in model.tracks]


def _pid_alive(path: Path) -> bool:
    try:
        os.kill(int(path.read_text().strip()), 0)
        return True
    except (FileNotFoundError, ValueError, ProcessLookupError, PermissionError):
        return False


def inspect(config: Benchmark, model: Model, track: str, case_id: str) -> dict:
    stale = 0
    failed = 0
    for attempt in range(1, config.max_attempts + 1):
        run = run_path(config, model, track, case_id, attempt)
        manifest_path = run / "run_manifest.json"
        if not run.exists():
            return {"state": "pending", "attempt": attempt, "run": str(run)}
        try:
            manifest = json.loads(manifest_path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            if _pid_alive(run / "logs" / "supervisor.pid"):
                return {"state": "running", "attempt": attempt, "run": str(run)}
            stale += 1
            continue
        if manifest.get("status") == "complete" and manifest.get("validation", {}).get("pass"):
            return {"state": "complete", "attempt": attempt, "run": str(run),
                    "duration_seconds": manifest.get("duration_seconds"),
                    "completed_utc": manifest.get("completed_utc")}
        if manifest.get("status") == "running" and _pid_alive(run / "logs" / "supervisor.pid"):
            return {"state": "running", "attempt": attempt, "run": str(run)}
        if manifest.get("status") == "failed":
            failed += 1
        else:
            stale += 1
    return {"state": "exhausted", "attempt": config.max_attempts, "run": str(run),
            "failed_attempts": failed, "stale_attempts": stale}


def snapshot(config: Benchmark, supervisor_pid: int | None = None) -> tuple[dict, dict]:
    identifiers = case_ids(config)
    info = {}
    totals = Counter()
    groups = {}
    for model, track in configurations(config):
        key = f"{model.key}/{track}"
        counts = Counter()
        running, exhausted, durations, completed = [], [], [], []
        for case_id in identifiers:
            item = inspect(config, model, track, case_id)
            info[(model.key, track, case_id)] = item
            counts[item["state"]] += 1
            totals[item["state"]] += 1
            if item["state"] == "running":
                running.append(case_id)
            elif item["state"] == "exhausted":
                exhausted.append(case_id)
            if item.get("duration_seconds") is not None:
                durations.append(item["duration_seconds"])
            if item.get("completed_utc"):
                completed.append((item["completed_utc"], case_id))
        groups[key] = {
            "model_key": model.key,
            "model": model.model,
            "track": track,
            "counts": dict(counts),
            "running_cases": running,
            "exhausted_cases": exhausted,
            "mean_duration_seconds": sum(durations) / len(durations) if durations else None,
            "latest_completion": max(completed) if completed else None,
        }
    status = {
        "protocol": config.protocol,
        "updated_utc": utc_now(),
        "supervisor_pid": supervisor_pid,
        "cases": len(identifiers),
        "configurations": len(configurations(config)),
        "total_runs": len(identifiers) * len(configurations(config)),
        "totals": dict(totals),
        "groups": groups,
    }
    return status, info


def _launch(config: Benchmark, model: Model, track: str, case_id: str, attempt: int) -> int:
    log_root = config.runs_root / "_supervisor"
    log_root.mkdir(parents=True, exist_ok=True)
    log = (log_root / f"{model.key}__{track}__{case_id}__a{attempt:02d}.log").open("ab")
    command = [
        sys.executable, "-m", "pixelworld.cli", "run-case",
        "--config", str(config.source), "--model", model.key,
        "--track", track, "--case", case_id, "--attempt", str(attempt),
    ]
    process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                               start_new_session=True, close_fds=True)
    return process.pid


def run(config: Benchmark, interval: float = 5.0) -> None:
    config.runs_root.mkdir(parents=True, exist_ok=True)
    stop = config.runs_root / "STOP"
    stop.unlink(missing_ok=True)
    group_order = {key: index for index, key in enumerate(
        (f"{model.key}/{track}" for model, track in configurations(config)))}
    while not stop.exists():
        status, info = snapshot(config, os.getpid())
        atomic_json(config.runs_root / "status.json", status)
        if status["totals"].get("exhausted", 0):
            raise RuntimeError("One or more tasks exhausted all attempts; inspect status.json")
        if status["totals"].get("complete", 0) == status["total_runs"]:
            break
        running_total = status["totals"].get("running", 0)
        capacity = config.max_concurrency - running_total
        if capacity > 0:
            candidates = []
            for model, track in configurations(config):
                key = f"{model.key}/{track}"
                group_running = status["groups"][key]["counts"].get("running", 0)
                available = config.max_per_config - group_running
                if available <= 0:
                    continue
                pending = [(case_id, info[(model.key, track, case_id)])
                           for case_id in case_ids(config)
                           if info[(model.key, track, case_id)]["state"] == "pending"]
                for case_id, item in pending[:available]:
                    fairness = status["groups"][key]["counts"].get("complete", 0)
                    candidates.append((fairness, group_order[key], int(case_id), model, track, case_id, item))
            candidates.sort(key=lambda item: item[:3])
            for _, _, _, model, track, case_id, item in candidates[:capacity]:
                _launch(config, model, track, case_id, item["attempt"])
        time.sleep(interval)
    final, _ = snapshot(config, os.getpid())
    atomic_json(config.runs_root / "status.json", final)


def stop(config: Benchmark) -> None:
    config.runs_root.mkdir(parents=True, exist_ok=True)
    (config.runs_root / "STOP").touch()
