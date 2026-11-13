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


def test_lowered_cap_preserves_authorized_success_but_never_launches_above_cap(tmp_path):
    from dataclasses import replace
    config,model=fixture(tmp_path)
    for attempt in (1,2):manifest(config,model,'bad',attempt,{'status':'failed'})
    authorize_failed(config,extra_attempts=4,max_rounds=None,apply=True)
    success=manifest(config,model,'bad',6,{'status':'complete','validation':{'pass':True}})
    capped=replace(config,max_total_attempts=5)
    assert inspect(capped,model,'text','bad')['state']=='complete'
    assert inspect(capped,model,'text','bad')['attempt']==6
    (success/'run_manifest.json').write_text('{"status":"failed"}')
    for attempt in (3,4,5):manifest(config,model,'bad',attempt,{'status':'failed'})
    state=inspect(capped,model,'text','bad')
    assert state['state']=='exhausted' and state['attempt']==5
    assert not (run_path(capped,model,'text','bad',7)).exists()


def test_pending_authorization_recovers_manager_without_another_grant(tmp_path):
    from tools.watch_failed_retries import needs_manager
    config,model=fixture(tmp_path)
    for attempt in (1,2):manifest(config,model,'bad',attempt,{'status':'failed'})
    manifest(config,model,'good',1,{'status':'complete','validation':{'pass':True}})
    authorize_failed(config,apply=True)
    report=authorize_failed(config,apply=True)
    assert report['authorized_cases']==0 and report['pending_cases']==1
    assert needs_manager(report)
    assert not needs_manager({'authorized_cases':0,'pending_cases':0,'running_cases':0})


def test_retry_service_skips_completed_cohort_without_changing_original_config(tmp_path):
    from tools.watch_failed_retries import unfinished_retry_scope
    config, model = fixture(tmp_path)
    config.runs_root.mkdir()
    (config.runs_root/'status.json').write_text(json.dumps({'groups':{'m/text':{'counts':{'complete':2}}}}))
    filtered = unfinished_retry_scope(config)
    assert filtered.models == ()
    assert config.models[0].tracks == ('text',)
    assert filtered.source == config.source


def test_retry_service_retains_pending_and_exhausted_cohorts(tmp_path):
    from tools.watch_failed_retries import unfinished_retry_scope
    config, model = fixture(tmp_path)
    config.runs_root.mkdir()
    (config.runs_root/'status.json').write_text(json.dumps({'groups':{'m/text':{'counts':{'complete':1,'exhausted':1}}}}))
    assert unfinished_retry_scope(config).models == config.models


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


def test_live_old_attempt_is_not_duplicated_by_a_retry_grant(tmp_path, monkeypatch):
    config, model = fixture(tmp_path)
    for attempt in (1, 2):
        manifest(config, model, "bad", attempt, {"status": "failed"})
    authorize_failed(config, apply=True)
    old = run_path(config, model, "text", "bad", 1)
    (old / "run_manifest.json").write_text(json.dumps({"status": "running"}))
    (old / "logs").mkdir()
    (old / "logs/supervisor.pid").write_text(str(os.getpid()))
    monkeypatch.setattr('pixelworld.supervisor._pid_alive', lambda path, expected_arguments=(): True)
    assert inspect(config, model, "text", "bad")["state"] == "running"


def test_reused_pid_does_not_hide_a_completed_later_attempt(tmp_path):
    config, model = fixture(tmp_path)
    old = manifest(config, model, 'bad', 1, {'status':'running'})
    (old/'logs').mkdir()
    (old/'logs/supervisor.pid').write_text(str(os.getpid()))
    manifest(config, model, 'bad', 2, {'status':'complete','validation':{'pass':True}})
    assert inspect(config, model, 'text', 'bad')['state'] == 'complete'
    assert inspect(config, model, 'text', 'bad')['attempt'] == 2
    (run_path(config, model, 'text', 'bad', 2)/'run_manifest.json').unlink()
    assert inspect(config, model, 'text', 'bad')['state'] != 'running'


def test_validated_submission_takes_priority_over_an_older_live_record(tmp_path, monkeypatch):
    config, model = fixture(tmp_path)
    manifest(config, model, 'bad', 1, {'status':'running'})
    manifest(config, model, 'bad', 2, {'status':'complete','validation':{'pass':True}})
    monkeypatch.setattr('pixelworld.supervisor._pid_alive', lambda path, expected_arguments=(): True)
    assert inspect(config, model, 'text', 'bad')['state'] == 'complete'


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


def test_repeated_failure_does_not_starve_an_unattempted_case(tmp_path, monkeypatch):
    from pixelworld import supervisor
    config, model = fixture(tmp_path)
    for attempt in (1,2):manifest(config,model,'bad',attempt,{'status':'failed'})
    authorize_failed(config,max_rounds=None,apply=True)
    (config.source.parent/'scheduling_limits.json').write_text(json.dumps({'prioritize_less_attempted_cases':True}))
    launched=[]
    def launch(*args):
        launched.append(args[3]);(config.runs_root/'STOP').touch();return 123
    monkeypatch.setattr(supervisor,'_launch',launch)
    supervisor.run(config,interval=.001)
    assert launched==['good','bad']
    assert (run_path(config,model,'text','bad',1)/'run_manifest.json').is_file()
