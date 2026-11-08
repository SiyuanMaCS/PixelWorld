"""Offline protocol/contamination tests; no baseline media or GPU inference."""
from pathlib import Path
import importlib.util
import json
import sys

import numpy as np
from PIL import Image
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import prepare_wbench as wb
import evaluate_wbench as ew
import prepare_worldscore as ws
import evaluate_worldscore as es


def fixture_run(tmp, benchmark="wbench", cid="1", turn=1, initial=None):
    root = tmp / f"run{turn}"
    snapshot = root / "input_snapshot"; snapshot.mkdir(parents=True)
    frames_dir = root / "workspace/frames"; frames_dir.mkdir(parents=True)
    rgb = np.full((3, 4, 6, 3), 40 + turn, dtype=np.uint8)
    rgb[-1] = 70 + turn
    if initial is not None:
        rgb[0] = initial
    spec = wb.media_spec(benchmark, 6, 4, 3, 2)
    spec.update(turn=turn, action="W")
    Image.fromarray(rgb[0]).save(snapshot / "first_frame.png")
    (snapshot / "prompt.txt").write_text("official action")
    wb.write_json(snapshot / "task_spec.json", spec)
    wb.write_json(root / "media_contract.json", spec)
    prov = {"benchmark": benchmark, "case_id": cid, "turn": turn,
            "prompt": "official action", "media": spec, "feedback": None,
            "input_image_sha256": wb.sha256(snapshot / "first_frame.png"),
            "input_prompt_sha256": wb.sha256(snapshot / "prompt.txt")}
    manifest = {"status": "complete", "validation": {"pass": True}, "media_contract": spec,
                "input_image_sha256": prov["input_image_sha256"], "input_prompt_sha256": prov["input_prompt_sha256"]}
    wb.write_json(root / "run_manifest.json", manifest)
    for i, frame in enumerate(rgb):
        Image.fromarray(frame).save(frames_dir / f"{i:02d}.png")
    pp = tmp / f"prov{turn}.json"; wb.write_json(pp, prov)
    return root, pp, rgb


def test_validated_native_rgb(tmp_path):
    run, pp, rgb = fixture_run(tmp_path)
    result, spec, _ = ew.load_rgb(run, wb.read_json(pp))
    assert np.array_equal(result, rgb)
    assert spec["fps"] == 2


@pytest.mark.parametrize("corrupt", ["incomplete", "prompt", "frame_zero", "gap", "contract"])
def test_corrupt_rgb_rejected(tmp_path, corrupt):
    run, pp, rgb = fixture_run(tmp_path)
    if corrupt == "incomplete":
        manifest = wb.read_json(run / "run_manifest.json"); manifest["status"] = "failed"
        wb.write_json(run / "run_manifest.json", manifest)
    if corrupt == "prompt":
        (run / "input_snapshot/prompt.txt").write_text("GT leaked")
    if corrupt == "frame_zero":
        Image.fromarray(rgb[-1]).save(run / "workspace/frames/00.png")
    if corrupt == "gap":
        (run / "workspace/frames/01.png").unlink()
    if corrupt == "contract":
        wb.write_json(run / "media_contract.json", {"frames": 1})
    with pytest.raises(ValueError):
        ew.load_rgb(run, wb.read_json(pp))


def test_chain_rejects_gt_feedback_and_misordering(tmp_path):
    r1, p1, rgb1 = fixture_run(tmp_path)
    r2, p2, rgb2 = fixture_run(tmp_path, turn=2, initial=rgb1[-1])
    import hashlib
    prov = wb.read_json(p2)
    prov["feedback"] = {"previous_provenance_sha256": wb.sha256(p1),
                        "previous_run_manifest_sha256": wb.sha256(r1 / "run_manifest.json"),
                        "last_rgb_sha256": hashlib.sha256(rgb1[-1].tobytes()).hexdigest()}
    wb.write_json(p2, prov)
    assert len(ew.check_chain([(r1, p1), (r2, p2)], "wbench", "1", 2)) == 2
    with pytest.raises(ValueError):
        ew.check_chain([(r2, p2), (r1, p1)], "wbench", "1", 2)
    prov["feedback"]["last_rgb_sha256"] = "gt"
    wb.write_json(p2, prov)
    with pytest.raises(ValueError):
        ew.check_chain([(r1, p1), (r2, p2)], "wbench", "1", 2)
    with pytest.raises(ValueError):
        ew.check_chain([(r1, p1)], "wbench", "1", 2)


def test_no_silent_qwen_judge_substitution():
    ew.require_original_judge(wb.JUDGE, True)
    with pytest.raises(ValueError):
        ew.require_original_judge("Qwen/Qwen3.8-27B", True)
    with pytest.raises(RuntimeError):
        ew.require_original_judge(wb.JUDGE, False)


def test_contamination_and_traversal(tmp_path):
    with pytest.raises(ValueError):
        wb.contained(tmp_path, "../mask.png")
    with pytest.raises(ValueError):
        wb.safe_id("../../scores")
    output = tmp_path / "inputs"
    with pytest.raises(ValueError):
        wb.isolated(output, output / "evaluation.json")
    run, _, _ = fixture_run(tmp_path)
    with pytest.raises(ValueError):
        ew.external_output(run / "workspace/evaluation", [run])


@pytest.mark.parametrize("fps", [float("nan"), float("inf"), 0, -1, 241])
def test_invalid_timing(fps):
    with pytest.raises(ValueError):
        wb.media_spec("wbench", 6, 4, 3, fps)


def scores(schema, value):
    return {a: {m: {"score": value, "score_normalized": value} for m in ms} for a, ms in schema.items()}


def test_worldscore_dynamic_includes_static():
    result = es.strict_aggregate({"s": scores(es.STATIC, .8)}, {"d": scores(es.DYNAMIC, .4)}, ["s"], ["d"])
    assert result["WorldScore-Static"] == 80
    assert result["WorldScore-Dynamic"] == 68 # (7*80+3*40)/10, NOT 40
    static = es.strict_aggregate({"s": scores(es.STATIC, .8)}, None, ["s"], ["d"])
    assert "WorldScore-Dynamic" not in static


@pytest.mark.parametrize("corrupt", ["missing_case", "extra_case", "missing_metric", "nan", "out_of_range"])
def test_worldscore_partial_scores_never_full(corrupt):
    s = {"s": scores(es.STATIC, .5)}
    if corrupt == "missing_case": s = {}
    if corrupt == "extra_case": s["extra"] = scores(es.STATIC, .5)
    if corrupt == "missing_metric": del s["s"]["subjective_quality"]["clip_aesthetic"]
    if corrupt == "nan": s["s"]["camera_control"]["camera_error"]["score_normalized"] = float("nan")
    if corrupt == "out_of_range": s["s"]["camera_control"]["camera_error"]["score_normalized"] = 2
    with pytest.raises(ValueError):
        es.strict_aggregate(s, None, ["s"], [])


def test_official_protocol_cached_inputs(tmp_path):
    """Optional pinned-cache integration; never fetch upstream in tests."""
    if not (wb.VENDOR / "data/cases/case_1.json").exists() or not (ws.VENDOR / "data/WorldScore-Dataset/static/static.json").exists():
        pytest.skip("ignored official input cache unavailable")
    cases = wb.load_cases(wb.VENDOR / "data")
    record = wb.prepare_turn(cases["1"], 1, tmp_path / "wb", tmp_path / "wb.json")
    assert set(p.name for p in (tmp_path / "wb").iterdir()) == {"first_frame.png", "prompt.txt", "task_spec.json"}
    assert record["prompt"] == "The subject moves forward. The camera follows, maintaining distance and framing."
    with pytest.raises(ValueError):
        wb.prepare_turn(cases["1"], 2, tmp_path / "bad", tmp_path / "bad.json")
    rows = ws.load_metadata(ws.VENDOR / "data/WorldScore-Dataset", "static")
    assert len(rows) == 2000
    assert sum(len(r["camera_path"]) for r in rows) == 2800
    record = ws.prepare_segment(rows[80], 80, 1, tmp_path / "ws", tmp_path / "ws.json")
    assert record["official_segments"] == 3
    assert record["complete_case_frames"] == 148
    assert "Cozy Dining Room" in record["prompt"] and "Camera move left" in record["prompt"]
    assert set(p.name for p in (tmp_path / "ws").iterdir()) == {"first_frame.png", "prompt.txt", "task_spec.json"}
    es.camera_metadata(rows[80], 50, tmp_path / "camera")
    cameras = wb.read_json(tmp_path / "camera/camera_data.json")
    assert len(cameras["cameras_interp"]) == 148


def test_lossless_export_synthetic_only(tmp_path):
    if importlib.util.find_spec("av") is None:
        pytest.skip("optional video export dependency absent")
    rgb = np.arange(3 * 4 * 6 * 3, dtype=np.uint8).reshape(3, 4, 6, 3)
    metadata = ew.export_video(rgb, 2, tmp_path / "synthetic.mp4")
    assert metadata["rgb_roundtrip_exact"] and not metadata["resampled"]


def test_wbench_coverage_rejects_missing_applicable_metrics(tmp_path, monkeypatch):
    monkeypatch.setattr(ew, 'load_cases', lambda _: {'1':{'metric_list':['imaging_quality','visual_plausibility']}})
    root=tmp_path/'pixelworld_fixture/evaluation'
    (root/'imaging_quality').mkdir(parents=True)
    wb.write_json(root/'imaging_quality/case_1.json', {'score':.5})
    result=ew.check_metric_coverage(tmp_path,'pixelworld_fixture',['1'])
    assert not result['complete_applicable_metric_coverage']
    assert 'missing 1/visual_plausibility' in result['errors']
    (root/'visual_plausibility').mkdir()
    wb.write_json(root/'visual_plausibility/case_1.json', {'score':.6,'error':None})
    assert ew.check_metric_coverage(tmp_path,'pixelworld_fixture',['1'])['complete_applicable_metric_coverage']
    wb.write_json(root/'visual_plausibility/case_1.json', {'score':.6,'error':'fixture inference failed'})
    assert not ew.check_metric_coverage(tmp_path,'pixelworld_fixture',['1'])['complete_applicable_metric_coverage']
