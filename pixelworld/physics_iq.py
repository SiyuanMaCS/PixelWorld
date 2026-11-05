from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import csv
import json
import os
import shutil
import subprocess

import numpy as np
from huggingface_hub import hf_hub_download, snapshot_download
from huggingface_hub.errors import GatedRepoError
from PIL import Image

from .config import Benchmark
from .constants import (PHYSICS_IQ_COMMIT, PHYSICS_IQ_DATASET,
                        PHYSICS_IQ_DATASET_REVISION, PHYSICS_IQ_DESCRIPTIONS_SHA256,
                        PHYSICS_IQ_INPUTS, PHYSICS_IQ_REPO, REPO_ROOT)
from .supervisor import inspect
from .util import atomic_json, sha256, utc_now


PINNED_MANIFEST = REPO_ROOT / "data" / "physics_iq_verified_i2v.json"


def setup_upstream(path: Path) -> Path:
    path = path.resolve()
    if not (path / ".git").is_dir():
        path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--filter=blob:none", PHYSICS_IQ_REPO, str(path)], check=True)
    if subprocess.check_output(["git", "-C", str(path), "status", "--porcelain"], text=True).strip():
        raise RuntimeError(f"Refusing to modify dirty Physics-IQ checkout: {path}")
    subprocess.run(["git", "-C", str(path), "fetch", "origin", PHYSICS_IQ_COMMIT, "--depth", "1"], check=True)
    subprocess.run(["git", "-C", str(path), "checkout", "--detach", PHYSICS_IQ_COMMIT], check=True)
    actual = subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()
    if actual != PHYSICS_IQ_COMMIT:
        raise RuntimeError(f"Physics-IQ commit mismatch: {actual}")
    return path


def setup_inputs(inputs_root: Path, upstream: Path, cache_root: Path | None = None,
                 source_dir: Path | None = None) -> dict:
    upstream = setup_upstream(upstream)
    descriptions = upstream / "descriptions" / "best_practice" / "descriptions_base.csv"
    if sha256(descriptions) != PHYSICS_IQ_DESCRIPTIONS_SHA256:
        raise RuntimeError("Pinned Physics-IQ descriptions CSV hash mismatch")
    pinned = json.loads(PINNED_MANIFEST.read_text())
    cases = pinned["cases"]
    if len(cases) != PHYSICS_IQ_INPUTS:
        raise RuntimeError("Pinned I2V manifest must contain exactly 198 cases")
    prompts = {row["generated_video_name"][:4]: row for row in csv.DictReader(descriptions.open())
               if "_take-1_" in row["scenario"]}
    cache_root = (cache_root or inputs_root.parent / "allowed_source_switch_frames").resolve()
    inputs_root.mkdir(parents=True, exist_ok=True)

    def prepare(case: dict) -> dict:
        identifier = case["id"]
        source = source_dir / case["source_file"] if source_dir else None
        if source is None or not source.is_file():
            try:
                source = Path(hf_hub_download(
                    repo_id=PHYSICS_IQ_DATASET,
                    filename=case["source_file"],
                    repo_type="dataset",
                    revision=PHYSICS_IQ_DATASET_REVISION,
                    local_dir=cache_root,
                ))
            except GatedRepoError as error:
                raise RuntimeError(
                    "Physics-IQ Verified is gated. Run `hf auth login`, or pass "
                    "`--source-dir /path/to/physics-IQ-benchmark-verified`."
                ) from error
        if sha256(source) != case["source_sha256"]:
            raise RuntimeError(f"Source switch-frame hash mismatch: {identifier}")
        target = inputs_root / identifier
        target.mkdir(parents=True, exist_ok=True)
        with Image.open(source) as image:
            if image.width * 9 != image.height * 16:
                raise RuntimeError(f"Non-16:9 switch frame: {source}")
            resized = image.convert("RGB").resize((256, 144), Image.Resampling.BOX)
            if __import__("hashlib").sha256(resized.tobytes()).hexdigest() != case["resized_rgb_sha256"]:
                raise RuntimeError(f"Resized RGB hash mismatch: {identifier}")
            resized.save(target / "first_frame.png")
        prompt = prompts[identifier]["description"].strip()
        if __import__("hashlib").sha256(prompt.encode()).hexdigest() != case["prompt_sha256"]:
            raise RuntimeError(f"Prompt hash mismatch: {identifier}")
        (target / "prompt.txt").write_text(prompt + "\n")
        return {**case, "first_frame": f"inputs/{identifier}/first_frame.png",
                "prompt": f"inputs/{identifier}/prompt.txt",
                "first_frame_png_sha256": sha256(target / "first_frame.png")}

    with ThreadPoolExecutor(max_workers=8) as executor:
        records = list(executor.map(prepare, cases))
    payload = {
        "protocol": pinned["protocol"],
        "prepared_utc": utc_now(),
        "official_commit": PHYSICS_IQ_COMMIT,
        "dataset_repo": PHYSICS_IQ_DATASET,
        "dataset_revision": PHYSICS_IQ_DATASET_REVISION,
        "reference_or_mask_downloaded": False,
        "source_mode": "existing-directory" if source_dir else "pinned-huggingface-download",
        "count": len(records),
        "cases": records,
    }
    atomic_json(inputs_root.parent / "manifest.json", payload)
    return payload


def setup_evaluator(upstream: Path, benchmark_parent: Path, install: bool = True,
                    download_data: bool = True) -> dict:
    upstream = setup_upstream(upstream)
    if install:
        uv = shutil.which("uv")
        if not uv:
            raise RuntimeError("uv is required for the pinned official evaluator environment")
        subprocess.run([uv, "sync"], cwd=upstream, check=True)
    dataset = benchmark_parent / "physics-IQ-benchmark-verified"
    if download_data:
        dataset.parent.mkdir(parents=True, exist_ok=True)
        snapshot_download(repo_id=PHYSICS_IQ_DATASET, repo_type="dataset",
                          revision=PHYSICS_IQ_DATASET_REVISION, local_dir=dataset)
    elif not dataset.is_dir():
        raise FileNotFoundError(
            f"--no-download requires an existing official dataset at {dataset}")
    record = {
        "prepared_utc": utc_now(),
        "upstream": str(upstream),
        "upstream_commit": PHYSICS_IQ_COMMIT,
        "benchmark_parent": str(benchmark_parent.resolve()),
        "dataset": str(dataset.resolve()),
        "dataset_revision": PHYSICS_IQ_DATASET_REVISION,
        "installed": install,
        "downloaded": download_data,
    }
    atomic_json(benchmark_parent / "PIXELWORLD_EVALUATOR_READY.json", record)
    return record


def _ffmpeg() -> str:
    value = shutil.which("ffmpeg")
    if not value:
        raise RuntimeError("ffmpeg is required")
    return value


def export_videos(config: Benchmark, model_key: str, track: str, output: Path) -> Path:
    model = config.model(model_key)
    manifest = json.loads((config.inputs_root.parent / "manifest.json").read_text())
    cases = manifest["cases"]
    if len(cases) != PHYSICS_IQ_INPUTS:
        raise RuntimeError("Official evaluation requires all 198 cases")
    video_dir = output / f"pixelworld-{model.key}-{track}-bpp-run_01"
    video_dir.mkdir(parents=True, exist_ok=True)
    ffmpeg = _ffmpeg()

    def encode(case: dict) -> dict:
        info = inspect(config, model, track, case["id"])
        if info["state"] != "complete":
            raise RuntimeError(f"Incomplete case: {model.key}/{track}/{case['id']}")
        workspace = Path(info["run"]) / "workspace"
        frames = workspace / "frames"
        target = video_dir / case["generated_video_name"]
        subprocess.run([
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-framerate", "4", "-start_number", "0", "-i", str(frames / "%02d.png"),
            "-frames:v", "20", "-an", "-c:v", "libx264rgb", "-preset", "ultrafast",
            "-threads", "1", "-crf", "0", "-pix_fmt", "rgb24", "-r", "4", str(target),
        ], check=True)
        decoded = subprocess.run([
            ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(target),
            "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
        ], check=True, stdout=subprocess.PIPE).stdout
        expected = b"".join(np.asarray(Image.open(frames / f"{index:02d}.png").convert("RGB"),
                                             dtype=np.uint8).tobytes() for index in range(20))
        if decoded != expected:
            raise RuntimeError(f"Lossless RGB export mismatch: {case['id']}")
        return {"id": case["id"], "filename": target.name,
                "video_sha256": sha256(target), "decoded_rgb_exact": True,
                "source_run": info["run"]}

    with ThreadPoolExecutor(max_workers=8) as executor:
        records = list(executor.map(encode, cases))
    atomic_json(output / "input_manifest.json", {
        "created_utc": utc_now(), "model_key": model.key, "track": track,
        "count": len(records), "fps": 4, "frames": 20, "duration_seconds": 5,
        "resolution": [256, 144], "videos": records,
    })
    return video_dir


def evaluate(config: Benchmark, model_key: str, track: str, upstream: Path,
             benchmark_parent: Path, output: Path, n_process: int = 8) -> dict:
    upstream = setup_upstream(upstream)
    ready_path = benchmark_parent / "PIXELWORLD_EVALUATOR_READY.json"
    if not ready_path.is_file():
        raise RuntimeError("Run `pixelworld physics-iq setup-evaluator` first")
    ready = json.loads(ready_path.read_text())
    if ready.get("upstream_commit") != PHYSICS_IQ_COMMIT:
        raise RuntimeError("Evaluator ready marker has a different commit")
    descriptions = upstream / "descriptions" / "best_practice" / "descriptions_base.csv"
    if sha256(descriptions) != PHYSICS_IQ_DESCRIPTIONS_SHA256:
        raise RuntimeError("Descriptions hash mismatch")
    video_dir = export_videos(config, model_key, track, output / "generated_videos_5s")
    result_root = output / "official_results"
    output.mkdir(parents=True, exist_ok=True)
    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError("uv is required to run the pinned evaluator")
    command = [
        uv, "run", "python", "-m", "physiq.run_physics_iq",
        "--input_folders", str(video_dir),
        "--output_folder", str(result_root),
        "--descriptions_file", str(descriptions),
        "--benchmark_base_folder", str(benchmark_parent),
        "--n_process", str(n_process),
    ]
    log_path = output / "official_evaluation.log"
    with log_path.open("a") as log:
        subprocess.run(command, cwd=upstream, stdout=log, stderr=subprocess.STDOUT, check=True)
    result = (result_root / "physics-IQ-benchmark-verified" / "results" /
              f"{video_dir.name}_metrics.json")
    if not result.is_file():
        raise RuntimeError(f"Official evaluator did not write {result}")
    metrics = json.loads(result.read_text())
    summary = {
        "protocol": "Physics-IQ Verified official",
        "official": True,
        "upstream_commit": PHYSICS_IQ_COMMIT,
        "dataset_revision": PHYSICS_IQ_DATASET_REVISION,
        "model_key": model_key,
        "track": track,
        "input_mode": "I2V",
        "prompt_setting": "bpp-base",
        "independent_runs": 1,
        "inputs": 198,
        "fps": 4,
        "duration_seconds": 5,
        "resolution": [256, 144],
        "verified_score": metrics["final_score_view"],
        "original_formula_score": metrics["final_score_orig"],
        "spatial": metrics["score_spatial_view"],
        "spatiotemporal": metrics["score_spatiotemporal_view"],
        "weighted_spatial": metrics["score_weighted_spatial_view"],
        "mse": metrics["score_mse_view"],
        "official_metrics": str(result),
        "official_command": command,
        "completed_utc": utc_now(),
    }
    atomic_json(output / "scores.json", summary)
    return summary
