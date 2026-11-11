import json

import numpy as np
import pytest

from tools.sync_incremental_previews import build_quick_case, quick_page_is_current


def example(tmp_path, status='complete'):
    run = tmp_path/'run'
    (run/'workspace').mkdir(parents=True)
    (run/'run_manifest.json').write_text(json.dumps({
        'status':status, 'validation':{'pass':True},
        'model':'Example', 'case_id':'0001',
    }))
    (run/'media_contract.json').write_text(json.dumps({'width':3,'height':2,'frames':2,'fps':4}))
    np.savez_compressed(run/'workspace/pixels.npz', pixels=np.zeros((2,3,2),dtype=np.uint32))
    return run, tmp_path/'public'


def test_quick_video_is_playable_before_trace_exists(tmp_path):
    run, output = example(tmp_path)
    build_quick_case(run, output)
    assert quick_page_is_current(run, output)
    assert (output/'final/poster.png').is_file()
    assert list((output/'final').glob('*.rgb.gz'))
    assert 'class=play' in (output/'quick.html').read_text()
    assert not (output/'index.html').exists()


def test_quick_video_invalidates_when_submission_changes(tmp_path):
    run, output = example(tmp_path)
    build_quick_case(run, output)
    (run/'run_manifest.json').write_text((run/'run_manifest.json').read_text()+' ')
    assert not quick_page_is_current(run, output)


def test_quick_video_does_not_publish_failed_candidate(tmp_path):
    run, output = example(tmp_path, status='failed')
    with pytest.raises(ValueError, match='validated complete'):
        build_quick_case(run, output)
    assert not (output/'quick.html').exists()


def test_final_video_publishes_without_waiting_for_rich_renderer(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from tools import sync_incremental_previews as sync
    root=tmp_path/'runs'
    group=root/'generations/physics_iq/m/text'
    run=group/'case_0001_attempt_01'
    (run/'workspace').mkdir(parents=True)
    (run/'run_manifest.json').write_text(json.dumps({
        'status':'complete','validation':{'pass':True},'model':'Fixture','model_key':'m',
        'track':'text','case_id':'0001','attempt':1,
        'started_utc':'2026-11-11T00:00:00Z','completed_utc':'2026-11-11T00:01:00Z',
    }))
    (run/'media_contract.json').write_text(json.dumps({'width':3,'height':2,'frames':2,'fps':4}))
    np.savez_compressed(run/'workspace/pixels.npz',pixels=np.zeros((2,3,2),dtype=np.uint32))
    (root/'generations/physics_iq/status.json').write_text(json.dumps({
        'cases':2,'groups':{'m/text':{'counts':{'complete':1,'pending':1}}},
    }))
    monkeypatch.setattr(sync,'SUITES',{'physics_iq':'fixture'})
    commands=[]
    monkeypatch.setattr(sync.subprocess,'Popen',lambda command,**kwargs:commands.append(command) or SimpleNamespace(pid=99999999))
    monkeypatch.setattr(sync,'build_case',lambda *_:pytest.fail('Rich rendering must run outside publication'))
    result=sync.sync_previews(root,tmp_path/'staging',tmp_path/'public')
    assert len(result['quick_updated'])==1
    assert result['updated']==[]
    assert len(commands)==1 and any(x.endswith('build_one_preview.py') for x in commands[0])
    assert 'quick.html' in (tmp_path/'public/fixture/m/text/index.html').read_text()


def test_completed_statistics_cache_invalidates_on_a_new_completion(tmp_path):
    from tools.build_baseline_monitor import completed_stats
    root=tmp_path/'suite'
    run=root/'m/text/case_0001_attempt_01'
    run.mkdir(parents=True)
    manifest=run/'run_manifest.json'
    def update(tokens,stamp):
        manifest.write_text(json.dumps({'status':'complete','validation':{'pass':True},
            'duration_seconds':60,'token_usage':{'output_tokens':tokens,'input_tokens':10}}))
        (root/'status.json').write_text(json.dumps({'groups':{'m/text':{'counts':{'complete':1},'latest_completion':[stamp,'0001']}}}))
    update(100,'2026-11-11T00:00:00Z')
    assert completed_stats(root,'m','text')['avg_output']==100
    assert list((root/'publication_stats_cache').glob('*.json'))
    update(200,'2026-11-11T00:01:00Z')
    assert completed_stats(root,'m','text')['avg_output']==200
