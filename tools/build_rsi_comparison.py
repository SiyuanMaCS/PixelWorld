"""Render the observed RSI pair without claiming an unevaluated quality gain."""
from pathlib import Path
import argparse,json,sys
import datetime as dt
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.build_bench_review import document,player,build_case,export_pixels

def quality(run,label):
    if label=='unscored_initial_attempt':return '未评分（保留原始审计失败）'
    root=run/'evaluation/rsi_pair_original9B'
    folders=[root/label]+sorted(root.glob(label+'_eval_retry_*'))
    for folder in folders:
        path=folder/'summary.json'
        if path.exists():
            report=json.loads(path.read_text())
            items=report.get('items',[])
            if len(items)==1 and not report.get('parse_failures') and not report.get('prediction_failures'):
                return f'{items[0]["PA"]} / {items[0]["IA"]}'
    return '待原版9B评分'

def observed_cost(path):
    m=json.loads((path/'run_manifest.json').read_text())
    snapshots=[json.loads(p.read_text()) for p in (path/'trace').glob('round_*/snapshot.json')]
    snapshots=[s for s in snapshots if s.get('required_output_files_complete')]
    first=min((dt.datetime.fromisoformat(s['utc']) for s in snapshots),default=None)
    start=dt.datetime.fromisoformat(m['started_utc'])
    return {'first_saved_seconds':(first-start).total_seconds() if first else None,
            'wall_seconds':m.get('duration_seconds'),'output_tokens':m.get('token_usage',{}).get('output_tokens'),
            'distinct_rgb_candidates':len({s.get('canonical_rgb_sha256') for s in snapshots if s.get('canonical_rgb_sha256')})}

def build(run,web):
    report=json.loads((run/'analysis/rsi_v1_pair.json').read_text())
    paths={'baseline_first':run/'generations/robojudge/gpt61-sol/vision-agent/case_common50_0000_attempt_01',
           'baseline_success':run/'generations/robojudge/gpt61-sol/vision-agent/case_common50_0000_attempt_02',
           'rsi':run/'rsi/prototype_first/gpt61-sol/vision-agent/case_common50_0000_attempt_01'}
    labels={'baseline_first':'Baseline · 初次执行','baseline_success':'Baseline · 审计通过的重试','rsi':'RSI v1 · 候选优先'}
    scored=quality(run,'native')!='待原版9B评分' and quality(run,'rsi_v1')!='待原版9B评分'
    conclusion=('本例原版9B评分：Baseline PA/IA 3/3，RSI v1 4/3。首个候选更早，但接受的单次执行耗时与tokens增加；一个开发样本不能证明通用改善。' if scored else 'RSI更早保存首个候选，但最终耗时与tokens增加。质量评分尚未完成；不据此宣布整体改善。')
    body=('<a class=back href="index.html">← 实验导航</a><h1>RSI探索 · 同输入对照</h1>'
          '<p class=muted>GPT-6.1-Sol / Vision-Agent · RoboJudge common50_0000 · 相同输入、工具、100k预算与媒体参数。</p>'
          '<div class=box><h3>当前结论</h3><p>'+conclusion+'</p>'
          '<p class=desc>初次baseline被冻结审计判为relative-parent-traversal。实际命令中该字符串只是分支标签，Image.open读取的是工作目录内frames/03.png。原有状态保留，这个审计问题独立记录，不修改冻结baseline。</p></div>'
          '<div class=scroll><table><tr><th>执行</th><th>首个保存候选</th><th>最终墙钟</th><th>输出tokens</th><th>不同RGB候选</th><th>PA / IA (1–5)</th></tr>')
    for key,row in report['runs'].items():
        q=quality(run,{'baseline_success':'native','rsi':'rsi_v1'}.get(key,'unscored_initial_attempt'))
        body+=f'<tr><td>{labels[key]}</td><td>{row["first_saved_seconds"]/60:.2f}分钟</td><td>{row["wall_seconds"]/60:.2f}分钟</td><td>{row["output_tokens"]}</td><td>{row["distinct_rgb_candidates"]}</td><td>{q}</td></tr>'
    body+='</table></div><p class=note>Baseline两次执行共35,276输出tokens：接受的重试单次17,489，初次17,787被审计拦下。RSI单次22,795。单次执行成本与整个case交付成本不能混用。API等待影响墙钟；PA/IA不是独立摄影质量指标。</p><div class=video-grid>'
    for key,path in paths.items():
        out=web/'rsi_assets'/key;build_case(path,out);page=out/'index.html';page.write_text(page.read_text().replace('../../../../../index.html','../../index.html').replace('../../../../index.html','../../index.html'));spec=json.loads((path/'media_contract.json').read_text());video=export_pixels(path/'workspace',out/'final',spec)
        body+=f'<article class=card><h3>{labels[key]}</h3>'
        if video:body+=player({**video,'pixels':f'rsi_assets/{key}/final/'+video['pixels_file'],'poster':f'rsi_assets/{key}/final/poster.png'})
        body+=f'<p><a href="rsi_assets/{key}/index.html">候选、检查图与完整工具轨迹 →</a></p></article>'
    body+='</div><p><a href="https://github.com/SiyuanMaCS/PixelWorld/tree/main/research/rsi_v1">RSI任务提示与设计说明 →</a></p>'
    if (run/'analysis/rsi_v2_pair.json').exists():
        report2=json.loads((run/'analysis/rsi_v2_pair.json').read_text())
        labels2={'baseline':'Baseline · 原生自主生成','rsi_v2':'RSI v2 · 场景结构提示'}
        paths2={'baseline':run/'generations/robojudge/gpt61-sol/vision-agent/case_common50_0002_attempt_01',
                'rsi_v2':run/'rsi/structure_first/gpt61-sol/vision-agent/case_common50_0002_attempt_01'}
        conclusion2=('本例原版9B评分从Baseline的4/4降到RSI v2的2/3，成本也增加。判分理由提到面包转移与夹持接触不清楚；显式结构提示未在本例带来改善。' if quality(run,'rsi_v2')!='待原版9B评分' else '本例首个候选与最终提交均更慢，输出tokens增加；是否改善质量仍待原版9B配对评分。')
        body+='<h2>RSI v2 · 场景结构提示</h2><p class=muted>GPT-6.1-Sol / Vision-Agent · RoboJudge common50_0002 · 独立干净上下文，baseline保持冻结。</p><div class=box><p>'+conclusion2+'开发样本不能代表全量效果。</p></div>'
        body+='<div class=scroll><table><tr><th>执行</th><th>首个保存候选</th><th>最终墙钟</th><th>输出tokens</th><th>不同RGB候选</th><th>PA / IA (1–5)</th></tr>'
        for key,row in report2['runs'].items():
            q=quality(run,'native_v2' if key=='baseline' else key)
            body+=f'<tr><td>{labels2[key]}</td><td>{row["first_saved_seconds"]/60:.2f}分钟</td><td>{row["wall_seconds"]/60:.2f}分钟</td><td>{row["output_tokens"]}</td><td>{row["distinct_rgb_candidates"]}</td><td>{q}</td></tr>'
        body+='</table></div><div class=video-grid>'
        for key,path in paths2.items():
            asset_key='native_v2' if key=='baseline' else key
            out=web/'rsi_assets'/asset_key;build_case(path,out);page=out/'index.html';page.write_text(page.read_text().replace('../../../../../index.html','../../index.html').replace('../../../../index.html','../../index.html'))
            spec=json.loads((path/'media_contract.json').read_text());video=export_pixels(path/'workspace',out/'final',spec)
            body+=f'<article class=card><h3>{labels2[key]}</h3>'
            if video:body+=player({**video,'pixels':f'rsi_assets/{asset_key}/final/'+video['pixels_file'],'poster':f'rsi_assets/{asset_key}/final/poster.png'})
            body+=f'<p><a href="rsi_assets/{asset_key}/index.html">每轮候选播放、检查图与工具轨迹 →</a></p></article>'
        body+='</div><p><a href="https://github.com/SiyuanMaCS/PixelWorld/tree/main/research/rsi_v2">RSI v2任务提示与设计说明 →</a></p>'
    probe=run/'rsi_v3_started.json'
    if probe.exists():
        state=json.loads(probe.read_text());path=Path(state['run']);m=json.loads((path/'run_manifest.json').read_text()) if (path/'run_manifest.json').exists() else {}
        body+='<h2>RSI v3 · 从首帧可见姿态继续</h2><p class=muted>GPT-6.1-Sol / Vision-Agent · RoboJudge common50_0003 · 第三个独立开发样本。</p>'
        body+=f'<div class=box><p>当前状态：{m.get("status","initializing")}。减少未观测几何假设，同时保留自主生成、检查和修订。首次候选和最终结果均保留。</p></div>'
        if quality(run,'rsi_v3')!='待原版9B评分':body+='<p class=note>本例原版9B评分：Baseline 4/3，RSI v3 3/3。输出tokens约少9%，最终墙钟约多8%；判分理由提到拖影与接触不清楚。不能据此称为更好的harness。</p>'
        control=run/'generations/robojudge/gpt61-sol/vision-agent/case_common50_0003_attempt_01'
        body+='<div class=video-grid>'
        for key,source,label in [('native_v3',control,'Baseline · 原生自主生成'),('rsi_v3',path,'RSI v3 · 首帧姿态提示')]:
            if not (source/'run_manifest.json').exists():continue
            out=web/'rsi_assets'/key;build_case(source,out);page=out/'index.html';page.write_text(page.read_text().replace('../../../../../index.html','../../index.html').replace('../../../../index.html','../../index.html'))
            spec=json.loads((source/'media_contract.json').read_text());video=export_pixels(source/'workspace',out/'final',spec)
            body+=f'<article class=card><h3>{label}</h3>'
            if video:body+=player({**video,'pixels':f'rsi_assets/{key}/final/'+video['pixels_file'],'poster':f'rsi_assets/{key}/final/poster.png'})
            cost=observed_cost(source)
            body+=f'<p>已记录不同RGB候选：{cost["distinct_rgb_candidates"]}；PA / IA：{quality(run,key)}</p>'
            if cost['output_tokens'] is not None:body+=f'<p>输出tokens：{cost["output_tokens"]}；最终墙钟：{cost["wall_seconds"]:.1f}秒</p>'
            body+=f'<p><a href="rsi_assets/{key}/index.html">候选、检查图与工具轨迹 →</a></p></article>'
        body+='</div><p><a href="https://github.com/SiyuanMaCS/PixelWorld/tree/main/research/rsi_v3">RSI v3任务提示与实验设计 →</a></p>'
    body+='<p class=note>PA与IA是原版RoboJudge-9B对本开发样本的1–5评分，不是完整shared50均值，也不是排行榜分数。评测结果不进入任何baseline生成上下文。</p>'
    page=document('RSI development comparison · PixelWorld',body).replace('href="../index.html"','href="index.html"').replace('href="protocol.html"','href="bench_smoke_codex_20261109/protocol.html"')
    (web/'rsi_comparison.html').write_text(page)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run-root',type=Path,required=True);p.add_argument('--web-root',type=Path,required=True);a=p.parse_args();build(a.run_root,a.web_root)
