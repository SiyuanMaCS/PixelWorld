import json
from pathlib import Path

from pixelworld.config import load_config
from pixelworld.constants import DEFAULT_TRACKS, TRACKS
from pixelworld.web import build
from pixelworld.runner import run_case
from PIL import Image


def config(tmp_path, **extra):
    value = {"models": [{"key": "m", "model": "m"}]}
    value.update(extra)
    p = tmp_path / "config.json"
    p.write_text(json.dumps(value))
    return load_config(p)


def test_new_config_defaults_to_two_tracks(tmp_path):
    result = config(tmp_path)
    assert result.protocol == "pixelworld-v2"
    assert result.models[0].tracks == DEFAULT_TRACKS == ("text", "vision-agent")


def test_implicit_legacy_config_preserves_three_tracks(tmp_path):
    result = config(tmp_path, protocol="pixelworld-physics-iq-v1")
    assert result.models[0].tracks == TRACKS


def test_explicit_legacy_track_is_still_supported(tmp_path):
    result = config(tmp_path, models=[{"key": "m", "model": "m", "tracks": ["vision-input"]}])
    assert result.models[0].tracks == ("vision-input",)


def test_gallery_columns_follow_enabled_tracks(tmp_path):
    for protocol, expected in (("pixelworld-v2", 2), ("pixelworld-physics-iq-v1", 3)):
        result = config(tmp_path, protocol=protocol, case_ids=["0001"])
        result.inputs_root.mkdir(parents=True, exist_ok=True)
        (result.inputs_root.parent / "manifest.json").write_text(json.dumps({
            "cases": [{"id": "0001", "scenario": "synthetic-ui-test"}]}))
        site = tmp_path / protocol
        report = build(result, site)
        text = (site / "index.html").read_text()
        assert report["configurations"] == expected
        assert ("<th>Vision-Input (legacy)</th>" in text) == (expected == 3)
        assert "<th>Text</th>" in text and "<th>Vision-Agent</th>" in text


def test_task_contract_profile_is_versioned(tmp_path):
    for protocol, expected in (('pixelworld-v2','minimal-v2'),('pixelworld-physics-iq-v1','legacy-v1')):
        result=config(tmp_path,protocol=protocol)
        source=result.inputs_root/'0001';source.mkdir(parents=True,exist_ok=True)
        Image.new('RGB',(256,144)).save(source/'first_frame.png')
        (source/'prompt.txt').write_text('Synthetic dry-run profile check')
        value=run_case(result,'m','text','0001',attempt=1 if expected=='minimal-v2' else 2,
                       codex_binary='/bin/true',dry_run=True)
        assert value['generation_contract']==expected
        rules=(Path(value['workspace'])/'GENERATION_RULES.md').read_text()
        assert ('Before coding' in rules)==(expected=='legacy-v1')
