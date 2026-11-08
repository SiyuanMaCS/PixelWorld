"""Submission gates use unscored provenance fixtures; no video-model inference."""
import json
from pathlib import Path
from types import SimpleNamespace
import uuid

import pytest

from tools import prepare_vbench_submission as submission
from tools import watch_vbench_evaluation as watcher


def fixture_runs(tmp_path, monkeypatch):
    model = SimpleNamespace(key="test-model", tracks=["text"])
    config = SimpleNamespace(runs_root=tmp_path)
    runs = {}
    for sample in range(5):
        cid = f"0000_s{sample}"
        run = tmp_path / cid
        run.mkdir()
        record = {"model_key": model.key, "track": "text", "case_id": cid,
                  "full_trace": {"thread_id": str(uuid.uuid4())}}
        (run / "run_manifest.json").write_text(json.dumps(record))
        runs[cid] = {"state": "complete", "run": str(run), "attempt": 1}
    monkeypatch.setattr(submission, "inspect", lambda c, m, t, cid: runs[cid])
    return config, model, runs


def test_collect_uses_only_earliest_supervisor_accepted_attempt(tmp_path, monkeypatch):
    config, model, runs = fixture_runs(tmp_path, monkeypatch)
    records, missing = submission.collect_runs(config, model, "text", [0])
    assert not missing
    assert len(records) == 5
    assert all(record["run"] == Path(runs[f'0000_s{record["sample_index"]}']["run"]) for record in records)


def test_missing_or_budget_exhausted_sample_blocks_full_export(tmp_path, monkeypatch):
    config, model, runs = fixture_runs(tmp_path, monkeypatch)
    runs["0000_s2"] = {"state": "exhausted", "reason": "output_token_budget_exhausted", "run": str(tmp_path/"failed")}
    records, missing = submission.collect_runs(config, model, "text", [0])
    assert len(records) == 4
    assert missing[0]["case_id"] == "0000_s2"
    assert missing[0]["reason"] == "output_token_budget_exhausted"


def test_duplicate_session_is_not_an_independent_sample(tmp_path, monkeypatch):
    config, model, runs = fixture_runs(tmp_path, monkeypatch)
    first = json.loads((Path(runs["0000_s0"]["run"])/"run_manifest.json").read_text())
    other = Path(runs["0000_s1"]["run"])/"run_manifest.json"
    record = json.loads(other.read_text())
    record["full_trace"] = first["full_trace"]
    other.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="independent"):
        submission.collect_runs(config, model, "text", [0])


def test_incorrect_cohort_identity_cannot_enter_submission(tmp_path, monkeypatch):
    config, model, runs = fixture_runs(tmp_path, monkeypatch)
    path = Path(runs["0000_s1"]["run"])/"run_manifest.json"
    record = json.loads(path.read_text())
    record["track"] = "vision-agent"
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="identity"):
        submission.collect_runs(config, model, "text", [0])


def test_prepare_waits_without_exporting_partial_artifacts(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    config = SimpleNamespace(runs_root=tmp_path/"generations", model=lambda _: "model")
    monkeypatch.setattr(submission, "validate_source", lambda _: None)
    monkeypatch.setattr(submission, "load_official_metadata", lambda _: [{"prompt_en": "unscored fixture"}])
    monkeypatch.setattr(submission, "requested_scope", lambda *args: ([0], []))
    monkeypatch.setattr(submission, "collect_runs", lambda *args: ([], [{"case_id": "0000_s0", "state": "pending"}]))
    monkeypatch.setattr(submission, "export_record", lambda *args: pytest.fail("No export before complete scope"))
    output = tmp_path / "eval/submission.json"
    report = submission.prepare(config, "model", "text", source, tmp_path/"unused_proof", output)
    assert report["status"] == "waiting_for_generation"
    assert not output.exists()


def test_watcher_progress_hint_never_triggers_partial_scoring(tmp_path, monkeypatch):
    root = tmp_path/"generations"
    root.mkdir()
    (root/"status.json").write_text(json.dumps({"groups": {"test-model/text": {"counts": {"complete": 4, "exhausted": 1}}}}))
    config = SimpleNamespace(runs_root=root, models=[SimpleNamespace(key="test-model", tracks=["text"])])
    monkeypatch.setattr(watcher, "load_official_metadata", lambda _: [{}])
    monkeypatch.setattr(watcher, "collect_runs", lambda *args: pytest.fail("No repeated full scan while waiting"))
    output = tmp_path/"evaluation"
    states = watcher.step(config, tmp_path/"source", tmp_path/"proof", output, {})
    assert states["test-model/text"]["phase"] == "waiting_for_generation"
    assert states["test-model/text"]["exhausted_samples"] == 1
    assert not states["test-model/text"]["official_full_score"]


def test_watcher_fully_validates_ready_hint_before_export(tmp_path, monkeypatch):
    root = tmp_path/"generations"
    root.mkdir()
    (root/"status.json").write_text(json.dumps({"groups": {"test-model/text": {"counts": {"complete": 5}}}}))
    config = SimpleNamespace(runs_root=root, models=[SimpleNamespace(key="test-model", tracks=["text"])])
    monkeypatch.setattr(watcher, "load_official_metadata", lambda _: [{}])
    # A stale readiness hint must not bypass the authoritative inventory.
    monkeypatch.setattr(watcher, "collect_runs", lambda *args: ([], [{"state": "exhausted"}]))
    monkeypatch.setattr(watcher, "prepare", lambda *args: pytest.fail("Incomplete inventory cannot be exported"))
    states = watcher.step(config, tmp_path/"source", tmp_path/"proof", tmp_path/"evaluation", {})
    assert states["test-model/text"]["phase"] == "waiting_for_generation"
    assert not states["test-model/text"]["official_full_score"]
