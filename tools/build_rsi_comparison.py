"""Render the observed RSI pair without claiming an unevaluated quality gain."""
from pathlib import Path
import argparse,json,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.build_bench_review import document,player,build_case,export_pixels

def quality(run,label):
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

def build(run,web):
    report=json.loads((run/'analysis/rsi_v1_pair.json').read_text())
    paths={'baseline_first':run/'generations/robojudge/gpt61-sol/vision-agent/case_common50_0000_attempt_01',
           'baseline_success':run/'generations/robojudge/gpt61-sol/vision-agent/case_common50_0000_attempt_02',
           'rsi':run/'rsi/prototype_first/gpt61-sol/vision-agent/case_common50_0000_attempt_01'}
    labels={'baseline_first':'Baseline · 初次执行','baseline_success':'Baseline · 审计通过的重试','rsi':'RSI v1 · 候选优先'}
    body=('<a class=back href="index.html">← 实验导航</a><h1>RSI探索 · 同输入对照</h1>'
          '<p class=muted>GPT-6.1-Sol / Vision-Agent · RoboJudge common50_0000 · 相同输入、工具、100k预算与媒体参数。</p>'
          '<div class=box><h3>当前结论</h3><p>RSI更早保存首个候选，但最终耗时与tokens增加。质量评分尚未完成；不据此宣布整体改善。</p>'
          '<p class=desc>初次baseline被冻结审计判为relative-parent-traversal。实际命令中该字符串只是分支标签，Image.open读取的是工作目录内frames/03.png。原有状态保留，这个审计问题独立记录，不修改冻结baseline。</p></div>'
          '<div class=scroll><table><tr><th>执行</th><th>首个保存候选</th><th>最终墙钟</th><th>输出tokens</th><th>不同RGB候选</th><th>PA / IA (1–5)</th></tr>')
    for key,row in report['runs'].items():
        q=quality(run,{'baseline_success':'native','rsi':'rsi_v1'}.get(key,'unscored_initial_attempt'))
        body+=f'<tr><td>{labels[key]}</td><td>{row["first_saved_seconds"]/60:.2f}分钟</td><td>{row["wall_seconds"]/60:.2f}分钟</td><td>{row["output_tokens"]}</td><td>{row["distinct_rgb_candidates"]}</td><td>{q}</td></tr>'
    body+='</table></div><p class=note>单例探索。首个格式正确候选、完整审计交付和重试成本分别报告；API等待会影响墙钟。正式PA/IA与视觉质量比较仍待完成。</p><div class=video-grid>'
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
        body+='<h2>RSI v2 · 场景结构提示</h2><p class=muted>GPT-6.1-Sol / Vision-Agent · RoboJudge common50_0002 · 独立干净上下文，baseline保持冻结。</p><div class=box><p>本例首个候选与最终提交均更慢，输出tokens也增加。提示显式强调锚点、关节连接和接触，但是否改善质量仍由同一原版9B评分与逐轮视频共同检查。两个开发样本不能代表全量效果。</p></div>'
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
    body+='<p class=note>PA与IA是原版RoboJudge-9B对本开发样本的1–5评分，不是完整shared50均值，也不是排行榜分数。评测结果不进入任何baseline生成上下文。</p>'
    page=document('RSI development comparison · PixelWorld',body).replace('href="../index.html"','href="index.html"').replace('href="protocol.html"','href="bench_smoke_codex_20261109/protocol.html"')
    (web/'rsi_comparison.html').write_text(page)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run-root',type=Path,required=True);p.add_argument('--web-root',type=Path,required=True);a=p.parse_args();build(a.run_root,a.web_root)
