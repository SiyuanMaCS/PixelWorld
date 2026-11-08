#!/usr/bin/env python3
"""WorldScore RGB exports and strict complete-scope normalized score aggregation.

No silent padding, resampling, missing-dimension zeros or partial leaderboard score.
Upstream GPU evaluator remains separate; preflight documents provisioning blockers.
"""
from __future__ import annotations

import argparse
import ast
import json
import math
import os
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from prepare_wbench import sha256, read_json, write_json
from prepare_worldscore import VENDOR, CODE_REVISION, DATA_REVISION, load_metadata, case_identity, official_functions, generation_prompts
from evaluate_wbench import check_chain, external_output, export_video
from official_runtime import preflight as runtime_preflight, execute

STATIC = {"camera_control": ("camera_error",), "object_control": ("object_detection",),
          "content_alignment": ("clip_score",), "3d_consistency": ("reprojection_error",),
          "photometric_consistency": ("optical_flow_aepe",), "style_consistency": ("gram_matrix",),
          "subjective_quality": ("clip_iqa+", "clip_aesthetic")}
DYNAMIC = {"motion_accuracy": ("motion_accuracy",), "motion_magnitude": ("optical_flow",),
           "motion_smoothness": ("motion_smoothness",)}
CAMERA_HASH = "68265db20d04a867e04130e605ce291877664605fe70b4f0e2dfce1ea3314a2f"
REQUIRED_MODULES = ('torch', 'numpy', 'cv2', 'omegaconf', 'submitit', 'structlog',
                    'fire', 'transformers', 'clip', 'open_clip', 'lpips', 'timm', 'einops')
REQUIRED_WEIGHTS = {'droid', 'groundingdino', 'sam', 'sam2', 'clip', 'clip_iqa',
                    'clip_aesthetic', 'flowformer', 'raft', 'sea_raft', 'vfimamba'}


def check_runtime(source: Path, python: str, lock: Path) -> dict:
    return runtime_preflight(source, CODE_REVISION, python, REQUIRED_MODULES, lock, REQUIRED_WEIGHTS)


def check_export_scope(exports: Path, movement: str, scope: str,
                       data: Path = VENDOR/'data/WorldScore-Dataset') -> list[str]:
    rows = load_metadata(data, movement)
    expected = {case_identity(row) for row in rows}
    root = exports/'worldscore_output'
    files = list((root/movement).rglob('image_data.json'))
    ids = {str(p.parent.relative_to(root)) for p in files}
    if not ids or not ids <= expected or len(files) != len(ids):
        raise ValueError('Export must contain unique real official cases')
    if scope == 'full' and ids != expected:
        raise ValueError('Full metric run requires every official case in the selected split')
    if scope == 'case-smoke' and len(ids) != 1:
        raise ValueError('Case smoke requires one complete ordered sequence')
    for path in files:
        record = read_json(path.parent/'pixelworld_provenance.json')
        if record.get('producer') != 'PixelWorld' or record.get('code_revision') != CODE_REVISION:
            raise ValueError('Only provenance-checked PixelWorld exports may be scored')
        if record.get('case_id') != str(path.parent.relative_to(root)):
            raise ValueError('Case identity differs from provenance')
        frames = sorted((path.parent/'frames').glob('*.png'))
        if len(frames) != read_json(path)['total_frames']:
            raise ValueError('Export frame count is incomplete')
        if record.get('frame_sha256') != {p.name: sha256(p) for p in frames}:
            raise ValueError('Exported frame bytes changed')
    return sorted(ids)


def camera_metadata(row: dict, frames: int, output: Path, source: Path = VENDOR / "source") -> None:
    """Run pinned official analytic camera controls, not a reference renderer/model."""
    path = source / "worldscore/benchmark/helpers/camera_generator.py"
    if sha256(path) != CAMERA_HASH:
        raise ValueError("Pinned official camera source changed")
    nodes = [n for n in ast.parse(path.read_text()).body
             if not (isinstance(n, ast.ImportFrom) and (n.module or "").startswith("worldscore"))]
    import torch
    ns = {"layout_info": official_functions(source)["layout_info"],
          "type2model": {"videogen": ["pixelworld"]},
          "get_model2type": lambda d: {v: k for k, vs in d.items() for v in vs},
          "get_torch_device": lambda: torch.device("cpu")}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), ns)
    cfg = {"benchmark_root": str(output), "frames": frames, "model": "pixelworld",
           "focal_length": 500, "camera_speed": 1}
    ns["CameraGen"](cfg).generate_cameras(row["camera_path"], str(output))


def strict_aggregate(static_records: dict[str, dict], dynamic_records: dict[str, dict] | None,
                     static_ids: list[str], dynamic_ids: list[str],
                     applicable_static: dict[str, set[str]] | None = None) -> dict:
    """Exactly upstream means/rounding, with identity/schema/finite checks first."""
    if len(static_ids) != len(set(static_ids)) or len(dynamic_ids) != len(set(dynamic_ids)):
        raise ValueError("Duplicate official identities")
    if set(static_records) != set(static_ids):
        raise ValueError("Static scores must cover exact official identities")
    if dynamic_records is not None and set(dynamic_records) != set(dynamic_ids):
        raise ValueError("Dynamic scores must cover exact official identities")
    scores = {}
    for records, schema in [(static_records, STATIC), (dynamic_records, DYNAMIC)]:
        if records is None:
            continue
        if not records:
            raise ValueError("No scores")
        for aspect, metrics in schema.items():
            metric_means = []
            for metric in metrics:
                values = []
                selected = (applicable_static.get(aspect, set(records))
                            if records is static_records and applicable_static else set(records))
                if not selected or not selected <= set(records):
                    raise ValueError('Invalid metric-specific official coverage')
                for cid in selected:
                    record = records[cid]
                    try:
                        item = record[aspect][metric]
                        value = item["score_normalized"]
                        raw = item["score"]
                    except (KeyError, TypeError):
                        raise ValueError(f"Missing {aspect}/{metric} in {cid}") from None
                    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
                        raise ValueError("Normalized evaluator score must be finite in [0,1]")
                    raw_values = raw if isinstance(raw, list) else [raw]
                    if not raw_values or any(type(x) not in (int, float) or not math.isfinite(x) for x in raw_values):
                        raise ValueError("Invalid raw evaluator score")
                    values.append(value)
                metric_means.append(float(np.mean(values)))
            scores[aspect] = round(float(np.mean(metric_means)) * 100, 2)
    scores["WorldScore-Static"] = round(float(np.mean([scores[a] for a in STATIC])), 2)
    if dynamic_records is not None:
        # Dynamic leaderboard total includes seven Static + three Dynamic dimensions.
        scores["WorldScore-Dynamic"] = round(float(np.mean([scores[a] for a in STATIC | DYNAMIC])), 2)
    return scores


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    e = sub.add_parser("export")
    e.add_argument("--split", choices=["static", "dynamic"], required=True)
    e.add_argument("--metadata-index", type=int, required=True)
    e.add_argument("--index", type=Path, required=True, help="JSON list of run/provenance in segment order")
    e.add_argument("--output", type=Path, required=True)
    e.add_argument("--data", type=Path, default=VENDOR / "data/WorldScore-Dataset")
    a = sub.add_parser("aggregate")
    a.add_argument("--scores", type=Path, required=True, help="JSON {static:{case_id:record}, dynamic:{...}}")
    a.add_argument("--setting", choices=["static", "dynamic"], required=True)
    a.add_argument("--data", type=Path, default=VENDOR / "data/WorldScore-Dataset")
    a.add_argument("--output", type=Path, required=True)
    check = sub.add_parser("preflight")
    check.add_argument('--python', default=os.environ.get('WORLDSCORE_PYTHON', sys.executable))
    check.add_argument('--weights-lock', type=Path, default=VENDOR/'weights_lock.json')
    check.add_argument('--source', type=Path, default=VENDOR/'source')
    check.add_argument('--output', type=Path)
    run = sub.add_parser('run')
    run.add_argument('--exports', type=Path, required=True)
    run.add_argument('--config', type=Path, required=True, help='JSON official Evaluator path/config values')
    run.add_argument('--output', type=Path, required=True)
    run.add_argument('--split', choices=('static','dynamic'), required=True)
    run.add_argument('--scope', choices=('full','case-smoke'), default='full')
    run.add_argument('--python', default=os.environ.get('WORLDSCORE_PYTHON', sys.executable))
    run.add_argument('--weights-lock', type=Path, default=VENDOR/'weights_lock.json')
    run.add_argument('--source', type=Path, default=VENDOR/'source')
    run.add_argument('--num-jobs', type=int, default=1)
    args = p.parse_args()
    if args.command == "preflight":
        report = check_runtime(args.source, args.python, args.weights_lock)
        if args.output: write_json(args.output, report)
        print(json.dumps(report))
        if report['status'] != 'ready': raise SystemExit(2)
        return
    if args.command == 'run':
        ids = check_export_scope(args.exports, args.split, args.scope)
        report = check_runtime(args.source, args.python, args.weights_lock)
        if report['status'] != 'ready':
            print(json.dumps(report)); raise SystemExit(2)
        cfg = read_json(args.config)
        if (not cfg.get('model', '').startswith('pixelworld') or cfg.get('generate_type') != 'i2v'
                or Path(cfg['runs_root']).resolve() != args.exports.resolve()
                or cfg.get('output_dir') != 'worldscore_output'
                or cfg.get('visual_movement') != args.split):
            raise ValueError('Evaluator config must target actual PixelWorld exports and the declared split')
        code = '''import json,sys
from worldscore.benchmark.utils.modeltype import type2model
cfg=json.load(open(sys.argv[1]))
# Official model registration is metadata only; metric code/bounds stay unchanged.
if cfg['model'] not in type2model['videogen']:type2model['videogen'].append(cfg['model'])
from worldscore.benchmark.helpers.evaluator import Evaluator
Evaluator(cfg).evaluate(num_jobs=int(sys.argv[2]),use_slurm=False,
                       only_calculate_mean=False,delete_calculated_results=False)
'''
        env = os.environ.copy()
        env['PYTHONPATH'] = str(args.source.resolve()) + os.pathsep + env.get('PYTHONPATH','')
        env.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
        result = execute([args.python, '-c', code, str(args.config.resolve()), str(args.num_jobs)],
                         args.source.resolve(), args.output, env)
        result.update(scope=args.scope, case_ids=ids, metric_source_unchanged=True,
                      model_registration_only=cfg['model'])
        write_json(args.output/'execution.json', result)
        print(json.dumps(result))
        if result['returncode']: raise SystemExit(result['returncode'])
        return
    if args.command == "aggregate":
        records = read_json(args.scores)
        static_ids = [case_identity(r) for r in load_metadata(args.data, "static")]
        dynamic_ids = [case_identity(r) for r in load_metadata(args.data, "dynamic")]
        # The official evaluator skips content alignment on intra-scene camera
        # paths; missing values there are inapplicable, not failed evaluations.
        layout = official_functions()['layout_info']
        applicable = {'content_alignment': {case_identity(row) for row in load_metadata(args.data,'static')
                       if layout[row['camera_path'][0]]['layout_type'] != 'intra'}}
        result = strict_aggregate(records["static"], records["dynamic"] if args.setting == "dynamic" else None,
                                  static_ids, dynamic_ids, applicable)
        if args.output.exists():
            raise FileExistsError("Refusing to overwrite score report")
        write_json(args.output, {"scores": result, "code_revision": CODE_REVISION,
                                "setting": args.setting, "evaluation_provenance": "team_evaluated_not_organizer_verified"})
        return
    rows = load_metadata(args.data, args.split)
    if not 0 <= args.metadata_index < len(rows):
        raise ValueError("Official metadata index outside split")
    row = rows[args.metadata_index]
    cid = case_identity(row)
    count = official_functions()["get_scene_num"](row["camera_path"])
    items = [(Path(x["run"]), Path(x["provenance"])) for x in read_json(args.index)]
    external_output(args.output, [x[0] for x in items])
    chain = check_chain(items, "worldscore", cid, count)
    prompts = generation_prompts(row)
    for i, (_, prov_path) in enumerate(items):
        prov = read_json(prov_path)
        if prov.get("code_revision") != CODE_REVISION or prov.get("dataset_revision") != DATA_REVISION or prov.get("metadata_index") != args.metadata_index or prov.get("prompt") != prompts[i]:
            raise ValueError("Export must use pinned complete official scene controls")
    merged = np.concatenate([chain[0][0]] + [x[0][1:] for x in chain[1:]])
    n = count * (chain[0][1]["frames"] - 1) + 1
    if len(merged) != n:
        raise ValueError("WorldScore segment overlap convention violated")
    root = args.output / "worldscore_output" / cid
    root.mkdir(parents=True)
    frame_dir = root / "frames"; frame_dir.mkdir()
    for i, frame in enumerate(merged):
        Image.fromarray(frame).save(frame_dir / f"{i:03d}.png")
    Image.fromarray(merged[0]).save(root / "input_image.png")
    image_data = row | {"num_scenes": count, "total_frames": n}
    if args.split == "static":
        image_data["anchor_frame_idx"] = [i * (chain[0][1]["frames"] - 1) for i in range(count + 1)]
        camera_metadata(row, chain[0][1]["frames"], root)
    write_json(root / "image_data.json", image_data)
    videos = root / "videos"; videos.mkdir()
    video = export_video(merged, chain[0][1]["fps"], videos / "output.mp4")
    provenance = {"producer": "PixelWorld", "code_revision": CODE_REVISION, "case_id": cid,
               "scope": "complete_case_smoke_not_full_split", "video": video, "segments": count,
               "drop_subsequent_first_frames": True, "official_total_frames": n,
               "frame_sha256": {p.name: sha256(p) for p in frame_dir.glob('*.png')}}
    write_json(args.output / "export_manifest.json", provenance)
    write_json(root / 'pixelworld_provenance.json', provenance)
    print(json.dumps({"exported": True, "official_split_score_ready": False}))


if __name__ == "__main__":
    main()
