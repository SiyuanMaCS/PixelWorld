import json
from pathlib import Path
import os
import subprocess
import sys
import time

from pixelworld.config import load_config
from pixelworld.runner import codex_command


def make_config(tmp_path: Path, provider=None):
    value = {
        "inputs_root": "inputs",
        "runs_root": "runs",
        "models": [{
            "key": "model-a", "model": "actual-model", "reasoning_effort": "high",
            "provider": provider or {"type": "builtin"},
            "tracks": ["text", "vision-input", "vision-agent"],
        }],
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(value))
    return load_config(path)


def disabled(command, feature):
    return any(command[index:index + 2] == ["--disable", feature]
               for index in range(len(command) - 1))


def test_three_track_command_boundaries(tmp_path):
    config = make_config(tmp_path)
    model = config.model("model-a")
    workspace = tmp_path / "workspace"
    text = codex_command(model, "text", workspace)
    vision_input = codex_command(model, "vision-input", workspace)
    vision_agent = codex_command(model, "vision-agent", workspace)
    assert "--image" not in text and disabled(text, "view_image")
    assert vision_input[vision_input.index("--image") + 1].endswith("first_frame.png")
    assert disabled(vision_input, "view_image")
    assert "--image" in vision_agent and not disabled(vision_agent, "view_image")
    for command in (text, vision_input, vision_agent):
        assert ["--sandbox", "workspace-write"] == command[command.index("--sandbox"):command.index("--sandbox") + 2]
        assert "sandbox_workspace_write.network_access=false" in command
        assert any(value.startswith("shell_environment_policy.set.PATH=") for value in command)
        assert 'web_search="disabled"' in command
        assert "skills.bundled.enabled=false" in command
        assert command.index("--ask-for-approval") < command.index("exec")
        assert disabled(command, "multi_agent") and disabled(command, "image_generation")


def test_custom_responses_provider_is_explicit(tmp_path):
    config = make_config(tmp_path, {
        "type": "responses", "id": "gateway", "name": "Gateway",
        "base_url": "https://api.example.com/v1", "env_key": "GATEWAY_API_KEY",
    })
    command = codex_command(config.model("model-a"), "text", tmp_path / "w")
    joined = "\n".join(command)
    assert 'model_provider="gateway"' in joined
    assert 'model_providers.gateway.base_url="https://api.example.com/v1"' in joined
    assert 'model_providers.gateway.env_key="GATEWAY_API_KEY"' in joined
    assert "secret" not in joined.lower()


def test_relative_paths_are_resolved_from_config(tmp_path):
    config = make_config(tmp_path)
    assert config.inputs_root == tmp_path / "inputs"
    assert config.runs_root == tmp_path / "runs"


def test_clean_run_freezes_provider_catalog_without_user_config(tmp_path):
    from PIL import Image
    from pixelworld.runner import run_case
    catalog = tmp_path / 'catalog.json'
    catalog.write_text('{"models":[{"slug":"actual-model"}]}')
    config = make_config(tmp_path, {
        'type':'responses', 'id':'gateway', 'name':'Gateway',
        'base_url':'http://127.0.0.1:9585/v1', 'env_key':'TEST_KEY',
        'model_catalog_json':'catalog.json', 'stream_idle_timeout_ms':3600000,
    })
    source = config.inputs_root / 'case_alpha'
    source.mkdir(parents=True)
    Image.new('RGB', (256,144), 'white').save(source/'first_frame.png')
    (source/'prompt.txt').write_text('Fixture instruction.')
    result = run_case(config, 'model-a', 'text', 'case_alpha', dry_run=True)
    run = config.runs_root/'model-a/text/case_case_alpha_attempt_01'
    assert result['model_catalog_snapshot']['file']=='model_catalog.json'
    before=(run/'model_catalog.json').read_bytes()
    catalog.write_text('{"models":[{"slug":"changed-later"}]}')
    assert (run/'model_catalog.json').read_bytes()==before
    assert '--ignore-user-config' in result['command']
    assert any(v.startswith('model_catalog_json=') and str(run) in v for v in result['command'])
    assert 'model_providers.gateway.stream_idle_timeout_ms=3600000' in result['command']


def test_queue_supports_benchmark_case_names(tmp_path, monkeypatch):
    from pixelworld import supervisor
    config=make_config(tmp_path)
    from dataclasses import replace
    config=replace(config,case_ids=('sample_2','common50_0001'),max_concurrency=1)
    launched=[]
    def launch(config,model,track,case,attempt):
        launched.append(case)
        (config.runs_root/'STOP').touch()
        return 123
    monkeypatch.setattr(supervisor,'_launch',launch)
    supervisor.run(config,interval=0.001)
    assert launched==['common50_0001']


def test_failed_case_does_not_cancel_unrelated_pending_cases(tmp_path, monkeypatch):
    import pytest
    from dataclasses import replace
    from pixelworld import supervisor
    from pixelworld.runner import run_path
    config = make_config(tmp_path)
    model = replace(config.models[0], tracks=('text',))
    config = replace(config, models=(model,), case_ids=('bad', 'good'), max_attempts=1)
    failed = run_path(config, model, 'text', 'bad', 1)
    failed.mkdir(parents=True)
    (failed / 'run_manifest.json').write_text(json.dumps({'status': 'failed'}))
    launched = []
    def launch(config, model, track, case, attempt):
        launched.append(case)
        run = run_path(config, model, track, case, attempt)
        run.mkdir(parents=True)
        (run / 'run_manifest.json').write_text(json.dumps(
            {'status': 'complete', 'validation': {'pass': True}}))
        return 123
    monkeypatch.setattr(supervisor, '_launch', launch)
    with pytest.raises(RuntimeError, match='other cases have finished'):
        supervisor.run(config, interval=0.001)
    assert launched == ['good']
    final = json.loads((config.runs_root / 'status.json').read_text())
    assert final['totals'] == {'exhausted': 1, 'complete': 1}


def test_pid_alive_treats_zombie_as_dead(tmp_path):
    import pytest
    from pixelworld import supervisor
    if not Path('/proc').exists() or not hasattr(os, 'fork'):
        pytest.skip('requires Linux /proc and fork')
    script = (
        "import os,time\n"
        "pid=os.fork()\n"
        "if pid==0: os._exit(0)\n"
        "print(pid, flush=True)\n"
        "time.sleep(10)\n"
        "os.waitpid(pid, 0)\n"
    )
    proc = subprocess.Popen([sys.executable, '-c', script],
                            stdout=subprocess.PIPE, text=True)
    try:
        assert proc.stdout is not None
        child_pid = int(proc.stdout.readline().strip())
        stat_path = Path('/proc') / str(child_pid) / 'stat'
        deadline = time.time() + 5
        while time.time() < deadline:
            if stat_path.exists() and stat_path.read_text().rsplit(') ', 1)[1].split()[0] == 'Z':
                break
            time.sleep(0.05)
        else:
            pytest.skip('could not observe zombie state')
        pid_file = tmp_path / 'supervisor.pid'
        pid_file.write_text(f'{child_pid}\n')
        assert supervisor._pid_alive(pid_file) is False
    finally:
        proc.terminate()
        proc.wait(timeout=5)
