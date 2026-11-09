import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from pixelworld.config import load_config
from pixelworld.runner import _wait, run_case
from pixelworld.snapshot import candidate_key, freeze
from pixelworld.token_budget import UsageMonitor, restore_candidate
from pixelworld.media import DEFAULT_MEDIA
from test_audit import make_artifacts


def cfg(tmp_path, **changes):
    value = {'inputs_root': 'inputs', 'runs_root': 'runs',
             'models': [{'key': 'fake', 'model': 'fixture', 'tracks': ['text']}]}
    value.update(changes)
    path = tmp_path/'config.json';path.write_text(json.dumps(value))
    return load_config(path)


def event(output, stamp, response='r', delta=None):
    return {'type': 'token_usage_record', 'timestamp': stamp,
            'payload': {'session_id': 's', 'turn_id': 't', 'response_id': response,
                        'usage': {'output_tokens': output if delta is None else delta},
                        'thread_token_usage': {'output_tokens': output}}}


def test_default_is_100k_and_legacy_is_explicit(tmp_path):
    assert cfg(tmp_path).output_token_budget == 100000
    assert cfg(tmp_path, output_token_budget=50000).output_token_budget == 50000
    assert cfg(tmp_path, protocol='pixelworld-v1').output_token_budget is None
    assert cfg(tmp_path, output_token_budget=None).output_token_budget is None


@pytest.mark.parametrize('value', [0, -1, '50000', True])
def test_invalid_budget(tmp_path, value):
    with pytest.raises(ValueError):cfg(tmp_path, output_token_budget=value)


def test_reported_cumulative_usage_not_time_or_duplicate_events(tmp_path):
    monitor = UsageMonitor(tmp_path/'events', tmp_path, dt.datetime.now(dt.timezone.utc), 50, 10)
    monitor.consume(event(20, '2026-11-08T00:00:00Z', response='a'))
    monitor.consume(event(20, '2026-11-08T00:00:00Z', response='a'))
    assert monitor.total == 30 and monitor.record_count == 1
    monitor.consume(event(45, '2026-11-08T03:00:00Z', response='b'))
    assert monitor.total == 55 and monitor.report()['observed_overshoot_tokens'] == 5


def test_codex_request_counter(tmp_path):
    monitor = UsageMonitor(tmp_path/'events', tmp_path, dt.datetime.now(dt.timezone.utc), 50)
    monitor.consume({'type': 'event_msg', 'timestamp': '2026-11-08T00:00:00Z', 'payload': {
        'type': 'token_count', 'info': {'total_token_usage': {'output_tokens': 51,
        'reasoning_output_tokens': 20}}}})
    assert monitor.total == 51  # reasoning is not added a second time
    assert monitor.crossed_utc


def test_monitor_reads_only_complete_appended_records(tmp_path):
    path = tmp_path/'rollout.jsonl';path.write_text('')
    monitor = UsageMonitor(tmp_path/'events', tmp_path, dt.datetime.now(dt.timezone.utc), 50)
    monitor.path = path
    value = json.dumps(event(60, '2026-11-08T00:00:00Z'))
    path.write_text(value[:20]);assert not monitor.poll()
    with path.open('a') as f:f.write(value[20:]+'\n')
    assert monitor.poll() and monitor.total == 60


def test_external_cutoff_uses_api_counter(tmp_path):
    path = tmp_path/'rollout.jsonl'
    path.write_text(json.dumps(event(60, '2026-11-08T00:00:00Z'))+'\n')
    monitor = UsageMonitor(tmp_path/'events', tmp_path, dt.datetime.now(dt.timezone.utc), 50)
    monitor.path = path
    agent = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(60)'], start_new_session=True)
    began = time.monotonic()
    status, watchdog = _wait(agent, tmp_path/'events', tmp_path, token_monitor=monitor)
    assert status != 0 and time.monotonic()-began < 2
    assert watchdog['reason'] == 'output_token_budget_exhausted'


def test_keeps_candidate_before_crossing_and_audits_it(tmp_path):
    workspace, trace, logs = tmp_path/'workspace', tmp_path/'trace', tmp_path/'logs'
    logs.mkdir();make_artifacts(workspace)
    p=workspace/'pixels.npz';os.utime(workspace/'generate.py', ns=(p.stat().st_mtime_ns-1,p.stat().st_mtime_ns-1))
    record=freeze(workspace,trace,0,candidate_key(workspace));assert record
    (logs/'events.jsonl').write_text('')
    (workspace/'pixels.npz').write_bytes(b'partial')
    selection=restore_candidate(workspace,trace,logs,'2099-01-01T00:00:00Z',-15,'text',True,DEFAULT_MEDIA)
    assert selection['snapshot_round']==0
    assert (tmp_path/'interrupted_artifacts/pixels.npz').read_bytes()==b'partial'


def test_real_runner_fixture_monitors_persisted_request_usage(tmp_path):
    """Local CLI test double, no API or generative model invocation."""
    from PIL import Image
    config=cfg(tmp_path, output_token_budget=50)
    source=config.inputs_root/'0001';source.mkdir(parents=True)
    Image.new('RGB',(32,24),(20,40,60)).save(source/'first_frame.png')
    (source/'prompt.txt').write_text('Fixture only.')
    (source/'task_spec.json').write_text(json.dumps({'task_type':'i2v','width':32,'height':24,'frames':6,'fps':3,'audio':None}))
    binary=tmp_path/'fake-codex'
    binary.write_text('''#!/usr/bin/env python3
import sys,os,time,json,datetime
if '--version' in sys.argv: print('fixture-cli');sys.exit(0)
from pathlib import Path
from PIL import Image
import numpy as np
w=Path(sys.argv[sys.argv.index('-C')+1]);os.chdir(w);sys.path.insert(0,str(w))
sid='11111111-1111-1111-1111-111111111111'
print(json.dumps({'type':'thread.started','thread_id':sid}),flush=True)
now=datetime.datetime.now(datetime.timezone.utc)
folder=Path(os.environ['CODEX_HOME'])/'sessions'/now.strftime('%Y/%m/%d');folder.mkdir(parents=True)
log=folder/('rollout-'+sid+'.jsonl')
def usage(total,name):
 row={'type':'token_usage_record','timestamp':datetime.datetime.now(datetime.timezone.utc).isoformat(),'payload':{'session_id':sid,'turn_id':'t','response_id':name,'usage':{'output_tokens':total},'thread_token_usage':{'output_tokens':total}}}
 with log.open('a') as f:f.write(json.dumps(row)+'\\n')
usage(10,'a')
from artifact_io import save
(w/'generate.py').write_text('# initial fixture\\n')
save(np.repeat(np.array(Image.open('first_frame.png'))[None],6,axis=0),w)
time.sleep(1.3)
usage(60,'b')
(w/'generate.py').write_text('# incomplete revision\\n');(w/'pixels.npz').write_bytes(b'partial')
time.sleep(60)
''')
    binary.chmod(0o755)
    result=run_case(config,'fake','text','0001',codex_binary=str(binary))
    assert result['status']=='complete' and result['stop_reason']=='output_token_budget_exhausted'
    assert result['validation']['completion_mode']=='budget_frozen'
    assert result['token_budget']['reported_output_tokens']==60
    assert result['token_usage']['output_tokens'] is None
    assert result['token_usage']['reported_completed_request_output_tokens']==60
    assert result['submission_selection']['source']=='last_valid_snapshot_before_token_crossing'
