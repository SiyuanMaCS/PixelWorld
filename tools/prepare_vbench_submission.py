#!/usr/bin/env python3
"""Build an official-scope submission from completed independent PixelWorld runs.

No agent, generator program, baseline, or evaluator model is executed here.
Missing deliveries block export; failed attempts remain in the inventory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from pixelworld.config import load_config
from pixelworld.supervisor import inspect
from pixelworld.util import atomic_json, utc_now
from evaluate_vbench_i2v import requested_scope, validate_manifest, validate_source
from evaluate_wbench import export_video, load_rgb
from prepare_vbench_i2v import DEFAULT_SOURCE, METADATA_SHA256, SOURCE_COMMIT, load_official_metadata, sha256
from PIL import Image
import numpy as np


def collect_runs(config, model, track: str, indices: list[int]) -> tuple[list[dict], list[dict]]:
    """Use the supervisor's earliest accepted attempt, never score-based selection."""
    if track not in model.tracks:
        raise ValueError("Track is absent from this generation configuration")
    records, missing, sessions = [], [], set()
    for index in indices:
        for sample in range(5):
            cid = f"{index:04d}_s{sample}"
            state = inspect(config, model, track, cid)
            if state["state"] != "complete":
                missing.append({"case_id": cid, **state})
                continue
            run = Path(state["run"]).resolve()
            manifest = json.loads((run / "run_manifest.json").read_text())
            session = manifest.get("full_trace", {}).get("thread_id")
            try:
                uuid.UUID(session)
            except (ValueError, TypeError, AttributeError):
                raise ValueError(f"Missing independent session evidence: {cid}") from None
            if session in sessions:
                raise ValueError("Five samples must have independent generation sessions")
            sessions.add(session)
            if (manifest.get("model_key"), manifest.get("track"), manifest.get("case_id")) != (model.key, track, cid):
                raise ValueError("Run identity differs from cohort/sample")
            if not run.is_relative_to(config.runs_root.resolve()):
                raise ValueError("Run escapes generation root")
            records.append({"pair_index": index, "sample_index": sample, "run": run, "manifest": manifest})
    return records, missing


def load_input_proof(path: Path, source: Path, rows: list[dict], ratio: str) -> dict:
    proof = json.loads(path.read_text())
    if (proof.get("source_commit") != SOURCE_COMMIT or proof.get("metadata_sha256") != METADATA_SHA256
            or proof.get("ratio") != ratio or proof.get("official_pair_count") != len(rows)):
        raise ValueError("Initial-image provenance does not match pinned official scope")
    images = {item["image_name"]: item for item in proof["images"]}
    if len(images) != len(proof["images"]) or set(images) != {row["image_name"] for row in rows}:
        raise ValueError("Initial-image provenance is incomplete or duplicated")
    for name, item in images.items():
        if item.get("valid") is not True or sha256(source / "vbench2_beta_i2v/data/crop" / ratio / name) != item.get("sha256"):
            raise ValueError("Original official crop hash changed")
    return images


def export_record(record: dict, row: dict, source: Path, ratio: str,
                  generation_root: Path, export_root: Path) -> dict:
    run, manifest = record["run"], record["manifest"]
    spec = manifest["media_contract"]
    if spec.get("benchmark") not in ("vbench-i2v", "vbench_i2v"):
        raise ValueError("Submission is not a VBench-I2V run")
    original = source / "vbench2_beta_i2v/data/crop" / ratio / row["image_name"]
    # Reconstruct only deterministic input preprocessing, never a continuation.
    with Image.open(original) as image:
        expected = image.convert("RGB").resize((spec["width"], spec["height"]), Image.Resampling.LANCZOS)
        expected_rgb = np.asarray(expected)
    with Image.open(run / "input_snapshot/first_frame.png") as image:
        if not np.array_equal(np.asarray(image.convert("RGB")), expected_rgb):
            raise ValueError("Conditioning is not the declared resize of the official crop")
    # Preserve the legacy underscore alias in already validated inputs.
    provenance = {"benchmark": spec["benchmark"], "media": spec,
                  "input_image_sha256": manifest["input_image_sha256"],
                  "input_prompt_sha256": hashlib.sha256(row["prompt_en"].encode()).hexdigest(),
                  "prompt": row["prompt_en"]}
    rgb, spec, _ = load_rgb(run, provenance)
    name = f'{record["pair_index"]:04d}_s{record["sample_index"]}'
    video, receipt = export_root / f"{name}.mp4", export_root / f"{name}.json"
    run_hash = sha256(run / "run_manifest.json")
    rgb_hash = hashlib.sha256(rgb.tobytes()).hexdigest()
    if video.exists() or receipt.exists():
        if not video.is_file() or not receipt.is_file():
            raise ValueError("Interrupted export requires explicit diagnosis; no silent overwrite")
        saved = json.loads(receipt.read_text())
        if (saved.get("run_manifest_sha256") != run_hash or saved.get("rgb_sha256") != rgb_hash
                or saved.get("sha256") != sha256(video) or saved.get("rgb_roundtrip_exact") is not True):
            raise ValueError("Cached export differs from its validated submission")
    else:
        export_root.mkdir(parents=True, exist_ok=True)
        saved = export_video(rgb, spec["fps"], video)
        saved.update(run_manifest_sha256=run_hash, rgb_sha256=rgb_hash)
        atomic_json(receipt, saved)
    return {"pair_index": record["pair_index"], "sample_index": record["sample_index"],
            "image_name": row["image_name"], "prompt_en": row["prompt_en"],
            "path": str(video.relative_to(generation_root)), "sha256": saved["sha256"],
            "seed": None, "api_seed_status": "not_reported",
            "generation_session_id": manifest["full_trace"]["thread_id"],
            "run_manifest": str((run / "run_manifest.json").relative_to(generation_root)),
            "run_manifest_sha256": run_hash,
            "original_crop_sha256": sha256(original), "native_media": spec,
            "lossless_rgb_roundtrip": True}


def prepare(config, model_key: str, track: str, source: Path, input_proof: Path,
            output: Path, ratio: str = "16-9", scope: str = "standard", pair_index: int | None = None) -> dict:
    source, output = source.resolve(), output.resolve()
    generation_root = config.runs_root.resolve()
    if output.is_relative_to(generation_root) or source.is_relative_to(generation_root):
        raise ValueError("Evaluator source and manifest must remain outside generation")
    validate_source(source)
    rows = load_official_metadata(source / "vbench2_beta_i2v/vbench2_i2v_full_info.json")
    indices, _ = requested_scope(rows, scope, pair_index, None)
    model = config.model(model_key)
    records, missing = collect_runs(config, model, track, indices)
    report = {"updated_utc": utc_now(), "scope": scope, "model": model_key, "track": track,
              "expected_samples": len(indices) * 5, "accepted_samples": len(records),
              "missing": missing, "status": "waiting_for_generation" if missing else "preparing",
              "official_full_score": False}
    if missing:
        return report  # Do not export an incomplete subset as a full submission.
    load_input_proof(input_proof, source, rows, ratio)
    exports = generation_root / "_evaluation_exports" / model_key / track / ("standard" if scope == "standard" else f"smoke_{pair_index:04d}")
    artifacts = [export_record(item, rows[item["pair_index"]], source, ratio, generation_root, exports)
                 for item in records]
    manifest = {"producer": "PixelWorld", "benchmark": "VBench++ I2V", "source_commit": SOURCE_COMMIT,
                "metadata_sha256": METADATA_SHA256, "ratio": ratio, "scope": scope,
                "input_proof_sha256": sha256(input_proof), "artifacts": artifacts}
    validate_manifest(manifest, rows, indices, generation_root, ratio)
    if output.exists():
        if json.loads(output.read_text()) != manifest:
            raise ValueError("Existing submission differs; refusing to overwrite")
    else:
        atomic_json(output, manifest)
    report.update(status="ready_for_original_evaluation", manifest=str(output), manifest_sha256=sha256(output))
    return report


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--track", choices=["text", "vision-agent"], required=True)
    p.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    p.add_argument("--input-provenance", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--report", type=Path, required=True)
    p.add_argument("--ratio", default="16-9")
    p.add_argument("--scope", choices=["standard", "official-data-smoke"], default="standard")
    p.add_argument("--pair-index", type=int)
    a = p.parse_args()
    report = prepare(load_config(a.config), a.model, a.track, a.source, a.input_provenance, a.output,
                     a.ratio, a.scope, a.pair_index)
    if a.report.resolve().is_relative_to(load_config(a.config).runs_root.resolve()):
        raise ValueError("Submission report must remain outside generation")
    atomic_json(a.report, report)
    print(json.dumps({k: v for k, v in report.items() if k != "missing"}))


if __name__ == "__main__":
    main()
