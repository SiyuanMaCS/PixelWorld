import json
import os
from pathlib import Path

from PIL import Image

from pixelworld.config import load_config
from pixelworld.retries import authorize_failed
from pixelworld.runner import _prior_attempt_usage, run_case, run_path
from pixelworld.supervisor import inspect


def fixture(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"inputs_root": "inputs", "runs_root": "runs", "case_ids": ["bad", "good"],
                               "models": [{"key": "m", "model": "fixture", "tracks": ["text"]}]}))
    config = load_config(path)
    for case in config.case_ids:
        source = config.inputs_root / case
        source.mkdir(parents=True)
        Image.new("RGB", (32, 24), "white").save(source / "first_frame.png")
        (source / "prompt.txt").write_text("Fixture input only.")
        (source / "task_spec.json").write_text(json.dumps(
            {"task_type": "i2v", "width": 32, "height": 24, "frames": 6, "fps": 3, "audio": None}))
    return config, config.models[0]


def manifest(config, model, case, attempt, value):
    path = run_path(config, model, "text", case, attempt)
    path.mkdir(parents=True, exist_ok=True)
    (path / "run_manifest.json").write_text(json.dumps(value))
    return path


def test_retry_preserves_failure_history_and_does_not_redo_success(tmp_path):
    config, model = fixture(tmp_path)
    old = manifest(config, model, "bad", 1, {"status": "failed", "retryable": False,
                   "stop_reason": "output_token_budget_exhausted", "token_usage": {"output_tokens": 120000}})
    before = (old / "run_manifest.json").read_bytes()
    manifest(config, model, "good", 2, {"status": "complete", "validation": {"pass": True}})
    result = authorize_failed(config, apply=True)
    assert result["authorized_cases"] == 1 and result["items"][0]["start_attempt"] == 3
    assert (old / "run_manifest.json").read_bytes() == before
    assert inspect(config, model, "text", "good")["state"] == "complete"
    assert inspect(config, model, "text", "bad")["attempt"] == 3
    assert authorize_failed(config, apply=True)["authorized_cases"] == 0


def test_new_retry_budget_is_fresh_and_accumulates_within_its_round(tmp_path):
    config, model = fixture(tmp_path)
    for attempt in (1, 2):
        manifest(config, model, "bad", attempt,
                 {"status": "failed", "token_usage": {"output_tokens": 70000}})
    authorize_failed(config, apply=True)
    output, unknown, _ = _prior_attempt_usage(config, model, "text", "bad", 3)
    assert output == 0 and unknown is False
    result = run_case(config, "m", "text", "bad", 3, codex_binary="/bin/true", dry_run=True)
    assert result["output_token_budget"] == 100000
    assert result["budget_scope_start_attempt"] == 3 and result["prior_attempt_output_tokens"] == 0
    path = run_path(config, model, "text", "bad", 3)
    (path / "run_manifest.json").write_text(json.dumps(
        {"status": "failed", "token_usage": {"output_tokens": 60000}}))
    assert _prior_attempt_usage(config, model, "text", "bad", 4)[:2] == (60000, False)


def test_live_old_attempt_is_not_duplicated_by_a_retry_grant(tmp_path):
    config, model = fixture(tmp_path)
    for attempt in (1, 2):
        manifest(config, model, "bad", attempt, {"status": "failed"})
    authorize_failed(config, apply=True)
    old = run_path(config, model, "text", "bad", 1)
    (old / "run_manifest.json").write_text(json.dumps({"status": "running"}))
    (old / "logs").mkdir()
    (old / "logs/supervisor.pid").write_text(str(os.getpid()))
    assert inspect(config, model, "text", "bad")["state"] == "running"


def test_budget_exhaustion_and_max_retry_rounds_still_bound_work(tmp_path):
    config, model = fixture(tmp_path)
    for attempt in (1, 2):
        manifest(config, model, "bad", attempt, {"status": "failed"})
    authorize_failed(config, apply=True)
    manifest(config, model, "bad", 3, {"status": "failed", "retryable": False,
             "stop_reason": "output_token_budget_exhausted", "token_usage": {"output_tokens": 100001}})
    result = inspect(config, model, "text", "bad")
    assert result["state"] == "exhausted" and result["budget_terminal"]
    assert authorize_failed(config, apply=True)["authorized_cases"] == 0


def test_continuous_retry_reopens_exhausted_rounds_with_cooldown_and_fresh_budget(tmp_path):
    config,model=fixture(tmp_path)
    for attempt in (1,2):manifest(config,model,'bad',attempt,{'status':'failed','token_usage':{'output_tokens':50000}})
    manifest(config,model,'good',1,{'status':'complete','validation':{'pass':True}})
    first=authorize_failed(config,max_rounds=None,apply=True)
    assert first['items'][0]['start_attempt']==3
    for attempt in (3,4):manifest(config,model,'bad',attempt,{'status':'failed','token_usage':{'output_tokens':50000}})
    assert authorize_failed(config,max_rounds=None,apply=True,cooldown_seconds=300)['authorized_cases']==0
    second=authorize_failed(config,max_rounds=None,apply=True)
    assert second['items'][0]['start_attempt']==5
    assert _prior_attempt_usage(config,model,'text','bad',5)[:2]==(0,False)
    assert inspect(config,model,'text','good')['state']=='complete'
    assert (run_path(config,model,'text','bad',1)/'run_manifest.json').is_file()


def test_incomplete_physics_cohort_returns_to_waiting_when_retries_are_pending(tmp_path, monkeypatch):
    from tools import watch_physics_evaluation as watcher
    config, model = fixture(tmp_path)
    config.runs_root.mkdir(parents=True)
    (config.runs_root / "status.json").write_text(json.dumps({"groups": {
        "m/text": {"counts": {"complete": 196, "pending": 2}}}}))
    monkeypatch.setattr(watcher, "official_cases", lambda: [{"id": str(i)} for i in range(198)])
    states = watcher.step(config, None, tmp_path / "evaluation",
                          {"m/text": {"phase": "incomplete_official_scope"}})
    assert states["m/text"]["phase"] == "waiting_for_generation"


def test_shared_model_limit_defers_launch_until_an_existing_slot_is_free(tmp_path, monkeypatch):
    from dataclasses import replace
    from pixelworld import scheduling, supervisor
    config, model = fixture(tmp_path)
    root = tmp_path / "experiment"
    config = replace(config, source=root / "config.json", runs_root=root / "generations/suite")
    root.mkdir()
    (root / "scheduling_limits.json").write_text(json.dumps({"max_per_model": 2}))
    command = f"python -m pixelworld.cli run-case --config {config.source} --model m --case x --track text"
    samples = [command + "\n" + command, command]
    monkeypatch.setattr(scheduling.subprocess, "check_output", lambda *a, **k: samples.pop(0))
    launched = []
    def launch(*args):
        launched.append(args[3])
        (config.runs_root / "STOP").touch()
        return 123
    monkeypatch.setattr(supervisor, "_launch", launch)
    supervisor.run(config, interval=0.001)
    assert len(launched) == 1 and not samples
