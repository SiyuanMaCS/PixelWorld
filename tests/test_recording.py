import io
import json
from pathlib import Path

from pixelworld.events import capture_stream
from pixelworld.snapshot import candidate_key, freeze, record_code
from test_audit import make_artifacts


def test_external_timestamps_preserve_raw_api_events(tmp_path):
    original = b'{"type":"turn.completed","usage":{"output_tokens":120}}\n'
    raw, events = tmp_path/'raw.jsonl', tmp_path/'events.jsonl'
    capture_stream(io.BytesIO(original), raw, events)
    assert raw.read_bytes() == original
    value = json.loads(events.read_text())
    assert value['usage']['output_tokens'] == 120
    assert value['_harness_received']['monotonic_ns'] > 0


def test_candidate_records_without_model_reports_and_rejects_corruption(tmp_path):
    workspace = tmp_path/'workspace'
    make_artifacts(workspace)
    for name in ('OBSERVATION.md','METHOD.md'):
        (workspace/name).unlink()
    # Existing test fixture creates the script last; model scripts are written
    # before generating their output. Update only the fixture's timestamp.
    code = workspace/'generate.py';pixels = workspace/'pixels.npz'
    import os
    os.utime(code, ns=(pixels.stat().st_mtime_ns-1,pixels.stat().st_mtime_ns-1))
    key = candidate_key(workspace)
    assert key
    trace = tmp_path/'trace'
    value = freeze(workspace,trace,0,key)
    assert value and value['artifact_checks']['all_png_tensor_exact']
    assert 'METHOD.md' not in value['files']
    assert not (workspace/'METHOD.md').exists()
    (workspace/'frames/10.png').write_bytes(b'')
    assert freeze(workspace,trace,1,key) is None
    assert not (trace/'round_001').exists()
    assert len((trace/'rounds.jsonl').read_text().splitlines()) == 1


def test_code_history_is_external_and_includes_pre_generation_changes(tmp_path):
    workspace=tmp_path/'workspace';workspace.mkdir()
    code=workspace/'generate.py';code.write_text('x = 1\n')
    trace=tmp_path/'trace'
    a=record_code(workspace,trace,None)
    code.write_text('x = 2\n');b=record_code(workspace,trace,a)
    code.write_text('x = 1\n');record_code(workspace,trace,b)
    assert len((trace/'code_history.jsonl').read_text().splitlines()) == 3
    assert len(list((trace/'code_versions').glob('*.py'))) == 2
    assert not (workspace/'code_history.jsonl').exists()
