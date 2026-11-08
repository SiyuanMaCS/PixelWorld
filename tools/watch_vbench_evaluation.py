#!/usr/bin/env python3
"""Wait for complete cohorts, export once, then run pinned standard evaluation.

This is an evaluator-side service. It neither launches agents nor repairs or
selects generated candidates. Run with the official GPU evaluator environment.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pixelworld.config import load_config
from pixelworld.util import atomic_json, utc_now
from prepare_vbench_i2v import DEFAULT_SOURCE, load_official_metadata
from prepare_vbench_submission import collect_runs, prepare


def step(config, source: Path, input_proof: Path, output: Path, states: dict) -> dict:
    rows = load_official_metadata(source / "vbench2_beta_i2v/vbench2_i2v_full_info.json")
    indices = list(range(len(rows)))
    status_path = config.runs_root / "status.json"
    generation = json.loads(status_path.read_text()) if status_path.exists() else {}
    for model in config.models:
        for track in model.tracks:
            key = f"{model.key}/{track}"
            previous = states.get(key, {})
            if previous.get("phase") in ("complete", "failed"):
                continue
            entry = {"model": model.key, "track": track, "scope": "standard1118x5", "official_full_score": False}
            try:
                # Progress is only a cheap waiting hint. Never use these counts
                # as submission evidence: a potentially ready cohort is fully
                # re-read and validated below before any model is loaded.
                counts = generation.get("groups", {}).get(key, {}).get("counts")
                if counts is not None and counts.get("complete", 0) < len(rows)*5:
                    entry.update(accepted_samples=counts.get("complete", 0), expected_samples=len(rows)*5,
                                 pending_or_failed=len(rows)*5-counts.get("complete", 0),
                                 exhausted_samples=counts.get("exhausted", 0), phase="waiting_for_generation",
                                 generation_status_utc=generation.get("updated_utc"),
                                 authoritative_submission_check="pending_complete_cohort")
                    states[key] = entry
                    continue
                records, missing = collect_runs(config, model, track, indices)
                entry.update(accepted_samples=len(records), expected_samples=len(rows)*5,
                             pending_or_failed=len(missing),
                             exhausted_samples=sum(item['state'] == 'exhausted' for item in missing),
                             phase="waiting_for_generation")
                if not missing:
                    cohort = output / model.key / track
                    manifest = cohort / "submission.json"
                    result = prepare(config, model.key, track, source, input_proof, manifest)
                    atomic_json(cohort / "submission_report.json", result)
                    entry.update(phase="original_standard_evaluation", result_dir=str(cohort / "scores"))
                    states[key] = entry
                    atomic_json(output / "scheduler.json", {"updated_utc": utc_now(), "cohorts": states, "pid": os.getpid()})
                    scores = cohort / "scores"
                    # Preserve existing results; verify phase on service restart.
                    provenance_path = scores / "evaluation_provenance.json"
                    if provenance_path.exists():
                        provenance = json.loads(provenance_path.read_text())
                        if (provenance.get("scope") != "standard" or provenance.get("status") != "complete"
                                or not (scores / "official_aggregate_score.json").is_file()):
                            raise ValueError("Prior evaluation incomplete; inspect rather than silently rescore")
                    else:
                        cmd = [sys.executable, str(Path(__file__).with_name("evaluate_vbench_i2v.py")),
                               "--source", str(source), "--manifest", str(manifest),
                               "--generation-root", str(config.runs_root), "--output", str(scores),
                               "--scope", "standard", "--ratio", "16-9"]
                        with (cohort / "original_eval.log").open("wb") as log:
                            code = subprocess.call(cmd, stdout=log, stderr=subprocess.STDOUT)
                        if code:
                            raise RuntimeError(f"Original evaluation exited {code}; original_eval.log retained")
                    score = json.loads((scores / "official_aggregate_score.json").read_text())
                    if score.get("scope") != "full-official-i2v-suite":
                        raise ValueError("Full aggregate provenance absent")
                    entry.update(phase="complete", official_full_score=True, aggregate=score)
            except Exception as exc:
                entry.update(phase="failed", error_type=type(exc).__name__, error=str(exc), official_full_score=False)
            states[key] = entry
    atomic_json(output / "scheduler.json", {"updated_utc": utc_now(), "cohorts": states, "pid": os.getpid()})
    return states


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    p.add_argument("--input-provenance", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--interval", type=float, default=60)
    p.add_argument("--max-hours", type=float, default=24*14)
    p.add_argument("--once", action="store_true")
    a = p.parse_args()
    config = load_config(a.config)
    output = a.output.resolve()
    if output.is_relative_to(config.runs_root.resolve()) or a.interval < 1 or a.max_hours <= 0:
        raise ValueError("Evaluator-side directory and positive bounded watch interval required")
    output.mkdir(parents=True, exist_ok=True)
    lock = (output / "scheduler.lock").open("a+")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    states_path = output / "scheduler.json"
    states = json.loads(states_path.read_text())["cohorts"] if states_path.exists() else {}
    deadline = time.monotonic() + a.max_hours*3600
    while time.monotonic() < deadline and not (output / "STOP").exists():
        states = step(config, a.source.resolve(), a.input_provenance.resolve(), output, states)
        if a.once or all(item.get("phase") in ("complete", "failed") for item in states.values()):
            break
        time.sleep(a.interval)


if __name__ == "__main__":
    main()
