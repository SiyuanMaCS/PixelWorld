from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import csv
import hashlib
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
    atomic_json(inputs_root.parent / f"{inputs_root.name}_manifest.json", payload)
    generic = inputs_root.parent / "manifest.json"
    # Preserve another benchmark's inventory in a shared input parent.
    if not generic.exists() or json.loads(generic.read_text()).get("dataset_revision") == PHYSICS_IQ_DATASET_REVISION:
        atomic_json(generic, payload)
    return payload


def setup_evaluator(upstream: Path, benchmark_parent: Path, install: bool = True,
                    download_data: bool = True) -> dict:
    upstream = setup_upstream(upstream)
    if install:
        uv = shutil.which("uv")
        if not uv:
            raise RuntimeError("uv is required for the pinned official evaluator environment")
        subprocess.run([uv, "sync"], cwd=upstream, check=True)
        evaluator_python = subprocess.check_output(
            [uv, "run", "--no-sync", "python", "-c", "import sys; print(sys.executable)"],
            cwd=upstream, text=True,
        ).strip()
    else:
        environment = Path(os.environ.get("UV_PROJECT_ENVIRONMENT", str(upstream / ".venv")))
        if not environment.is_absolute():
            environment = upstream / environment
        evaluator_python = str(environment.resolve() / "bin/python")
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
        "python": evaluator_python,
    }
    atomic_json(benchmark_parent / "PIXELWORLD_EVALUATOR_READY.json", record)
    return record


def _ffmpeg() -> str:
    value = shutil.which("ffmpeg")
    if not value:
        raise RuntimeError("ffmpeg is required")
    return value


def official_cases() -> list[dict]:
    """Pinned identities are independent of shared prepared-input inventories."""
    pinned = json.loads(PINNED_MANIFEST.read_text())
    cases = pinned["cases"]
    if (pinned.get("dataset_revision") != PHYSICS_IQ_DATASET_REVISION
            or len(cases) != PHYSICS_IQ_INPUTS
            or [case["id"] for case in cases] != [f"{i:04d}" for i in range(1, 199)]):
        raise ValueError("Official Physics-IQ evaluation requires the pinned198 identities")
    return cases


def conditioning_evidence_directory(run: Path, manifest: dict) -> Path:
    """Use preserved inputs without inventing snapshots for early run records."""
    snapshot = run / "input_snapshot"
    if snapshot.is_dir():
        return snapshot
    if "initial_input_snapshot" in manifest or "initial_input_hashes" in manifest:
        raise ValueError("Recorded Physics-IQ input snapshot is missing")
    # Early native runs kept inputs in workspace and recorded their file hashes.
    # validated_rgb still checks those hashes and both official input identities.
    return run / "workspace"


def verify_run_model_identity(manifest: dict, model, track: str) -> str:
    if manifest.get("track") != track:
        raise ValueError("Physics-IQ run belongs to another model or track")
    if manifest.get("model_key") == model.key:
        return "model_key_exact"
    # A preserved builtin TRAE run may have a different local key from its
    # later Codex routing config. Accept only the exact same builtin model ID.
    if (manifest.get("cli_backend") == "trae"
            and (manifest.get("provider") or {}).get("type") == "builtin"
            and manifest.get("model")
            and model.model == "traex/" + manifest["model"]):
        return "preserved_builtin_model_id_exact"
    raise ValueError("Physics-IQ run belongs to another model or track")


def validated_rgb(run: Path, case: dict) -> tuple[np.ndarray, dict]:
    """Recheck immutable BPP/initial RGB and current submitted pixels before export."""
    manifest = json.loads((run / "run_manifest.json").read_text())
    if manifest.get("status") != "complete" or manifest.get("validation", {}).get("pass") is not True:
        raise ValueError("Physics-IQ export requires a completed validated run")
    if manifest.get("case_id") != case["id"]:
        raise ValueError("Physics-IQ run identity differs from official case")
    spec = json.loads((run / "media_contract.json").read_text())
    expected = {"task_type": "i2v", "width": 256, "height": 144, "frames": 20, "fps": 4, "audio": None}
    if spec != manifest.get("media_contract") or any(spec.get(k) != v for k, v in expected.items()):
        raise ValueError("Current primary Physics-IQ export requires native256x144/4FPS/20frames")
    snapshot = conditioning_evidence_directory(run, manifest)
    for name, key in [("first_frame.png", "input_image_sha256"), ("prompt.txt", "input_prompt_sha256")]:
        if sha256(snapshot / name) != manifest.get(key):
            raise ValueError("Immutable Physics-IQ input changed")
    prompt = (snapshot / "prompt.txt").read_text().strip()
    if hashlib.sha256(prompt.encode()).hexdigest() != case["prompt_sha256"]:
        raise ValueError("Input is not the pinned official base BPP")
    with Image.open(snapshot / "first_frame.png") as image:
        initial = np.asarray(image.convert("RGB"))
    if initial.shape != (144, 256, 3) or hashlib.sha256(initial.tobytes()).hexdigest() != case["resized_rgb_sha256"]:
        raise ValueError("Input RGB differs from the pinned official switch-frame resize")
    tensor = run / "workspace/pixels.npz"
    if manifest.get("pixels_sha256") and sha256(tensor) != manifest["pixels_sha256"]:
        raise ValueError("Submitted Physics-IQ tensor changed")
    with np.load(tensor, allow_pickle=False) as data:
        pixels = data["pixels"]
        if (pixels.shape != (144, 256, 20) or pixels.dtype.kind not in "ui"
                or np.any(pixels < 0) or np.any(pixels > 0xFFFFFF)):
            raise ValueError("Invalid submitted Physics-IQ RGB tensor")
        packed = pixels.transpose(2, 0, 1).astype(np.uint32)
        rgb = np.stack([(packed >> s) & 255 for s in (16, 8, 0)], axis=-1).astype(np.uint8)
    frames = run / "workspace/frames"
    if {p.name for p in frames.glob("*.png")} != {f"{i:02d}.png" for i in range(20)}:
        raise ValueError("Incomplete or extra Physics-IQ PNG sequence")
    for i in range(20):
        with Image.open(frames / f"{i:02d}.png") as image:
            if image.mode != "RGB" or not np.array_equal(np.asarray(image), rgb[i]):
                raise ValueError("Physics-IQ tensor and PNG sequence disagree")
    if not np.array_equal(rgb[0], initial):
        raise ValueError("Physics-IQ frame zero differs from conditioning")
    return rgb, manifest


def export_videos(config: Benchmark, model_key: str, track: str, output: Path) -> Path:
    model = config.model(model_key)
    cases = official_cases()
    accepted = {}
    for case in cases:
        info = inspect(config, model, track, case["id"])
        if info["state"] != "complete":
            raise RuntimeError(f"Incomplete case: {model.key}/{track}/{case['id']}")
        accepted[case["id"]] = info
    video_dir = output / f"pixelworld-{model.key}-{track}-bpp-run_01"
    if video_dir.exists():
        raise FileExistsError("Existing Physics-IQ export must be preserved; use a new evaluation directory")
    video_dir.mkdir(parents=True)
    ffmpeg = _ffmpeg()

    def encode(case: dict) -> dict:
        info = accepted[case["id"]]
        rgb, run_manifest = validated_rgb(Path(info["run"]), case)
        model_identity = verify_run_model_identity(run_manifest, model, track)
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
        expected = rgb.tobytes()
        if decoded != expected:
            raise RuntimeError(f"Lossless RGB export mismatch: {case['id']}")
        return {"id": case["id"], "filename": target.name,
                "video_sha256": sha256(target), "decoded_rgb_exact": True,
                "source_run": info["run"], "source_run_manifest_sha256": sha256(Path(info["run"]) / "run_manifest.json"),
                "source_pixels_sha256": run_manifest.get("pixels_sha256"),
                "source_model_key": run_manifest.get("model_key"),
                "source_model": run_manifest.get("model"),
                "source_cli_backend": run_manifest.get("cli_backend"),
                "model_identity_check": model_identity,
                "input_evidence_directory": str(conditioning_evidence_directory(Path(info["run"]), run_manifest)),
                "input_evidence_kind": "immutable_snapshot" if (Path(info["run"]) / "input_snapshot").is_dir()
                                       else "early_workspace_inputs_hash_verified",
                "input_rgb_sha256": case["resized_rgb_sha256"], "base_bpp_sha256": case["prompt_sha256"]}

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
