"""External archival/accounting of the case's own native proxy responses."""
import hashlib,json,shutil
from pathlib import Path

def archive_proxy_trace(run: Path, proxy: Path) -> dict:
    events=run/'logs/events.raw.jsonl'
    thread=None
    for line in events.read_text().splitlines():
        try:e=json.loads(line)
        except ValueError:continue
        if e.get('type')=='thread.started':thread=e.get('thread_id');break
    if not thread:return {'status':'missing','reason':'No CLI thread identity'}
    target=run/'logs/proxy_trace';target.mkdir(exist_ok=True)
    records=[];totals={k:0 for k in ['input_tokens','output_tokens','total_tokens','cached_input_tokens','cache_creation_input_tokens','reasoning_output_tokens']}
    incomplete=[];matched=0;reported=0;rejected=0
    for p in proxy.glob('*.input.json'):
        data=json.loads(p.read_text())
        if data.get('prompt_cache_key')!=thread:continue
        matched+=1;stem=p.name[:-len('.input.json')]
        ep=proxy/(stem+'.events.json')
        native=json.loads(ep.read_text()) if ep.exists() else []
        usage=[e['data'] for e in native if e['event']=='token_usage']
        has_output=any(e['event']=='output' and isinstance(e.get('data'),dict) and any(e['data'].get(k) for k in ('response','reasoning_content','tool_calls','multimodal_contents')) for e in native)
        queue=any(e['event']=='error' and isinstance(e.get('data'),dict) and e['data'].get('code')==4050 for e in native) and not has_output and not usage
        row={'request_id':stem,'queue_rejected_before_sampling':queue,'usage_reports':len(usage),'files':[]}
        if len(usage)==1:
            reported+=1;u=usage[0];row['native_usage']=u
            for dst,src in [('input_tokens','prompt_tokens'),('output_tokens','completion_tokens'),('total_tokens','total_tokens'),('cached_input_tokens','cache_read_input_tokens'),('cache_creation_input_tokens','cache_creation_input_tokens'),('reasoning_output_tokens','reasoning_tokens')]:
                value=u.get(src)
                if isinstance(value,int):totals[dst]+=value
        elif queue:rejected+=1
        else:incomplete.append(stem)
        for suffix in ['input.json','native.json','events.json','response.json','error.txt']:
            f=proxy/(stem+'.'+suffix)
            if f.exists():
                dest=target/f.name;shutil.copy2(f,dest);dest.chmod(0o600)
                row['files'].append({'file':f.name,'sha256':hashlib.sha256(dest.read_bytes()).hexdigest()})
        records.append(row)
    report={'status':'complete' if matched and not incomplete else 'partial','thread_id':thread,'matched_requests':matched,
            'reported_sampled_requests':reported,'pre_sampling_queue_rejections':rejected,'unresolved_requests':incomplete,
            'reported_usage_totals':totals if reported else None,'requests':records,
            'scope':'Native usage reports from sampled requests. Explicit pre-sampling queue rejection has no model-sampling usage; raw unreported rejection is preserved.'}
    (target/'manifest.json').write_text(json.dumps(report,indent=2));return report

def usage_from_proxy(report: dict) -> dict | None:
    if report.get('status')!='complete' or not report.get('reported_usage_totals'):return None
    return {'schema_version':1,'status':'recorded',**report['reported_usage_totals'],
            'source':'case-associated native proxy token_usage reports',
            'usage_events':report['reported_sampled_requests'],'pre_sampling_queue_rejections':report['pre_sampling_queue_rejections'],
            'inflight_usage_unknown':False,'reasoning_inclusion':'provider-reported; not added a second time',
            'scope_note':report['scope']}
