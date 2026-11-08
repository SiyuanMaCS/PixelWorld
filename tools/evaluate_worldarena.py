#!/usr/bin/env python3
"""Fail-closed adapter for the UNCHANGED pinned WorldArena Track 1 scorers.

No model generation, no substitute judge, no permissive missing-field average.
`full` requires all 1000 TEST episodes. `one-episode-smoke` never emits a
leaderboard total. A named CSV compatibility export fixes only two verified
field-name defects while preserving the original metric computations.
"""
from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import importlib.util
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

try:
    from tools.prepare_worldarena import (ARCHIVE_SHA256, DATASET_REVISION, OFFICIAL_PREFIX,
                                         SOURCE_COMMIT, SPEC, archive_index, episode_inventory,
                                         sha256, write_json)
except ModuleNotFoundError:
    from prepare_worldarena import (ARCHIVE_SHA256, DATASET_REVISION, OFFICIAL_PREFIX,
                                   SOURCE_COMMIT, SPEC, archive_index, episode_inventory,
                                   sha256, write_json)

REFERENCE_REVISION = "7b368882024e8ebc7658e01d57d65fdb58fe788b"
REFERENCE_SHA256 = "f7765dae0785b9cf6f9ac46bbd090157d768b5a8a5145a6cb93ef8f5dfcddb15"
BOARD_SHA256 = "7646a29c01f0ccf8010a2cc6c25f0d50874de143f9cf6d29126aa2a46e27d014"
HF_MODEL_MANIFEST = Path(__file__).resolve().parents[1] / "configs/evaluation/worldarena-hf-models.json"
CORE = {
    "image_quality": "Image Quality", "aesthetic_quality": "Aesthetic Quality",
    "dynamic_degree": "Dynamic Degree", "flow_score": "Flow Score",
    "motion_smoothness": "Motion Smoothness", "subject_consistency": "Subject Consistency",
    "background_consistency": "Background Consistency", "photometric_smoothness": "Photometric Consistency",
    "trajectory_accuracy": "Trajectory Accuracy", "depth_accuracy": "Depth Accuracy",
    "semantic_alignment": "Semantic Alignment",
}
VLM = {"Interaction_Quality": "Interaction Quality", "Perspectivity": "Perspectivity",
       "Instruction_Following": "Instruction Following"}
BOARD_FIELDS = ["Image Quality", "Aesthetic Quality", "JEPA Similarity", "Dynamic Degree",
                "Flow Score", "Motion Smoothness", "Subject Consistency", "Background Consistency",
                "Photometric Consistency", "Interaction Quality", "Trajectory Accuracy", "Depth Accuracy",
                "Perspectivity", "Instruction Following", "Semantic Alignment"]


def load_json(path: Path):
    # Reject duplicate fields and NaN/Infinity before any aggregation.
    def unique(pairs):
        result = {}
        for k, v in pairs:
            if k in result:
                raise ValueError(f"Duplicate JSON field: {k}")
            result[k] = v
        return result
    return json.loads(path.read_text(), object_pairs_hook=unique,
                      parse_constant=lambda v: (_ for _ in ()).throw(ValueError(f"Nonfinite JSON: {v}")))


def check_source(source: Path) -> None:
    head = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if head != SOURCE_COMMIT:
        raise ValueError("Official source commit mismatch")
    # Tracked official files must remain byte-for-byte unchanged. Generated caches are irrelevant.
    subprocess.run(["git", "-C", str(source), "diff", "--exit-code", "HEAD", "--"],
                   check=True, stdout=subprocess.DEVNULL)


def check_legal(legal: Path, provenance: Path) -> dict:
    p = load_json(provenance)
    if {x.name for x in legal.iterdir()} != {"first_frame.png", "prompt.txt", "task_spec.json"}:
        raise ValueError("Legal directory contains extra/missing files")
    if any(x.is_symlink() or not x.is_file() for x in legal.iterdir()):
        raise ValueError("Legal inputs must be regular files, not reference links")
    if p["dataset_revision"] != DATASET_REVISION or p["archive_sha256"] != ARCHIVE_SHA256:
        raise ValueError("Legal provenance pin mismatch")
    if p["split"] != "TEST" or p["reference_future_accessed"] is not False:
        raise ValueError("Invalid legal input provenance")
    for name, key in [("first_frame.png", "first_frame_sha256"), ("prompt.txt", "prompt_sha256"),
                      ("task_spec.json", "task_spec_sha256")]:
        if sha256(legal / name) != p[key]:
            raise ValueError(f"Legal input hash mismatch: {name}")
    prompt = (legal / "prompt.txt").read_text()
    if not prompt.startswith(OFFICIAL_PREFIX) or prompt.count(OFFICIAL_PREFIX) != 1:
        raise ValueError("Original instruction prefix changed")
    if load_json(legal / "task_spec.json") != SPEC:
        raise ValueError("Media/task contract mismatch")
    from PIL import Image
    with Image.open(legal / "first_frame.png") as img:
        if img.size != (640, 480) or img.mode != "RGB":
            raise ValueError("Legal initial image contract mismatch")
    return p


def select_episodes(scope: str, episode: str) -> list[str]:
    if not re.fullmatch(r"episode(?:[1-9][0-9]{0,2}|1000)", episode):
        raise ValueError("Invalid TEST episode")
    if scope == "full":
        return [f"episode{i}" for i in range(1, 1001)]
    if scope == "one-episode-smoke":
        return [episode]
    raise ValueError("Scope must be explicit")


def external_filename(episode: str) -> str:
    return f"fixed_scene_task_episode_{episode[7:]}.mp4"


def internal_id(episode: str) -> str:
    return f"fixed_scene_task_{episode}"


def check_video(path: Path) -> dict:
    import av
    with av.open(str(path)) as c:
        if len(c.streams.video) != 1 or c.streams.audio:
            raise ValueError(f"Expected one video stream, no audio: {path.name}")
        s = c.streams.video[0]
        if s.width != 640 or s.height != 480 or s.average_rate != 24:
            raise ValueError(f"Expected 640x480 / 24fps: {path.name}")
        count = 0
        last_time = None
        for frame in c.decode(s):
            if frame.pts is None:
                raise ValueError(f"Missing frame timestamps: {path.name}")
            time = frame.pts * frame.time_base
            if last_time is not None and abs(float(time - last_time) - 1 / 24) > 1e-6:
                raise ValueError(f"Non-24fps frame timestamps: {path.name}")
            last_time = time
            count += 1
        if count != 121:
            raise ValueError(f"Expected exactly 121 decodable frames: {path.name}, got {count}")
    return {"sha256": sha256(path), "frames": count, "fps": 24, "width": 640, "height": 480}


def check_submission(videos: Path, model: str, episodes: list[str], decode: bool = True,
                     variant: int = 0) -> dict:
    expected_dir = model + "_test" + (f"_{variant}" if variant else "")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", model) or videos.name != expected_dir:
        raise ValueError("Generated directory must be exactly <model>_test")
    expected = {external_filename(e) for e in episodes}
    if {p.name for p in videos.iterdir()} != expected:
        raise ValueError("Submission scope/filenames mismatch (no extras, nesting, padding or missing episodes)")
    if any(not p.is_file() or p.is_symlink() for p in videos.iterdir()):
        raise ValueError("Submission must contain regular generated videos only")
    return {p.name: check_video(p) if decode else {} for p in sorted(videos.iterdir())}


def source_contract(source: Path, board: Path) -> dict:
    check_source(source)
    if sha256(board) != BOARD_SHA256:
        raise ValueError("Official leaderboard implementation content pin mismatch")
    tree = ast.parse(board.read_text())
    fields = next(ast.literal_eval(n.value) for n in tree.body
                  if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "BASIC_METRICS"
                                                     for t in n.targets))
    if fields != BOARD_FIELDS:
        raise ValueError("Leaderboard field coverage changed")
    agg = source / "video_quality/csv_results/aggregate_results.py"
    text = agg.read_text()
    blockers = []
    if 'row["JEPA_Similarity"] = jepa_score' in text and '"JEPA Similarity"' in text:
        blockers.append("official-aggregator-JEPA_Similarity-not-in-COLUMN_ORDER: DictWriter raises ValueError")
    if '"photometric_consistency": "Photometric Consistency"' in text and '"photometric_smoothness"' not in text:
        blockers.append("official-aggregator-does-not-map-scorer-photometric_smoothness-to-Photometric-Consistency")
    return {"board_fields": fields, "board_field_count": len(fields), "official_csv_metric_count": 16,
            "board_excludes": ["Action Following"], "known_upstream_blockers": blockers,
            "guideline_aggregation": "arithmetic mean of all indicators * 100",
            "board_aggregation": "per-field mean rounded 4 decimals; percent rounded 2; mean 15 percent fields rounded 2",
            "full_total_allowed": False if blockers else True}


def preflight(source: Path, board: Path) -> dict:
    contract = source_contract(source, board)
    modules = ["decord", "pyiqa", "clip", "sam3", "transformers", "videojedi", "vjepa", "fastdtw"]
    missing = [m for m in modules if importlib.util.find_spec(m) is None]
    import torch
    return {"source_commit": SOURCE_COMMIT, "dataset_revision": DATASET_REVISION,
            "official_test_count": 1000, "contract": contract,
            "missing_modules_current_python": missing, "cuda_available": torch.cuda.is_available(),
            "python": sys.version.split()[0], "no_generation_launched": True, "official_score": None}


def verify_hf_checkpoint(directory: Path, pin: dict) -> dict[str, str]:
    """Verify official config, tokenizer and all shards; no invented config field."""
    verified = {}
    for name, meta in pin["files"].items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Unsafe canonical model file path")
        path = directory / relative
        if not path.is_file() or path.stat().st_size != meta["bytes"]:
            raise ValueError(f"Missing/incomplete canonical model file: {pin['repo_id']}/{name}")
        sha = hashlib.sha256()
        git = hashlib.sha1()
        git.update(b"blob " + str(path.stat().st_size).encode() + b"\0")
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
                sha.update(block)
                git.update(block)
        algorithm = meta["hash_algorithm"]
        actual = sha.hexdigest() if algorithm == "sha256" else git.hexdigest()
        if algorithm not in ("sha256", "git-blob-sha1") or actual != meta["digest"]:
            raise ValueError(f"Canonical model object hash mismatch: {pin['repo_id']}/{name}")
        verified[str(path.resolve())] = sha.hexdigest()
    return verified


def check_weight_lock(lock: Path, cfg: dict) -> None:
    """Only provisioned, hashed official checkpoints; never silently select another VLM."""
    data = load_json(lock)
    if data["source_commit"] != SOURCE_COMMIT or data["ckpt"] != cfg["ckpt"]:
        raise ValueError("Checkpoint lock does not match official source/config")
    required = {"vlm": "Qwen/Qwen3-VL-8B-Instruct", "caption": "Qwen/Qwen2.5-VL-7B-Instruct",
                "jepa": "https://dl.fbaipublicfiles.com/jepa/vith16/"}
    if data["model_identities"] != required or not data["artifacts"]:
        raise ValueError("Pinned official judge/JEPA identities required; no replacement judge")
    pins = load_json(HF_MODEL_MANIFEST)["models"]
    verified = {}
    for role, directory in [("vlm", Path(cfg["ckpt"]["vlm_model"])),
                            ("caption", Path(cfg["ckpt"]["semantic_alignment"]["caption"]))]:
        if pins[role]["repo_id"] != required[role] or not pins[role].get("revision"):
            raise ValueError("Canonical HF model revision/identity mismatch")
        verified.update(verify_hf_checkpoint(directory, pins[role]))
    for artifact in data["artifacts"]:
        path = Path(artifact["path"])
        actual = verified.get(str(path.resolve())) or sha256(path)
        if "legal_inputs" in path.resolve().parts or actual != artifact["sha256"]:
            raise ValueError("Weight artifact missing/mutated or inside legal input")


def archive_payloads(archive: Path, index: dict, selected: set[str]) -> dict[str, bytes]:
    """Read validated members in one pass, without repeatedly seeking gzip."""
    if not selected <= set(index):
        raise ValueError("Required aligned archive members are missing")
    names = {index[key].name: key for key in selected}
    payloads = {}
    with tarfile.open(archive, "r|gz") as stream:
        for member in stream:
            key = names.get(member.name)
            if key is not None:
                if key in payloads or not member.isfile() or member.issym() or member.islnk():
                    raise ValueError("Invalid or duplicate selected archive member")
                payloads[key] = stream.extractfile(member).read()
    if set(payloads) != selected:
        raise ValueError("Selected archive members are incomplete")
    return payloads


def stage_inputs(archive: Path, references: Path, videos: Path, work: Path, episodes: list[str]) -> None:
    if "legal_inputs" in work.resolve().parts or "legal_inputs" in references.resolve().parts:
        raise ValueError("Reference/staged evaluation data cannot be in legal_inputs")
    if sha256(archive) != ARCHIVE_SHA256 or sha256(references) != REFERENCE_SHA256:
        raise ValueError("Input/reference archive pins mismatch")
    # Reference root cannot be inside the legal directory. All staging is eval-only.
    with tarfile.open(archive) as t, tarfile.open(references) as rt:
        idx, ridx = archive_index(t), archive_index(rt)
        episode_inventory(idx)
    # Verify every one of the 4000 image/instruction assets byte-for-byte.
    # Repeated random access to gzip can reread hundreds of GB for this check.
    assets = {key for key in idx if key.startswith(("first_frame/", "instructions/",
                                                  "instructions_1/", "instructions_2/"))}
    initial = archive_payloads(archive, idx, assets)
    reference = archive_payloads(references, ridx, assets | {f"video/{e}.mp4" for e in episodes})
    if any(initial[key] != reference[key] for key in assets):
        raise ValueError("Later public GT archive is not aligned with pinned March 6 inputs")
    work.mkdir(parents=True, exist_ok=False)
    core_summary, vlm_summary = [], []
    for e in episodes:
        name = internal_id(e) + ".mp4"
        gen = work / (videos.name) / name
        gen.parent.mkdir(exist_ok=True)
        shutil.copyfile(videos / external_filename(e), gen)
        if len(episodes) == 1000:
            # All 16 local indicators require the official two action-prompt variants.
            for variant in (1, 2):
                variant_dir = work / (videos.name + f"_{variant}")
                variant_dir.mkdir(exist_ok=True)
                shutil.copyfile(videos.parent / (videos.name + f"_{variant}") / external_filename(e),
                                variant_dir / name)
        # Official preprocess uses parts[-5] for task, basename for episode.
        gt = work / "gt_layout/fixed_scene_task/a/b/video" / (e + ".mp4")
        gt.parent.mkdir(parents=True, exist_ok=True)
        gt.write_bytes(reference[f"video/{e}.mp4"])
        flat = work / "gt_flat" / name
        flat.parent.mkdir(exist_ok=True)
        os.link(gt, flat)
        image = work / "initial_images" / (e + ".png")
        image.parent.mkdir(exist_ok=True)
        image.write_bytes(initial[f"first_frame/fixed_scene_task/{e}.png"])
        prompt = json.loads(initial[f"instructions/fixed_scene_task/{e}.json"])["instruction"]
        row = {"gt_path": str(gt.resolve()), "image": str(image.resolve()), "prompt": [prompt]}
        core_summary.append(row)
        vlm_summary.append({**row, "gt_path": str(flat.resolve())})
    write_json(work / "summary_core.json", core_summary)
    write_json(work / "summary_vlm.json", vlm_summary)
    immutable = {str(p.relative_to(work)): sha256(p) for p in work.rglob("*") if p.is_file()}
    write_json(work / "staging_provenance.json", {"reference_revision": REFERENCE_REVISION,
               "reference_sha256": REFERENCE_SHA256, "input_revision": DATASET_REVISION,
               "aligned_input_assets": 4000, "episodes": episodes, "reference_data_eval_only": True,
               "staged_file_sha256": immutable})


def check_staged(work: Path, model: str, episodes: list[str]) -> None:
    p = load_json(work / "staging_provenance.json")
    if (p["episodes"] != episodes or p["input_revision"] != DATASET_REVISION
            or p["reference_sha256"] != REFERENCE_SHA256 or p["aligned_input_assets"] != 4000
            or p["reference_data_eval_only"] is not True):
        raise ValueError("Staged evaluation scope/provenance mismatch")
    for name, digest in p["staged_file_sha256"].items():
        path = work / name
        if not path.resolve().is_relative_to(work.resolve()) or sha256(path) != digest:
            raise ValueError("Staged generated/reference/input bytes changed")
    expected = {internal_id(e) + ".mp4" for e in episodes}
    dirs = [work / (model + "_test"), work / "gt_flat"]
    if len(episodes) == 1000:
        dirs += [work / (model + f"_test_{v}") for v in (1, 2)]
    for folder in dirs:
        if {p.name for p in folder.iterdir()} != expected:
            raise ValueError("Staged evaluation exact filename coverage mismatch")


def scorer_commands(source: Path, work: Path, model: str, config: Path,
                    base_python: str, vlm_python: str, jepa_python: str,
                    include_action: bool = False) -> list[tuple[Path, list[str]]]:
    """Direct unchanged Python entrypoints avoid shell hardcoded env/path placeholders."""
    vq = source / "video_quality"
    gen = str(work / (model + "_test"))
    cfg = str(config)
    commands = [
        (vq, [base_python, "preprocess_datasets.py", "--summary_json", str(work / "summary_core.json"),
              "--gen_video_dir", gen, "--output_base", str(work / "data")]),
        (vq, [base_python, "processing/video_resize.py", "--config_path", cfg]),
        (vq, [base_python, "processing/detection_tracking.py", "--config_path", cfg, "--detect_gt"]),
        (vq, [base_python, "processing/detection_tracking.py", "--config_path", cfg]),
        (vq, [base_python, "evaluate.py", "--dimension", *CORE, "--config", cfg, "--overwrite"]),
        (vq, [vlm_python, "VLM_judge.py", "--model_name", model, "--video_dir", gen,
              "--summary_json", str(work / "summary_vlm.json"), "--metrics", "all", "--num_frames", "16",
              "--output_root", str(work / "output_VLM"), "--tmp_root", str(work / "tmp_VLM"),
              "--config_path", cfg]),
        (vq / "JEDi", [jepa_python, "batch.py", "--real_dir", str(work / "gt_flat"), "--gen_dir", gen,
                       "--output_root", str(work / "output_JEDi"), "--save_intersection", str(work / "intersection_names.json")]),
    ]
    if include_action:
        commands += [
            (vq, [base_python, "preprocess_datasets_diversity.py", "--summary_json", str(work / "summary_core.json"),
                  "--gen_video_dir", gen, "--output_base", str(work / "data_action_following")]),
            (vq, [base_python, "evaluate.py", "--dimension", "action_following", "--config", cfg, "--overwrite"]),
        ]
    return commands


def numeric(value, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError(f"Missing/non-normalized metric: {label}")
    return float(value)


def check_raw_results(work: Path, model: str, episodes: list[str], include_action: bool = False) -> None:
    expected = {internal_id(e) for e in episodes}
    core = load_json(work / "output/generated_results.json")
    if set(core) - {"logics"} != set(CORE):
        raise ValueError("Exact core metric fields required")
    for key in CORE:
        payload = core[key]
        if not isinstance(payload, list) or len(payload) != 2 or not isinstance(payload[1], list):
            raise ValueError("Unexpected official metric payload")
        ids = []
        for row in payload[1]:
            parts = Path(row["video_path"]).parts
            anchor = parts.index("generated_dataset")
            ident = parts[anchor + 1] + "_" + parts[anchor + 2]
            ids.append(ident)
            numeric(row["video_results_normalized"], key)
        if set(ids) != expected or len(ids) != len(expected):
            raise ValueError(f"Incomplete/duplicate core episode coverage: {key}")
    vlm_dir = work / "output_VLM" / model
    files = list(vlm_dir.iterdir())
    filename = f"{model}_summary_val_all_intern.json"
    if {p.name for p in files} != {filename}:
        raise ValueError("Unexpected VLM result files")
    rows = load_json(vlm_dir / filename)
    if len(rows) != len(expected) or {Path(r["video"]).stem for r in rows} != expected:
        raise ValueError("Incomplete/duplicate VLM episode coverage")
    for row in rows:
        if row.get("error") or set(row["metrics"]) != set(VLM):
            raise ValueError("Official VLM judge failed or omitted fields")
        for key, score in row["metrics"].items():
            n = numeric(score["score_normalized"], key)
            if type(score["score"]) is not int or not 1 <= score["score"] <= 5 or n != round(score["score"] / 5, 4):
                raise ValueError("VLM raw/normalized score mismatch")
    jepa = load_json(work / "output_JEDi/results.json")
    numeric(jepa["score"], "JEPA Similarity")
    names = load_json(work / "intersection_names.json")
    if len(names) != len(expected) or set(names) != expected:
        raise ValueError("JEPA scorer silently dropped pairs")
    if include_action:
        action = load_json(work / "output_action_following/generated_results.json")
        if set(action) != {"action_following"}:
            raise ValueError("Exact Action Following metric required for full 16-indicator local scope")
        rows = action["action_following"][1]
        ids = []
        for row in rows:
            parts = Path(row["video_path"]).parts
            anchor = parts.index("generated_dataset")
            ids.append(parts[anchor + 1] + "_" + parts[anchor + 2])
            numeric(row["video_results_normalized"], "Action Following")
        if len(ids) != len(expected) or set(ids) != expected:
            raise ValueError("Incomplete/duplicate Action Following episode coverage")


def aggregate_official(source: Path, work: Path, model: str, episodes: list[str], board: Path,
                       scope: str) -> dict:
    check_raw_results(work, model, episodes, include_action=scope == "full")
    # Never patch the official CSV writer's bugs or fill its omitted fields.
    subprocess.run([sys.executable, str(source / "video_quality/csv_results/aggregate_results.py"),
                    "--base_dir", str(work), "--model_name", model], check=True)
    with (work / "csv_results/aggregated_results.csv").open() as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != ["Model_Name", "Video_ID", "Subject Consistency", "Aesthetic Quality", "Image Quality",
                                 "Background Consistency", "Dynamic Degree", "Interaction Quality", "Perspectivity",
                                 "Instruction Following", "Semantic Alignment", "Action Following", "Flow Score",
                                 "Depth Accuracy", "Trajectory Accuracy", "Photometric Consistency", "Motion Smoothness", "JEPA Similarity"]:
            raise ValueError("Official CSV schema changed")
        rows = list(reader)
    if len(rows) != len(episodes) or {r["Video_ID"] for r in rows} != {internal_id(e) for e in episodes}:
        raise ValueError("Official CSV episode coverage mismatch")
    for r in rows:
        if r["Model_Name"] != model:
            raise ValueError("Official CSV model identity mismatch")
        for field in BOARD_FIELDS:
            numeric(float(r[field]), field)
        if scope == "full":
            numeric(float(r["Action Following"]), "Action Following")
    # This pin has known aggregation blockers: no total is allowed even if a partial file exists.
    contract = source_contract(source, board)
    if contract["known_upstream_blockers"]:
        raise ValueError("Pinned official aggregation is blocked; no substitute/fabricated total")
    if scope != "full":
        return {"label": "one-episode-smoke-NOT-leaderboard", "official_score": None}
    raise ValueError("Upstream aggregation contract changed: explicit new protocol required")


def aggregate_compatible(source: Path, work: Path, model: str, episodes: list[str],
                         board: Path, scope: str) -> dict:
    """Two documented key substitutions; no metric or normalization changes.

    Full retains all 1000 episodes and required Action Following outputs. The
    returned comparison score follows the public board's 15-field formula.
    This does not certify publication or silently reduce generation scope.
    """
    if scope == 'full' and episodes != select_episodes('full', 'episode1'):
        raise ValueError('Full comparison requires all 1000 TEST episodes')
    check_source(source)
    if sha256(board) != BOARD_SHA256:
        raise ValueError('Public leaderboard implementation pin mismatch')
    check_raw_results(work, model, episodes, include_action=scope == 'full')
    original = source/'video_quality/csv_results/aggregate_results.py'
    text = original.read_text()
    replacements = [
        ('row["JEPA_Similarity"] = jepa_score', 'row["JEPA Similarity"] = jepa_score'),
        ('"photometric_consistency": "Photometric Consistency"',
         '"photometric_smoothness": "Photometric Consistency"'),
    ]
    for old, new in replacements:
        if text.count(old) != 1:
            raise ValueError('Official exporter changed; compatibility substitutions require re-audit')
        text = text.replace(old, new)
    compat = work/'csv_compatibility'
    compat.mkdir(exist_ok=True)
    script = compat/'aggregate_results.py'
    script.write_text(text)
    provenance = {'protocol': 'worldarena-csv-key-compat-v1', 'metric_source_commit': SOURCE_COMMIT,
                  'original_exporter_sha256': sha256(original), 'compatible_exporter_sha256': sha256(script),
                  'replacements': replacements, 'metric_math_unchanged': True,
                  'board_sha256': BOARD_SHA256, 'scope': scope, 'episodes': len(episodes),
                  'no_missing_metric_imputation': True}
    write_json(compat/'provenance.json', provenance)
    subprocess.run([sys.executable, str(script), '--base_dir', str(work), '--model_name', model], check=True)
    output = work/'csv_results/aggregated_results.csv'
    with output.open() as handle:
        rows = list(csv.DictReader(handle))
    expected = {internal_id(e) for e in episodes}
    if len(rows) != len(expected) or {r['Video_ID'] for r in rows} != expected:
        raise ValueError('Complete unique episode coverage required')
    for row in rows:
        if row['Model_Name'] != model:
            raise ValueError('Model identity mismatch')
        for field in BOARD_FIELDS:
            numeric(float(row[field]), field)
        if scope == 'full':
            numeric(float(row['Action Following']), 'Action Following')
    result = {'protocol': provenance['protocol'], 'scope': scope, 'raw_metrics_complete': True,
              'organizer_verified': False, 'official_score': None,
              'compatibility_provenance': str(compat/'provenance.json')}
    if scope != 'full':
        return {**result, 'label': 'one-episode-smoke-NOT-leaderboard', 'local_board_score': None}
    # Use the pinned public implementation itself after checking every field;
    # its permissive missing-field handling cannot conceal missing data here.
    spec = importlib.util.spec_from_file_location('pixelworld_pinned_worldarena_board', board)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    loader = module.DataLoader(str(work/'csv_results'))
    import pandas as pd
    row = loader._load_table_file(str(output), model)
    scored = loader._process_data(pd.DataFrame([row]))
    if len(scored) != 1:
        raise ValueError('Public board did not produce exactly one model row')
    result.update(local_board_score=float(scored.iloc[0]['EWMScore']),
                  metric_fields=BOARD_FIELDS, published_board_metric_count=len(BOARD_FIELDS))
    return result


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=["preflight", "validate-legal", "stage", "plan", "run", "aggregate", "aggregate-compatible"])
    p.add_argument("--source", type=Path, default=Path("vendor/worldarena-eval-night/source"))
    p.add_argument("--board", type=Path, default=Path("vendor/worldarena-eval-night/leaderboard/data_loader.py"))
    p.add_argument("--scope", choices=["full", "one-episode-smoke"])
    p.add_argument("--episode", default="episode1")
    p.add_argument("--model", default="pixelworld_codex")
    p.add_argument("--videos", type=Path)
    p.add_argument("--legal", type=Path)
    p.add_argument("--provenance", type=Path)
    p.add_argument("--archive", type=Path)
    p.add_argument("--references", type=Path)
    p.add_argument("--work", type=Path)
    p.add_argument("--config", type=Path)
    p.add_argument("--weights-lock", type=Path, default=Path("vendor/worldarena-eval-night/weights_lock.json"))
    p.add_argument("--base-python", default=sys.executable)
    p.add_argument("--vlm-python", default=sys.executable)
    p.add_argument("--jepa-python", default=sys.executable)
    p.add_argument("--output", type=Path)
    args = p.parse_args()
    try:
        source, board = args.source.resolve(), args.board.resolve()
        if args.command == "validate-legal":
            result = {"legal_inputs_valid": True, "provenance": check_legal(args.legal, args.provenance)}
        elif args.command == "preflight":
            result = preflight(source, board)
        else:
            if not args.scope:
                raise ValueError("--scope is required; smoke must never default to full")
            episodes = select_episodes(args.scope, args.episode)
            work = args.work.resolve()
            check_source(source)
            if args.command == "stage":
                check_submission(args.videos, args.model, episodes)
                if args.scope == "full":
                    for variant in (1, 2):
                        variant_dir = args.videos.parent / (args.videos.name + f"_{variant}")
                        # Apply the same exact episode/media checks without silently renaming variants.
                        check_submission(variant_dir, args.model, episodes, variant=variant)
                stage_inputs(args.archive, args.references, args.videos, work, episodes)
                result = {"staged": True, "scope": args.scope, "episodes": episodes}
            elif args.command in {"plan", "run"}:
                commands = scorer_commands(source, work, args.model, args.config.resolve(),
                                           args.base_python, args.vlm_python, args.jepa_python,
                                           include_action=args.scope == "full")
                if args.command == "run":
                    import yaml
                    check_staged(work, args.model, episodes)
                    cfg = yaml.safe_load(args.config.read_text())
                    if cfg.get("model_name") != "test":
                        raise ValueError("Official config model_name must remain test")
                    check_weight_lock(args.weights_lock, cfg)
                    if cfg["data"] != {"gt_path": str(work / "data/gt_dataset"),
                                       "val_base": str(work / "data/generated_dataset")} or cfg["save_path"] != str(work / "output"):
                        raise ValueError("Config paths must use this isolated eval work directory")
                    if args.scope == "full" and (cfg.get("data_action_following") != {
                            "gt_path": str(work / "data_action_following/gt_dataset"),
                            "val_base": str(work / "data_action_following/generated_dataset")}
                            or cfg.get("save_path_action_following") != str(work / "output_action_following")):
                        raise ValueError("Full-scope action config must use isolated data/output paths")
                    def verify_paths(obj):
                        if isinstance(obj, dict):
                            for v in obj.values(): verify_paths(v)
                        elif isinstance(obj, str) and ("/" in obj or "your absolute path" in obj):
                            if not Path(obj).exists() or "your absolute path" in obj:
                                raise ValueError("Official checkpoint path is missing/unconfigured")
                    verify_paths(cfg["ckpt"])
                    for i, (cwd, cmd) in enumerate(commands):
                        with (work / f"scorer_{i}.log").open("w") as f:
                            subprocess.run(cmd, cwd=cwd, stdout=f, stderr=subprocess.STDOUT, check=True)
                    check_raw_results(work, args.model, episodes, include_action=args.scope == "full")
                result = {"scope": args.scope, "label": "full-scope" if args.scope == "full" else "one-episode-smoke-NOT-leaderboard",
                          "commands": [{"cwd": str(cwd), "argv": cmd} for cwd, cmd in commands], "official_score": None}
            else:
                aggregate = aggregate_compatible if args.command == 'aggregate-compatible' else aggregate_official
                result = aggregate(source, work, args.model, episodes, board, args.scope)
        if args.output:
            write_json(args.output, result)
        print(json.dumps(result, indent=2))
    except (ValueError, OSError, subprocess.CalledProcessError, KeyError, TypeError) as exc:
        result = {"status": "blocked", "blocker": str(exc), "official_score": None,
                  "scope": args.scope, "no_substitute_judge": True}
        if args.output:
            write_json(args.output, result)
        print(json.dumps(result, indent=2), file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
