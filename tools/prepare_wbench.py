#!/usr/bin/env python3
"""Prepare a single WBench turn; advance ONLY from validated PixelWorld RGB.

Infrastructure metadata stays outside the three-file generation input directory.
No evaluator annotations, masks, reference media or previous GT are exported.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
from pathlib import Path
import re
import shutil

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor/wbench-eval-night"
CODE_REVISION = "edc4e80e642baac4f2b5764dec9f1a491200af8f"
DATA_REVISION = "16b560d77afaa51ed127eaf4fe81d9340289dd6a"
SCOPE_HASH = "5cb5d028bd91a7f3c0e307cd0e93805b4707fb9d97c76b2d9e1f1ad9e690ca5e"
PROMPT_HASH = "b5243f25ae5f85d7809b1dc8b24eadcd3aa9ec524571d9ab883b42d52f82badd"
JUDGE = "doubao-seed-2-0-lite-260215"
SMOKE_IMAGE_SHA256 = "af0fa129b52f66072acf6fca559cbce4eed97f901f8b8b8aeb95576ae7fe98d7"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def safe_id(value) -> str:
    value = str(value)
    if not re.fullmatch(r"[A-Za-z0-9_]+", value):
        raise ValueError("Unsafe case identity")
    return value


def contained(root: Path, relative: str) -> Path:
    p = Path(relative)
    if p.is_absolute() or ".." in p.parts or "\\" in relative:
        raise ValueError("Unsafe source path")
    result = (root / p).resolve()
    if not result.is_relative_to(root.resolve()):
        raise ValueError("Source symlink escapes input root")
    return result


def load_cases(data: Path) -> dict[str, dict]:
    paths = sorted((data / "cases").glob("case_*.json"))
    digest = hashlib.sha256()
    rows = {}
    for path in paths:
        digest.update(path.name.encode() + b"\0" + bytes.fromhex(sha256(path)))
        row = read_json(path)
        cid = safe_id(row["id"])
        if cid in rows or path.name != f"case_{cid}.json":
            raise ValueError("Duplicate/misnamed official case")
        turns = row["interactions"]
        if [x["turn"] for x in turns] != list(range(1, len(turns) + 1)):
            raise ValueError("Official turn order is not contiguous")
        rows[cid] = row
    if len(rows) != 289 or sum(len(x["interactions"]) for x in rows.values()) != 1058:
        raise ValueError("Requires pinned Full 289 cases / 1058 turns")
    if digest.hexdigest() != SCOPE_HASH:
        raise ValueError("Official case bytes changed; explicit protocol repin required")
    return rows


def turn_prompt(case: dict, turn: int, source: Path = VENDOR / "source") -> str:
    path = source / "src/models/text/prompt_builder.py"
    if sha256(path) != PROMPT_HASH:
        raise ValueError("Pinned upstream prompt builder changed")
    namespace = {}
    exec(compile(ast.parse(path.read_text()), str(path), "exec"), namespace)
    # Kling/Wan override _build_turn_prompt without setting is_first_turn.
    # Preserve that exact released behavior, not an invented richer prompt.
    return namespace["build_turn_prompt"](
        case, case["interactions"][turn - 1],
        perspective=case["settings"]["perspective"],
    )


def media_spec(benchmark: str, width: int, height: int, frames: int, fps: float) -> dict:
    if any(type(v) is not int or v < 1 for v in (width, height, frames)) or frames < 2:
        raise ValueError("Invalid RGB dimensions/frame count")
    if not math.isfinite(fps) or not 0 < fps <= 240:
        raise ValueError("Invalid FPS")
    return dict(benchmark=benchmark, task_type="i2v", width=width, height=height,
                frames=frames, fps=fps, audio=None)


def isolated(output: Path, provenance: Path) -> None:
    if provenance.resolve().is_relative_to(output.resolve()):
        raise ValueError("Provenance/evaluator metadata must remain outside generation inputs")
    if output.exists() or provenance.exists():
        raise FileExistsError("Refusing to overwrite inputs/provenance")


def prepare_turn(case: dict, turn: int, output: Path, provenance: Path,
                 data: Path = VENDOR / "data", source: Path = VENDOR / "source",
                 width: int = 256, frames: int = 20, fps: float = 4,
                 previous_run: Path | None = None, previous_provenance: Path | None = None) -> dict:
    isolated(output, provenance)
    if type(turn) is not int or not 1 <= turn <= len(case["interactions"]):
        raise ValueError("Turn outside official case")
    cid = safe_id(case["id"])
    feedback = None
    if turn == 1:
        if previous_run or previous_provenance:
            raise ValueError("First turn must use official initial image")
        image_path = contained(data, case["settings"]["initial_image"])
        with Image.open(image_path) as im:
            image = im.convert("RGB")
            original_size = image.size
            if type(width) is not int or width < 1:
                raise ValueError("Invalid target width")
            image = image.resize((width, max(1, round(image.height * width / image.width))), Image.Resampling.LANCZOS)
        source_hash = sha256(image_path)
        if cid == "1" and source_hash != SMOKE_IMAGE_SHA256:
            raise ValueError("Pinned official smoke initial image changed")
    else:
        if previous_run is None or previous_provenance is None:
            raise ValueError("Continuation requires previous validated PixelWorld run AND provenance")
        from evaluate_wbench import load_rgb
        previous = read_json(previous_provenance)
        if (previous.get("benchmark"), previous.get("case_id"), previous.get("turn")) != ("wbench", cid, turn - 1):
            raise ValueError("Wrong preceding case/turn")
        if previous.get("code_revision") != CODE_REVISION or previous.get("dataset_revision") != DATA_REVISION or previous.get("prompt") != turn_prompt(case, turn - 1, source):
            raise ValueError("Previous turn was not prepared from pinned official protocol")
        rgb, spec, manifest = load_rgb(previous_run, previous)
        if (frames, fps) != (spec["frames"], spec["fps"]):
            raise ValueError("Do not silently change continuation timing")
        image = Image.fromarray(rgb[-1])
        if width != image.width:
            raise ValueError("Do not resize previous generated feedback")
        original_size = image.size
        source_hash = hashlib.sha256(rgb[-1].tobytes()).hexdigest()
        feedback = {"kind": "previous_pixelworld_last_rgb_frame", "previous_provenance_sha256": sha256(previous_provenance),
                    "previous_run_manifest_sha256": sha256(previous_run / "run_manifest.json"),
                    "last_rgb_sha256": source_hash}
    spec = media_spec("wbench", image.width, image.height, frames, fps)
    prompt = turn_prompt(case, turn, source)
    spec.update(turn=turn, action=case["interactions"][turn - 1]["action"])
    output.mkdir(parents=True)
    try:
        image.save(output / "first_frame.png")
        (output / "prompt.txt").write_text(prompt, encoding="utf-8")
        write_json(output / "task_spec.json", spec)
        record = dict(benchmark="wbench", setting="Full", scope="single_turn_smoke", case_id=cid,
                      turn=turn, official_turns=len(case["interactions"]), code_revision=CODE_REVISION,
                      dataset_revision=DATA_REVISION, case_sha256=sha256(data / "cases" / f"case_{cid}.json"),
                      prompt_strategy="released_kling_wan_build_turn_prompt_default_is_first_turn_false",
                      prompt=prompt, media=spec, original_size=original_size, source_image_sha256=source_hash,
                      input_image_sha256=sha256(output / "first_frame.png"),
                      input_prompt_sha256=sha256(output / "prompt.txt"), feedback=feedback,
                      conditioning="initial official still at turn 1; previous PixelWorld last RGB thereafter; action only")
        provenance.parent.mkdir(parents=True, exist_ok=True)
        write_json(provenance, record)
        return record
    except Exception:
        shutil.rmtree(output)
        raise


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data", type=Path, default=VENDOR / "data")
    p.add_argument("--source", type=Path, default=VENDOR / "source")
    p.add_argument("--case-id", required=True)
    p.add_argument("--turn", type=int, default=1)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--provenance", type=Path, required=True)
    p.add_argument("--previous-run", type=Path)
    p.add_argument("--previous-provenance", type=Path)
    p.add_argument("--width", type=int, default=256)
    p.add_argument("--frames", type=int, default=20)
    p.add_argument("--fps", type=float, default=4)
    a = p.parse_args()
    case = load_cases(a.data)[safe_id(a.case_id)]
    result = prepare_turn(case, a.turn, a.output, a.provenance, a.data, a.source,
                          a.width, a.frames, a.fps, a.previous_run, a.previous_provenance)
    print(json.dumps({"input_ready": True, "benchmark": "wbench", "case_id": result["case_id"],
                      "turn": result["turn"], "output": str(a.output), "formal_score_ready": False}))


if __name__ == "__main__":
    main()
