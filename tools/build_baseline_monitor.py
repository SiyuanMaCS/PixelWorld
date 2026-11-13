"""Publish fixed-baseline Physics-IQ progress, including explicitly reused legacy groups."""
from pathlib import Path
import argparse,json,html,sys
import statistics
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.build_bench_review import document, physics_verified_display
from tools.sync_stable_pixelworld_pages import quarantine_stats

MODELS={'gpt61-sol':'GPT-6.1-Sol','gpt56-sol':'GPT-5.6-Sol','gpt6-astra':'GPT-6-Astra','deepseek-v41':'DeepSeek-V4.1-Flash','seed21-pro':'Seed-2.1-Pro-0915'}

def read(p):
    try:return json.loads(p.read_text())
    except (OSError,ValueError):return {}

def fmt(value, digits=1):
    if value is None:return '—'
    if isinstance(value, int):return f'{value:,}'
    return f'{value:,.{digits}f}'

def fmt_age(seconds):
    seconds=max(0,float(seconds))
    if seconds<60:return f'{seconds:.0f}s'
    return f'{seconds/60:.1f}m'

def event_status(generation, model, track, case):
    attempts=sorted((generation/model/track).glob(f'case_{case}_attempt_*/logs/events.jsonl'))
    if not attempts:return 'event: no log yet'
    path=max(attempts,key=lambda p:p.stat().st_mtime)
    age=max(0,time.time()-path.stat().st_mtime)
    try:lines=path.read_text(errors='ignore').splitlines()
    except OSError:return 'event: log unreadable'
    events=[]
    for line in lines[-12:]:
        try:events.append(json.loads(line))
        except ValueError:pass
    last=events[-1] if events else {}
    typ=str(last.get('type','unknown'));msg=str(last.get('message',''))
    if 'Connection failed' in msg or 'Reconnecting... waiting for network' in msg:
        label='network retry';css='warn'
    elif typ in ('item.started','item.completed','turn.completed'):
        label='recent output/tool activity';css='live'
    elif typ=='turn.failed':
        label='turn failed';css='bad'
    elif age>900:
        label='stale event log';css='warn'
    else:
        label=typ.replace('_',' ');css='live'
    return f'<span class="{css}">{html.escape(label)}</span> · {fmt_age(age)} ago'

def completed_stats(root, model, track):
    group=read(root/'status.json').get('groups',{}).get(model+'/'+track,{})
    counts=group.get('counts',{})
    immutable=counts.get('complete',0)>0 and counts.get('complete')==sum(counts.values())
    cache=root/'publication_stats_cache'/f'{model}__{track}.json'
    signature=[counts,group.get('latest_completion')]
    try:signature.append((root/model/track).stat().st_mtime_ns)
    except OSError:signature.append(None)
    saved=read(cache) if immutable else {}
    if saved.get('signature')==signature:
        return saved.get('stats')
    rows=[]
    for path in sorted((root/model/track).glob('case_*_attempt_*/run_manifest.json')):
        manifest=read(path)
        if manifest.get('status')!='complete' or manifest.get('validation',{}).get('pass') is not True:
            continue
        usage=manifest.get('token_usage') or {}
        duration=manifest.get('duration_seconds')
        output=usage.get('output_tokens')
        input_tokens=usage.get('input_tokens')
        if isinstance(duration,(int,float)) and isinstance(output,int):
            rows.append({'duration':duration,'output':output,
                         'input':input_tokens if isinstance(input_tokens,int) else None})
    if not rows:return None
    durations=[x['duration']/60 for x in rows]
    outputs=[x['output'] for x in rows]
    inputs=[x['input'] for x in rows if isinstance(x['input'],int)]
    result={'n':len(rows),'avg_min':statistics.mean(durations),'p50_min':statistics.median(durations),
            'avg_output':statistics.mean(outputs),'p50_output':statistics.median(outputs),
            'avg_input':statistics.mean(inputs) if inputs else None,'p50_input':statistics.median(inputs) if inputs else None}
    if immutable:
        cache.parent.mkdir(exist_ok=True)
        temporary=cache.with_suffix('.tmp')
        temporary.write_text(json.dumps({'signature':signature,'stats':result}))
        temporary.replace(cache)
    return result

def stats_cell(stats):
    if not stats:return '<td>—</td>'
    return (f'<td><strong>{stats["n"]}</strong><span class=status>'
            f'耗时 avg {fmt(stats["avg_min"])}m / p50 {fmt(stats["p50_min"])}m<br>'
            f'output avg {fmt(stats["avg_output"],0)} / p50 {fmt(stats["p50_output"],0)}<br>'
            f'input avg {fmt(stats["avg_input"],0)} / p50 {fmt(stats["p50_input"],0)}</span></td>')

def activity_badge(counts):
    if counts.get('running',0)>0:return '<span class=badge>ACTIVE</span>'
    if counts.get('complete',0)>=198:return '<span class=pill>DONE</span>'
    return '<span class="pill">RETRY</span>' if counts.get('exhausted',0) else '<span class="pill">QUEUED</span>'

def build(run,web,legacy):
    status=read(run/'generations/physics_iq/status.json')
    gpt_status=read(run/'generations/physics_iq_gpt_native_v2/status.json')
    seed_status=read(run/'generations/physics_iq_seed21_native_v2/status.json')
    old=read(legacy);groups={**status.get('groups',{}),**gpt_status.get('groups',{}),**seed_status.get('groups',{})};frozen=read(run/'BASELINE_FROZEN.json')
    body=('<a class=back href="index.html">← 实验导航</a><h1>Physics-IQ · Baseline 全量</h1>'
          '<p class=muted>完整198个I2V/BPP输入，每模型Text与Vision。已完成的旧协议结果复用，不重复生成。</p>'
          '<div class="card feature"><span class=badge>冻结原生 harness · 100k</span>'
          f'<div class=facts><div><strong>198</strong>每组任务</div><div><strong>{len(MODELS)}</strong>模型</div><div><strong>2</strong>Tracks</div></div>'
          '<p class=desc>256×144 · 4FPS · 20帧／5秒。模型自主检查和修订。旧50k及legacy运行明确单列来源。</p>'
          '<a href="https://github.com/SiyuanMaCS/PixelWorld/tree/main/baselines/native_v2_100k">baseline代码与复现文档 →</a></div>'
          '<h2 id=models>模型 × Track</h2><div class=scroll><table class=matrix><tr><th>模型</th><th>Text</th><th>Vision</th></tr>')
    for model,label in MODELS.items():
        body+=f'<tr><th>{label}</th>'
        for track in ['text','vision-agent']:
            entry=groups.get(model+'/'+track,{})
            c=entry.get('counts',{})
            last=entry.get('latest_completion') or ['—','—']
            if not c and model in ('gpt61-sol','gpt56-sol'):
                slug='gpt-6-1' if model=='gpt61-sol' else 'gpt-5-6'
                legacy_entry=old.get('configs',{}).get(slug+'-'+track,{})
                legacy_n=legacy_entry.get('counts',{}).get('complete',0)
                body+=(f'<td><strong>0/198 native_v2</strong><span class=status>新冻结协议尚未重跑；旧{legacy_n}/198结果移入Legacy参考区，不计入主表</span>'
                       f'<a href="#legacy">查看Legacy参考 →</a></td>')
            else:
                bench_dir='physics_iq_gpt_native_v2' if model in ('gpt61-sol','gpt56-sol') else ('physics_iq_seed21_native_v2' if model=='seed21-pro' else 'physics_iq')
                infra_count=quarantine_stats(run,[bench_dir])['by_group'].get((model,track),0)
                running_cases=', '.join(entry.get('running_cases') or [])
                activity=''
                if entry.get('running_cases'):
                    gen_root=run/'generations'/bench_dir
                    activity='<br>'.join(
                        f'{html.escape(case)}: {event_status(gen_root,model,track,case)}'
                        for case in (entry.get('running_cases') or [])[:3]
                    )
                body+=(f'<td>{activity_badge(c)} <strong>{c.get("complete",0)}/198 有效视频</strong><span class=status>{c.get("running",0)}运行中 · {c.get("exhausted",0)}模型未交付/待重试 · {c.get("pending",198-c.get("complete",0)-c.get("running",0)-c.get("exhausted",0))}待调度</span>'
                       + (f'<span class="status warn">{infra_count} infra/recovery attempts quarantined</span>' if infra_count else '')
                       + (f'<span class=status>正在跑：{html.escape(running_cases)}</span>' if running_cases else '')
                       + (f'<span class=status>最近事件：{activity}</span>' if activity else '')
                       + f'<span class=status>最新完成 UTC：{html.escape(str(last[0]))}<br>{html.escape(str(last[1]))}</span>'
                       f'<a href="bench_smoke_codex_20261109/{bench_dir}/{model}/{track}/index.html">视频与逐轮候选 →</a></td>')
        body+='</tr>'
    body+='</table></div>'
    body+='<h2 id=legacy>Legacy参考结果</h2><p class=note>以下为早期legacy-v1协议完成结果：任务提示、输出要求、记录字段与预算口径均不同，只作历史参考，不进入native_v2主实验均值或完成率。</p>'
    body+='<div class=scroll><table><tr><th>模型</th><th>Track</th><th>完成</th><th>Legacy平均耗时</th><th>链接</th></tr>'
    for slug,label in [('gpt-6-1','GPT-6.1-Sol'),('gpt-5-6','GPT-5.6-Sol')]:
        for track in ['text','vision-agent']:
            entry=old.get('configs',{}).get(slug+'-'+track,{})
            n=entry.get('counts',{}).get('complete',0)
            mean=entry.get('mean_duration_seconds')
            body+=f'<tr><td>{label}</td><td>{track}</td><td>{n}/198</td><td>{fmt(mean/60 if mean else None)}m</td><td><a href="matrix_{slug}-{track}.html">打开legacy全量视频 →</a></td></tr>'
    body+='</table></div>'
    body+='<h2 id=performance>耗时与 token 统计</h2><p class=note>仅统计已完成且通过validation的有效视频；running和失败case不进入均值。Legacy组只显示旧状态里的平均耗时，token均值缺失时不补0。</p>'
    body+='<div class=scroll><table><tr><th>模型</th><th>Text</th><th>Vision</th></tr>'
    for model,label in MODELS.items():
        body+=f'<tr><th>{label}</th>'
        for track in ['text','vision-agent']:
            if model in ('gpt61-sol','gpt56-sol') and not (run/'generations/physics_iq_gpt_native_v2'/model/track).exists():
                slug='gpt-6-1' if model=='gpt61-sol' else 'gpt-5-6'
                entry=old.get('configs',{}).get(slug+'-'+track,{})
                mean=entry.get('mean_duration_seconds')
                n=entry.get('counts',{}).get('complete')
                body+=f'<td><strong>{n or "—"}</strong><span class=status>legacy平均耗时 {fmt(mean/60 if mean else None)}m<br>token均值：旧记录未统一回填</span></td>'
            else:
                root=run/('generations/physics_iq_gpt_native_v2' if model in ('gpt61-sol','gpt56-sol') else ('generations/physics_iq_seed21_native_v2' if model=='seed21-pro' else 'generations/physics_iq'))
                body+=stats_cell(completed_stats(root,model,track))
        body+='</tr>'
    body+='</table></div>'
    body+='<h2 id=evaluation>评测阶段</h2><p class=note>完整198个真实有效输出到齐后，运行原始Verified评测；缺失视频不补零、不删除。旧组评分在原有全量页保留。</p>'
    cohorts={}
    for scheduler_name in ['physics_full_scheduler','physics_gpt_native_v2_full_scheduler','physics_seed21_native_v2_full_scheduler']:
        cohorts.update(read(run/'evaluation'/scheduler_name/'scheduler.json').get('cohorts',{}))
    body+='<div class=scroll><table><tr><th>组</th><th>阶段</th><th>有效输出</th><th>阻塞/说明</th><th>完整Verified /100</th></tr>'
    for key,entry in cohorts.items():
        score=entry.get('score',{}).get('verified_score') if entry.get('official_full_score') else None
        phase=entry.get('phase','待运行')
        note=entry.get('blocker') or entry.get('error') or '—'
        if phase=='incomplete_official_scope':
            note=f'{entry.get("exhausted_cases",0)} 条模型未交付；有效输出未达到198，不能计算完整官方分数'
        accepted=entry.get('accepted_cases',198 if entry.get('official_full_score') else '—')
        body+=f'<tr><td>{html.escape(key)}</td><td>{html.escape(phase)}</td><td>{accepted}/198</td><td>{html.escape(str(note))}</td><td>{physics_verified_display(score)}</td></tr>'
    body+='</table></div><p><a href="robojudge.html">RoboJudge全量实验 →</a></p>'
    page=document('Physics-IQ baseline · PixelWorld',body).replace('href="../index.html"','href="index.html"').replace('href="index.html#models"','href="#models"').replace('href="index.html#evaluation"','href="#evaluation"').replace('href="protocol.html"','href="bench_smoke_codex_20261109/protocol.html"')
    (web/'physics_iq_baseline.html').write_text(page)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run-root',type=Path,required=True);p.add_argument('--web-root',type=Path,required=True);p.add_argument('--legacy-status',type=Path,required=True);a=p.parse_args();build(a.run_root,a.web_root,a.legacy_status)
