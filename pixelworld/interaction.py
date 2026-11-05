"""Sequential I2V with only the preceding generated last frame as history."""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import shutil

from .config import Benchmark
from .media import contract
from .runner import run_case, run_path
from .util import atomic_json, sha256, utc_now


def run_sequence(config: Benchmark, model_key: str, track: str, episode: str) -> dict:
    source = config.inputs_root / episode
    plan = json.loads((source / "interactions.json").read_text())
    spec = contract(source)
    if spec["task_type"] != "i2v" or not plan:
        raise ValueError("Sequence requires an initial image and nonempty interactions")
    sequence = config.runs_root / model_key / track / f"sequence_{episode}"
    sequence.mkdir(parents=True, exist_ok=False)
    # Not mounted in the agent workspace. Future interactions are never passed.
    shutil.copy2(source / "interactions.json", sequence / "interactions.json")
    inputs = sequence / "turn_inputs"
    per_turn = replace(config, inputs_root=inputs)
    current = source / "first_frame.png"
    record = {"status": "running", "episode": episode, "started_utc": utc_now(),
              "conditioning": "previous generated final frame only; fresh agent each turn",
              "turns": []}
    atomic_json(sequence / "sequence_manifest.json", record)
    for index, item in enumerate(plan):
        case_id = f"{episode}_turn_{index+1:02d}"
        folder = inputs / case_id
        folder.mkdir(parents=True)
        shutil.copy2(current, folder / "first_frame.png")
        (folder / "prompt.txt").write_text(item["prompt"])
        atomic_json(folder / "task_spec.json", spec | {"turn": index+1, "action": item["action"]})
        value = run_case(per_turn, model_key, track, case_id)
        run = run_path(per_turn, config.model(model_key), track, case_id, 1)
        record["turns"].append({"turn": index+1, "case_id": case_id, "run": str(run),
                                "action": item["action"], "prompt": item["prompt"],
                                "input_sha256": sha256(current), "status": value["status"]})
        if value["status"] != "complete":
            record.update(status="failed", completed_utc=utc_now())
            atomic_json(sequence / "sequence_manifest.json", record)
            return record
        current = run / "workspace" / "frames" / f"{spec['frames']-1:02d}.png"
        record["turns"][-1]["last_frame_sha256"] = sha256(current)
        atomic_json(sequence / "sequence_manifest.json", record)
    record.update(status="complete", completed_utc=utc_now())
    atomic_json(sequence / "sequence_manifest.json", record)
    return record
