import csv
import json
from pathlib import Path

import pytest
from PIL import Image

from pixelworld.config import load_config
from pixelworld import runner
from pixelworld.usage import collect_usage, record_run, backfill


def log(path, events):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(event) for event in events) + "\n")


def test_multi_turn_usage_preserves_reasoning_and_cache_fields(tmp_path):
    p = tmp_path / "events.jsonl"
    log(p, [
        {"type": "item.completed", "usage": {"output_tokens": 999}},
        {"type": "turn.completed", "usage": {"input_tokens": 100, "output_tokens": 50,
             "reasoning_output_tokens": 20, "cache_write_input_tokens": 30}},
        {"type": "turn.completed", "usage": {"input_tokens": 200, "output_tokens": 75,
             "reasoning_output_tokens": 30, "cache_write_input_tokens": 40}},
    ])
    value = collect_usage(p)
    assert value["status"] == "recorded"
    assert value["output_tokens"] == 125
    assert value["reasoning_output_tokens"] == 50
    assert value["cache_creation_input_tokens"] == 70
    assert value["cached_input_tokens"] is None
    assert value["total_tokens"] is None


def test_missing_partial_and_truncated_usage_are_not_zero(tmp_path):
    p = tmp_path / "events.jsonl"
    assert collect_usage(p)["status"] == "missing"
    assert collect_usage(p, finished=False)["status"] == "pending"
    log(p, [{"type": "turn.completed", "usage": {"input_tokens": 100, "output_tokens": 50}},
            {"type": "turn.failed"}])
    with p.open("a") as stream:
        stream.write('not-json\n[1, 2]\n{"unfinished":')
    value = collect_usage(p)
    assert value["status"] == "partial"
    assert value["output_tokens"] is None
    assert value["raw_turn_usages"][0]["usage"]["output_tokens"] == 50
    assert value["malformed_jsonl_lines"] == 3


def test_backfill_preserves_attempts_status_and_skips_active_writer(tmp_path):
    for attempt, status in ((1, "failed"), (2, "complete"), (3, "running")):
        run = tmp_path / "runs" / f"case_0001_attempt_{attempt:02d}"
        run.mkdir(parents=True)
        (run / "run_manifest.json").write_text(json.dumps({"model": "test", "track": "text",
            "case_id": "0001", "attempt": attempt, "status": status, "custom": "preserved"}))
        log(run / "logs/events.jsonl", [{"type": "turn.completed", "usage": {
            "input_tokens": 100, "output_tokens": attempt * 10}}])
    active = tmp_path / "runs/case_0001_attempt_03"
    before = (active / "run_manifest.json").read_bytes()
    report = backfill(tmp_path / "runs", tmp_path / "report")
    assert report["recorded"] == 2 and report["pending"] == 1
    assert (active / "run_manifest.json").read_bytes() == before
    accepted = tmp_path / "runs/case_0001_attempt_02"
    manifest = json.loads((accepted / "run_manifest.json").read_text())
    assert manifest["status"] == "complete" and manifest["custom"] == "preserved"
    assert manifest["token_usage"]["output_tokens"] == 20
    assert not record_run(accepted)
    rows = list(csv.DictReader((tmp_path / "report/per_run.csv").open()))
    assert len(rows) == 3
    assert rows[0]["output_tokens"] == "10" and rows[1]["output_tokens"] == "20"


@pytest.mark.parametrize("exit_code", [0, 1])
def test_runner_persists_api_usage_on_success_and_failure(tmp_path, monkeypatch, exit_code):
    source = tmp_path / "inputs/0001"
    source.mkdir(parents=True)
    Image.new("RGB", (256, 144), (70, 80, 90)).save(source / "first_frame.png")
    (source / "prompt.txt").write_text("Synthetic runner integration smoke; not a model result.")
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"inputs_root": "inputs", "runs_root": "runs",
        "models": [{"key": "fake", "model": "fake", "provider": {"type": "builtin"},
                    "tracks": ["text"]}]}))
    fake = tmp_path / "fake-codex"
    fake.write_text('''#!/usr/bin/env python3
import sys, os, json, contextlib, io
if '--version' in sys.argv:
    print('codex-cli synthetic-test-double'); sys.exit(0)
workspace = sys.argv[sys.argv.index('-C')+1]
os.chdir(workspace); sys.path.insert(0, workspace)
from pathlib import Path
from PIL import Image
import numpy as np
from artifact_io import save
Path('generate.py').write_text('# Synthetic runner integration fixture.\\n')
src=np.asarray(Image.open('first_frame.png'))
with contextlib.redirect_stdout(io.StringIO()):
    save(np.repeat(src[None],20,axis=0),Path('.'))
Image.fromarray(src).save('transition_check.png')
print(json.dumps({'type':'turn.completed','usage':{'input_tokens':120,'output_tokens':80,'reasoning_output_tokens':30}}))
sys.exit(EXIT_CODE)
'''.replace("EXIT_CODE", str(exit_code)))
    fake.chmod(0o755)
    monkeypatch.setattr(runner, "WATCHDOG_POLL_SECONDS", .01)
    result = runner.run_case(load_config(config_path), "fake", "text", "0001", codex_binary=str(fake))
    assert result["status"] == ("complete" if exit_code == 0 else "failed")
    assert result["token_usage"]["output_tokens"] == 80
    assert result["token_usage"]["reasoning_output_tokens"] == 30
    path = tmp_path / "runs/fake/text/case_0001_attempt_01"
    assert json.loads((path / "logs/token_usage.json").read_text()) == result["token_usage"]
    assert json.loads((path / "run_manifest.json").read_text())["token_usage"] == result["token_usage"]
    assert (path / "task_prompt.txt").read_text().startswith("Generate the RGB video requested")
    assert result["task_prompt_file"] == "task_prompt.txt"
    assert result['generation_contract'] == 'minimal-v2'
    assert not (path / 'workspace/OBSERVATION.md').exists()
    assert not (path / 'workspace/METHOD.md').exists()
    assert (path / 'logs/events.raw.jsonl').is_file()
    if exit_code == 0:
        from pixelworld.web import build
        (source.parent.parent / 'manifest.json').write_text(json.dumps({
            'cases':[{'id':'0001','scenario':'synthetic-runner-smoke'}]}))
        result_config = load_config(config_path)
        # Limit this fixture's gallery to its single prepared input.
        from dataclasses import replace
        result_config = replace(result_config, case_ids=('0001',))
        site = tmp_path / 'site'
        report = build(result_config,site)
        assert report['players'] == 1
        trace = (site/'traces/fake/text/0001/index.html').read_text()
        assert 'No optional method report was written.' in trace
        assert 'Code changes' in trace
