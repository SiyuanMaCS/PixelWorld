import base64
import hashlib
import json
from pathlib import Path

from pixelworld.recording import write_bundle


def fixture_run(tmp_path):
    logs=tmp_path/'logs';logs.mkdir()
    work=tmp_path/'workspace';work.mkdir()
    (work/'prompt.txt').write_text('Fixture only.')
    (tmp_path/'task_prompt.txt').write_text('Use the local fixture tools.')
    calls=[{'type':'message','id':'user','role':'user','content':[{'type':'input_text','text':'Fixture only.'}]},
           {'type':'custom_tool_call','id':'call','call_id':'c','name':'exec','input':f'cat {work}/prompt.txt'},
           {'type':'custom_tool_call_output','id':'output','call_id':'c','output':[{'type':'text','text':'Fixture only.'}]},
           {'type':'message','id':'answer','role':'assistant','phase':'final','content':[{'type':'output_text','text':'draft'}]}]
    usage=lambda rid,out,cum:{'type':'token_usage_record','timestamp':'2026-11-08T00:00:00Z',
        'payload':{'session_id':'s','turn_id':'t','response_id':rid,
                   'usage':{'input_tokens':20,'output_tokens':out},
                   'thread_token_usage':{'output_tokens':cum}}}
    rows=[{'type':'history_mutation','timestamp':'2026-11-08T00:00:00Z','payload':{'items':calls}},
          usage('a',10,10), usage('a',10,10), usage('b',20,30),
          {'type':'history_mutation','timestamp':'2026-11-08T00:00:01Z','payload':{'items':[
              calls[-1]|{'content':[{'type':'output_text','text':'x'*5000}]}]}}]
    (logs/'full_rollout.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
    (logs/'events.jsonl').write_text(json.dumps({'type':'turn.completed','usage':{'output_tokens':30}})+'\n')
    (tmp_path/'run_manifest.json').write_text(json.dumps({'status':'complete','model':'fixture',
        'track':'text','case_id':'0001','validation':{'pass':True},
        'input_prompt_sha256':hashlib.sha256((work/'prompt.txt').read_bytes()).hexdigest(),
        'token_usage':{'output_tokens':30}}))
    return logs,work


def test_one_raw_archive_two_exports_no_tokenization(tmp_path):
    logs,work=fixture_run(tmp_path);before=(logs/'full_rollout.jsonl').read_bytes()
    summary=write_bundle(tmp_path)
    assert summary['sft_full_trajectory_candidate'] and not summary['training_ready']
    assert (logs/'full_rollout.jsonl').read_bytes()==before
    target=tmp_path/'recording'
    conversation=[json.loads(l) for l in (target/'conversation_events.jsonl').read_text().splitlines()]
    assert len(conversation)==4 and conversation[-1]['content'][0]['text']=='x'*5000
    assert conversation[1]['input']=='cat {WORKSPACE}/prompt.txt'
    assert conversation[1]['input_format']=='freeform'
    assert not conversation[2]['supervision_candidate']
    ledger=[json.loads(l) for l in (target/'api_usage.jsonl').read_text().splitlines()]
    assert len(ledger)==2 and sum(r['usage']['output_tokens'] for r in ledger)==30
    assert ledger[-1]['cumulative']['output_tokens']==30


def test_missing_content_and_interrupted_runs_remain_in_analysis(tmp_path):
    logs,work=fixture_run(tmp_path)
    raw=json.loads((logs/'full_rollout.jsonl').read_text().splitlines()[0])
    raw['payload']['items'][-1]['content'][0]['text']='traex-rollout-blob:v1:sha256:'+('0'*64)+':123'
    (logs/'full_rollout.jsonl').write_text(json.dumps(raw)+'\n')
    manifest=json.loads((tmp_path/'run_manifest.json').read_text());manifest['stop_reason']='output_token_budget_exhausted'
    (tmp_path/'run_manifest.json').write_text(json.dumps(manifest))
    summary=write_bundle(tmp_path)
    assert not summary['sft_full_trajectory_candidate']
    assert 'interrupted_trajectory' in summary['completeness_issues']
    assert 'unavailable_blob_content' in summary['completeness_issues']
    assert json.loads((tmp_path/'recording/index.json').read_text())['analysis_eligible']


def test_returned_images_are_materialized_and_encrypted_reasoning_is_not_a_target(tmp_path):
    logs,work=fixture_run(tmp_path)
    row={'type':'history_mutation','payload':{'items':[
        {'type':'custom_tool_call_output','id':'image','call_id':'img','output':[
            {'type':'input_image','image_url':'data:image/png;base64,'+base64.b64encode(b'fixture-image').decode()}]},
        {'type':'reasoning','id':'reason','content':[{'type':'reasoning_text','text':'Visible only.'}],
         'summary':[],'encrypted_content':'opaque-do-not-train'}]}}
    with (logs/'full_rollout.jsonl').open('a') as f:f.write(json.dumps(row)+'\n')
    write_bundle(tmp_path)
    text=(tmp_path/'recording/conversation_events.jsonl').read_text()
    assert 'opaque-do-not-train' not in text and 'Visible only.' in text
    assert len(list((tmp_path/'recording/media').glob('*')))==1
    reason=json.loads(text.splitlines()[-1])
    assert reason['encrypted_content_present'] and not reason['supervision_candidate']


def test_changed_initial_input_blocks_sft_candidate(tmp_path):
    logs,work=fixture_run(tmp_path)
    (work/'prompt.txt').write_text('Changed after input.')
    assert 'initial_asset_changed:prompt.txt' in write_bundle(tmp_path)['completeness_issues']


def test_original_input_snapshot_is_used_for_training_assets(tmp_path):
    logs,work=fixture_run(tmp_path)
    initial=tmp_path/'input_snapshot';initial.mkdir()
    (initial/'prompt.txt').write_text('Fixture only.')
    (initial/'artifact_io.py').write_text('# original helper')
    (work/'artifact_io.py').write_text('# model changed helper')
    manifest=json.loads((tmp_path/'run_manifest.json').read_text())
    manifest['initial_input_hashes']={'prompt.txt':hashlib.sha256((initial/'prompt.txt').read_bytes()).hexdigest(),
                                    'artifact_io.py':hashlib.sha256((initial/'artifact_io.py').read_bytes()).hexdigest()}
    (tmp_path/'run_manifest.json').write_text(json.dumps(manifest))
    write_bundle(tmp_path)
    index=json.loads((tmp_path/'recording/index.json').read_text())
    assert index['initial_asset_coverage']=='immutable_before_run'
    helper=next(r for r in index['initial_assets'] if r['name']=='artifact_io.py')
    assert helper['path']=='../input_snapshot/artifact_io.py'
    assert index['usage_coverage']=='per_request' and index['api_request_count']==2


def test_orphan_tool_returns_are_not_a_complete_sft_trajectory(tmp_path):
    logs,work=fixture_run(tmp_path)
    with (logs/'full_rollout.jsonl').open('a') as f:
        f.write(json.dumps({'type':'response_item','payload':{'type':'function_call_output',
            'id':'orphan','call_id':'missing-call','output':'result'}})+'\n')
    assert 'tool_returns_without_calls' in write_bundle(tmp_path)['completeness_issues']
