#!/usr/bin/env python3
"""Watch a generated benchmark cohort and record evaluation readiness.

This scheduler is intentionally conservative. It does not invent scores and it
does not treat partial generations as scored results. When no evaluator command
is configured, a complete cohort is marked with an explicit blocker so the
public monitor can show the true state.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pixelworld.config import load_config
from pixelworld.util import atomic_json, utc_now


TERMINAL = {"complete", "failed", "blocked_missing_evaluator_adapter"}


def group_counts(status: dict, model: str, track: str, expected: int) -> dict:
    group = status.get("groups", {}).get(f"{model}/{track}", {})
    counts = group.get("counts", {})
    complete = int(counts.get("complete", 0) or 0)
    running = int(counts.get("running", 0) or 0)
    exhausted = int(counts.get("exhausted", 0) or 0) + int(counts.get("failed", 0) or 0)
    pending = int(counts.get("pending", max(expected - complete - running - exhausted, 0)) or 0)
    latest = group.get("latest_completion")
    running_cases = group.get("running_cases") or []
    exhausted_cases = group.get("exhausted_cases") or []
    return {
        "complete": complete,
        "running": running,
        "pending": pending,
        "exhausted": exhausted,
        "latest_completion": latest,
        "running_cases": running_cases,
        "exhausted_cases": exhausted_cases,
    }


def render_command(template: str, *, config: Path, output: Path, model: str, track: str) -> list[str]:
    command = template.format(
        config=str(config),
        output=str(output),
        model=shlex.quote(model),
        track=shlex.quote(track),
    )
    return shlex.split(command)


def step(config_path: Path, output: Path, benchmark: str, evaluator_command: str | None,
         states: dict) -> dict:
    config = load_config(config_path)
    expected = len(config.case_ids or [])
    if expected <= 0:
        raise ValueError("Generic benchmark evaluation watcher requires explicit case_ids")
    status_path = config.runs_root / "status.json"
    generation = json.loads(status_path.read_text()) if status_path.exists() else {}
    for model in config.models:
        for track in model.tracks:
            key = f"{model.key}/{track}"
            previous = states.get(key, {})
            if previous.get("phase") in TERMINAL:
                # Keep terminal records stable unless generation is later repaired
                # enough to invalidate an incomplete-generation blocker.
                if previous.get("phase") != "failed":
                    continue
            counts = group_counts(generation, model.key, track, expected)
            entry = {
                "benchmark": benchmark,
                "model": model.key,
                "track": track,
                "expected_videos": expected,
                "accepted_videos": counts["complete"],
                "running_videos": counts["running"],
                "pending_videos": counts["pending"],
                "exhausted_videos": counts["exhausted"],
                "latest_completion": counts["latest_completion"],
                "running_cases": counts["running_cases"],
                "exhausted_cases": counts["exhausted_cases"][:10],
                "official_or_adapter_score": False,
                "generation_status_utc": generation.get("updated_utc"),
            }
            if counts["complete"] < expected:
                entry.update(
                    phase="waiting_for_generation",
                    blocker=None,
                    authoritative_submission_check="pending_complete_cohort",
                )
                states[key] = entry
                continue
            if counts["exhausted"]:
                entry.update(
                    phase="blocked_incomplete_generation",
                    blocker="Some cases are exhausted/failed; do not evaluate a partial cohort.",
                    authoritative_submission_check="complete_count_conflicts_with_exhausted",
                )
                states[key] = entry
                continue
            cohort = output / model.key / track
            cohort.mkdir(parents=True, exist_ok=True)
            if not evaluator_command:
                entry.update(
                    phase="blocked_missing_evaluator_adapter",
                    blocker=(
                        "No official/adapted evaluator command is configured for this benchmark. "
                        "Generation is complete, but scoring is not claimed."
                    ),
                    result_dir=str(cohort),
                )
                states[key] = entry
                continue
            try:
                evaluation_started = time.time()
                cmd = render_command(evaluator_command, config=config_path, output=cohort, model=model.key, track=track)
                entry.update(phase="adapter_evaluation", result_dir=str(cohort), command=cmd)
                states[key] = entry
                atomic_json(output / "scheduler.json", {"updated_utc": utc_now(), "cohorts": states, "pid": os.getpid()})
                with (cohort / "evaluation.log").open("ab") as log:
                    code = subprocess.call(cmd, stdout=log, stderr=subprocess.STDOUT)
                if code:
                    raise RuntimeError(f"Evaluator exited {code}; evaluation.log retained")
                summary = cohort / "summary.json"
                if not summary.is_file():
                    raise FileNotFoundError("Evaluator did not write summary.json")
                entry.update(phase="complete", official_or_adapter_score=True, summary=json.loads(summary.read_text()))
            except Exception as exc:
                entry.update(phase="failed", error_type=type(exc).__name__, error=str(exc),
                             official_or_adapter_score=False)
                prerequisites = cohort / 'prerequisites.json'
                # Filesystems can round mtime to a coarser clock than time.time.
                # The small tolerance accepts this invocation's fresh write,
                # while older watch iterations remain excluded.
                if prerequisites.is_file() and prerequisites.stat().st_mtime >= evaluation_started - 1:
                    detail = json.loads(prerequisites.read_text())
                    if str(detail.get('phase','')).startswith('blocked_'):
                        entry.update(phase='blocked_evaluation_prerequisites',
                                     blocker=detail, retryable=True)
            states[key] = entry
    atomic_json(output / "scheduler.json", {"updated_utc": utc_now(), "cohorts": states, "pid": os.getpid()})
    return states


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--benchmark", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--evaluator-command", default=None)
    parser.add_argument("--interval", type=float, default=60)
    parser.add_argument("--max-hours", type=float, default=24 * 14)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    config = load_config(args.config)
    output = args.output.resolve()
    if output.is_relative_to(config.runs_root.resolve()) or args.interval < 1 or args.max_hours <= 0:
        raise ValueError("Evaluator-side directory and positive bounded watch interval required")
    output.mkdir(parents=True, exist_ok=True)
    lock = (output / "scheduler.lock").open("a+")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    state_path = output / "scheduler.json"
    states = json.loads(state_path.read_text())["cohorts"] if state_path.exists() else {}
    deadline = time.monotonic() + args.max_hours * 3600
    while time.monotonic() < deadline and not (output / "STOP").exists():
        states = step(args.config.resolve(), output, args.benchmark, args.evaluator_command, states)
        if args.once or all(item.get("phase") in TERMINAL for item in states.values()):
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
