"""Prove an interrupted attempt's output total from its own native API records.

Only an explicit connection-stage rejection can close the unreported last
request. An idle timeout, partial output, disconnection or unknown stage is not
converted to zero. This does not launch a model or change a generation run.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path


def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def proves_no_sampling(record, events):
    error=record.get('native_error') or {}
    chain=error.get('model_call_chain') or []
    return (error.get('code')==3004 and bool(chain)
            and all(x.get('error_stage')=='connect' for x in chain)
            and not record.get('client_disconnected')
            and not record.get('native_usage')
            and bool(events)
            and all(x.get('event') in ('metadata','timing_cost','error','exception') or
                    (x.get('event')=='progress_notice' and isinstance(x.get('data'),str)
                     and re.fullmatch(r';Processing_[0-9]+_[A-Za-z0-9]+',x['data'])) for x in events)
            and any(x.get('event') in ('error','exception') and isinstance(x.get('data'),dict)
                    and x['data'].get('code')==3004 for x in events))


def prove(run, proxy, rejected_id):
    run=run.resolve();proxy=proxy.resolve();m=json.loads((run/'run_manifest.json').read_text())
    if m.get('status')!='failed' or m.get('prior_attempt_output_tokens',0)!=0:
        raise ValueError('Only a failed first independent attempt is supported')
    if m.get('stop_reason')=='output_token_budget_exhausted':raise ValueError('A spent budget cannot be restored')
    command=m['command']
    if not any('.request_max_retries=0' in x for x in command) or not any('.stream_max_retries=0' in x for x in command):
        raise ValueError('Cannot prove one terminal failed request when automatic CLI retries are enabled')
    source=run/'logs/events.raw.jsonl';stdout=[json.loads(x) for x in source.read_text().splitlines()]
    thread=next(x['thread_id'] for x in stdout if x.get('type')=='thread.started')
    errors=[x for x in stdout if x.get('type')=='error']
    terminal=[x for x in stdout if x.get('type') in ('turn.failed','turn.completed','turn.cancelled')]
    if len(errors)!=1 or len(terminal)!=1 or terminal[0]['type']!='turn.failed':
        raise ValueError('Unaccounted stream failure or multiple terminal events')
    message=errors[0].get('message','');prefix='Upstream error: '
    if prefix not in message:raise ValueError('Idle timeout/disconnection is not a zero-output rejection')
    failure=json.loads(message.split(prefix,1)[1])
    if failure.get('code')!=3004 or not failure.get('model_call_chain') or not all(x.get('error_stage')=='connect' for x in failure['model_call_chain']):
        raise ValueError('Terminal CLI error does not prove rejection before model sampling')
    records={}
    for line in (proxy/'requests.jsonl').open():
        try:record=json.loads(line)
        except ValueError:continue
        if record.get('id') in records:raise ValueError('Duplicate native request record')
        records[record['id']]=record
    rejected=records[rejected_id]
    request=proxy/(rejected_id+'.input.json');native=proxy/(rejected_id+'.events.json')
    if json.loads(request.read_text()).get('prompt_cache_key')!=thread:
        raise ValueError('Rejected request belongs to another agent context')
    if not proves_no_sampling(rejected,json.loads(native.read_text())):
        raise ValueError('Native terminal request may have generated unreported output')
    archive=run/'logs/full_rollout.jsonl';usage={};sampled=[]
    for line in archive.open():
        e=json.loads(line)
        if e.get('type')!='token_usage_record':continue
        p=e['payload'];identity=(p.get('session_id'),p.get('turn_id'),p.get('response_id'))
        if p.get('session_id')!=thread:raise ValueError('Archive mixes agent contexts')
        amount=p.get('usage',{}).get('output_tokens')
        if type(amount) is not int or amount<0:raise ValueError('Output amount is unknown/invalid')
        if identity in usage and usage[identity]!=amount:raise ValueError('Conflicting duplicate API usage')
        if identity in usage:continue
        report=records.get(p['response_id'],{}).get('native_usage') or {}
        if report.get('completion_tokens')!=amount:raise ValueError('Archived usage differs from native report')
        usage[identity]=amount;sampled.append({'response_id':p['response_id'],'output_tokens':amount})
    total=sum(usage.values());observed=(m.get('token_budget') or {}).get('reported_output_tokens')
    if observed is not None and total!=observed:raise ValueError('Native sum differs from the original cumulative counter')
    if observed is None and (total or any(x.get('type')=='item.completed' for x in stdout)):
        raise ValueError('Missing cumulative counter after observed model/tool work')
    return {'schema':'pixelworld-proven-connect-rejection-v1','status':'proven','run':str(run),
            'thread_id':thread,'rejected_response_id':rejected_id,'rejected_request_output_tokens':0,
            'verified_output_tokens':total,'sampled_requests':sampled,'native_error_code':3004,
            'evidence_sha256':{str(p):sha(p) for p in (run/'run_manifest.json',source,archive,request,native)},
            'accounting_scope':'Exact generated output from completed requests plus proven no sampling in terminal rejected request; billing/input usage of rejection is not inferred.'}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--proxy-log-root',type=Path,required=True)
    p.add_argument('--rejected-response-id',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    result=prove(a.run,a.proxy_log_root,a.rejected_response_id);a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'status':result['status'],'verified_output_tokens':result['verified_output_tokens'],'sampled_requests':len(result['sampled_requests'])}))
