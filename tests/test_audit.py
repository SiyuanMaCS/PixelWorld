import json
from pathlib import Path

import numpy as np
from PIL import Image

from pixelworld.audit import (canonicalize_tensor, invokes_network, invokes_subagent,
                              outside_command_paths, classify_outside_command_paths, validate)


def test_failed_literal_cd_is_warning_only_after_explicit_workspace_return(tmp_path):
    workspace=tmp_path/'workspace';workspace.mkdir()
    missing=tmp_path/'misspelled'
    command=f'cd {missing} 2>/dev/null; cd {workspace} && python generate.py'
    blocked,warnings=classify_outside_command_paths(command,workspace)
    assert blocked==[] and warnings==[str(missing)]
    # Existing outside directories and actual file reads remain blocked.
    missing.mkdir()
    assert classify_outside_command_paths(command,workspace)[0]==[str(missing)]
    assert classify_outside_command_paths(f'cat {missing}/reference.png',workspace)[0]
    missing.rmdir()
    assert classify_outside_command_paths(command+f'; cat {missing}/reference.png',workspace)[0]


def make_artifacts(workspace: Path, time_first=False):
    workspace.mkdir()
    frames = []
    yy, xx = np.indices((144, 256), dtype=np.uint16)
    for index in range(20):
        rgb = np.stack([(xx + index) % 256, (yy * 2 + index) % 256,
                        (xx + yy + index) % 256], axis=-1).astype(np.uint8)
        frames.append(rgb)
    frames = np.stack(frames)
    frames[0] = frames[0]
    Image.fromarray(frames[0]).save(workspace / "first_frame.png")
    folder = workspace / "frames"
    folder.mkdir()
    for index, frame in enumerate(frames):
        Image.fromarray(frame).save(folder / f"{index:02d}.png")
    values = frames.astype(np.uint32)
    packed = (values[..., 0] << 16) | (values[..., 1] << 8) | values[..., 2]
    tensor = packed if time_first else packed.transpose(1, 2, 0)
    np.savez_compressed(workspace / "pixels.npz", pixels=tensor)
    for name in ("generate.py", "inspection.png", "transition_check.png", "index.html",
                 "OBSERVATION.md", "METHOD.md"):
        if name.endswith(".png"):
            Image.fromarray(frames[0]).save(workspace / name)
        else:
            (workspace / name).write_text("ok")


def test_command_classification_is_command_level():
    assert invokes_subagent("codex exec 'child task'")
    assert not invokes_subagent("cat > METHOD.md <<'EOF'\nNo codex exec was used.\nEOF")
    assert invokes_network("curl https://example.com")
    assert not invokes_network("printf 'curl was forbidden' > METHOD.md")
    assert not invokes_network("cat > generate.py <<'PY'\n    curl = scorch * growth\nPY")
    assert not invokes_network("python - <<'PY'\ncurl=0.5\nPY")
    workspace = Path("/tmp/workspace")
    assert outside_command_paths("sed -n 1,20p /home/user/.codex/skills/SKILL.md", workspace)
    assert not outside_command_paths("/bin/bash -lc 'python3 generate.py'", workspace)
    assert not outside_command_paths("find . -not -path './candidate/*' -not -path './.git/*'",workspace)
    assert outside_command_paths('cat /candidate/other.png',workspace)


def test_python_division_is_not_an_absolute_file_access(tmp_path):
    assert outside_command_paths("python - <<'PY'\nx=int((r+g+b)/3/26)\nPY",tmp_path)==[]
    assert outside_command_paths("python - <<'PY'\nopen('/3/26').read()\nPY",tmp_path)==['/3/26']
    assert outside_command_paths('cat /3/26',tmp_path)==['/3/26']


def test_shell_wrapped_python_floor_division_does_not_hide_real_file_paths(tmp_path):
    import shlex
    script = "python - <<'PY'\na = 123/3//23\nprint(a)\nPY"
    assert outside_command_paths('/bin/bash -lc ' + shlex.quote(script), tmp_path) == []
    script = "python - <<'PY'\na = 123/3//23\nopen('/other/case/first_frame.png').read()\nPY"
    assert '/other/case/first_frame.png' in outside_command_paths(
        '/bin/bash -lc ' + shlex.quote(script), tmp_path)


def test_lossless_time_first_canonicalization(tmp_path):
    workspace = tmp_path / "workspace"
    logs = tmp_path / "logs"
    make_artifacts(workspace, time_first=True)
    before = np.load(workspace / "pixels.npz")["pixels"].copy()
    report = canonicalize_tensor(workspace, logs)
    after = np.load(workspace / "pixels.npz")["pixels"]
    assert report and report["rgb_frames_changed"] is False
    assert np.array_equal(after, before.transpose(1, 2, 0))


def test_validation_and_track_visual_boundary(tmp_path):
    workspace = tmp_path / "workspace"
    make_artifacts(workspace)
    clean = tmp_path / "clean.jsonl"
    clean.write_text(json.dumps({"type": "turn.completed"}) + "\n")
    assert validate(workspace, clean, 0, "text")["pass"]
    visual = tmp_path / "visual.jsonl"
    visual.write_text("\n".join([
        json.dumps({"type": "item.completed", "item": {"type": "view_image", "name": "view_image"}}),
        json.dumps({"type": "turn.completed"}),
    ]) + "\n")
    assert not validate(workspace, visual, 0, "text")["pass"]
    assert validate(workspace, visual, 0, "vision-agent")["pass"]


def test_frame_zero_is_checked_against_frozen_input(tmp_path):
    workspace = tmp_path / "workspace"
    make_artifacts(workspace)
    original = tmp_path / "input_snapshot" / "first_frame.png"
    original.parent.mkdir()
    with Image.open(workspace / "first_frame.png") as im:
        im.save(original)
    events = tmp_path / "events.jsonl"
    events.write_text(json.dumps({"type": "turn.completed"}) + "\n")
    assert validate(workspace, events, 0, "text")["pass"]
    # Altering the workspace input must not redefine the original I2V anchor.
    with Image.open(original) as im:
        changed = np.asarray(im.convert("RGB")).copy()
    changed[0, 0] ^= 255
    Image.fromarray(changed).save(workspace / "first_frame.png")
    assert validate(workspace, events, 0, "text")["pass"]
    Image.fromarray(changed).save(workspace / "frames" / "00.png")
    result = validate(workspace, events, 0, "text")
    assert result["frame0_exact"] is False
    assert result["pass"] is False


def test_image_return_hidden_by_stdout_projection_enforces_track(tmp_path):
    workspace=tmp_path/'workspace';make_artifacts(workspace)
    events=tmp_path/'events.jsonl'
    events.write_text('\n'.join([json.dumps({'type':'turn.completed'}),
        json.dumps({'type':'item.completed','item':{'type':'full_trace_image_return',
            'call_id':'nested-image','returned_images':[{'path':'tool_images/a.png'}]}})])+'\n')
    assert not validate(workspace,events,0,'text')['pass']
    assert not validate(workspace,events,0,'vision-input')['pass']
    assert validate(workspace,events,0,'vision-agent')['pass']


def test_failed_patch_request_does_not_claim_successful_external_write(tmp_path):
    workspace=tmp_path/'workspace';make_artifacts(workspace)
    events=tmp_path/'events.jsonl';outside=str(tmp_path/'missing/generate.py')
    events.write_text('\n'.join([json.dumps({'type':'item.completed','item':{'type':'file_change','status':'failed','changes':[{'path':outside,'kind':'update'}]}}),json.dumps({'type':'turn.completed'})])+'\n')
    result=validate(workspace,events,0,'vision-agent')
    assert result['pass'] and result['outside_workspace_file_changes']==[]
    assert result['failed_outside_workspace_file_change_attempts']==[outside]
