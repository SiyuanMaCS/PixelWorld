#!/usr/bin/env python3
"""Prepare VBench-2.0 selected-dimension T2V prompts for PixelWorld.

This copies only prompt text and a task_spec into generation inputs. Official
evaluation metadata, answers and judging prompts remain outside workspaces.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "vendor/vbench-i2v-night/source/VBench-2.0"
SELECTED = [
    "Mechanics",
    "Material",
    "Motion_Rationality",
    "Dynamic_Spatial_Relationship",
    "Instance_Preservation",
]


def load_dimension(source: Path, name: str) -> list[dict]:
    path = source / "prompts/meta_info" / f"{name}.json"
    rows = json.loads(path.read_text())
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"Empty VBench2 dimension: {name}")
    for row in rows:
        if row.get("dimension") != name or not row.get("prompt_en"):
            raise ValueError(f"Unexpected row in {path}")
    return rows


def prepare(output: Path, provenance: Path, source: Path, smoke: bool,
            width: int, height: int, frames: int, fps: float) -> dict:
    if output.exists() or provenance.exists():
        raise FileExistsError("Refusing to overwrite existing VBench2 inputs/provenance")
    output.mkdir(parents=True)
    records = []
    for dim in SELECTED:
        rows = load_dimension(source, dim)
        chosen = rows[:1] if smoke else rows
        for index, row in enumerate(chosen):
            case_id = f"{dim.lower()}_{index:04d}".replace("-", "_")
            case = output / case_id
            case.mkdir()
            (case / "prompt.txt").write_text(row["prompt_en"], encoding="utf-8")
            spec = {"benchmark": "vbench2_subset", "task_type": "t2v",
                    "width": width, "height": height, "frames": frames,
                    "fps": fps, "audio": None}
            (case / "task_spec.json").write_text(json.dumps(spec, indent=2) + "\n")
            records.append({"id": case_id, "dimension": dim, "prompt_en": row["prompt_en"],
                            "source_index": index, "media": spec})
    result = {"schema": "pixelworld-vbench2-subset-inputs-v1",
              "benchmark": "vbench2_subset", "source": str(source),
              "mode": "smoke" if smoke else "selected_full",
              "dimensions": SELECTED, "cases": records}
    provenance.parent.mkdir(parents=True, exist_ok=True)
    provenance.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--provenance", type=Path, required=True)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--width", type=int, default=256)
    parser.add_argument("--height", type=int, default=144)
    parser.add_argument("--frames", type=int, default=20)
    parser.add_argument("--fps", type=float, default=4)
    args = parser.parse_args()
    result = prepare(args.output.resolve(), args.provenance.resolve(),
                     args.source.resolve(), args.smoke, args.width,
                     args.height, args.frames, args.fps)
    print(json.dumps({"prepared": len(result["cases"]), "mode": result["mode"]}))


if __name__ == "__main__":
    main()
