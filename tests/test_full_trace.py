import base64
import datetime as dt
import json
import hashlib
from pathlib import Path

from pixelworld.full_trace import capture_rollout, extract_tools


def test_nested_image_call_and_actual_return_are_captured(tmp_path):
    rollout=tmp_path/'rollout.jsonl'
    image=base64.b64encode(b'png-bytes').decode()
    events=[{'type':'history_mutation','payload':{'items':[
        {'type':'custom_tool_call','name':'exec','call_id':'call_1','input':'image(await tools.view_image({path: "first_frame.png"}));'}]}},
        {'type':'history_mutation','payload':{'items':[
        {'type':'custom_tool_call_output','call_id':'call_1','output':[{'type':'input_image','image_url':'data:image/png;base64,'+image}]}]}},
        {'type':'history_mutation','payload':{'items':[
        {'type':'message','role':'assistant','content':[{'type':'output_text','text':'I reviewed 9 images'}]}]}}]
    rollout.write_text('\n'.join(json.dumps(e) for e in events))
    result=extract_tools(rollout,tmp_path)
    assert result['returned_images']==1
    assert result['tool_calls'][0]['nested_tool_expressions']==['view_image']
    assert (tmp_path/result['tool_calls'][0]['returned_images'][0]['path']).read_bytes()==b'png-bytes'


def test_capture_matches_own_thread_and_next_day_timezone(tmp_path):
    tid='00000000-0000-0000-0000-000000000001'
    home=tmp_path/'cli';logs=tmp_path/'logs';logs.mkdir()
    (logs/'events.jsonl').write_text(json.dumps({'type':'thread.started','thread_id':tid})+'\n')
    source=home/'sessions/2026/11/07';source.mkdir(parents=True)
    (source/f'rollout-{tid}.jsonl').write_text(json.dumps({'type':'history_mutation','payload':{'items':[]}})+'\n')
    result=capture_rollout(home,logs,dt.datetime(2026,11,6,20,tzinfo=dt.timezone.utc))
    assert result['status']=='recorded' and result['thread_id']==tid
    assert (logs/'full_rollout.jsonl').is_file()


def test_missing_full_rollout_is_unknown_not_zero_actual_calls(tmp_path):
    (tmp_path/'events.jsonl').write_text(json.dumps({'type':'thread.started','thread_id':'00000000-0000-0000-0000-000000000001'})+'\n')
    result=capture_rollout(tmp_path/'empty',tmp_path,dt.datetime.now(dt.timezone.utc))
    assert result['status']=='missing' and 'returned_images' not in result


def test_spilled_image_blob_is_restored_and_archive_is_self_contained(tmp_path):
    url='data:image/png;base64,'+base64.b64encode(b'png-bytes').decode()
    raw=url.encode();digest=hashlib.sha256(raw).hexdigest()
    blobs=tmp_path/'source_blobs';file=blobs/'sha256'/digest[:2]/digest
    file.parent.mkdir(parents=True);file.write_bytes(raw)
    logs=tmp_path/'logs';logs.mkdir();rollout=logs/'full_rollout.jsonl'
    rollout.write_text(json.dumps({'type':'history_mutation','payload':{'items':[
        {'type':'custom_tool_call','name':'exec','call_id':'a','input':'image(await tools.view_image({path:"x.png"}));'},
        {'type':'custom_tool_call_output','call_id':'a','output':[{'type':'input_image',
            'image_url':f'traex-rollout-blob:v1:sha256:{digest}:{len(raw)}'}]}]}})+'\n')
    result=extract_tools(rollout,logs,blobs)
    assert result['returned_images']==1 and result['unresolved_images']==0
    assert (logs/result['tool_calls'][0]['returned_images'][0]['path']).read_bytes()==b'png-bytes'
    file.unlink()
    assert extract_tools(rollout,logs)['unresolved_images']==0


def test_missing_image_blob_is_recorded_as_image_not_silently_dropped(tmp_path):
    rollout=tmp_path/'full_rollout.jsonl'
    rollout.write_text(json.dumps({'type':'history_mutation','payload':{'items':[
        {'type':'custom_tool_call','name':'exec','call_id':'a','input':'image(await tools.view_image({path:"x.png"}));'},
        {'type':'custom_tool_call_output','call_id':'a','output':[{'type':'input_image',
            'image_url':'traex-rollout-blob:v1:sha256:'+('0'*64)+':123'}]}]}})+'\n')
    result=extract_tools(rollout,tmp_path)
    assert result['returned_images']==1 and result['unresolved_images']==1
    assert result['tool_calls'][0]['returned_images'][0]['available'] is False


def test_large_assistant_text_and_tool_text_blobs_are_archived(tmp_path):
    blobs = tmp_path/'source_blobs';logs = tmp_path/'logs';logs.mkdir()
    references = []
    for text in ['large assistant output', 'large tool output']:
        raw = text.encode();digest = hashlib.sha256(raw).hexdigest()
        source = blobs/'sha256'/digest[:2]/digest
        source.parent.mkdir(parents=True, exist_ok=True);source.write_bytes(raw)
        references.append(f'traex-rollout-blob:v1:sha256:{digest}:{len(raw)}')
    rollout = logs/'full_rollout.jsonl'
    rollout.write_text(json.dumps({'type':'history_mutation','payload':{'items':[
        {'type':'message','role':'assistant','content':[{'type':'output_text','text':references[0]}]},
        {'type':'custom_tool_call_output','call_id':'a','output':[{'type':'text','text':references[1]}]}
    ]}})+'\n')
    result = extract_tools(rollout, logs, blobs)
    assert result['referenced_blobs'] == result['archived_blobs'] == 2
    assert result['unresolved_blobs'] == 0
    import shutil
    shutil.rmtree(blobs)
    assert extract_tools(rollout, logs)['archived_blobs'] == 2


def test_missing_text_blob_is_explicit_in_completeness_report(tmp_path):
    rollout=tmp_path/'full_rollout.jsonl'
    rollout.write_text(json.dumps({'type':'response_item','payload':{
        'type':'message','content':[{'type':'output_text','text':
        'traex-rollout-blob:v1:sha256:'+('0'*64)+':123'}]}})+'\n')
    result=extract_tools(rollout,tmp_path)
    assert result['unresolved_blobs']==1
