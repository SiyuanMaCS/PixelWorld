"""Render the complete shared50 input inventory and existing generation results."""
from __future__ import annotations
import argparse
import html
import json
import shutil
import statistics
import time
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.build_bench_review import document, player, export_pixels, build_case, case_page_is_current

MODELS={'gpt61-sol':'GPT-6.1-Sol','gpt56-sol':'GPT-5.6-Sol',
        'gpt6-astra':'GPT-6-Astra','deepseek-v41':'DeepSeek-V4.1-Flash',
        'seed21-pro':'Seed-2.1-Pro-0915','gemini38-flash':'Gemini-3.8-Flash'}
TRACKS=('text','vision-agent')
STUDY='bench_smoke_codex_20261109'

def read(path):
    try:return json.loads(path.read_text())
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

def completed_stats(generation, model, track):
    rows=[]
    for path in sorted((generation/model/track).glob('case_*_attempt_*/run_manifest.json')):
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
    return {'n':len(rows),'avg_min':statistics.mean(durations),'p50_min':statistics.median(durations),
            'avg_output':statistics.mean(outputs),'p50_output':statistics.median(outputs),
            'avg_input':statistics.mean(inputs) if inputs else None,'p50_input':statistics.median(inputs) if inputs else None}

def stats_cell(stats):
    if not stats:return '<td>—</td>'
    return (f'<td><strong>{stats["n"]}</strong><span class=status>'
            f'耗时 avg {fmt(stats["avg_min"])}m / p50 {fmt(stats["p50_min"])}m<br>'
            f'output avg {fmt(stats["avg_output"],0)} / p50 {fmt(stats["p50_output"],0)}<br>'
            f'input avg {fmt(stats["avg_input"],0)} / p50 {fmt(stats["p50_input"],0)}</span></td>')

def activity_badge(counts):
    if counts.get('running',0)>0:return '<span class=badge>ACTIVE</span>'
    if counts.get('complete',0)>=50:return '<span class=pill>DONE</span>'
    return '<span class=pill>IDLE</span>'

def video_export(path, asset, spec):
    receipt=asset/'export_receipt.json'
    if receipt.exists() and (asset/'poster.png').is_file():
        try:
            data=read(receipt)['video']
            if (asset/data['pixels_file']).is_file():return data
        except (KeyError,TypeError):
            pass
    return export_pixels(path/'workspace',asset,spec)

def generation_root(run, model):
    return run/'generations/robojudge_seed21_native_v2' if model=='seed21-pro' else run/'generations/robojudge'

def scheduler_rows(run):
    rows=[]
    for title,path in [
        ('baseline100k',run/'evaluation/robojudge_full_baseline100k/scheduler.json'),
        ('seed21-native-v2',run/'evaluation/robojudge_seed21_native_v2_full/scheduler.json'),
    ]:
        scheduler=read(path)
        done={**scheduler.get('blocked',{}),**scheduler.get('done',{})}
        for key,group in sorted(scheduler.get('groups',{}).items()):
            counts=group.get('counts',{})
            phase=done.get(key,{}).get('phase')
            if not phase:
                if counts.get('complete',0)==50 and not counts.get('exhausted',0):
                    phase='ready_or_scoring'
                else:
                    phase='waiting_for_generation'
            running=', '.join(group.get('running_cases') or [])
            exhausted=', '.join((group.get('exhausted_cases') or [])[:6])
            note='—'
            if phase=='waiting_for_cuda':
                note='CUDA GPU unavailable；等待可用 GPU 后自动继续官方评测，已有阻塞记录保留'
            elif phase=='existing_incomplete_evaluation_needs_review':
                execution=read(path.parent / key / 'execution.json')
                blockers=execution.get('blockers') or []
                note=('已有评测目录；执行阻塞：'+'; '.join(str(x) for x in blockers)
                      if blockers else '已有不完整评测目录，尚未完成评分')
                note+='；不计作 full score'
            elif counts.get('exhausted',0):
                note=f'{counts.get("exhausted",0)} exhausted; full shared50 前不评分'
            rows.append(
                '<tr>'
                f'<td>{html.escape(title)}</td><td>{html.escape(key)}</td>'
                f'<td>{html.escape(phase)}</td>'
                f'<td>{counts.get("complete",0)}/50</td>'
                f'<td>{counts.get("running",0)}</td><td>{counts.get("pending",0)}</td>'
                f'<td>{html.escape(running) if running else "—"}</td>'
                f'<td>{html.escape(note)}'
                + (f'<br><span class=status>exhausted: {html.escape(exhausted)}</span>' if exhausted else '')
                + '</td></tr>'
            )
    if not rows:
        return '<p class=note>RoboJudge watcher 尚未写入 scheduler 状态。</p>'
    return ('<div class=scroll><table><tr><th>Scheduler</th><th>Model / Track</th><th>Phase</th>'
            '<th>Complete</th><th>Running</th><th>Pending</th><th>Running case</th><th>Blocker / Note</th></tr>'
            + ''.join(rows) + '</table></div>')

def build(run,web,case_budget=8):
    inputs=run/'inputs/robojudge';generation=run/'generations/robojudge'
    cases=sorted(p.name for p in inputs.iterdir() if (p/'first_frame.png').is_file())
    if len(cases)!=50:raise ValueError('RoboJudge page requires the actual complete50 input inventory')
    output=web/'robojudge_assets';output.mkdir(exist_ok=True)
    progress=read(generation/'status.json')
    seed_progress=read(run/'generations/robojudge_seed21_native_v2/status.json')
    groups={**progress.get('groups',{}),**seed_progress.get('groups',{})}
    records={};scores={}
    for model in MODELS:
        for track in TRACKS:
            for case in cases:
                attempts=[]
                gen=generation_root(run,model)
                for path in sorted((gen/model/track).glob(f'case_{case}_attempt_*/run_manifest.json')):
                    manifest=read(path)
                    if manifest:attempts.append((path.parent,manifest))
                if attempts:
                    accepted=next((x for x in attempts if x[1].get('status')=='complete' and x[1].get('validation',{}).get('pass')),None)
                    chosen=accepted or attempts[-1]
                    if not accepted and any(read(p).get('status')=='running' for p in chosen[0].glob('recovery_*/recovery_manifest.json')):
                        chosen=(chosen[0],{**chosen[1],'status':'100k续跑中'})
                    records[(model,track,case)]=chosen
            pattern=f'robojudge_{model}_'+('text_' if track=='text' else '')+'gpu_smoke*/summary.json'
            for path in sorted((run/'evaluation').glob(pattern)):
                result=read(path)
                if result.get('valid_paired_count'):
                    for item in result.get('items',[]):scores[(model,track,item['case_id'])]=item
                    break
    body=('<a class=back href="index.html">← PixelWorld 实验导航</a><h1>RoboJudge · 具身 I2V</h1>'
          '<p class=muted>共享50个操作任务，比较不同模型的像素视频生成、物理合理性和指令遵循。</p>'
          '<div class=experiment-grid><article class="card feature"><span class=badge>主实验 · Shared50</span><h3>模型与输入条件对照</h3>'
          f'<div class=facts><div><strong>50</strong>共享任务</div><div><strong>{len(MODELS)}</strong>模型</div><div><strong>2</strong>Tracks</div></div>'
          '<p class=desc>完整50任务的后台队列已启动。这里显示已生成视频和既有单例评分，完整均分仍等待到齐。</p></article>'
          '<article class=card><span class=pill>原始 RoboJudge-9B</span><h3 style="margin-top:14px">两项评分</h3>'
          '<p class=desc>PA：物理合理性。IA：指令遵循。评分范围1–5。只有实际有效视频才显示已有评分。</p>'
          '<p class=tiny>新预算为累计100k输出token；已有50k阶段记录保留。Table8的prompt与聚合口径仍在核对。</p></article></div>'
          '<h2 id=models>模型 × Track</h2><div class=scroll><table class=matrix><tr><th>模型</th><th>Text</th><th>Vision</th></tr>')
    for model,label in MODELS.items():
        body+=f'<tr><th>{label}</th>'
        for track in TRACKS:
            entries=[records[(model,track,c)] for c in cases if (model,track,c) in records]
            valid=sum(m.get('status')=='complete' and m.get('validation',{}).get('pass') for _,m in entries)
            value=scores.get((model,track,'common50_0001'))
            score=f'单例 PA {value["PA"]} / IA {value["IA"]}' if value else '单例评分 —'
            group=groups.get(model+'/'+track,{});counts=group.get('counts',{})
            latest=group.get('latest_completion') or ['—','—']
            run_count=counts.get('running',0);fail_count=counts.get('exhausted',0)
            running_cases=', '.join(group.get('running_cases') or [])
            activity=''
            if group.get('running_cases'):
                gen=generation_root(run,model)
                activity='<br>'.join(
                    f'{html.escape(case)}: {event_status(gen,model,track,case)}'
                    for case in (group.get('running_cases') or [])[:3]
                )
            body+=(f'<td>{activity_badge(counts)} <strong>{valid} /50 有效视频</strong><span class=status>{run_count} 运行中 · {fail_count} 终止 · {score}</span>'
                   + (f'<span class=status>正在跑：{html.escape(running_cases)}</span>' if running_cases else '')
                   + (f'<span class=status>最近事件：{activity}</span>' if activity else '')
                   + f'<span class=status>最近完成 UTC：{html.escape(str(latest[0]))}<br>{html.escape(str(latest[1]))}</span>'
                   f'<a href="{STUDY}/robojudge/{model}/{track}/index.html">打开此组视频与 Trace →</a></td>')
        body+='</tr>'
    body+='</table></div><p class=note>当前这些单例分数不是shared50均分。正式对榜需要完整任务和一致的prompt、采样及聚合口径。</p>'
    body+='<h2 id=performance>耗时与 token 统计</h2><p class=note>仅统计已完成且通过validation的有效视频；running和失败case不进入均值。output tokens包含provider报告的reasoning输出，不另加一次。</p>'
    body+='<div class=scroll><table><tr><th>模型</th><th>Text</th><th>Vision</th></tr>'
    for model,label in MODELS.items():
        body+=f'<tr><th>{label}</th>'
        for track in TRACKS:
            body+=stats_cell(completed_stats(generation_root(run,model),model,track))
        body+='</tr>'
    body+=('</table></div>'
           '<h2 id=watcher>评测 Watcher 状态</h2>'
           '<p class=desc>完整 shared50 cohort 到齐前只等待；已有不完整评测目录、GPU不可用等情况以 blocker/note 展示，不补假分。</p>'
           + scheduler_rows(run) +
           '<h2 id=videos>按任务查看视频</h2><label for=case_select class=status>选择共享任务</label> <select id=case_select>')
    selected='common50_0001'
    for case in cases:
        body+=f'<option value="case-{case}"{" selected" if case==selected else ""}>{case}</option>'
    body+='</select>'
    for case in cases:
        prompt=(inputs/case/'prompt.txt').read_text()
        shutil.copy2(inputs/case/'first_frame.png',output/(case+'.png'))
        body+=f'<section class=case-panel id="case-{case}"{" hidden" if case!=selected else ""}><div class=box><h3>{case}</h3><p class=desc>{html.escape(prompt)}</p></div>'
        entries=[(model,track,records[(model,track,case)]) for model in MODELS for track in TRACKS if (model,track,case) in records]
        if not entries:
            body+=f'<article class=card><span class=pill>尚未生成</span><p class=desc>这是完整共享任务集的首帧；目前没有生成视频。</p><img style="max-width:420px" loading=lazy src="robojudge_assets/{case}.png" alt="输入首帧"></article>'
        else:
            body+='<div class=robo-videos>'
            for model,track,(path,manifest) in entries:
                folder=path.name;relative=f'{STUDY}/robojudge/{model}/{track}/{folder}'
                if case_budget > 0 and not case_page_is_current(path, web/relative):
                    build_case(path,web/relative)
                    case_budget -= 1
                asset=web/relative/'final';spec=read(path/'media_contract.json')
                video=video_export(path,asset,spec)
                body+=f'<article class=card><h3>{MODELS[model]}</h3><p><span class=badge>{track}</span> <span class=pill>{manifest["status"]}</span></p>'
                if video:body+=player({**video,'pixels':relative+'/final/'+video['pixels_file'],'poster':relative+'/final/poster.png'})
                else:body+='<div class=placeholder>尚无合格的像素视频</div>'
                score=scores.get((model,track,case))
                if score:body+=f'<p>PA <strong>{score["PA"]}</strong> · IA <strong>{score["IA"]}</strong> · 单例评分</p>'
                if case_page_is_current(path,web/relative):
                    body+=f'<p><a href="{relative}/index.html">逐轮候选、检查图与代码变化 →</a></p>'
                else:
                    body+='<p class=note>生成记录已更新，详情正在同步。</p>'
                body+='</article>'
            body+='</div>'
        body+='</section>'
    full_eval = run / 'evaluation/robojudge_full_baseline100k'
    eval_rows = []
    for model, label in MODELS.items():
        for track in TRACKS:
            summary = read(full_eval / model / track / 'summary.json')
            execution = read(full_eval / model / track / 'execution.json')
            if not summary and not execution:
                continue
            scope = summary.get('scope', {})
            blockers = '; '.join(execution.get('blockers', [])) if execution.get('blockers') else '—'
            means = summary.get('shared50_means') or summary.get('partial_paired_means') or {}
            score = '—'
            if summary.get('complete_shared50') and means.get('mean') is not None:
                score = f'PA {means["PA"]:.2f} · IA {means["IA"]:.2f} · Overall {means["mean"]:.2f}'
            eval_rows.append(
                f'<tr><td>{html.escape(label)}</td><td>{html.escape(track)}</td>'
                f'<td>{scope.get("prepared_count", 0)}/50 prepared</td>'
                f'<td>{html.escape(execution.get("status", "prepared"))}</td>'
                f'<td>{html.escape(blockers)}</td><td>{score}</td></tr>')
    if eval_rows:
        body += ('<h2 id=official-eval>官方 shared50 评测执行状态</h2>'
                 '<p class=desc>这里记录完整50任务输入是否已经导出，以及原始 RoboJudge-9B 推理是否完成。'
                 'GPU不可用等执行阻塞不会被填成0分。</p>'
                 '<div class=scroll><table><tr><th>模型</th><th>Track</th><th>准备范围</th><th>执行状态</th><th>阻塞/说明</th><th>完整均分</th></tr>'
                 + ''.join(eval_rows) + '</table></div>')
    body+=('<h2 id=evaluation>正式评分与公开参考</h2><p class=desc>shared50完整均分：尚未完成。以下仅引用论文中的公开参考成绩，不能直接与上面的单例评分排名。</p>'
           '<div class=scroll><table><tr><th>公开模型</th><th>PA</th><th>IA</th><th>Overall</th></tr>'
           '<tr><td>Wan2.6 Flash</td><td>3.827</td><td>4.027</td><td>3.927</td></tr>'
           '<tr><td>Veo3.1 Lite</td><td>3.580</td><td>3.780</td><td>3.680</td></tr></table></div>'
           '<p><a href="https://arxiv.org/pdf/2610.27782">论文Table8 →</a> · '
           f'<a href="{STUDY}/baseline_audit.html">评测口径核对 →</a></p>'
           '<script>document.getElementById("case_select").onchange=e=>document.querySelectorAll(".case-panel").forEach(p=>p.hidden=p.id!==e.target.value);</script>')
    result=document('RoboJudge · PixelWorld',body)
    result=result.replace('href="../index.html"','href="index.html"').replace('href="index.html#models"','href="#models"').replace('href="index.html#evaluation"','href="#evaluation"').replace('href="protocol.html"',f'href="{STUDY}/protocol.html"')
    result=result.replace('</style>','.robo-videos{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:20px}@media(max-width:700px){.robo-videos{grid-template-columns:1fr}}</style>')
    (web/'robojudge.html').write_text(result)
    return {'cases':len(cases),'recorded_cells':len(records),'scored_videos':len(scores),'path':str(web/'robojudge.html')}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run-root',type=Path,required=True);p.add_argument('--web-root',type=Path,required=True);p.add_argument('--case-budget',type=int,default=8);a=p.parse_args();print(json.dumps(build(a.run_root.resolve(),a.web_root.resolve(),a.case_budget)))
