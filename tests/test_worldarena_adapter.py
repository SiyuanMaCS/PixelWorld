"""Contract tests use fixtures, not generated/scored benchmark or baseline videos."""
import importlib.util
import io
import json
import tarfile
from pathlib import Path

import pytest
from PIL import Image

from tools import prepare_worldarena as prep
from tools import evaluate_worldarena as ev

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "vendor/worldarena-eval-night/source"
BOARD = ROOT / "vendor/worldarena-eval-night/leaderboard/data_loader.py"
ARCHIVE = ROOT / "vendor/worldarena-eval-night/data/test_dataset_latest2026-03-06.tar.gz"


def test_exact_test_scope_and_filenames():
    full = ev.select_episodes("full", "episode1")
    assert len(full) == 1000 and full[-1] == "episode1000"
    assert ev.select_episodes("one-episode-smoke", "episode42") == ["episode42"]
    assert ev.external_filename("episode42") == "fixed_scene_task_episode_42.mp4"
    assert ev.internal_id("episode42") == "fixed_scene_task_episode42"
    for value in ["episode0", "episode01", "episode1001", "../episode1"]:
        with pytest.raises(ValueError):
            ev.select_episodes("full", value)
    with pytest.raises(ValueError):
        ev.select_episodes("smoke", "episode1")


def test_submission_requires_exact_scope_no_subset_nesting_or_padding(tmp_path):
    folder = tmp_path / "pixelworld_codex_test"
    folder.mkdir()
    (folder / ev.external_filename("episode1")).touch()
    ev.check_submission(folder, "pixelworld_codex", ["episode1"], decode=False)
    with pytest.raises(ValueError, match="scope/filenames"):
        ev.check_submission(folder, "pixelworld_codex", ev.select_episodes("full", "episode1"), decode=False)
    with pytest.raises(ValueError, match="directory"):
        ev.check_submission(folder, "different", ["episode1"], decode=False)
    nested = folder / "extra"
    nested.mkdir()
    with pytest.raises(ValueError):
        ev.check_submission(folder, "pixelworld_codex", ["episode1"], decode=False)
    nested.rmdir()
    video = folder / ev.external_filename("episode1")
    video.unlink()
    video.symlink_to(tmp_path / "reference.mp4")
    (tmp_path / "reference.mp4").touch()
    with pytest.raises(ValueError, match="regular"):
        ev.check_submission(folder, "pixelworld_codex", ["episode1"], decode=False)


def test_json_rejects_duplicate_and_nonfinite(tmp_path):
    p = tmp_path / "bad.json"
    for text in ['{"score": 0.2, "score": 0.3}', '{"score": NaN}', '{"score": Infinity}']:
        p.write_text(text)
        with pytest.raises(ValueError):
            ev.load_json(p)


@pytest.mark.parametrize("value", [None, True, "0.5", -0.01, 1.01, float("nan"), float("inf")])
def test_no_missing_nonfinite_out_of_range_scores(value):
    with pytest.raises(ValueError):
        ev.numeric(value, "Image Quality")
    assert ev.numeric(0.0, "Image Quality") == 0.0


def test_unsafe_archive_not_extracted():
    for name in ["../test_dataset/foo", "/test_dataset/foo", "test_dataset/../../foo"]:
        b = io.BytesIO()
        with tarfile.open(fileobj=b, mode="w") as t:
            m = tarfile.TarInfo(name)
            t.addfile(m)
        b.seek(0)
        with tarfile.open(fileobj=b) as t, pytest.raises(ValueError):
            prep.archive_index(t)


def test_inventory_checks_all_modalities_and_count():
    index = {f"{role}/fixed_scene_task/episode{i}.{suffix}": None
             for role, suffix in [("instructions", "json"), ("instructions_1", "json"),
                                  ("instructions_2", "json"), ("first_frame", "png"), ("data", "hdf5")]
             for i in range(1, 1001)}
    assert len(prep.episode_inventory(index)) == 1000
    del index["data/fixed_scene_task/episode2.hdf5"]
    with pytest.raises(ValueError):
        prep.episode_inventory(index)


def test_official_pinned_legal_input_real_archive(tmp_path):
    if not ARCHIVE.exists():
        pytest.skip("Optional ignored official download unavailable")
    legal = tmp_path / "legal_inputs"
    p = prep.prepare(ARCHIVE, legal)
    assert p["official_test_count"] == 1000
    assert p["reference_future_accessed"] is False
    assert {x.name for x in legal.iterdir()} == {"first_frame.png", "prompt.txt", "task_spec.json"}
    assert Image.open(legal / "first_frame.png").size == (640, 480)
    assert (legal / "prompt.txt").read_text().count(prep.OFFICIAL_PREFIX) == 1
    ev.check_legal(legal, tmp_path / "input_provenance.json")
    with pytest.raises(ValueError, match="empty"):
        prep.prepare(ARCHIVE, legal)
    with (legal / "prompt.txt").open("a") as f:
        f.write(" added model-specific prompt")
    with pytest.raises(ValueError, match="hash mismatch"):
        ev.check_legal(legal, tmp_path / "input_provenance.json")


def test_wrong_dataset_archive_rejected_before_preparation(tmp_path):
    archive = tmp_path / "bad.tar.gz"
    archive.write_bytes(b"not the March 6 release")
    with pytest.raises(ValueError, match="March 6 pin"):
        prep.prepare(archive, tmp_path / "legal")
    assert not (tmp_path / "legal").exists()


def test_weight_lock_cannot_select_replacement_judge(tmp_path):
    lock = tmp_path / "lock.json"
    ckpt = {"vlm_model": str(tmp_path / "Qwen")}
    prep.write_json(lock, {"source_commit": ev.SOURCE_COMMIT, "ckpt": ckpt,
                          "model_identities": {"vlm": "replacement-judge"}, "artifacts": []})
    with pytest.raises(ValueError, match="no replacement"):
        ev.check_weight_lock(lock, {"ckpt": ckpt})


def test_commands_call_unchanged_official_scorers(tmp_path):
    commands = ev.scorer_commands(SOURCE, tmp_path, "pixelworld_codex", tmp_path / "config.yaml",
                                 "base_python", "vlm_python", "jepa_python")
    assert len(commands) == 7
    core = commands[4][1]
    assert core[1] == "evaluate.py" and core[core.index("--dimension") + 1:core.index("--config")] == list(ev.CORE)
    assert commands[5][1][0:2] == ["vlm_python", "VLM_judge.py"]
    assert "--num_frames" in commands[5][1] and "16" in commands[5][1]
    assert commands[6][1][0:2] == ["jepa_python", "batch.py"]
    assert "--max_samples" not in commands[6][1]
    assert not any("generate" in x or "baseline" in x for _, c in commands for x in c)
    full = ev.scorer_commands(SOURCE, tmp_path, "pixelworld_codex", tmp_path / "config.yaml",
                             "base", "vlm", "jepa", include_action=True)
    assert len(full) == 9 and full[-1][1][3] == "action_following"


def test_variant_submission_exact_names(tmp_path):
    folder = tmp_path / "pixelworld_codex_test_1"
    folder.mkdir()
    (folder / ev.external_filename("episode1")).touch()
    ev.check_submission(folder, "pixelworld_codex", ["episode1"], decode=False, variant=1)
    with pytest.raises(ValueError):
        ev.check_submission(folder, "pixelworld_codex", ["episode1"], decode=False)


def test_actual_source_field_and_aggregation_blockers():
    if not SOURCE.exists() or not BOARD.exists():
        pytest.skip("Optional official sources unavailable")
    contract = ev.source_contract(SOURCE, BOARD)
    assert contract["board_field_count"] == 15
    assert contract["official_csv_metric_count"] == 16
    assert contract["board_excludes"] == ["Action Following"]
    assert len(contract["known_upstream_blockers"]) == 2
    assert contract["full_total_allowed"] is False


def load_official_aggregator():
    if not SOURCE.exists():
        pytest.skip("Optional official sources unavailable")
    spec = importlib.util.spec_from_file_location("official_worldarena_csv", SOURCE / "video_quality/csv_results/aggregate_results.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_actual_unchanged_official_jepa_writer_blocker(tmp_path):
    # Isolated fixture demonstrates a code bug, not a benchmark score.
    agg = load_official_aggregator()
    (tmp_path / "output").mkdir()
    prep.write_json(tmp_path / "output/generated_results.json", {
        "image_quality": [0.5, [{"video_path": "generated_dataset/fixed_scene_task/episode1/1/video",
                                "video_results_normalized": 0.5}]]})
    (tmp_path / "output_JEDi").mkdir()
    prep.write_json(tmp_path / "output_JEDi/results.json", {"score": 0.5})
    with pytest.raises(ValueError, match="JEPA_Similarity"):
        agg.aggregate_results(str(tmp_path), "fixture_only")


def test_actual_photometric_field_is_omitted():
    agg = load_official_aggregator()
    assert "photometric_smoothness" not in agg.METRIC_KEY_MAP
    assert agg.METRIC_KEY_MAP["photometric_consistency"] == "Photometric Consistency"


def test_actual_board_15_field_aggregation(tmp_path):
    if not BOARD.exists():
        pytest.skip("Optional official leaderboard source unavailable")
    spec = importlib.util.spec_from_file_location("official_worldarena_board", BOARD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Synthetic numeric fixture solely validates aggregation/rounding. Not an official benchmark score.
    fields = {key: 0.2 for key in ev.BOARD_FIELDS}
    fields["Image Quality"] = 0.8
    fields["Action Following"] = 1.0  # explicitly ignored by actual board
    prep.write_json(tmp_path / "fixture_only.json", {"Metrics": fields})
    data = module.DataLoader(str(tmp_path)).load_results()
    assert data.iloc[0]["EWMScore"] == 24.0
    assert data.iloc[0]["Visual Quality"] == 40.0


def raw_fixture(work, model="fixture_only"):
    prep.write_json(work / "output/generated_results.json", {
        key: [0.5, [{"video_path": "generated_dataset/fixed_scene_task/episode1/1/video",
                     "video_results_normalized": 0.5}]] for key in ev.CORE})
    vlm_dir = work / "output_VLM" / model
    vlm_dir.mkdir(parents=True)
    prep.write_json(vlm_dir / f"{model}_summary_val_all_intern.json", [{
        "video": "fixed_scene_task_episode1.mp4", "error": None,
        "metrics": {key: {"score": 3, "score_normalized": 0.6} for key in ev.VLM}}])
    (work / "output_JEDi").mkdir()
    prep.write_json(work / "output_JEDi/results.json", {"score": 0.5})
    prep.write_json(work / "intersection_names.json", ["fixed_scene_task_episode1"])


def test_raw_strict_field_coverage_and_jepa_intersection(tmp_path):
    (tmp_path / "output").mkdir()
    raw_fixture(tmp_path)
    ev.check_raw_results(tmp_path, "fixture_only", ["episode1"])
    prep.write_json(tmp_path / "intersection_names.json", [])
    with pytest.raises(ValueError, match="dropped pairs"):
        ev.check_raw_results(tmp_path, "fixture_only", ["episode1"])


def test_named_compatibility_export_preserves_raw_values_and_upstream_source(tmp_path):
    if not SOURCE.exists() or not BOARD.exists():
        pytest.skip('Optional pinned sources unavailable')
    (tmp_path/'output').mkdir()
    raw_fixture(tmp_path)
    original = SOURCE/'video_quality/csv_results/aggregate_results.py'
    before = original.read_bytes()
    result = ev.aggregate_compatible(SOURCE,tmp_path,'fixture_only',['episode1'],BOARD,'one-episode-smoke')
    assert result['official_score'] is None and result['local_board_score'] is None
    import csv
    with (tmp_path/'csv_results/aggregated_results.csv').open() as f:
        row = next(csv.DictReader(f))
    assert float(row['JEPA Similarity']) == .5
    assert float(row['Photometric Consistency']) == .5
    assert float(row['Instruction Following']) == .6
    assert original.read_bytes() == before
    with pytest.raises(ValueError, match='all 1000'):
        ev.aggregate_compatible(SOURCE,tmp_path,'fixture_only',['episode1'],BOARD,'full')


def test_full_compatibility_calls_actual_public_15_field_board(tmp_path):
    if not SOURCE.exists() or not BOARD.exists():
        pytest.skip('Optional pinned sources unavailable')
    # Complete synthetic schema fixture; no models/videos are evaluated and
    # these numbers are never a benchmark artifact or published score.
    episodes=ev.select_episodes('full','episode1')
    paths=[f'generated_dataset/fixed_scene_task/{e}/1/video' for e in episodes]
    for directory in ('output','output_action_following','output_VLM/fixture_only','output_JEDi'):
        (tmp_path/directory).mkdir(parents=True)
    prep.write_json(tmp_path/'output/generated_results.json', {
        key:[.5,[{'video_path':p,'video_results_normalized':.5} for p in paths]] for key in ev.CORE})
    prep.write_json(tmp_path/'output_action_following/generated_results.json', {
        'action_following':[.5,[{'video_path':p,'video_results_normalized':.5} for p in paths]]})
    prep.write_json(tmp_path/'output_VLM/fixture_only/fixture_only_summary_val_all_intern.json', [
        {'video':ev.internal_id(e)+'.mp4','error':None,
         'metrics':{key:{'score':3,'score_normalized':.6} for key in ev.VLM}} for e in episodes])
    prep.write_json(tmp_path/'output_JEDi/results.json',{'score':.5})
    prep.write_json(tmp_path/'intersection_names.json',[ev.internal_id(e) for e in episodes])
    result=ev.aggregate_compatible(SOURCE,tmp_path,'fixture_only',episodes,BOARD,'full')
    assert result['local_board_score']==52.0
    assert result['published_board_metric_count']==15
    assert result['organizer_verified'] is False
    prep.write_json(tmp_path / "intersection_names.json", ["fixed_scene_task_episode1"])
    d = ev.load_json(tmp_path / "output/generated_results.json")
    del d["image_quality"]
    prep.write_json(tmp_path / "output/generated_results.json", d)
    with pytest.raises(ValueError, match="Exact core"):
        ev.check_raw_results(tmp_path, "fixture_only", ["episode1"])


def test_raw_partial_full_scope_rejected(tmp_path):
    (tmp_path / "output").mkdir()
    raw_fixture(tmp_path)
    with pytest.raises(ValueError, match="coverage"):
        ev.check_raw_results(tmp_path, "fixture_only", ev.select_episodes("full", "episode1"))
