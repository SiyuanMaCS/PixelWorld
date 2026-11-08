#!/usr/bin/env python3
"""Fail-closed adapter for the pinned official VBench++ I2V evaluator.

Only attested PixelWorld artifacts under the generation tree are accepted.
No custom-input mode, fallback models, synthetic scores, generation or baseline
rescoring. One-pair smoke uses official metadata but is NOT a leaderboard result.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import importlib
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import uuid

try:
    from .prepare_vbench_i2v import (
        DEFAULT_SOURCE, DIMENSIONS, METADATA_SHA256, RATIOS, REPO_ROOT,
        SAMPLES_PER_PAIR, SOURCE_COMMIT, load_official_metadata, select_indices, sha256,
    )
except ImportError:
    from prepare_vbench_i2v import (
        DEFAULT_SOURCE, DIMENSIONS, METADATA_SHA256, RATIOS, REPO_ROOT,
        SAMPLES_PER_PAIR, SOURCE_COMMIT, load_official_metadata, select_indices, sha256,
    )

GENERATION_ROOT = REPO_ROOT / "runs/bench_codex_20261109/generations"
DINO_COMMIT = "7c446df5b9f45747937fb0d72314eb9f7b66930a"
COTRACKER_COMMIT = "82e02e8029753ad4ef13cf06be7f4fc5facdda4d"


def required_resources(source: Path, cache: Path, torch_home: Path,
                       dimensions: list[str]) -> list[Path]:
    """Exact official dependencies, never DINOv2/CoTracker3 or metric substitutes."""
    resources = []
    for dimension in dimensions:
        if dimension in ("i2v_subject", "subject_consistency"):
            resources += [cache / "dino_model/facebookresearch_dino_main/hubconf.py",
                          cache / "dino_model/dino_vitbase16_pretrain.pth",
                          torch_home / "hub/checkpoints/dino_vitbase16_pretrain.pth"]
        elif dimension == "camera_motion":
            resources += [torch_home / "hub/facebookresearch_co-tracker_main/hubconf.py",
                          torch_home / "hub/checkpoints/cotracker2.pth"]
        elif dimension == "i2v_background":
            resources += [torch_home / "hub/facebookresearch_dino_main/hubconf.py",
                          torch_home / "hub/checkpoints/dino_vitbase16_pretrain.pth"]
            # DreamSim explicitly resets torch.hub to its ./models directory.
            resources += [source/'models/facebookresearch_dino_main/hubconf.py',
                          source/'models/checkpoints/dino_vitbase16_pretrain.pth']
            resources += [source / "models" / name for name in (
                "dino_vitb16_pretrain.pth", "dino_vitb16_lora/adapter_model.bin",
                "dino_vitb16_lora/adapter_config.json",
                "open_clip_vitb16_pretrain.pth.tar", "open_clip_vitb16_lora/adapter_model.bin",
                "open_clip_vitb16_lora/adapter_config.json", "clip_vitb16_pretrain.pth.tar",
                "clip_vitb16_lora/adapter_model.bin", "clip_vitb16_lora/adapter_config.json",
            )]
        elif dimension == "background_consistency":
            resources += [cache / "clip_model/ViT-B-32.pt"]
        elif dimension == "motion_smoothness":
            resources += [cache / "amt_model/amt-s.pth"]
        elif dimension == "dynamic_degree":
            resources += [cache / "raft_model/models/raft-things.pth"]
        elif dimension == "aesthetic_quality":
            resources += [cache / "clip_model/ViT-L-14.pt",
                          cache / "aesthetic_model/emb_reader/sa_0_4_vit_l_14_linear.pth"]
        elif dimension == "imaging_quality":
            resources += [cache / "pyiqa_model/musiq_spaq_ckpt-358bb6af.pth"]
    return list(dict.fromkeys(resources))


def validate_resources(source: Path, dimensions: list[str], generation_root: Path = GENERATION_ROOT) -> None:
    if not os.environ.get("VBENCH_CACHE_DIR") or not os.environ.get("TORCH_HOME"):
        raise ValueError("Source vendor/vbench-i2v-night/env.sh to isolate evaluator caches")
    cache, torch_home = Path(os.environ["VBENCH_CACHE_DIR"]), Path(os.environ["TORCH_HOME"])
    if any(p.resolve().is_relative_to(generation_root.resolve()) for p in (cache, torch_home)):
        raise ValueError("Evaluator caches must remain outside generation workspaces")
    missing = [p for p in required_resources(source, cache, torch_home, dimensions)
               if not p.is_file() or p.stat().st_size == 0]
    if missing:
        raise FileNotFoundError("Missing official evaluator resources: " + "; ".join(str(p) for p in missing))
    for needed, repo, pin in [
        (bool(set(dimensions) & {"i2v_subject", "subject_consistency", "i2v_background"}),
         cache / "dino_model/facebookresearch_dino_main", DINO_COMMIT),
        ("camera_motion" in dimensions, torch_home / "hub/facebookresearch_co-tracker_main", COTRACKER_COMMIT),
    ]:
        if needed:
            actual = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
            dirty = subprocess.check_output(["git", "-C", str(repo), "diff", "HEAD", "--name-only"], text=True).strip()
            if actual != pin or dirty:
                raise ValueError("Evaluator dependency source is not the pinned pristine revision")


def validate_source(source: Path) -> None:
    commit = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if commit != SOURCE_COMMIT:
        raise ValueError("Evaluator source commit differs from the protocol pin")
    # Data and caches may be added, but official tracked source must be pristine.
    dirty = subprocess.check_output(
        ["git", "-C", str(source), "diff", "HEAD", "--name-only"], text=True,
    ).strip()
    if dirty:
        raise ValueError("Official evaluator tracked files have local changes")


def requested_scope(rows: list[dict], scope: str, pair_index: int | None,
                    dimensions: list[str] | None) -> tuple[list[int], list[str]]:
    if scope == "standard":
        if pair_index is not None or (dimensions is not None and tuple(dimensions) != DIMENSIONS):
            raise ValueError("Standard scope requires all official pairs and all ten dimensions")
        return list(range(len(rows))), list(DIMENSIONS)
    if scope != "official-data-smoke" or pair_index is None:
        raise ValueError("Smoke requires one explicit official pair index")
    select_indices(rows, [pair_index])
    dims = dimensions or [d for d in DIMENSIONS if d in rows[pair_index]["dimension"]]
    if not dims or len(dims) != len(set(dims)) or any(
        d not in DIMENSIONS or d not in rows[pair_index]["dimension"] for d in dims
    ):
        raise ValueError("Smoke dimensions must apply to the selected official pair")
    return [pair_index], dims


def validate_manifest(manifest: dict, rows: list[dict], indices: list[int],
                      generation_root: Path, ratio: str) -> list[dict]:
    """Attestation + containment + exact identities + content hashes, not filenames alone.

    Manifest paths are relative to generation_root, not machine-specific absolute
    paths. An infrastructure operator must attest that these are genuine
    PixelWorld outputs; this is not a cryptographic proof of the producer.
    """
    if (manifest.get("producer") != "PixelWorld" or
            manifest.get("benchmark") != "VBench++ I2V" or
            manifest.get("source_commit") != SOURCE_COMMIT or
            manifest.get("metadata_sha256") != METADATA_SHA256 or
            manifest.get("ratio") != ratio):
        raise ValueError("Manifest must attest PixelWorld outputs for this exact official suite and ratio")
    expected = {(i, s) for i in indices for s in range(SAMPLES_PER_PAIR)}
    artifacts = manifest.get("artifacts", [])
    found, paths, sessions = set(), set(), set()
    result = []
    for item in artifacts:
        index, sample = item.get("pair_index"), item.get("sample_index")
        if type(index) is not int or type(sample) is not int:
            raise ValueError("Pair and sample indices must be integers")
        key = (index, sample)
        if key not in expected or key in found:
            raise ValueError("Unexpected or duplicate official pair/sample")
        if item.get("prompt_en") != rows[index]["prompt_en"] or item.get("image_name") != rows[index]["image_name"]:
            raise ValueError("Artifact prompt/image does not match the official pair")
        if type(item.get("seed")) is not int:
            # API-backed coding agents may expose no sampling seed. A fresh
            # completed session proves the sample identity without inventing one.
            if item.get("seed") is not None or item.get("api_seed_status") != "not_reported":
                raise ValueError("Record a seed or independent session provenance")
            session = item.get("generation_session_id")
            try:
                uuid.UUID(session)
            except (ValueError, TypeError, AttributeError):
                raise ValueError("Independent generation session identity is missing")
            provenance = Path(item.get("run_manifest", ""))
            if provenance.is_absolute() or ".." in provenance.parts:
                raise ValueError("Run manifest must be within the generation root")
            provenance = (generation_root / provenance).resolve()
            if not provenance.is_relative_to(generation_root.resolve()) or not provenance.is_file():
                raise ValueError("Independent run manifest is missing")
            run = json.loads(provenance.read_text())
            if (run.get("status") != "complete" or run.get("validation", {}).get("pass") is not True
                    or run.get("full_trace", {}).get("thread_id") != session
                    or item.get("run_manifest_sha256") != sha256(provenance)
                    or session in sessions):
                raise ValueError("Sample is not a unique completed generation session")
            sessions.add(session)
        relative = Path(item["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Artifact paths must be relative to the generation root")
        path = (generation_root / relative).resolve()
        if not path.is_relative_to(generation_root.resolve()) or path.suffix != ".mp4":
            raise ValueError("Only PixelWorld MP4 outputs within the generation root are allowed")
        if path in paths or not path.is_file() or path.stat().st_size == 0:
            raise ValueError("Missing, empty, or reused artifact")
        if item.get("sha256") != sha256(path):
            raise ValueError("PixelWorld artifact SHA256 mismatch")
        found.add(key)
        paths.add(path)
        result.append({**item, "resolved_path": path})
    if found != expected:
        raise ValueError(f"Exactly five samples per pair required: missing {len(expected - found)}")
    return sorted(result, key=lambda a: (a["pair_index"], a["sample_index"]))


def probe_video(path: Path, ratio: str) -> dict:
    raw = subprocess.check_output([
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
        "-show_entries", "stream=width,height,nb_read_frames,avg_frame_rate",
        "-of", "json", str(path),
    ], text=True)
    streams = json.loads(raw)["streams"]
    if len(streams) != 1:
        raise ValueError("Artifact requires one readable video stream")
    info = streams[0]
    w, h = info["width"], info["height"]
    rw, rh = map(int, ratio.split("-"))
    numerator, denominator = map(int, info["avg_frame_rate"].split("/"))
    if min(w, h) <= 0 or abs(w / h - rw / rh) > 0.01 or int(info["nb_read_frames"]) < 2 or denominator <= 0 or numerator <= 0:
        raise ValueError("Video ratio/frame count/FPS is invalid for this official input crop")
    return info


def validate_metric_results(results: dict, dimensions: list[str], rows: list[dict],
                            indices: list[int], scope: str) -> dict:
    """Camera returns [mean, type_means, videos]; other metrics return two items."""
    if set(results) != set(dimensions):
        raise ValueError('Official evaluator returned an incomplete dimension set')
    extra = {}
    for dim, result in results.items():
        count = sum(dim in rows[i]['dimension'] for i in indices) * 5
        if (not isinstance(result, list) or len(result) != (3 if dim == 'camera_motion' else 2)
                or type(result[0]) not in (int,float) or not math.isfinite(result[0])):
            raise ValueError(f'Incomplete or nonfinite official result for {dim}')
        videos = result[2] if dim == 'camera_motion' else result[1]
        if not isinstance(videos,list) or len(videos) != count:
            raise ValueError(f'Incomplete official per-video results for {dim}')
        if dim == 'camera_motion':
            expected = {'pan_left','pan_right','tilt_up','tilt_down','zoom_in','zoom_out','static'}
            groups = result[1]
            present = {v.get('prompt_type') for v in videos}
            if not isinstance(groups,dict) or set(groups) != expected or not present <= expected:
                raise ValueError('Official camera-motion category schema changed')
            for key in present:
                if type(groups[key]) not in (int,float) or not math.isfinite(groups[key]):
                    raise ValueError('Nonfinite represented camera category')
            if scope == 'standard' and present != expected:
                raise ValueError('Standard camera-motion suite omitted categories')
            if any(type(v.get('video_results')) not in (int,float) or not math.isfinite(v['video_results']) for v in videos):
                raise ValueError('Invalid camera per-video score')
            extra['camera_motion_coverage'] = {'represented_categories': sorted(present),
                                              'unrepresented_categories': sorted(expected-present),
                                              'unused_raw_category_nan_retained': scope != 'standard'}
    return extra


def official_aggregate(results: dict, provenance: dict, source: Path) -> dict:
    """Use unchanged official normalizers/weights only after full scope checks."""
    if (provenance.get('scope') != 'standard' or provenance.get('status') != 'complete'
            or provenance.get('pair_count') != 1118 or provenance.get('samples_per_pair') != 5
            or provenance.get('source_commit') != SOURCE_COMMIT
            or provenance.get('metadata_sha256') != METADATA_SHA256):
        raise ValueError('Aggregate leaderboard score requires completed full official1118x5 scope')
    validate_source(source)
    rows = load_official_metadata(source/'vbench2_beta_i2v/vbench2_i2v_full_info.json')
    validate_metric_results(results,list(DIMENSIONS),rows,list(range(len(rows))),'standard')
    script = source/'scripts/cal_i2v_final_score.py'
    path = str(script.parent.resolve())
    previous = list(sys.path)
    try:
        sys.path.insert(0,path)
        spec = importlib.util.spec_from_file_location('pixelworld_official_i2v_aggregation',script)
        module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        # Do not call submission(), which fills absent metrics with zeros.
        if not set(module.I2VKEY) <= set(results):
            raise ValueError('Missing official leaderboard metric')
        upload = {module.I2VKEY[key]:results[key][0] for key in module.I2VKEY}
        if any(type(x) not in (int,float) or not math.isfinite(x) for x in upload.values()):
            raise ValueError('Invalid official aggregate input')
        normalized = module.get_nomalized_score(upload)
        quality = module.get_i2v_quality_score(normalized)
        i2v = module.get_i2v_score(normalized)
        total = module.get_final_score(quality,i2v)
        return {'scope':'full-official-i2v-suite','source_commit':SOURCE_COMMIT,
                'quality_score':quality*100,'i2v_score':i2v*100,'total_score':total*100,
                'official_aggregation_script_sha256':sha256(script),
                'official_constants_sha256':sha256(script.parent/'constant.py'),
                'omitted_extra_raw_metrics':sorted(set(results)-set(module.I2VKEY)),
                'organizer_published':False,'no_missing_value_imputation':True}
    finally:
        sys.path[:] = previous


@contextmanager
def source_workdir(source: Path):
    previous = Path.cwd()
    os.chdir(source)
    try:
        yield
    finally:
        os.chdir(previous)


def execute_official(source: Path, output: Path, rows: list[dict], indices: list[int],
                     dimensions: list[str], artifacts: list[dict], ratio: str,
                     scope: str, evaluator_class=None) -> Path:
    """Stage exact standard filenames outside generation; call unchanged official API."""
    if output.exists():
        raise FileExistsError("Use a new evaluation output directory; no rescoring overwrite")
    output.mkdir(parents=True)
    videos = output / "pixelworld_videos"
    videos.mkdir()
    for artifact in artifacts:
        name = f'{rows[artifact["pair_index"]]["prompt_en"]}-{artifact["sample_index"]}.mp4'
        (videos / name).symlink_to(artifact["resolved_path"])
    metadata = source / "vbench2_beta_i2v/vbench2_i2v_full_info.json"
    if scope != "standard":
        metadata = output / "official_smoke_subset.json"
        metadata.write_text(json.dumps([rows[i] for i in indices], indent=2) + "\n")
    record = {
        "benchmark": "VBench++ I2V", "source_commit": SOURCE_COMMIT,
        "metadata_sha256": METADATA_SHA256, "mode": "vbench_standard",
        "scope": scope, "leaderboard_result": False,
        "dimensions": dimensions, "pair_count": len(indices),
        "samples_per_pair": 5, "ratio": ratio, "status": "started",
        "note": "Even full local evaluation is not an official leaderboard publication.",
    }
    record_path = output / "evaluation_provenance.json"
    record_path.write_text(json.dumps(record, indent=2) + "\n")
    try:
        if evaluator_class is None:
            evaluator_class = importlib.import_module("vbench2_beta_i2v").VBenchI2V
        with source_workdir(source):
            evaluator = evaluator_class("cuda", str(metadata), str(output))
            evaluator.evaluate(
                videos_path=str(videos), name="pixelworld", dimension_list=dimensions,
                resolution=ratio, mode="vbench_standard", local=True, read_frame=False,
                imaging_quality_preprocessing_mode="longer",
            )
        result_path = output / "pixelworld_eval_results.json"
        results = json.loads(result_path.read_text())
        record.update(validate_metric_results(results, dimensions, rows, indices, scope))
        record["status"] = "complete"
        record["results_sha256"] = sha256(result_path)
        if scope == 'standard':
            score = official_aggregate(results, record, source)
            (output/'official_aggregate_score.json').write_text(json.dumps(score,indent=2)+'\n')
    except Exception as exc:
        record["status"] = "failed"
        record["error_type"] = type(exc).__name__
        raise
    finally:
        record_path.write_text(json.dumps(record, indent=2) + "\n")
    return result_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument('--generation-root', type=Path, default=GENERATION_ROOT,
                        help='Root for manifest-relative PixelWorld artifacts; configurable on another host')
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ratio", choices=RATIOS, default="16-9")
    parser.add_argument("--scope", choices=("standard", "official-data-smoke"), default="standard")
    parser.add_argument("--pair-index", type=int)
    parser.add_argument("--dimensions", nargs="+", choices=DIMENSIONS)
    parser.add_argument("--preflight", action="store_true", help="Validate only; never load evaluator models or score")
    args = parser.parse_args()
    source, output, generation_root = args.source.resolve(), args.output.resolve(), args.generation_root.resolve()
    if output.is_relative_to(generation_root) or source.is_relative_to(generation_root):
        raise ValueError("Evaluator source/results must not be inside generation workspaces")
    validate_source(source)
    rows = load_official_metadata(source / "vbench2_beta_i2v/vbench2_i2v_full_info.json")
    indices, dimensions = requested_scope(rows, args.scope, args.pair_index, args.dimensions)
    artifacts = validate_manifest(json.loads(args.manifest.read_text()), rows, indices, generation_root, args.ratio)
    for index in indices:
        image = source / "vbench2_beta_i2v/data/crop" / args.ratio / rows[index]["image_name"]
        if not image.is_file():
            raise FileNotFoundError(f"Missing official crop: {image.name}")
    media = [probe_video(a["resolved_path"], args.ratio) for a in artifacts]
    if len({(m["width"], m["height"], m["nb_read_frames"], m["avg_frame_rate"]) for m in media}) != 1:
        raise ValueError("A single evaluation manifest must use consistent media settings")
    validate_resources(source, dimensions, generation_root)
    print(json.dumps({"validated_pairs": len(indices), "videos": len(artifacts),
                      "dimensions": dimensions, "scope": args.scope, "scores_computed": False}))
    if args.preflight:
        return
    sys.path.insert(0, str(source))
    import torch
    if not torch.cuda.is_available():
        raise RuntimeError("GPU-only evaluator checks pending: CUDA is unavailable; no CPU/model fallback")
    execute_official(source, output, rows, indices, dimensions, artifacts, args.ratio, args.scope)


if __name__ == "__main__":
    main()
