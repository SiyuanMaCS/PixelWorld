#!/usr/bin/env python3
"""Export one official WorldScore I2V segment, never reference/mask/eval data."""
from __future__ import annotations

import argparse
import ast
import hashlib
from pathlib import Path
import shutil
import json

from PIL import Image
from prepare_wbench import sha256, read_json, write_json, contained, isolated, media_spec

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor/worldscore-eval-night"
CODE_REVISION = "096c75fc4ada9c7d92e03140c3c1f0c8f383b61f"
DATA_REVISION = "42c4e267e1cc0529af1b0284ce018e04d43906e3"
METADATA_HASHES = {"static": "3024a3a07c0854433bd520086a090898f5f1f8a2360fd5012496cdf6da16fcda",
                   "dynamic": "5bb873f68ab9e907145b9c3aac2f09200e962f623472f999814c339beb857f2e"}
UTILS_HASH = "74a43eb4304c18ecbd5437ccfc35c842a44f20dfb5b07782cd687252fa16736e"


def load_metadata(data: Path, split: str) -> list[dict]:
    if split not in METADATA_HASHES:
        raise ValueError("Static and Dynamic must be selected explicitly")
    path = data / split / f"{split}.json"
    if sha256(path) != METADATA_HASHES[split]:
        raise ValueError("Official WorldScore metadata changed; repin required")
    rows = read_json(path)
    if len(rows) != {"static": 2000, "dynamic": 1000}[split] or len({r["image"] for r in rows}) != len(rows):
        raise ValueError("Full split requires every unique official entry")
    if any(r["visual_movement"] != split for r in rows):
        raise ValueError("Mixed split metadata")
    return rows


def official_functions(source: Path = VENDOR / "source") -> dict:
    path = source / "worldscore/benchmark/utils/utils.py"
    if sha256(path) != UTILS_HASH:
        raise ValueError("Pinned WorldScore prompt/crop source changed")
    # Extract pure source functions, avoiding evaluator imports/model downloads.
    selected = []
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "layout_info" for t in node.targets):
            selected.append(node)
        if isinstance(node, ast.FunctionDef) and node.name in {"generate_prompt_from_list", "get_scene_num", "center_crop"}:
            selected.append(node)
    namespace = {"Image": Image}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


def generation_prompts(row: dict, source: Path = VENDOR / "source") -> list[str]:
    static = row["visual_movement"] == "static"
    prompts = row["prompt_list"] if static else [row["prompt"]]
    # Exactly dataloader.generate_prompt_list, including its punctuation behavior.
    styled = [p + (" " if p.endswith(".") else ". ") + row["style"] for p in prompts]
    return official_functions(source)["generate_prompt_from_list"](styled, row["camera_path"], static=static)


def case_identity(row: dict) -> str:
    image = Path(row["image"].removeprefix("./"))
    if image.is_absolute() or ".." in image.parts or "\\" in str(image):
        raise ValueError("Unsafe image identity")
    if row["visual_movement"] == "static":
        return "/".join(["static", row["visual_style"], row["scene_type"], image.parent.name, image.stem])
    return "/".join(["dynamic", row["visual_style"], row["motion_type"], image.stem])


def prepare_segment(row: dict, index: int, turn: int, output: Path, provenance: Path,
                    data: Path = VENDOR / "data/WorldScore-Dataset", source: Path = VENDOR / "source",
                    width: int = 256, height: int = 144, frames: int = 50, fps: float = 10,
                    previous_run: Path | None = None, previous_provenance: Path | None = None) -> dict:
    isolated(output, provenance)
    funcs = official_functions(source)
    segments = funcs["get_scene_num"](row["camera_path"])
    prompts = generation_prompts(row, source)
    if len(prompts) != segments or not 1 <= turn <= segments:
        raise ValueError("Incomplete official camera/prompt sequence")
    spec = media_spec("worldscore", width, height, frames, fps)
    spec.update(turn=turn, action=row["camera_path"][turn - 1])
    cid = case_identity(row)
    feedback = None
    original_size = None
    image = None
    image_path = contained(data, row["image"])
    if turn == 1:
        if previous_run or previous_provenance:
            raise ValueError("Segment one must use official still")
        with Image.open(image_path) as im:
            original_size = im.size
        source_hash = sha256(image_path)
    else:
        if previous_run is None or previous_provenance is None:
            raise ValueError("Requires previous validated PixelWorld last RGB, not GT/new scene image")
        from evaluate_wbench import load_rgb
        prev = read_json(previous_provenance)
        if (prev.get("benchmark"), prev.get("case_id"), prev.get("turn")) != ("worldscore", cid, turn - 1):
            raise ValueError("Wrong previous scene/segment")
        if prev.get("code_revision") != CODE_REVISION or prev.get("dataset_revision") != DATA_REVISION or prev.get("prompt") != prompts[turn - 2]:
            raise ValueError("Previous segment was not prepared from pinned official protocol")
        rgb, old_spec, _ = load_rgb(previous_run, prev)
        if any(old_spec[k] != spec[k] for k in ("width", "height", "frames", "fps")):
            raise ValueError("Continuation media changed")
        image = Image.fromarray(rgb[-1])
        source_hash = hashlib.sha256(rgb[-1].tobytes()).hexdigest()
        feedback = {"kind": "previous_pixelworld_last_rgb_frame", "last_rgb_sha256": source_hash,
                    "previous_provenance_sha256": sha256(previous_provenance),
                    "previous_run_manifest_sha256": sha256(previous_run / "run_manifest.json")}
    output.mkdir(parents=True)
    try:
        if turn == 1:
            # Execute exact upstream center_crop incl. PIL's default resize filter.
            funcs["center_crop"](str(image_path), (width, height), str(output))
            (output / "input_image.png").rename(output / "first_frame.png")
        else:
            image.save(output / "first_frame.png")
        (output / "prompt.txt").write_text(prompts[turn - 1], encoding="utf-8")
        write_json(output / "task_spec.json", spec)
        record = {"benchmark": "worldscore", "split": row["visual_movement"], "case_id": cid,
                  "metadata_index": index, "turn": turn, "official_segments": segments,
                  "code_revision": CODE_REVISION, "dataset_revision": DATA_REVISION,
                  "metadata_sha256": METADATA_HASHES[row["visual_movement"]],
                  "prompt": prompts[turn - 1], "prompt_strategy": "official_videogen_i2v",
                  "media": spec, "original_size": original_size, "source_image_sha256": source_hash,
                  "input_image_sha256": sha256(output / "first_frame.png"),
                  "input_prompt_sha256": sha256(output / "prompt.txt"), "feedback": feedback,
                  "complete_case_frames": segments * (frames - 1) + 1,
                  "scope": "single_segment_smoke_not_official_full_score",
                  "conditioning": "center-cropped official still then generated last RGB; official camera text and target scene prompt only"}
        provenance.parent.mkdir(parents=True, exist_ok=True)
        write_json(provenance, record)
        return record
    except Exception:
        shutil.rmtree(output)
        raise


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data", type=Path, default=VENDOR / "data/WorldScore-Dataset")
    p.add_argument("--source", type=Path, default=VENDOR / "source")
    p.add_argument("--split", choices=["static", "dynamic"], required=True)
    p.add_argument("--index", type=int, default=0)
    p.add_argument("--turn", type=int, default=1)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--provenance", type=Path, required=True)
    p.add_argument("--previous-run", type=Path)
    p.add_argument("--previous-provenance", type=Path)
    p.add_argument("--width", type=int, default=256)
    p.add_argument("--height", type=int, default=144)
    p.add_argument("--frames", type=int, default=50)
    p.add_argument("--fps", type=float, default=10)
    a = p.parse_args()
    rows = load_metadata(a.data, a.split)
    if not 0 <= a.index < len(rows):
        raise ValueError("Official index out of range")
    result = prepare_segment(rows[a.index], a.index, a.turn, a.output, a.provenance,
                             a.data, a.source, a.width, a.height, a.frames, a.fps,
                             a.previous_run, a.previous_provenance)
    print(json.dumps({"input_ready": True, "benchmark": "worldscore", "case_id": result["case_id"],
                      "turn": a.turn, "official_segments": result["official_segments"],
                      "output": str(a.output), "formal_score_ready": False}))


if __name__ == "__main__":
    main()
