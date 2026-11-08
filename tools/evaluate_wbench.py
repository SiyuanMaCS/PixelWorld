#!/usr/bin/env python3
"""Strict PixelWorld RGB validation/export; original-judge-only WBench gate.

This does not manufacture a Full score from a partial report or substitute Qwen.
No generator programs or reference/baseline videos are executed or scored.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
from pathlib import Path
import subprocess

import numpy as np
from PIL import Image

from prepare_wbench import VENDOR, JUDGE, CODE_REVISION, DATA_REVISION, sha256, read_json, write_json, load_cases, turn_prompt
from official_runtime import preflight as runtime_preflight, execute

REQUIRED_WEIGHTS = {'clip', 'aesthetic', 'raft', 'transnetv2', 'dreamsim', 'hpsv3',
                    'sam2', 'megasam', 'da3', 'qwen2_vl_hps', 'pavrm'}
REQUIRED_MODULES = ('torch', 'numpy', 'cv2', 'yaml', 'clip', 'pyiqa', 'av',
                    'transformers', 'sam2', 'depth_anything_3', 'lietorch', 'droid_backends')


def check_runtime(source: Path, python: str, lock: Path, judge: str) -> dict:
    errors = []
    if judge != JUDGE:
        errors.append('published Full rows require the original Doubao judge')
    if not os.environ.get('VLM_API_KEY'):
        errors.append('VLM_API_KEY absent for original judge')
    return runtime_preflight(source, CODE_REVISION, python, REQUIRED_MODULES,
                             lock, REQUIRED_WEIGHTS, errors)


def stage_official_exports(index: Path, model: str, output: Path, scope: str,
                           data: Path = VENDOR / 'data') -> dict:
    if not model.startswith('pixelworld') or not all(c.isalnum() or c in '_-' for c in model):
        raise ValueError('Evaluator model tag must identify PixelWorld, never a baseline')
    cases = load_cases(data)
    entries = read_json(index)
    if not isinstance(entries, list) or not entries:
        raise ValueError('Require actual PixelWorld export directories')
    ids = []
    checked = []
    for entry in entries:
        folder = Path(entry['export']).resolve()
        record = read_json(folder / 'export_manifest.json')
        cid = record['case_id']
        if record.get('benchmark') != 'wbench' or record.get('code_revision') != CODE_REVISION or cid not in cases:
            raise ValueError('Export is not the pinned PixelWorld WBench case')
        video = folder / 'videos' / f'case_{cid}_combined.mp4'
        if not video.is_file() or sha256(video) != record['combined']['sha256']:
            raise ValueError('Exported RGB video changed')
        clips = folder / 'clips' / f'case_{cid}'
        expected = len(cases[cid]['interactions'])
        if len(record['clips']) != expected:
            raise ValueError('Incomplete turn sequence')
        for i, item in enumerate(record['clips']):
            clip = clips / f'turn_{i}.mp4'
            if not clip.is_file() or sha256(clip) != item['sha256']:
                raise ValueError('Exported turn clip changed')
        ids.append(cid)
        checked.append((cid, video, clips))
    if len(ids) != len(set(ids)) or (scope == 'full' and set(ids) != set(cases)):
        raise ValueError('Full requires all 289 exact case identities; no duplicates')
    if scope == 'case-smoke' and len(ids) != 1:
        raise ValueError('Case smoke must contain one complete official case')
    external_output(output, [])
    videos = output / model / 'videos'
    clips_out = output / model / 'clips'
    videos.mkdir(parents=True)
    clips_out.mkdir()
    for cid, video, clips in checked:
        shutil.copy2(video, videos / video.name)
        shutil.copytree(clips, clips_out / f'case_{cid}')
    record = {'producer': 'PixelWorld', 'scope': scope, 'case_ids': ids,
              'full_case_coverage': set(ids) == set(cases), 'source_commit': CODE_REVISION,
              'original_judge': JUDGE, 'official_total': None}
    write_json(output / 'staging_manifest.json', record)
    return record


def check_metric_coverage(output: Path, model: str, case_ids: list[str],
                          data: Path = VENDOR/'data') -> dict:
    """Verify applicable per-case metrics before trusting upstream report means."""
    cases = load_cases(data)
    root = output/model/'evaluation'
    errors, checked = [], 0
    for cid in case_ids:
        for metric in cases[cid]['metric_list']:
            directory = metric
            if metric in ('geometric_consistency','photometric_consistency'):
                directory = 'reconstruction_consistency'
            if metric == 'gated_spatial_consistency': directory = 'spatial_consistency'
            path = root/directory/f'case_{cid}.json'
            if not path.is_file():
                errors.append(f'missing {cid}/{metric}'); continue
            result = read_json(path)
            if result.get('error'):
                errors.append(f'failed {cid}/{metric}'); continue
            if metric == 'geometric_consistency': value = result.get('details',{}).get('geometric_consistency')
            elif metric == 'photometric_consistency': value = result.get('details',{}).get('photometric_psnr')
            elif metric == 'spatial_consistency': value = result.get('ret_sim')
            elif metric == 'navigation_trajectory': value = result.get('accuracy')
            else: value = result.get('summary',{}).get(metric, result.get('score'))
            if type(value) not in (int,float) or not math.isfinite(value):
                errors.append(f'missing/nonfinite value {cid}/{metric}'); continue
            checked += 1
    return {'complete_applicable_metric_coverage': not errors, 'case_count':len(case_ids),
            'checked_case_metrics':checked,'errors':errors,'official_total':None}


def load_rgb(run: Path, provenance: dict) -> tuple[np.ndarray, dict, dict]:
    manifest = read_json(run / "run_manifest.json")
    if manifest.get("status") != "complete" or manifest.get("validation", {}).get("pass") is not True:
        raise ValueError("Requires completed validated PixelWorld run")
    snapshot = run / "input_snapshot"
    spec = read_json(snapshot / "task_spec.json")
    if spec != provenance["media"] or spec != manifest.get("media_contract") or spec != read_json(run / "media_contract.json"):
        raise ValueError("Immutable media contract mismatch")
    if spec.get("benchmark") != provenance["benchmark"] or spec.get("task_type") != "i2v" or spec.get("audio") is not None:
        raise ValueError("Wrong benchmark/modality")
    for name, key in [("first_frame.png", "input_image_sha256"), ("prompt.txt", "input_prompt_sha256")]:
        actual = sha256(snapshot / name)
        if actual != manifest.get(key) or actual != provenance.get(key):
            raise ValueError("Immutable input hash mismatch")
    if (snapshot / "prompt.txt").read_text() != provenance["prompt"]:
        raise ValueError("Official prompt mismatch")
    n, h, w = (spec[k] for k in ("frames", "height", "width"))
    if any(type(x) is not int or x < 1 for x in (n, h, w)) or not math.isfinite(float(spec["fps"])) or not 0 < float(spec["fps"]) <= 240:
        raise ValueError("Invalid native RGB contract")
    tensor = run / "workspace/pixels.npz"
    pngs = sorted((run / "workspace/frames").glob("*.png"))
    rgb_tensor = rgb_png = None
    if tensor.exists():
        if manifest.get("pixels_sha256") and sha256(tensor) != manifest["pixels_sha256"]:
            raise ValueError("Submitted pixels hash mismatch")
        with np.load(tensor, allow_pickle=False) as data:
            pixels = data["pixels"]
            if pixels.shape != (h, w, n) or pixels.dtype.kind not in "ui" or np.any(pixels > 0xFFFFFF) or np.any(pixels < 0):
                raise ValueError("Invalid packed RGB tensor")
            packed = pixels.transpose(2, 0, 1).astype(np.uint32)
            rgb_tensor = np.stack([(packed >> s) & 255 for s in (16, 8, 0)], axis=-1).astype(np.uint8)
    if pngs:
        if [p.name for p in pngs] != [f"{i:02d}.png" for i in range(n)]:
            raise ValueError("PNG sequence must be contiguous, zero based and contract length")
        frames = []
        for p in pngs:
            with Image.open(p) as im:
                if im.mode != "RGB" or im.size != (w, h):
                    raise ValueError("PNG mode/size mismatch")
                frames.append(np.asarray(im).copy())
        rgb_png = np.stack(frames)
    if rgb_tensor is None and rgb_png is None:
        raise ValueError("Missing submitted RGB")
    if rgb_tensor is not None and rgb_png is not None and not np.array_equal(rgb_tensor, rgb_png):
        raise ValueError("Tensor/PNG disagreement")
    rgb = rgb_tensor if rgb_tensor is not None else rgb_png
    with Image.open(snapshot / "first_frame.png") as im:
        if not np.array_equal(rgb[0], np.asarray(im.convert("RGB"))):
            raise ValueError("Frame zero does not equal conditioning")
    return rgb, spec, manifest


def check_chain(items: list[tuple[Path, Path]], benchmark: str, cid: str, count: int):
    if len(items) != count:
        raise ValueError("Requires every official turn/segment, not a truncated case")
    result = []
    for i, (run, prov_path) in enumerate(items, 1):
        prov = read_json(prov_path)
        if (prov.get("benchmark"), prov.get("case_id"), prov.get("turn")) != (benchmark, cid, i):
            raise ValueError("Wrong/duplicate/out-of-order case turn")
        rgb, spec, manifest = load_rgb(run, prov)
        if result:
            previous_rgb, previous_spec, _ = result[-1]
            if spec["fps"] != previous_spec["fps"] or rgb.shape != previous_rgb.shape:
                raise ValueError("Turns require common native FPS/shape")
            if not np.array_equal(rgb[0], previous_rgb[-1]):
                raise ValueError("Continuation is not previous PixelWorld last frame")
            feedback = prov.get("feedback") or {}
            if feedback.get("previous_provenance_sha256") != sha256(items[i - 2][1]) or feedback.get("previous_run_manifest_sha256") != sha256(items[i - 2][0] / "run_manifest.json"):
                raise ValueError("Continuation provenance chain mismatch")
            if feedback.get("last_rgb_sha256") != hashlib.sha256(previous_rgb[-1].tobytes()).hexdigest():
                raise ValueError("Continuation last-RGB hash mismatch")
        elif prov.get("feedback") is not None:
            raise ValueError("Initial segment cannot have continuation feedback")
        result.append((rgb, spec, manifest))
    return result


def export_video(rgb: np.ndarray, fps: float, path: Path) -> dict:
    import av
    from fractions import Fraction
    rate = Fraction(str(fps))
    with av.open(str(path), "w") as container:
        stream = container.add_stream("libx264rgb", rate=rate)
        stream.width, stream.height = rgb.shape[2], rgb.shape[1]
        stream.pix_fmt = "rgb24"
        stream.options = {"crf": "0", "preset": "medium"}
        for i, image in enumerate(rgb):
            frame = av.VideoFrame.from_ndarray(image, format="rgb24")
            frame.pts, frame.time_base = i, 1 / rate
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    with av.open(str(path)) as container:
        decoded = np.stack([f.to_ndarray(format="rgb24") for f in container.decode(video=0)])
    if not np.array_equal(decoded, rgb):
        raise ValueError("Lossless RGB video roundtrip failed")
    return {"sha256": sha256(path), "shape": list(rgb.shape), "fps": fps,
            "duration_seconds": len(rgb) / fps, "codec": "libx264rgb", "crf": 0,
            "resampled": False, "rgb_roundtrip_exact": True}


def external_output(output: Path, runs: list[Path]) -> None:
    out = output.resolve()
    if any(out.is_relative_to(run.resolve()) for run in runs):
        raise ValueError("Evaluator output must stay outside generation runs")
    if any(p.name == "workspace" or (p / "run_manifest.json").exists() for p in (out, *out.parents)):
        raise ValueError("Evaluator output is generator-visible")
    if output.exists():
        raise FileExistsError("Refusing to overwrite evaluator export")


def require_original_judge(model: str, key_present: bool) -> None:
    if model != JUDGE:
        raise ValueError("Kling3/Wan2.7 Full comparison requires original Doubao judge; Qwen is non-comparable")
    if not key_present:
        raise RuntimeError("VLM_API_KEY absent; original judge service access not established")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    v = sub.add_parser("validate")
    v.add_argument("--run", type=Path, required=True)
    v.add_argument("--provenance", type=Path, required=True)
    e = sub.add_parser("export")
    e.add_argument("--case-id", required=True)
    e.add_argument("--index", type=Path, required=True, help='JSON list of {run, provenance}, in turn order')
    e.add_argument("--output", type=Path, required=True)
    e.add_argument("--data", type=Path, default=VENDOR / "data")
    r = sub.add_parser("preflight")
    r.add_argument("--judge", default=os.environ.get("VLM_MODEL_NAME", JUDGE))
    r.add_argument('--python', default=os.environ.get('WBENCH_PYTHON', os.sys.executable))
    r.add_argument('--weights-lock', type=Path, default=VENDOR/'weights_lock.json')
    r.add_argument('--source', type=Path, default=VENDOR/'source')
    r.add_argument('--output', type=Path)
    run = sub.add_parser('run')
    run.add_argument('--index', type=Path, required=True, help='JSON list of {export: directory}')
    run.add_argument('--output', type=Path, required=True)
    run.add_argument('--scope', choices=('full','case-smoke'), default='full')
    run.add_argument('--model', default='pixelworld_codex')
    run.add_argument('--python', default=os.environ.get('WBENCH_PYTHON', os.sys.executable))
    run.add_argument('--weights-lock', type=Path, default=VENDOR/'weights_lock.json')
    run.add_argument('--source', type=Path, default=VENDOR/'source')
    run.add_argument('--weights-dir', type=Path, default=VENDOR/'weights')
    run.add_argument('--gpus', default='0')
    run.add_argument('--vlm-workers', type=int, default=2)
    run.add_argument('--vp-python', required=True, help='Official PAVRM environment interpreter')
    run.add_argument('--vp-model', type=Path, required=True, help='Original fine-tuned PAVRM checkpoint directory')
    a = p.parse_args()
    if a.command == "validate":
        rgb, spec, _ = load_rgb(a.run, read_json(a.provenance))
        print(json.dumps({"validated": True, "shape": list(rgb.shape), "media": spec}))
    elif a.command == "preflight":
        report = check_runtime(a.source, a.python, a.weights_lock, a.judge)
        if a.output:
            write_json(a.output, report)
        print(json.dumps(report))
        if report['status'] != 'ready':
            raise SystemExit(2)
    elif a.command == 'run':
        report = check_runtime(a.source, a.python, a.weights_lock, JUDGE)
        if report['status'] != 'ready':
            print(json.dumps(report)); raise SystemExit(2)
        staged = stage_official_exports(a.index, a.model, a.output, a.scope)
        # Upstream main.py reads the official cases from its own data root.
        case_root = a.source/'data/cases'; case_root.mkdir(parents=True, exist_ok=True)
        for cid in staged['case_ids']:
            src = VENDOR/'data/cases'/f'case_{cid}.json'; dst = case_root/src.name
            if dst.exists() and sha256(dst) != sha256(src):
                raise ValueError('Upstream case cache differs from pinned dataset')
            if not dst.exists(): shutil.copy2(src, dst)
        env = os.environ.copy()
        env.update(VLM_MODEL_NAME=JUDGE, WBENCH_WEIGHTS_DIR=str(a.weights_dir.resolve()),
                   HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
        result = execute([a.python, str((a.source/'main.py').resolve()), '--model', a.model,
                          '--work_dir', str(a.output.resolve()), '--phase', 'all',
                          '--gpus', a.gpus, '--vlm_workers', str(a.vlm_workers)],
                         a.source.resolve(), a.output/'official_execution', env)
        if result['returncode']: raise SystemExit(result['returncode'])
        # This official metric is intentionally a separate original checkpoint
        # and environment, not the optional Qwen replacement for Doubao.
        link = a.source/'work_dirs'/a.model; link.parent.mkdir(parents=True,exist_ok=True)
        target = (a.output/a.model).resolve()
        if link.exists() and link.resolve() != target:
            raise ValueError('PAVRM work path already refers to another experiment')
        if not link.exists(): link.symlink_to(target, target_is_directory=True)
        vp = execute([a.vp_python,str((a.source/'tools/run_visual_plausibility.py').resolve()),
                      '--model',a.model,'--model_path',str(a.vp_model.resolve()),'--fps','2'],
                     a.source.resolve(),a.output/'official_pavrm_execution',env)
        if vp['returncode']: raise SystemExit(vp['returncode'])
        # Refresh the unchanged report after the standalone metric is present.
        report = execute([a.python,str((a.source/'main.py').resolve()),'--model',a.model,
                          '--work_dir',str(a.output.resolve()),'--phase','report'],
                         a.source.resolve(),a.output/'official_report_execution',env)
        if report['returncode']: raise SystemExit(report['returncode'])
        coverage = check_metric_coverage(a.output,a.model,staged['case_ids'])
        write_json(a.output/'coverage.json',coverage)
        result['coverage']=coverage
        # No invented five-dimension Total: preserve the unchanged official raw report.
        print(json.dumps(result))
        if not coverage['complete_applicable_metric_coverage']: raise SystemExit(2)
    else:
        case = load_cases(a.data)[a.case_id]
        items = [(Path(x["run"]), Path(x["provenance"])) for x in read_json(a.index)]
        external_output(a.output, [x[0] for x in items])
        chain = check_chain(items, "wbench", a.case_id, len(case["interactions"]))
        for i, (_, prov_path) in enumerate(items, 1):
            prov = read_json(prov_path)
            if prov.get("code_revision") != CODE_REVISION or prov.get("dataset_revision") != DATA_REVISION or prov.get("prompt") != turn_prompt(case, i):
                raise ValueError("Export must use pinned official prompt/protocol")
            if prov.get("case_sha256") != sha256(a.data / "cases" / f"case_{a.case_id}.json"):
                raise ValueError("Official case identity hash mismatch")
        a.output.mkdir(parents=True)
        videos = a.output / "videos"; videos.mkdir()
        clips = a.output / "clips" / f"case_{a.case_id}"; clips.mkdir(parents=True)
        boundaries = [0]; exports = []
        for i, (rgb, spec, _) in enumerate(chain):
            exports.append(export_video(rgb, spec["fps"], clips / f"turn_{i}.mp4"))
            boundaries.append(boundaries[-1] + len(rgb))
        combined = np.concatenate([x[0] for x in chain]) # WBench keeps all segment frames, including shared anchors.
        export = export_video(combined, chain[0][1]["fps"], videos / f"case_{a.case_id}_combined.mp4")
        write_json(a.output / "turns.json", {"fps": chain[0][1]["fps"], "cases": {a.case_id: {"turn_frames": boundaries}}})
        write_json(a.output / "export_manifest.json", {"producer": "PixelWorld", "benchmark": "wbench", "code_revision": CODE_REVISION,
                   "judge_required": JUDGE, "case_id": a.case_id, "scope": "complete_case_smoke_not_Full",
                   "combined": export, "clips": exports, "turn_frames": boundaries})
        print(json.dumps({"exported": True, "full_score_ready": False}))


if __name__ == "__main__":
    main()
