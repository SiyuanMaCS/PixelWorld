"""Publish fixed-baseline Physics-IQ progress, including explicitly reused legacy groups."""
from pathlib import Path
import argparse,json,html,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.build_bench_review import document

MODELS={'gpt61-sol':'GPT-6.1-Sol','gpt56-sol':'GPT-5.6-Sol','gpt6-astra':'GPT-6-Astra','deepseek-v41':'DeepSeek-V4.1-Flash'}

def read(p):
    try:return json.loads(p.read_text())
    except (OSError,ValueError):return {}

def build(run,web,legacy):
    status=read(run/'generations/physics_iq/status.json');old=read(legacy);groups=status.get('groups',{});frozen=read(run/'BASELINE_FROZEN.json')
    body=('<a class=back href="index.html">← 实验导航</a><h1>Physics-IQ · Baseline 全量</h1>'
          '<p class=muted>完整198个I2V/BPP输入，每模型Text与Vision-Agent。已完成的旧协议结果复用，不重复生成。</p>'
          '<div class="card feature"><span class=badge>冻结原生 harness · 100k</span>'
          '<div class=facts><div><strong>198</strong>每组任务</div><div><strong>4</strong>模型</div><div><strong>2</strong>Tracks</div></div>'
          '<p class=desc>256×144 · 4FPS · 20帧／5秒。模型自主检查和修订。旧50k及legacy运行明确单列来源。</p>'
          '<a href="https://github.com/SiyuanMaCS/PixelWorld/tree/main/baselines/native_v2_100k">baseline代码与复现文档 →</a></div>'
          '<h2 id=models>模型 × Track</h2><div class=scroll><table class=matrix><tr><th>模型</th><th>Text</th><th>Vision-Agent</th></tr>')
    for model,label in MODELS.items():
        body+=f'<tr><th>{label}</th>'
        for track in ['text','vision-agent']:
            if model in ('gpt61-sol','gpt56-sol'):
                slug='gpt-6-1' if model=='gpt61-sol' else 'gpt-5-6';entry=old.get('configs',{}).get(slug+'-'+track,{});n=entry.get('counts',{}).get('complete',0)
                body+=f'<td><strong>{n}/198 已完成</strong><span class=status>复用legacy结果 · 原有协议与预算</span><a href="matrix_{slug}-{track}.html">打开已有全量视频 →</a></td>'
            else:
                entry=groups.get(model+'/'+track,{});c=entry.get('counts',{});last=entry.get('latest_completion') or ['—','—']
                body+=(f'<td><strong>{c.get("complete",0)}/198 有效视频</strong><span class=status>{c.get("running",0)}运行中 · {c.get("exhausted",0)}终止 · {c.get("pending",0)}待生成</span>'
                       f'<span class=status>最新完成 UTC：{html.escape(str(last[0]))}<br>{html.escape(str(last[1]))}</span>'
                       f'<a href="bench_smoke_codex_20261109/physics_iq/{model}/{track}/index.html">视频与逐轮候选 →</a></td>')
        body+='</tr>'
    body+='</table></div><h2 id=evaluation>评测阶段</h2><p class=note>完整198个真实有效输出到齐后，运行原始Verified评测；缺失视频不补零、不删除。旧组评分在原有全量页保留。</p>'
    scheduler=read(run/'evaluation/physics_full_scheduler/scheduler.json')
    body+='<div class=scroll><table><tr><th>组</th><th>阶段</th><th>完整Verified</th></tr>'
    for key,entry in scheduler.get('cohorts',{}).items():
        score=entry.get('score',{}).get('verified_score') if entry.get('official_full_score') else None
        body+=f'<tr><td>{html.escape(key)}</td><td>{html.escape(entry.get("phase","待运行"))}</td><td>{score if score is not None else "—"}</td></tr>'
    body+='</table></div><p><a href="robojudge.html">RoboJudge全量实验 →</a></p>'
    page=document('Physics-IQ baseline · PixelWorld',body).replace('href="../index.html"','href="index.html"').replace('href="index.html#models"','href="#models"').replace('href="index.html#evaluation"','href="#evaluation"').replace('href="protocol.html"','href="bench_smoke_codex_20261109/protocol.html"')
    (web/'physics_iq_baseline.html').write_text(page)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run-root',type=Path,required=True);p.add_argument('--web-root',type=Path,required=True);p.add_argument('--legacy-status',type=Path,required=True);a=p.parse_args();build(a.run_root,a.web_root,a.legacy_status)
