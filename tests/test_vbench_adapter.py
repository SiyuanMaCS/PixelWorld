"""Adapter contract tests; no evaluator model inference or video scoring."""
import copy
import json
from pathlib import Path

import pytest
from PIL import Image

from tools import evaluate_vbench_i2v as evaluate
from tools import prepare_vbench_i2v as prepare


@pytest.fixture
def rows():
    return [{"prompt_en": "a bear, camera static", "image_name": "bear.jpg",
             "dimension": ["i2v_subject", "camera_motion"]}]


@pytest.fixture
def manifest(tmp_path, rows):
    root = tmp_path / "generations"
    root.mkdir()
    artifacts = []
    for sample in range(5):
        # Bytes exercise provenance validation ONLY; not a scored video fixture.
        path = root / f"sample-{sample}.mp4"
        path.write_bytes(f"unscored-test-artifact-{sample}".encode())
        artifacts.append({"pair_index": 0, "sample_index": sample,
                          "prompt_en": rows[0]["prompt_en"], "image_name": "bear.jpg",
                          "path": path.name, "sha256": prepare.sha256(path), "seed": sample + 11})
    return root, {"producer": "PixelWorld", "benchmark": "VBench++ I2V",
                  "source_commit": prepare.SOURCE_COMMIT,
                  "metadata_sha256": prepare.METADATA_SHA256,
                  "ratio": "16-9", "artifacts": artifacts}


def test_standard_scope_preserves_all_dimensions_and_pairs(rows):
    indices, dims = evaluate.requested_scope(rows, "standard", None, None)
    assert indices == [0]
    assert len(dims) == 10 and "temporal_flickering" in dims
    assert prepare.SAMPLES_PER_PAIR == 5
    with pytest.raises(ValueError):
        evaluate.requested_scope(rows, "standard", None, ["i2v_subject"])
    with pytest.raises(ValueError):
        evaluate.requested_scope(rows, "standard", 0, None)


def test_actual_camera_three_item_schema_and_unused_category_nan():
    groups = dict.fromkeys(['pan_left','pan_right','tilt_up','tilt_down','zoom_in','zoom_out','static'],float('nan'))
    groups['pan_left']=1.0
    results={'camera_motion':[1.0,groups,[{'prompt_type':'pan_left','video_results':1.0} for _ in range(5)]]}
    rows=[{'dimension':['camera_motion']}]
    report=evaluate.validate_metric_results(results,['camera_motion'],rows,[0],'official-data-smoke')
    assert report['camera_motion_coverage']['represented_categories']==['pan_left']
    with pytest.raises(ValueError,match='omitted categories'):
        evaluate.validate_metric_results(results,['camera_motion'],rows,[0],'standard')
    results['camera_motion'][2].pop()
    with pytest.raises(ValueError,match='per-video'):
        evaluate.validate_metric_results(results,['camera_motion'],rows,[0],'official-data-smoke')


def test_official_aggregate_never_accepts_smoke_scope(tmp_path):
    with pytest.raises(ValueError,match='full official'):
        evaluate.official_aggregate({}, {'scope':'official-data-smoke','status':'complete'},tmp_path)


def test_actual_official_aggregate_functions_and_extra_raw_dimension():
    source=prepare.DEFAULT_SOURCE
    if not source.exists():pytest.skip('optional official source unavailable')
    rows=prepare.load_official_metadata(source/'vbench2_beta_i2v/vbench2_i2v_full_info.json')
    raw={key:[.5,[{} for _ in range(sum(key in row['dimension'] for row in rows)*5)]]
         for key in prepare.DIMENSIONS}
    categories=['pan_left','pan_right','tilt_up','tilt_down','zoom_in','zoom_out','static']
    count=len(raw['camera_motion'][1])
    raw['camera_motion']=[.5,dict.fromkeys(categories,.5),
        [{'prompt_type':categories[i%7],'video_results':.5} for i in range(count)]]
    provenance={'scope':'standard','status':'complete','pair_count':1118,'samples_per_pair':5,
                'source_commit':prepare.SOURCE_COMMIT,'metadata_sha256':prepare.METADATA_SHA256}
    # Numeric schema fixture only; never publish this as a benchmark score.
    result=evaluate.official_aggregate(raw,provenance,source)
    assert result['omitted_extra_raw_metrics']==['temporal_flickering']
    assert result['total_score']==pytest.approx((result['quality_score']+result['i2v_score'])/2)
    del raw['camera_motion']
    with pytest.raises(ValueError,match='incomplete dimension'):
        evaluate.official_aggregate(raw,provenance,source)


@pytest.mark.parametrize("index,dims", [(None, None), (-1, None), (1, None),
                                      (0, ["i2v_background"]), (0, ["camera_motion"] * 2)])
def test_smoke_rejects_nonofficial_scope(rows, index, dims):
    with pytest.raises(ValueError):
        evaluate.requested_scope(rows, "official-data-smoke", index, dims)


def test_manifest_accepts_exact_five_attested_outputs(rows, manifest):
    root, data = manifest
    artifacts = evaluate.validate_manifest(data, rows, [0], root, "16-9")
    assert len(artifacts) == 5
    assert all(a["resolved_path"].is_relative_to(root) for a in artifacts)


def test_api_samples_need_unique_completed_sessions_not_fabricated_seeds(rows, manifest):
    import uuid
    root, data = manifest
    for i, item in enumerate(data["artifacts"]):
        session = str(uuid.uuid4())
        record = root / f"run-{i}.json"
        record.write_text(json.dumps({"status": "complete", "validation": {"pass": True},
                                      "full_trace": {"thread_id": session}}))
        item.update(seed=None, api_seed_status="not_reported", generation_session_id=session,
                    run_manifest=record.name, run_manifest_sha256=prepare.sha256(record))
    assert len(evaluate.validate_manifest(data, rows, [0], root, "16-9")) == 5
    # Identical RGB can result from independent deterministic programs; paths
    # and run identities remain distinct, so equal content is permitted.
    first = (root / data["artifacts"][0]["path"]).read_bytes()
    for item in data["artifacts"]:
        path = root / item["path"]
        path.write_bytes(first)
        item["sha256"] = prepare.sha256(path)
    assert len(evaluate.validate_manifest(data, rows, [0], root, "16-9")) == 5
    data["artifacts"][1].update({k: data["artifacts"][0][k] for k in
                                ("generation_session_id", "run_manifest", "run_manifest_sha256")})
    with pytest.raises(ValueError, match="unique completed"):
        evaluate.validate_manifest(data, rows, [0], root, "16-9")


@pytest.mark.parametrize("mutation", ["baseline", "missing", "duplicate", "extra",
                                     "hash", "prompt", "image", "seed", "absolute",
                                     "escape", "repin", "ratio", "bool_index"])
def test_manifest_rejects_illegal_artifacts(rows, manifest, mutation):
    root, original = manifest
    data = copy.deepcopy(original)
    item = data["artifacts"][0]
    if mutation == "baseline":
        data["producer"] = "Wan2.2"
    elif mutation == "missing":
        data["artifacts"].pop()
    elif mutation == "duplicate":
        data["artifacts"][1] = item.copy()
    elif mutation == "extra":
        data["artifacts"].append({**item, "sample_index": 5})
    elif mutation == "hash":
        item["sha256"] = "0" * 64
    elif mutation == "prompt":
        item["prompt_en"] += " modified"
    elif mutation == "image":
        item["image_name"] = "other.jpg"
    elif mutation == "seed":
        del item["seed"]
    elif mutation == "absolute":
        item["path"] = str(root / item["path"])
    elif mutation == "escape":
        item["path"] = "../baseline.mp4"
    elif mutation == "repin":
        data["source_commit"] = "main"
    elif mutation == "ratio":
        data["ratio"] = "1-1"
    elif mutation == "bool_index":
        item["pair_index"] = False
    with pytest.raises(ValueError):
        evaluate.validate_manifest(data, rows, [0], root, "16-9")


def test_symlink_cannot_escape_generation_root(rows, manifest, tmp_path):
    root, data = manifest
    path = root / data["artifacts"][0]["path"]
    path.unlink()
    outside = tmp_path / "baseline.mp4"
    outside.write_bytes(b"not legal")
    path.symlink_to(outside)
    with pytest.raises(ValueError, match="within the generation root"):
        evaluate.validate_manifest(data, rows, [0], root, "16-9")


def test_preparation_copies_only_initial_still_and_prompt(tmp_path, rows):
    images = tmp_path / "official_crop"
    images.mkdir()
    Image.new("RGB", (320, 180), (20, 40, 60)).save(images / "bear.jpg")
    (images / "reference_continuation.mp4").write_bytes(b"never read or copied")
    output, provenance = tmp_path / "inputs", tmp_path / "infra/provenance.json"
    result = prepare.prepare_inputs(rows, [0], images, output, provenance, "16-9", width=256)
    assert {p.name for p in (output / "0000").iterdir()} == {
        "first_frame.png", "prompt.txt", "task_spec.json"}
    assert Image.open(output / "0000/first_frame.png").size == (256, 144)
    assert (output / "0000/prompt.txt").read_text() == rows[0]["prompt_en"]
    assert "dimension" not in (output / "0000/task_spec.json").read_text()
    assert result["samples_per_pair"] == 5
    assert provenance.exists()
    with pytest.raises(FileExistsError):
        prepare.prepare_inputs(rows, [0], images, output, provenance, "16-9")


def test_provenance_cannot_leak_into_inputs(tmp_path, rows):
    with pytest.raises(ValueError, match="outside generation"):
        prepare.prepare_inputs(rows, [0], tmp_path, tmp_path / "inputs",
                               tmp_path / "inputs/provenance.json", "16-9")


def test_bad_image_has_no_partial_input_folder(tmp_path, rows):
    (tmp_path / "bear.jpg").write_bytes(b"not an image")
    output = tmp_path / "inputs"
    with pytest.raises(Exception):
        prepare.prepare_inputs(rows, [0], tmp_path, output, tmp_path / "infra.json", "16-9")
    assert not output.exists()


def test_reject_unpinned_metadata(tmp_path):
    path = tmp_path / "full_info.json"
    path.write_text("[]")
    with pytest.raises(ValueError, match="pinned official"):
        prepare.load_official_metadata(path)


def test_resource_list_never_substitutes_models(tmp_path):
    paths = evaluate.required_resources(tmp_path / "source", tmp_path / "cache",
                                        tmp_path / "torch", list(prepare.DIMENSIONS))
    names = [str(p) for p in paths]
    assert any("dino_vitbase16_pretrain.pth" in p for p in names)
    assert any("cotracker2.pth" in p for p in names)
    assert any("clip_vitb16_lora/adapter_model.bin" in p for p in names)
    assert not any("dinov2" in p or "cotracker3" in p for p in names)
    assert len(names) == len(set(names))


def test_missing_resources_fail_before_any_model_loading(tmp_path, monkeypatch):
    monkeypatch.setenv("VBENCH_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("TORCH_HOME", str(tmp_path / "torch"))
    with pytest.raises(FileNotFoundError, match="musiq_spaq"):
        evaluate.validate_resources(tmp_path / "source", ["imaging_quality"])
    # temporal_flickering is the real upstream weight-free dimension, not a fallback.
    evaluate.validate_resources(tmp_path / "source", ["temporal_flickering"])


def test_resources_require_isolated_cache_configuration(tmp_path, monkeypatch):
    monkeypatch.delenv("VBENCH_CACHE_DIR", raising=False)
    with pytest.raises(ValueError, match="isolate"):
        evaluate.validate_resources(tmp_path, ["temporal_flickering"])


def test_probe_validates_without_loading_models(monkeypatch):
    def probe(cmd, text):
        assert cmd[0] == "ffprobe"
        return json.dumps({"streams": [{"width": 256, "height": 144,
                                        "nb_read_frames": "20", "avg_frame_rate": "4/1"}]})
    monkeypatch.setattr(evaluate.subprocess, "check_output", probe)
    assert evaluate.probe_video(Path("pixelworld.mp4"), "16-9")["width"] == 256
    with pytest.raises(ValueError):
        evaluate.probe_video(Path("pixelworld.mp4"), "1-1")


def test_official_api_staging_and_smoke_label(tmp_path, rows, manifest):
    root, data = manifest
    artifacts = evaluate.validate_manifest(data, rows, [0], root, "16-9")
    source = tmp_path / "source"
    source.mkdir()
    output = tmp_path / "eval"
    previous = Path.cwd()

    class RecordingEvaluator:
        def __init__(self, device, metadata, out):
            assert device == "cuda"
            assert json.loads(Path(metadata).read_text()) == rows
            self.out = Path(out)

        def evaluate(self, **kwargs):
            assert Path.cwd() == source
            assert kwargs["mode"] == "vbench_standard"
            assert kwargs["local"] is True
            assert kwargs["resolution"] == "16-9"
            assert "custom_image_folder" not in kwargs
            staged = Path(kwargs["videos_path"])
            assert {p.name for p in staged.iterdir()} == {
                f"a bear, camera static-{s}.mp4" for s in range(5)}
            assert all(p.is_symlink() for p in staged.iterdir())
            # Fake return only tests API/schema handling, never published as scores.
            (self.out / "pixelworld_eval_results.json").write_text(json.dumps({
                "i2v_subject": [0.5, [{} for _ in range(5)]]}))

    evaluate.execute_official(source, output, rows, [0], ["i2v_subject"], artifacts,
                              "16-9", "official-data-smoke", RecordingEvaluator)
    assert Path.cwd() == previous
    provenance = json.loads((output / "evaluation_provenance.json").read_text())
    assert provenance["leaderboard_result"] is False
    assert provenance["scope"] == "official-data-smoke"
    assert provenance["status"] == "complete"
    with pytest.raises(FileExistsError):
        evaluate.execute_official(source, output, rows, [0], ["i2v_subject"], artifacts,
                                  "16-9", "official-data-smoke", RecordingEvaluator)


def test_incomplete_official_result_is_failed(tmp_path, rows, manifest):
    root, data = manifest
    artifacts = evaluate.validate_manifest(data, rows, [0], root, "16-9")
    source = tmp_path / "source"
    source.mkdir()
    output = tmp_path / "eval"
    previous = Path.cwd()

    class IncompleteEvaluator:
        def __init__(self, device, metadata, out):
            self.out = Path(out)

        def evaluate(self, **kwargs):
            (self.out / "pixelworld_eval_results.json").write_text('{"i2v_subject": [NaN, []]}')

    with pytest.raises(ValueError, match="nonfinite"):
        evaluate.execute_official(source, output, rows, [0], ["i2v_subject"], artifacts,
                                  "16-9", "official-data-smoke", IncompleteEvaluator)
    assert Path.cwd() == previous
    assert json.loads((output / "evaluation_provenance.json").read_text())["status"] == "failed"
