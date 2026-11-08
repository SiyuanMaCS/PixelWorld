#!/usr/bin/env python3
"""Export only official VBench++ I2V initial images and verbatim prompts.

No videos, reference continuations, evaluator models, dimensions or scores are
copied into the generation input folders. Provenance stays with infrastructure.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil

from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_COMMIT = "fd18b3d055cb0fc6f066ca90fe2c3c8cbb698490"
METADATA_SHA256 = "8cf4d34dc11779a336c216a1a71d482927cfa24a1bf736ab5c92425609f129f8"
DEFAULT_SOURCE = REPO_ROOT / "vendor/vbench-i2v-night/source"
DIMENSION_COUNTS = {
    "i2v_subject": 246,
    "i2v_background": 109,
    "camera_motion": 763,
    "subject_consistency": 246,
    "background_consistency": 109,
    "motion_smoothness": 246,
    "dynamic_degree": 246,
    "aesthetic_quality": 355,
    "imaging_quality": 355,
    "temporal_flickering": 355,
}
DIMENSIONS = tuple(DIMENSION_COUNTS)
RATIOS = ("1-1", "8-5", "7-4", "16-9")
SAMPLES_PER_PAIR = 5


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_official_metadata(path: Path) -> list[dict]:
    if sha256(path) != METADATA_SHA256:
        raise ValueError("Metadata does not match the pinned official I2V suite")
    rows = json.loads(path.read_text())
    if len(rows) != 1118 or len({r["image_name"] for r in rows}) != 355:
        raise ValueError("Official suite size changed; an explicit repin is required")
    for row in rows:
        for key in ("image_name", "prompt_en"):
            value = row[key]
            if not value or Path(value).name != value or "\\" in value or "\x00" in value:
                raise ValueError(f"Unsafe {key} in official metadata")
    return rows


def select_indices(rows: list[dict], indices: list[int]) -> list[int]:
    if not indices or len(indices) != len(set(indices)):
        raise ValueError("Select nonempty, unique official pair indices")
    if any(i < 0 or i >= len(rows) for i in indices):
        raise ValueError("Official pair index out of range")
    return indices


def prepare_inputs(
    rows: list[dict], indices: list[int], image_root: Path, output: Path,
    provenance: Path, ratio: str, width: int | None = None,
    fps: float = 4, frames: int = 20,
) -> dict:
    """Copy/re-encode selected still images only; never open any video file."""
    if ratio not in RATIOS or (width is not None and width <= 0) or fps <= 0 or frames < 2:
        raise ValueError("Invalid ratio or output media settings")
    select_indices(rows, indices)
    output = output.resolve()
    if provenance.resolve().is_relative_to(output):
        raise ValueError("Evaluator provenance must remain outside generation inputs")
    if output.exists() or provenance.exists():
        raise FileExistsError("Refusing to overwrite inputs or provenance")
    # Validate every selected image before creating any generation input.
    sources = []
    for index in indices:
        image_name = rows[index]["image_name"]
        if Path(image_name).name != image_name or "\\" in image_name:
            raise ValueError("Unsafe image name")
        source = (image_root / image_name).resolve()
        if not source.is_relative_to(image_root.resolve()):
            raise ValueError("Image symlink escapes the official image root")
        with Image.open(source) as image:
            image.verify()
        sources.append(source)
    records = []
    output.mkdir(parents=True)
    try:
        for index, source in zip(indices, sources):
            row = rows[index]
            case = output / f"{index:04d}"
            case.mkdir()
            with Image.open(source) as image:
                image = image.convert("RGB")
                original_size = image.size
                if width is not None:
                    image = image.resize(
                        (width, round(image.height * width / image.width)),
                        Image.Resampling.LANCZOS,
                    )
                image.save(case / "first_frame.png")
                w, h = image.size
            (case / "prompt.txt").write_text(row["prompt_en"], encoding="utf-8")
            spec = {
                "benchmark": "vbench-i2v", "task_type": "i2v", "width": w,
                "height": h, "frames": frames, "fps": fps, "audio": None,
            }
            (case / "task_spec.json").write_text(json.dumps(spec, indent=2) + "\n")
            records.append({
                "pair_index": index, "case_id": f"{index:04d}",
                "image_name": row["image_name"], "prompt_en": row["prompt_en"],
                "source_image_sha256": sha256(source),
                "initial_image_sha256": sha256(case / "first_frame.png"),
                "original_size": original_size, "media": spec,
            })
        result = {
            "benchmark": "VBench++ I2V", "source_commit": SOURCE_COMMIT,
            "metadata_sha256": METADATA_SHA256, "ratio": ratio,
            "official_pairs_total": len(rows), "samples_per_pair": SAMPLES_PER_PAIR,
            "conditioning": "official initial still image + verbatim prompt only",
            "resized": width is not None, "cases": records,
        }
        provenance.parent.mkdir(parents=True, exist_ok=True)
        provenance.write_text(json.dumps(result, indent=2) + "\n")
    except Exception:
        shutil.rmtree(output)
        raise
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--image-root", type=Path, help="Official crop/<ratio> folder")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--provenance", type=Path, required=True)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--indices", type=int, nargs="+")
    selection.add_argument("--all", action="store_true", help="All 1,118 pairs, not just three I2V dimensions")
    parser.add_argument("--ratio", choices=RATIOS, default="16-9")
    parser.add_argument("--width", type=int, help="Explicit generation resize; evaluator still uses official crop")
    parser.add_argument("--fps", type=float, default=4)
    parser.add_argument("--frames", type=int, default=20)
    args = parser.parse_args()
    rows = load_official_metadata(args.source / "vbench2_beta_i2v/vbench2_i2v_full_info.json")
    indices = list(range(len(rows))) if args.all else args.indices
    image_root = args.image_root or args.source / "vbench2_beta_i2v/data/crop" / args.ratio
    result = prepare_inputs(rows, indices, image_root, args.output, args.provenance,
                            args.ratio, args.width, args.fps, args.frames)
    print(json.dumps({"prepared_pairs": len(result["cases"]), "samples_per_pair": 5}))


if __name__ == "__main__":
    main()
