"""Generation scoring infrastructure only; fixture pixels are not benchmark videos."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image
import pytest

SPEC = importlib.util.spec_from_file_location(
    "robojudge_adapter", Path(__file__).parents[1] / "tools/evaluate_robojudge_shared50.py")
adapter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapter)


@pytest.fixture
def sample(tmp_path):
    run = tmp_path / "generations/model/vision-agent/case_common50_0000_attempt_01"
    ws, snap = run / "workspace", run / "input_snapshot"
    (ws / "frames").mkdir(parents=True)
    snap.mkdir()
    frames = np.arange(4 * 16 * 32 * 3, dtype=np.uint8).reshape(4, 16, 32, 3)
    spec = dict(task_type="i2v", benchmark="robojudge", frames=4, height=16, width=32, fps=4, audio=None)
    task = dict(key="agibot_world/task/episode", dataset="agibot_world", instruction="Move the cup.")
    Image.fromarray(frames[0]).save(snap / "first_frame.png")
    (snap / "prompt.txt").write_text(adapter.ROBOT_PREFIX + task["instruction"] + "\n")
    adapter.write_json(snap / "task_spec.json", spec)
    adapter.write_json(run / "media_contract.json", spec)
    for i, f in enumerate(frames):
        Image.fromarray(f).save(ws / "frames" / f"{i:02d}.png")
    v = frames.astype(np.uint32)
    np.savez_compressed(ws / "pixels.npz", pixels=((v[..., 0] << 16) | (v[..., 1] << 8) | v[..., 2]).transpose(1, 2, 0))
    manifest = dict(status="complete", validation={"pass": True}, media_contract=spec,
                    model_key="model", track="vision-agent", case_id="common50_0000",
                    input_image_sha256=adapter.sha256(snap / "first_frame.png"),
                    input_prompt_sha256=adapter.sha256(snap / "prompt.txt"),
                    pixels_sha256=adapter.sha256(ws / "pixels.npz"))
    adapter.write_json(run / "run_manifest.json", manifest)
    return run, frames, task


def test_packed_rgb_matches_png_and_initial(sample):
    run, frames, task = sample
    actual, spec, manifest = adapter.load_frames(run, task)
    assert np.array_equal(frames, actual)
    assert spec["fps"] == 4 and manifest["validation"]["pass"]


@pytest.mark.parametrize("dataset", ["egodex_human", "egoscaler_human", "epickitchens_human"])
def test_human_corpa_use_published_egocentric_prefix(sample, dataset):
    run, frames, task = sample
    task["dataset"] = dataset
    path = run / "input_snapshot/prompt.txt"
    path.write_text(adapter.HUMAN_PREFIX + task["instruction"] + "\n")
    manifest = adapter.read_json(run / "run_manifest.json")
    manifest["input_prompt_sha256"] = adapter.sha256(path)
    adapter.write_json(run / "run_manifest.json", manifest)
    assert np.array_equal(adapter.load_frames(run, task)[0], frames)
    assert adapter.HUMAN_PREFIX == "In a first-person egocentric video, a real human hand starts to "


def test_png_only_is_accepted(sample):
    run, frames, task = sample
    (run / "workspace/pixels.npz").unlink()
    assert np.array_equal(adapter.load_frames(run, task)[0], frames)


@pytest.mark.parametrize("mutation,match", [
    ("incomplete", "not complete"), ("png_gap", "contiguous"),
    ("png_wrong", "tensor/PNG mismatch"), ("snapshot", "snapshot hash"),
    ("task", "original task"), ("contract", "contracts disagree"),
    ("tensor", "artifact hash changed"),
])
def test_rejects_invalid_submission(sample, mutation, match):
    run, frames, task = sample
    if mutation == "incomplete":
        manifest = adapter.read_json(run / "run_manifest.json")
        manifest["status"] = "running"
        adapter.write_json(run / "run_manifest.json", manifest)
    elif mutation == "png_gap":
        (run / "workspace/frames/01.png").unlink()
    elif mutation == "png_wrong":
        Image.fromarray(np.zeros_like(frames[1])).save(run / "workspace/frames/01.png")
    elif mutation == "snapshot":
        (run / "input_snapshot/prompt.txt").write_text("wrong")
    elif mutation == "task":
        task["instruction"] = "wrong original task"
    elif mutation == "contract":
        spec = adapter.read_json(run / "media_contract.json")
        spec["fps"] = 3
        adapter.write_json(run / "media_contract.json", spec)
    else:
        with (run / "workspace/pixels.npz").open("ab") as f:
            f.write(b"changed")
    with pytest.raises(ValueError, match=match):
        adapter.load_frames(run, task)


def test_refuses_generator_visible_evaluation(sample):
    run, _, _ = sample
    with pytest.raises(ValueError, match="generation runs"):
        adapter.external_output(run / "workspace/evaluation", run.parents[2])
    with pytest.raises(ValueError, match="visible to a generator"):
        adapter.external_output(run / "results", run / "workspace")


def test_scope_requires_all_50_and_no_duplicate_attempts():
    expected = [f"common50_{i:04d}" for i in range(50)]
    records = [{"case_id": i, "status": "prepared"} for i in expected]
    assert adapter.scope_report(records, expected)["complete_shared50"]
    assert len(adapter.scope_report(records[:1], expected)["missing"]) == 49
    assert not adapter.scope_report(records + records[:1], expected)["complete_shared50"]
    records[4]["status"] = "failed"
    assert adapter.scope_report(records, expected)["failed"] == [expected[4]]


def write_predictions(output, rows, count=1):
    records = [{"case_id": f"common50_{i:04d}", "status": "prepared"} for i in range(count)]
    scope = adapter.scope_report(records, [f"common50_{i:04d}" for i in range(50)])
    adapter.write_json(output / "plan.json", {"scope": scope, "records": records})
    (output / "predictions.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def prediction(case, axis, score):
    field = "physical_adherence" if axis == "PA" else "instruction_alignment"
    return {"item_id": case, "axis": axis, "predict": json.dumps({"reasoning": "fixture", field: score})}


def test_reports_generation_means_not_pearson(tmp_path):
    rows = [prediction(f"common50_{i:04d}", a, s) for i in range(50) for a, s in (("PA", 3), ("IA", 5))]
    write_predictions(tmp_path, rows, count=50)
    result = adapter.summarize(tmp_path)
    assert result["complete_shared50"]
    assert result["shared50_means"] == {"PA": 3, "IA": 5, "mean": 4}
    assert "pearson" not in result


def test_partial_smoke_never_claims_shared50(tmp_path):
    write_predictions(tmp_path, [prediction("common50_0000", "PA", 3), prediction("common50_0000", "IA", 5)])
    result = adapter.summarize(tmp_path)
    assert not result["complete_shared50"]
    assert result["shared50_means"] is None
    assert result["partial_paired_means"]["mean"] == 4


@pytest.mark.parametrize("bad", ["reasoning: 4; score unclear", '{"physical_adherence": 6}',
                                 '{"physical_adherence": 3.2}', '{"physical_adherence": true}'])
def test_invalid_prediction_preserved_not_imputed(tmp_path, bad):
    row = prediction("common50_0000", "PA", 3)
    row["predict"] = bad
    write_predictions(tmp_path, [row, prediction("common50_0000", "IA", 5)])
    result = adapter.summarize(tmp_path)
    assert len(result["parse_failures"]) == 1
    assert result["valid_paired_count"] == 0
    assert result["prediction_failures"][0]["PA"] is None


def test_duplicate_and_truncated_outputs_fail(tmp_path):
    row = prediction("common50_0000", "PA", 3)
    write_predictions(tmp_path, [row, row, prediction("common50_0000", "IA", 5)])
    with (tmp_path / "predictions.jsonl").open("a") as f:
        f.write('{"item_id":')
    result = adapter.summarize(tmp_path)
    assert len(result["parse_failures"]) == 2
    assert result["valid_paired_count"] == 0


def test_exact_official_cli_defaults(tmp_path):
    cmd = adapter.official_command(tmp_path)
    assert cmd[cmd.index("--max-new-tokens") + 1] == "2048"
    assert cmd[cmd.index("--attn-implementation") + 1] == "sdpa"
    assert cmd[cmd.index("--ckpt") + 1].endswith("robojudge-eval-night/checkpoint")
    assert "--enable-thinking" not in cmd
    assert not any("seed42" in x or "seed43" in x for x in cmd)


def test_lossless_export_native_timing(sample, tmp_path):
    av = pytest.importorskip("av")
    _, frames, _ = sample
    path = tmp_path / "fixture.mp4"
    meta = adapter.export_video(frames, 4, path)
    assert meta["rgb_roundtrip_exact"]
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        assert float(stream.average_rate) == 4
        assert stream.frames == 4
        decoded = list(container.decode(video=0))
        assert [float(f.pts * f.time_base) for f in decoded] == [0, .25, .5, .75]


def test_official_prompt_and_pins_if_installed():
    source = adapter.VENDOR / "source/code/inference.py"
    if not source.exists():
        pytest.skip("isolated official source not installed")
    adapter.verify_source()
    spec = importlib.util.spec_from_file_location("official_robojudge", source)
    official = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(official)
    pa = official.make_prompt("PA", {}, "ours.mp4", None)
    ia = official.make_prompt("IA", {}, "ours.mp4", "Move the cup.")
    assert pa[0]["content"] == official.PA_SYSTEM_BODY
    assert "Move the cup" not in json.dumps(pa)
    assert "Move the cup" in json.dumps(ia)
    media = pa[1]["content"][0]
    assert media == {"type": "video", "video": "ours.mp4", "fps": 4.,
                     "max_frames": 32, "max_pixels": 65536, "min_pixels": 256}
    assert not any(p["type"] == "image" for p in ia[1]["content"])


def test_preparation_keeps_failures_and_minimal_inputs(sample, tmp_path, monkeypatch):
    run, frames, task = sample
    monkeypatch.setattr(adapter, "load_tasks", lambda _: [task] * 50)
    monkeypatch.setattr(adapter, "export_video", lambda f, fps, p: {"rgb_roundtrip_exact": True})
    output = tmp_path / "evaluation"
    args = SimpleNamespace(generations=run.parents[2], model="model", track="vision-agent",
                           output=output, tasks=run / "media_contract.json", allow_partial=True)
    assert adapter.prepare(args) == 0
    plan = adapter.read_json(output / "plan.json")
    assert len(plan["scope"]["missing"]) == 49
    assert set(plan["records"][0]["input"]) == {"item_id", "video_url", "instruction", "init_frame_url"}
    assert plan["records"][0]["input"]["instruction"] == task["instruction"]
    assert not (run / "workspace/predictions.jsonl").exists()


def test_blocked_run_records_execution_and_null_axes(tmp_path, monkeypatch):
    write_predictions(tmp_path, [])
    (tmp_path / "predictions.jsonl").unlink()
    monkeypatch.setattr(adapter, "verify_source", lambda: (_ for _ in ()).throw(ValueError("source blocker")))
    args = SimpleNamespace(output=tmp_path, allow_partial=True, allow_unsupported_bf16=False)
    assert adapter.run_official(args) == 2
    execution = adapter.read_json(tmp_path / "execution.json")
    assert execution["status"] == "blocked"
    assert "source blocker" in execution["blockers"][0]
    assert adapter.read_json(tmp_path / "summary.json")["valid_paired_count"] == 0
    with pytest.raises(ValueError, match="never overwrite"):
        adapter.run_official(args)
