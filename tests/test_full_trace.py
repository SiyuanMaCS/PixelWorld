import base64
import datetime as dt
import json
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
