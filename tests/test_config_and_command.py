import json
from pathlib import Path

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
