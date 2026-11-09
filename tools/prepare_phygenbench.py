#!/usr/bin/env python3
"""Prepare PhyGenBench text prompts for PixelWorld T2V generation."""
from __future__ import annotations
import argparse
import json
from pathlib import Path


SOURCE = Path("/mnt/bn/embodied-lf3/masiyuan/PhysFix-workspace/phygenbench/phygen_prompts.json")
REPORTING = {
    "Force": "Mechanics",
    "Light": "Optics",
    "Heat": "Thermal",
    "Physical Properties": "Material",
    "Chemical Properties": "Material",
}


def prepare(output: Path, provenance: Path, source: Path, smoke: bool,
            width: int, height: int, frames: int, fps: float) -> dict:
    rows = json.loads(source.read_text())
    if len(rows) != 160:
        raise ValueError("Expected the local PhyGenBench 160-prompt file")
    if output.exists() or provenance.exists():
        raise FileExistsError("Refusing to overwrite existing PhyGenBench inputs/provenance")
    output.mkdir(parents=True)
    selected = []
    if smoke:
        seen = set()
        for index, row in enumerate(rows):
            category = row["main_category"]
            if category not in seen:
                selected.append((index, row))
                seen.add(category)
            if len(seen) == len(REPORTING):
                break
    else:
        selected = list(enumerate(rows))
    records = []
    for index, row in selected:
        case_id = f"phygen_{index+1:03d}"
        case = output / case_id
        case.mkdir()
        (case / "prompt.txt").write_text(row["caption"], encoding="utf-8")
        spec = {"benchmark": "phygenbench", "task_type": "t2v",
                "width": width, "height": height, "frames": frames,
                "fps": fps, "audio": None}
        (case / "task_spec.json").write_text(json.dumps(spec, indent=2) + "\n")
        records.append({"id": case_id, "source_index": index,
                        "main_category": row["main_category"],
                        "reporting_dimension": REPORTING[row["main_category"]],
                        "physical_laws": row.get("physical_laws"),
                        "sub_category": row.get("sub_category"),
                        "caption": row["caption"], "media": spec})
    result = {"schema": "pixelworld-phygenbench-inputs-v1",
              "benchmark": "phygenbench", "source": str(source),
              "mode": "smoke" if smoke else "full_160", "cases": records}
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
