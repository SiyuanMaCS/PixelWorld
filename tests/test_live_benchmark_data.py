import json
import numpy as np
from tools.live_benchmark_data import case_data, update


def make_run(root, status='running', video=True):
    run = root / 'generations/physics_iq_512w24fps_gpt_native/m/text/case_0001_attempt_01'
    (run / 'workspace').mkdir(parents=True)
    (run / 'logs').mkdir()
    (run / 'input_snapshot').mkdir()
    (run / 'run_manifest.json').write_text(json.dumps({
        'status':status, 'case_id':'0001', 'model_key':'m', 'model':'M',
        'track':'text', 'attempt':1, 'started_utc':'2026-11-13T00:00:00Z'}))
    (run / 'media_contract.json').write_text(json.dumps({'width':3,'height':2,'frames':2,'fps':4}))
    (run / 'logs/token_budget.json').write_text('{"reported_output_tokens":123}')
    (run / 'input_snapshot/prompt.txt').write_text('Move the ball.')
    (run / 'logs/events.jsonl').write_text(json.dumps({'type':'item.completed','item':{
        'type':'command_execution','command':'python generate.py','aggregated_output':'saved'}})+'\n')
    if video:
        np.savez_compressed(run/'workspace/pixels.npz',pixels=np.zeros((2,3,2),dtype=np.uint32))
    return run


def test_running_candidate_can_play_before_final_submission(tmp_path):
    run=make_run(tmp_path)
    output=tmp_path/'public'
    d=case_data(run,output)
    assert d['status']=='running'
    assert d['output_tokens']==123
    assert len(d['candidates'])==1
    assert (output/d['candidates'][0]['pixels']).is_file()
    assert d['events'][0]['command']=='python generate.py'
    assert json.loads((run/'run_manifest.json').read_text())['status']=='running'


def test_unsubmitted_run_has_tools_and_tokens_without_false_failure(tmp_path):
    run=make_run(tmp_path,video=False)
    d=case_data(run,tmp_path/'public')
    assert d['candidates']==[] and d['status']=='running'
    assert d['output_tokens']==123 and d['events']


def test_live_metadata_tracks_new_output_and_redacts_private_paths(tmp_path):
    run=make_run(tmp_path)
    suite=run.parents[2]
    (suite/'status.json').write_text(json.dumps({'cases':198,'groups':{
        'm/text':{'counts':{'running':1,'pending':197},'running_cases':['0001']}}}))
    (run/'logs/events.jsonl').write_text(json.dumps({'type':'item.completed','item':{
        'type':'command_execution','command':'python /mnt/private/generate.py','aggregated_output':'ok'}})+'\n')
    output=tmp_path/'live';cache={}
    update(tmp_path,output,cache)
    detail=output/'physics_iq_512w24fps_gpt_native/m/text/case_0001_attempt_01.json'
    assert '/mnt/private' not in detail.read_text()
    (run/'logs/token_budget.json').write_text('{"reported_output_tokens":456}')
    update(tmp_path,output,cache)
    assert json.loads(detail.read_text())['output_tokens']==456


def test_token_update_does_not_reencode_saved_video(tmp_path, monkeypatch):
    from tools import live_benchmark_data as live
    run=make_run(tmp_path)
    destination=tmp_path/'public'
    first=case_data(run,destination)
    (run/'logs/token_budget.json').write_text('{"reported_output_tokens":789}')
    monkeypatch.setattr(live,'export_candidate',lambda *_: (_ for _ in ()).throw(AssertionError('No RGB encoding for token-only changes')))
    second=case_data(run,destination,previous=first)
    assert second['output_tokens']==789
    assert second['candidates']==first['candidates']


def test_visual_returns_are_published_from_frozen_logs_only(tmp_path):
    from PIL import Image
    run=make_run(tmp_path,video=False)
    (run/'logs/tool_images').mkdir()
    Image.new('RGB',(2,2),'red').save(run/'logs/tool_images/read.png')
    (run/'logs/events.jsonl').write_text(json.dumps({'type':'item.completed','item':{
        'type':'full_trace_image_return','returned_images':[
            {'path':'tool_images/read.png','available':True},
            {'path':'../../private.png','available':True}]}})+'\n')
    output=tmp_path/'public'
    data=case_data(run,output)
    assert len(data['events'][0]['images'])==1
    assert (output/data['events'][0]['images'][0]).is_file()
