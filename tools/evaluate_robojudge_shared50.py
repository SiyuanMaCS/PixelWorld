#!/usr/bin/env python3
"""Offline RoboJudge generation adapter; never invokes generator code or gold scores.

prepare -> run (GPU, unchanged official inference.py) -> summarize.
All exports, predictions, failures and scope reports stay outside generation runs.
The --gold argument of upstream inference means an input JSONL, not human labels.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
VENDOR = REPO / "vendor/robojudge-eval-night"
CODE_REVISION = "db6c2b7bd8e447ad1e21a63a48c5e26e816811e2"
CHECKPOINT_REVISION = "54b5fd7b93e0288bc91a8827af03b72eec7ffad1"
INFERENCE_SHA256 = "1297568c13ec892a7c3ece267384484f350ebdfaee7d8d5dbebfd63642df2d3b"
SCOPE_SHA256 = "32251941a86d85182040ee335bb52588e3e6e754d2ff3c513813d72bdbe5d9fc"
TASKS_SHA256 = "3d34600638bb53187956932c07d31e89e1b8b08293809ebf18786b12a11e51e0"
DATASET_REVISION = "7ba7a753d5c4644bbcc0a926cc1e7a46678aa54b"
ROBOT_PREFIX = "In a fixed robotic workspace, a rigid and physically consistent embodied robotic arm with high stability and no deformation proceeds to "
HUMAN_PREFIX = "In a first-person egocentric video, a real human hand starts to "
HUMAN_DATASETS = frozenset({"egodex_human", "egoscaler_human", "epickitchens_human"})


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_tasks(path: Path) -> list[dict]:
    if sha256(path) != TASKS_SHA256:
        raise ValueError("pinned shared-50 original instruction cache changed")
    rows = read_json(path)
    scope = read_json(VENDOR / "shared50_inputs.json")
    if sha256(VENDOR / "shared50_inputs.json") != SCOPE_SHA256:
        raise ValueError("original shared-50 scope changed")
    if len(rows) != 50 or len({r["key"] for r in rows}) != 50:
        raise ValueError("requires exactly 50 unique original tasks")
    if [r["key"] for r in rows] != [r["key"] for r in scope]:
        raise ValueError("shared-50 task order/identity changed")
    for row, original in zip(rows, scope):
        if not isinstance(row.get("instruction"), str) or not row["instruction"].strip():
            raise ValueError("original instruction text missing")
        if row.get("dataset_revision") != DATASET_REVISION:
            raise ValueError("unexpected instruction dataset revision")
        expected = original["instruction_url"].replace("/resolve/main/", f"/resolve/{DATASET_REVISION}/")
        if row.get("instruction_url") != expected:
            raise ValueError("instruction URL is not the pinned original task")
    return rows


def external_output(output: Path, generations: Path) -> None:
    if output.is_relative_to(generations):
        raise ValueError("evaluation output must not be inside generation runs")
    for parent in (output, *output.parents):
        if (parent / "run_manifest.json").exists() or parent.name == "workspace":
            raise ValueError("evaluation output must not be visible to a generator")


def load_frames(run: Path, task: dict) -> tuple[np.ndarray, dict, dict]:
    manifest = read_json(run / "run_manifest.json")
    if manifest.get("status") != "complete" or manifest.get("validation", {}).get("pass") is not True:
        raise ValueError("run is not complete and validated")
    ws, snapshot = run / "workspace", run / "input_snapshot"
    spec = read_json(run / "media_contract.json")
    if spec != manifest.get("media_contract") or spec != read_json(snapshot / "task_spec.json"):
        raise ValueError("immutable media contracts disagree")
    if spec.get("benchmark") != "robojudge" or spec.get("task_type") != "i2v" or spec.get("audio") is not None:
        raise ValueError("requires RoboJudge RGB i2v contract without audio")
    n, h, w = (spec[k] for k in ("frames", "height", "width"))
    if any(type(x) is not int or x < 1 for x in (n, h, w)) or not 0 < float(spec["fps"]) <= 240:
        raise ValueError("invalid RGB shape/fps")
    for name, field in (("first_frame.png", "input_image_sha256"), ("prompt.txt", "input_prompt_sha256")):
        if sha256(snapshot / name) != manifest.get(field):
            raise ValueError(f"immutable snapshot hash mismatch: {name}")
    prefix = HUMAN_PREFIX if task["dataset"] in HUMAN_DATASETS else ROBOT_PREFIX
    prompt = (snapshot / "prompt.txt").read_text().strip()
    if prompt != prefix + task["instruction"].strip():
        raise ValueError("generator instruction does not match original task plus published generation prefix")
    tensor_path = ws / "pixels.npz"
    try:
        pngs = sorted((ws / "frames").glob("*.png"), key=lambda p: int(p.stem))
    except ValueError:
        raise ValueError("PNG frame names must be numeric") from None
    from_tensor = None
    if tensor_path.exists():
        if manifest.get("pixels_sha256") and sha256(tensor_path) != manifest["pixels_sha256"]:
            raise ValueError("submitted RGB artifact hash changed")
        with np.load(tensor_path, allow_pickle=False) as data:
            pixels = data["pixels"]
            if pixels.shape != (h, w, n) or pixels.dtype.kind not in "ui" or np.any(pixels > 0xFFFFFF) or np.any(pixels < 0):
                raise ValueError("invalid packed RGB tensor")
            packed = pixels.transpose(2, 0, 1).astype(np.uint32)
            from_tensor = np.stack([(packed >> shift) & 255 for shift in (16, 8, 0)], axis=-1).astype(np.uint8)
    from_png = None
    if pngs:
        if [p.name for p in pngs] != [f"{i:02d}.png" for i in range(n)]:
            raise ValueError("PNG sequence must be exact, contiguous and zero based")
        images = []
        for path in pngs:
            with Image.open(path) as im:
                if im.mode != "RGB" or im.size != (w, h):
                    raise ValueError("PNG is not contract-sized RGB")
                images.append(np.asarray(im).copy())
        from_png = np.stack(images)
    if from_tensor is None and from_png is None:
        raise ValueError("no submitted RGB/PNG artifact")
    if from_tensor is not None and from_png is not None and not np.array_equal(from_tensor, from_png):
        raise ValueError("RGB tensor/PNG mismatch")
    frames = from_tensor if from_tensor is not None else from_png
    with Image.open(snapshot / "first_frame.png") as im:
        initial = np.asarray(im.convert("RGB"))
    if not np.array_equal(frames[0], initial):
        raise ValueError("frame zero differs from immutable initial scene")
    return frames, spec, manifest


def export_video(frames: np.ndarray, fps: float, path: Path) -> dict:
    """Lossless RGB H.264 MP4 at native dimensions, timing and frame order."""
    import av
    from fractions import Fraction

    rate = Fraction(str(fps))
    with av.open(str(path), "w") as container:
        stream = container.add_stream("libx264rgb", rate=rate)
        stream.width, stream.height = frames.shape[2], frames.shape[1]
        stream.pix_fmt = "rgb24"
        stream.options = {"crf": "0", "preset": "medium"}
        for i, image in enumerate(frames):
            frame = av.VideoFrame.from_ndarray(image, format="rgb24")
            frame.pts, frame.time_base = i, 1 / rate
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    with av.open(str(path)) as container:
        decoded = np.stack([f.to_ndarray(format="rgb24") for f in container.decode(video=0)])
    if not np.array_equal(decoded, frames):
        raise ValueError("evaluation video RGB round-trip mismatch")
    return {"codec": "libx264rgb", "crf": 0, "pixel_format": "rgb24", "fps": float(rate),
            "shape": list(frames.shape), "rgb_roundtrip_exact": True, "sha256": sha256(path)}


def scope_report(records: list[dict], expected: list[str]) -> dict:
    by_id = {r["case_id"]: r for r in records}
    missing = [i for i in expected if i not in by_id]
    failed = [r["case_id"] for r in records if r["status"] != "prepared"]
    duplicates = sorted({r["case_id"] for r in records if sum(x["case_id"] == r["case_id"] for x in records) > 1})
    return {"original_task_count": 50, "prepared_count": sum(r["status"] == "prepared" for r in records),
            "missing": missing, "failed": failed, "duplicates": duplicates,
            "complete_shared50": len(expected) == 50 and not (missing or failed or duplicates)}


def submitted_attempts(folder: Path) -> tuple[list[Path], list[dict]]:
    """Use the earliest completed validated submission, not every retry folder."""
    groups, unexpected = {}, []
    for run in folder.glob("case_*_attempt_*"):
        match = re.fullmatch(r"case_(common50_\d{4})_attempt_(\d+)", run.name)
        if not match:
            unexpected.append(run)
            continue
        try:
            manifest = read_json(run / "run_manifest.json")
        except (OSError, ValueError):
            manifest = {}
        accepted = (manifest.get("status") == "complete"
                    and manifest.get("validation", {}).get("pass") is True)
        groups.setdefault(match[1], []).append((int(match[2]), run, accepted, manifest.get("status")))
    selected, ignored = list(unexpected), []
    for case, attempts in sorted(groups.items()):
        attempts.sort(key=lambda item: item[0])
        chosen = next((item for item in attempts if item[2]), attempts[0])
        selected.append(chosen[1])
        for attempt, run, accepted, status in attempts:
            if run != chosen[1]:
                ignored.append({'case_id': case, 'run': str(run), 'attempt': attempt,
                                'status': status, 'completed_validated': accepted,
                                'reason': 'first_completed_validated_submission_selected' if chosen[2]
                                          else 'all_attempts_failed_case_failure_preserved'})
    return sorted(selected), ignored


def prepare(args) -> int:
    root, output = args.generations.resolve(), args.output.resolve()
    external_output(output, root)
    output.mkdir(parents=True, exist_ok=False)
    tasks = load_tasks(args.tasks)
    expected = [f"common50_{i:04d}" for i in range(50)]
    records = []
    submissions, ignored = submitted_attempts(root / args.model / args.track)
    for run in submissions:
        match = re.fullmatch(r"case_(common50_\d{4})_attempt_\d+", run.name)
        if not match:
            records.append({"case_id": run.name, "status": "failed", "error": "unexpected task identity"})
            continue
        case = match[1]
        record = {"case_id": case, "run": os.path.relpath(run, output), "status": "failed"}
        records.append(record)
        try:
            index = expected.index(case)
            frames, spec, manifest = load_frames(run, tasks[index])
            if manifest.get("case_id") != case or manifest.get("model_key") != args.model or manifest.get("track") != args.track:
                raise ValueError("run manifest identity mismatch")
            folder = output / f"media/{case}/{run.name}"
            folder.mkdir(parents=True)
            video = folder / "evaluation.mp4"
            record["export"] = export_video(frames, spec["fps"], video)
            shutil.copyfile(run / "input_snapshot/first_frame.png", folder / "initial.png")
            record["initial_sha256"] = sha256(folder / "initial.png")
            # Only required official input fields. No human scores, continuations or rationales.
            record["input"] = {"item_id": case, "video_url": os.path.relpath(video, output),
                               "instruction": tasks[index]["instruction"].strip(),
                               "init_frame_url": os.path.relpath(folder / "initial.png", output)}
            record["source_key"] = tasks[index]["key"]
            record["status"] = "prepared"
        except Exception as exc:
            record["error"] = f"{type(exc).__name__}: {exc}"
    scope = scope_report(records, expected)
    plan = {"schema": "robojudge-shared50-adapter-v1", "model": args.model, "track": args.track,
            "code_revision": CODE_REVISION, "checkpoint_revision": CHECKPOINT_REVISION,
            "dataset_revision": DATASET_REVISION, "tasks_sha256": sha256(args.tasks),
            "adapter_sha256": sha256(Path(__file__)), "scope": scope, "records": records,
            "attempt_selection_policy": "earliest_completed_validated_submission_no_quality_selection",
            "ignored_attempts": ignored}
    write_json(output / "plan.json", plan)
    with (output / "inputs.jsonl").open("w") as f:
        for r in records:
            if r["status"] == "prepared":
                f.write(json.dumps(r["input"], ensure_ascii=False) + "\n")
    print(json.dumps(scope))
    return 0 if scope["complete_shared50"] or (args.allow_partial and scope["prepared_count"] and not scope["duplicates"]) else 2


def verify_source() -> None:
    source = VENDOR / "source"
    revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if revision != CODE_REVISION or sha256(source / "code/inference.py") != INFERENCE_SHA256:
        raise ValueError("official source pin/hash mismatch; refusing modified inference")


def gpu_check() -> dict:
    try:
        import torch
    except ImportError as exc:
        return {"required_dtype": "bfloat16", "attn_implementation": "sdpa",
                "blockers": [f"isolated torch unavailable: {type(exc).__name__}: {exc}"]}
    result = {"torch": torch.__version__, "cuda_runtime": torch.version.cuda,
              "required_dtype": "bfloat16", "attn_implementation": "sdpa", "blockers": []}
    if not torch.cuda.is_available():
        result["blockers"].append("CUDA GPU unavailable")
        return result
    prop = torch.cuda.get_device_properties(0)
    result.update(gpu=prop.name, vram_bytes=prop.total_memory,
                  compute_capability=list(torch.cuda.get_device_capability(0)),
                  native_bfloat16=torch.cuda.is_bf16_supported(including_emulation=False))
    if not result["native_bfloat16"]:
        result["blockers"].append("GPU lacks native bfloat16; official precision is not replaced")
    try:
        q = torch.zeros((1, 2, 4, 16), device="cuda", dtype=torch.bfloat16)
        torch.nn.functional.scaled_dot_product_attention(q, q, q)
        torch.cuda.synchronize()
        result["bfloat16_sdpa_probe"] = "pass"
    except Exception as exc:
        result["bfloat16_sdpa_probe"] = type(exc).__name__ + ": " + str(exc)
        result["blockers"].append("bfloat16 SDPA probe failed")
    return result


def official_command(output: Path) -> list[str]:
    return [sys.executable, str(VENDOR / "source/code/inference.py"),
            "--ckpt", str(VENDOR / "checkpoint"), "--gold", str(output / "inputs.jsonl"),
            "--data-root", ".", "--out", str(output / "predictions.jsonl"),
            "--shard", "0", "--num-shards", "1", "--limit", "0",
            "--max-new-tokens", "2048", "--attn-implementation", "sdpa"]


def summarize(output: Path) -> dict:
    plan = read_json(output / "plan.json")
    expected = {r["case_id"] for r in plan["records"] if r["status"] == "prepared"}
    seen, invalid_duplicates, errors = {}, set(), []
    path = output / "predictions.jsonl"
    for line_no, line in enumerate(path.read_text().splitlines() if path.exists() else [], 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            key = row["item_id"], row["axis"]
            if key[0] not in expected or key[1] not in ("PA", "IA"):
                raise ValueError("unexpected prediction identity/axis")
            if key in seen:
                seen[key] = None
                invalid_duplicates.add(key)
                raise ValueError("duplicate prediction")
            # Do not infer scores from incidental rationale digits or clamp invalid outputs.
            text = row["predict"].strip()
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
            pred = json.loads(text)
            field = "physical_adherence" if key[1] == "PA" else "instruction_alignment"
            score = pred[field]
            if type(score) is not int or not 1 <= score <= 5:
                raise ValueError("expected explicit integer 1-5 in official axis JSON")
            seen[key] = score
        except Exception as exc:
            errors.append({"line": line_no, "error": f"{type(exc).__name__}: {exc}"})
    paired = []
    failures = []
    for case in sorted(expected):
        pa = None if (case, "PA") in invalid_duplicates else seen.get((case, "PA"))
        ia = None if (case, "IA") in invalid_duplicates else seen.get((case, "IA"))
        if pa is None or ia is None:
            failures.append({"case_id": case, "PA": pa, "IA": ia, "status": "missing_or_invalid_axis"})
        else:
            paired.append({"case_id": case, "PA": pa, "IA": ia, "mean": (pa + ia) / 2})
    complete = plan["scope"]["complete_shared50"] and len(paired) == 50 and not errors
    means = {axis: sum(r[axis] for r in paired) / len(paired) if paired else None for axis in ("PA", "IA", "mean")}
    result = {"metric": "generation PA/IA 1-5; not judge Pearson agreement", "scope": plan["scope"],
              "complete_shared50": complete, "valid_paired_count": len(paired),
              "shared50_means": means if complete else None, "partial_paired_means": means if not complete else None,
              "items": paired, "prediction_failures": failures, "parse_failures": errors,
              "preparation_failures": [r for r in plan["records"] if r["status"] != "prepared"]}
    write_json(output / "summary.json", result)
    return result


def run_official(args) -> int:
    output = args.output.resolve()
    external_output(output, REPO / "__not_a_generation_root__")
    plan = read_json(output / "plan.json")
    if (output / "execution.json").exists() or (output / "predictions.jsonl").exists():
        raise ValueError("use a fresh evaluation directory; never overwrite predictions/failures")
    execution = {"code_revision": CODE_REVISION, "checkpoint_revision": CHECKPOINT_REVISION,
                 "status": "blocked", "blockers": [], "command": official_command(output)}
    try:
        verify_source()
        if not plan["scope"]["complete_shared50"] and not args.allow_partial:
            raise ValueError("shared-50 incomplete; explicit --allow-partial required for smoke")
        if plan["scope"]["duplicates"] or not plan["scope"]["prepared_count"]:
            raise ValueError("no unambiguous prepared inputs")
        if plan["code_revision"] != CODE_REVISION or plan["checkpoint_revision"] != CHECKPOINT_REVISION:
            raise ValueError("plan protocol pins changed")
        rows = [r["input"] for r in plan["records"] if r["status"] == "prepared"]
        if [json.loads(line) for line in (output / "inputs.jsonl").read_text().splitlines()] != rows:
            raise ValueError("official input JSONL changed since preparation")
        for r in plan["records"]:
            if r["status"] == "prepared":
                if sha256(output / r["input"]["video_url"]) != r["export"]["sha256"]:
                    raise ValueError("evaluation video changed since preparation")
                if sha256(output / r["input"]["init_frame_url"]) != r["initial_sha256"]:
                    raise ValueError("initial-frame context changed since preparation")
        checkpoint = read_json(VENDOR / "checkpoint_manifest.json")
        if checkpoint["revision"] != CHECKPOINT_REVISION or checkpoint["repo_id"] != "HuggingFriends/RoboJudge-9B":
            raise ValueError("published checkpoint pin mismatch")
        required = {"model.safetensors", "config.json", "processor_config.json", "generation_config.json",
                    "tokenizer.json", "tokenizer_config.json", "chat_template.jinja"}
        if not required <= checkpoint["files"].keys():
            raise ValueError("published checkpoint incomplete")
        for name, meta in checkpoint["files"].items():
            if sha256(VENDOR / "checkpoint" / name) != meta["sha256"]:
                raise ValueError(f"checkpoint file hash mismatch: {name}")
        execution["gpu"] = gpu_check()
        blockers = execution["gpu"]["blockers"]
        if blockers and not (args.allow_unsupported_bf16 and blockers == ["GPU lacks native bfloat16; official precision is not replaced"]):
            raise ValueError("; ".join(blockers))
        execution["status"] = "running"
        write_json(output / "execution.json", execution)
        env = os.environ.copy()
        env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1")
        # Official Qwen utility supports torchvision; keep its default backend selection.
        env.pop("FORCE_QWENVL_VIDEO_READER", None)
        with (output / "official.stdout.log").open("w") as stdout, (output / "official.stderr.log").open("w") as stderr:
            code = subprocess.call(execution["command"], cwd=output, env=env, stdout=stdout, stderr=stderr)
        execution.update(status="finished" if code == 0 else "failed", returncode=code)
    except Exception as exc:
        execution["blockers"].append(f"{type(exc).__name__}: {exc}")
    finally:
        write_json(output / "execution.json", execution)
        result = summarize(output)
    return 0 if execution.get("returncode") == 0 and (result["complete_shared50"] or (args.allow_partial and result["valid_paired_count"] == plan["scope"]["prepared_count"] and not result["parse_failures"])) else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--generations", type=Path, required=True)
    prep.add_argument("--model", required=True)
    prep.add_argument("--track", choices=("text", "vision-agent", "vision-input"), default="vision-agent")
    prep.add_argument("--tasks", type=Path, default=VENDOR / "shared50_tasks.json")
    prep.add_argument("--output", type=Path, required=True)
    prep.add_argument("--allow-partial", action="store_true")
    run = sub.add_parser("run")
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--allow-partial", action="store_true")
    run.add_argument("--allow-unsupported-bf16", action="store_true", help="explicit diagnostic attempt; preserves official bf16, no fallback")
    summary = sub.add_parser("summarize")
    summary.add_argument("--output", type=Path, required=True)
    check = sub.add_parser("check-gpu")
    check.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "prepare":
        return prepare(args)
    if args.action == "run":
        return run_official(args)
    if args.action == "summarize":
        return 0 if summarize(args.output.resolve())["complete_shared50"] else 2
    result = gpu_check()
    write_json(args.output, result)
    print(json.dumps(result))
    return 2 if result["blockers"] else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, KeyError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(2)
