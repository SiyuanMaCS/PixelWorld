import importlib.util
import json
from pathlib import Path

import numpy as np
from PIL import Image

from pixelworld.audit import validate
from pixelworld.constants import ASSET_ROOT
from pixelworld.media import contract, task_rules, DEFAULT_MEDIA
from pixelworld.snapshot import candidate_key, freeze


def output(tmp_path, task_type="t2v", audio=None, n=6):
    spec = {"task_type": task_type, "frames": n, "width": 32, "height": 24,
            "fps": 3, "audio": audio}
    (tmp_path / "task_spec.json").write_text(json.dumps(spec))
    (tmp_path / "prompt.txt").write_text("A ball bounces.")
    (tmp_path / "generate.py").write_text("# candidate code\n")
    frames = np.arange(n*24*32*3, dtype=np.uint8).reshape(n,24,32,3)
    if task_type == "i2v":
        Image.fromarray(frames[0]).save(tmp_path / "first_frame.png")
    module_spec = importlib.util.spec_from_file_location("helper", ASSET_ROOT / "artifact_io.py")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    pcm = np.zeros((16000,1), dtype=np.int16) if audio else None
    module.save(frames, tmp_path, audio=pcm)
    events = tmp_path / "events.jsonl"
    events.write_text('{"type":"turn.completed"}\n')
    return contract(tmp_path), events


def test_t2v_audio_and_snapshot(tmp_path):
    spec, events = output(tmp_path, audio={"sample_rate": 8000, "channels": 1})
    assert validate(tmp_path, events, 0, "vision-agent", False, spec)["pass"]
    trace = tmp_path / "trace"
    assert freeze(tmp_path, trace, 0, candidate_key(tmp_path, spec), spec)
    assert (trace / "round_000" / "audio.wav").exists()
    # Incorrect audio contract fails, even though all RGB files are valid.
    wrong = spec | {"audio": {"sample_rate": 16000, "channels": 1}}
    assert not validate(tmp_path, events, 0, "vision-agent", False, wrong)["pass"]


def test_variable_i2v_validates_every_png(tmp_path):
    spec, events = output(tmp_path, task_type="i2v")
    assert validate(tmp_path, events, 0, "vision-agent", False, spec)["pass"]
    Image.new("RGB", (32, 24), "red").save(tmp_path / "frames" / "04.png")
    assert not validate(tmp_path, events, 0, "vision-agent", False, spec)["pass"]
    assert freeze(tmp_path, tmp_path / "trace", 0, candidate_key(tmp_path, spec), spec) is None


def test_v2v_predicts_future_instead_of_copying_last_historical_frame(tmp_path):
    spec, events=output(tmp_path,task_type='v2v')
    Image.new('RGB',(32,24),'black').save(tmp_path/'first_frame.png')
    result=validate(tmp_path,events,0,'vision-agent',False,spec)
    assert result['pass'] and result['frame0_exact'] is None
    assert freeze(tmp_path,tmp_path/'trace',0,candidate_key(tmp_path,spec),spec)


def test_video_edit_can_change_the_first_frame(tmp_path):
    from pixelworld.media import task_rules
    spec, events = output(tmp_path, task_type='video_edit')
    Image.new('RGB',(32,24),'black').save(tmp_path/'first_frame.png')
    result = validate(tmp_path,events,0,'vision-agent',False,spec)
    assert result['pass'] and result['frame0_exact'] is None
    rules = task_rules(spec)
    assert 'full duration' in rules and 'not a required copy' in rules
    assert 'future continuation' not in rules


def test_more_than_100_frames_are_checked_in_numeric_order(tmp_path):
    spec, events = output(tmp_path, n=121)
    assert validate(tmp_path, events, 0, "vision-agent", False, spec)["pass"]
    Image.new("RGB", (32,24), "red").save(tmp_path / "frames" / "103.png")
    assert not validate(tmp_path, events, 0, "vision-agent", False, spec)["pass"]


def test_export_derives_missing_inspection_without_mutating_candidate(tmp_path):
    from pixelworld.smoke_web import encode
    spec, _ = output(tmp_path)
    (tmp_path/'inspection.png').unlink()
    original=(tmp_path/'pixels.npz').read_bytes()
    target=tmp_path/'web'
    record=encode(tmp_path,target,spec)
    assert record['inspection_derived']
    assert (target/'inspection.png').is_file()
    assert not (tmp_path/'inspection.png').exists()
    assert (tmp_path/'pixels.npz').read_bytes()==original


def test_photographic_target_is_explicit_and_leaves_existing_task_modes_unchanged(tmp_path):
    base = DEFAULT_MEDIA | {'task_type':'t2v'}
    assert 'photographic realism' not in task_rules(base)
    (tmp_path/'task_spec.json').write_text(json.dumps(base | {'visual_target':'photoreal'}))
    photo = contract(tmp_path)
    assert photo['visual_target'] == 'photoreal'
    assert 'live-action photographic realism' in task_rules(photo)
    assert 'directly in image/pixel space' in task_rules(photo)
    assert 'Do not build a separate scene/world model' in task_rules(photo)
    for kind in ['i2v','v2v','video_edit']:
        assert 'photographic realism' not in task_rules(DEFAULT_MEDIA | {'task_type':kind})
