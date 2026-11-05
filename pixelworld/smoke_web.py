"""Benchmark smoke review pages, with playable candidates and observed tools."""
from __future__ import annotations

import argparse
import difflib
import hashlib
import html
import json
from pathlib import Path
import shutil
import wave

import numpy as np
from PIL import Image, ImageDraw

from .constants import ASSET_ROOT
from .media import DEFAULT_MEDIA
from .util import atomic_json, utc_now

CSS = """*{box-sizing:border-box}:root{color-scheme:dark}body{margin:0;background:#10141c;color:#edf1f7;font:15px/1.65 system-ui}main{max-width:1180px;padding:24px 18px 70px;margin:auto}h1{font-size:36px;margin:8px 0}h2{margin-top:30px}a{color:#9ad0ff;text-decoration:none}.muted{color:#a6b3c5}.card,article,.box{background:#19212d;border:1px solid #344257;border-radius:12px;padding:16px;margin:14px 0}.table{overflow:auto}table{border-collapse:collapse;width:100%}th,td{border:1px solid #344257;padding:10px;text-align:left;vertical-align:top}.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}.grid>.card{margin:0}.screen{position:relative;background:#080c12;aspect-ratio:var(--aspect)}canvas,.poster{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;image-rendering:pixelated}.controls{display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:12px 0}button{font:inherit;background:#b9eb92;color:#19250f;border:0;border-radius:7px;padding:8px 12px;cursor:pointer}.seek{flex:1;min-width:100px}.clock{font-size:12px;color:#adbed4}.inspection{width:100%;height:auto;image-rendering:pixelated}pre{background:#0a1018;padding:12px;border-radius:8px;white-space:pre-wrap;word-break:break-word;font:12px/1.6 monospace}details{margin:10px 0}summary{cursor:pointer}.badge{display:inline-block;border:1px solid #56704b;padding:2px 9px;border-radius:20px;color:#c4efa9}.wave{width:100%;max-height:120px}@media(max-width:760px){.grid{grid-template-columns:1fr}h1{font-size:28px}}"""


def clean(value: str) -> str:
    # Public exports never expose private host paths or credentials.
    import re
    return re.sub(r"/(?:mnt|home|tmp)/[^\s\"'<>]+", "[workspace path]", value)


def page(title: str, body: str, script: str = "") -> str:
    return f'<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title><style>{CSS}</style><main>{body}</main><script>{script}</script></html>'


def encode(workspace: Path, target: Path, spec: dict) -> dict:
    target.mkdir(parents=True, exist_ok=True)
    with np.load(workspace / "pixels.npz", allow_pickle=False) as archive:
        pixels = archive["pixels"]
    h, w, n = (spec[k] for k in ("height", "width", "frames"))
    if pixels.shape == (n,h,w):
        pixels = pixels.transpose(1,2,0)
    if pixels.shape != (h,w,n):
        raise ValueError("Unexpected tensor shape")
    rgb = np.stack([(pixels>>16)&255,(pixels>>8)&255,pixels&255],axis=-1).astype(np.uint8).transpose(2,0,1,3)
    digest = hashlib.sha256(rgb.tobytes()).hexdigest()[:16]
    asset = f'pixels-{digest}.png'
    if not (target/asset).exists():
        delta = rgb.copy();delta[1:] = np.bitwise_xor(rgb[1:],rgb[:-1])
        Image.fromarray(delta.reshape(n*h,w,3)).save(target/asset)
    Image.fromarray(rgb[0]).save(target/'poster.png')
    for name in ('inspection.png','transition_check.png','audio.wav'):
        if (workspace/name).is_file():
            shutil.copy2(workspace/name,target/name)
    derived = not (workspace/'inspection.png').is_file()
    if derived:
        # A stable RGB candidate may precede the agent's optional contact sheet.
        # Export a view of its frozen pixels without changing the snapshot.
        sheet=Image.new('RGB',(w*4,(h+22)*2),(10,16,24));draw=ImageDraw.Draw(sheet)
        for i,index in enumerate(np.linspace(0,n-1,8).round().astype(int)):
            x,y=(i%4)*w,(i//4)*(h+22)
            draw.text((x+4,y+3),f'frame {index:02d} / {index/spec["fps"]:.2f}s',fill='white')
            sheet.paste(Image.fromarray(rgb[index]),(x,y+22))
        sheet.save(target/'inspection.png')
    if (workspace/'generate.py').is_file():
        (target/'generate.py').write_text(clean((workspace/'generate.py').read_text()))
    return {"asset":asset,"poster":"poster.png","width":w,"height":h,"frames":n,"fps":spec['fps'],"inspection_derived":derived,
            "audio":"audio.wav" if (target/'audio.wav').is_file() else None}


def player(record: dict, prefix: str = "") -> str:
    data = record.copy()
    for key in ('asset','poster','audio'):
        if data.get(key):data[key] = prefix + data[key]
    payload = html.escape(json.dumps(data), quote=True)
    return f'''<div class="player" data-player="{payload}"><div class="screen" style="--aspect:{data['width']}/{data['height']}"><canvas></canvas><img class="poster" src="{html.escape(data['poster'])}"></div><div class="controls"><button class="play">▶ 播放</button><button class="replay">↻ 重播</button><input class="seek" type="range" min="0" value="0"><label><input class="loop" type="checkbox" checked>循环</label><span class="clock"></span></div></div>'''


def waveform(audio: Path, target: Path) -> None:
    with wave.open(str(audio),'rb') as handle:
        channels = handle.getnchannels()
        pcm = np.frombuffer(handle.readframes(handle.getnframes()),dtype='<i2').reshape(-1,channels).mean(axis=1)/32768
    bins = np.array_split(pcm,900)
    im = Image.new('RGB',(900,100),(10,16,24));draw=ImageDraw.Draw(im)
    for x,b in enumerate(bins):
        peak=float(np.max(np.abs(b))) if len(b) else 0
        draw.line((x,50-peak*45,x,50+peak*45),fill=(139,210,255))
    im.save(target)


def trace(run: Path, target: Path, back: str) -> dict:
    manifest = json.loads((run/'run_manifest.json').read_text())
    spec = manifest.get('media_contract',DEFAULT_MEDIA)
    workspace = run/'workspace'
    events=[]
    for line in (run/'logs/events.jsonl').read_text(errors='replace').splitlines():
        try:event=json.loads(line)
        except json.JSONDecodeError:continue
        if event.get('type')=='item.completed' and event.get('item',{}).get('type')!='reasoning':events.append(event)
    snapshots=sorted((run/'trace').glob('round_*'))
    final = encode(workspace,target/'final',spec)
    usage=manifest.get('token_usage',{})
    prompt=html.escape((workspace/'prompt.txt').read_text())
    body=f'<p><a href="{back}">← Smoke 总览</a></p><h1>{html.escape(manifest["case_id"])}</h1><p class="muted">{html.escape(manifest["model"])} · {html.escape(manifest["track"])} · {spec["width"]}×{spec["height"]} · {spec["frames"]} frames / {spec["fps"]:g} fps</p><div class="box"><strong>当前任务输入</strong><p>{prompt}</p></div><h2>最终视频</h2>{player(final,"final/")}<p><a href="final/generate.py">生成代码</a> · <a href="contract.json">输入与输出契约</a></p>'
    if final['audio']:
        waveform(target/'final/audio.wav',target/'waveform.png')
        body+='<p>音频与 RGB 使用同一播放器时钟；点击播放会同时播放 WAV。</p><img class="wave" src="waveform.png">'
    body+=f'<div class="box">保存的候选：{len(snapshots)} · output tokens：{usage.get("output_tokens","未上报")} · reasoning output tokens：{usage.get("reasoning_output_tokens","未上报")} · 耗时：{manifest.get("duration_seconds",0):.0f}s</div><h2>逐轮生成与修改</h2><p class="muted">候选由外部 harness 保存。是否读图，以对应工具事件为依据。</p>'
    previous=[]
    for i,source in enumerate(snapshots):
        folder=target/f'candidate_{i:02d}';rec=encode(source,folder,spec)
        snap=json.loads((source/'snapshot.json').read_text())
        code=(source/'generate.py').read_text().splitlines();diff='\n'.join(difflib.unified_diff(previous,code,fromfile='previous',tofile='current',lineterm=''));previous=code
        image_note='<p class="muted">该候选未存检查图；此图由外部 harness 从本轮真实 RGB 帧导出。</p>' if rec['inspection_derived'] else ''
        body+=f'<article><h3>Candidate {i+1}</h3><p class="muted">{snap.get("utc","")} · RGB hash {snap.get("canonical_rgb_sha256","")[:16]}</p>{player(rec,f"candidate_{i:02d}/")}<img class="inspection" src="candidate_{i:02d}/inspection.png">{image_note}<details><summary>本轮代码修改</summary><pre>{html.escape(clean(diff))}</pre></details><a href="candidate_{i:02d}/generate.py">本轮完整代码</a></article>'
    observed=[]
    body+='<h2>可观测工具时间线</h2>'
    for event in events:
        item=event.get('item',{});kind=item.get('type','tool');time=event.get('_harness_received',{}).get('utc','')
        label=str(item.get('command') or item.get('text') or item.get('name') or kind)
        output=str(item.get('aggregated_output') or item.get('output') or '')
        observed.append({'time':time,'type':kind,'input':clean(label),'output':clean(output),'exit_code':item.get('exit_code')})
        body+=f'<details><summary>{html.escape(time[-16:])} · {html.escape(kind)} · {html.escape(clean(label.splitlines()[0])[:160])}</summary><pre>{html.escape(clean(label))}</pre><pre>{html.escape(clean(output)[:12000])}</pre></details>'
    atomic_json(target/'observed_trace.json',observed)
    atomic_json(target/'contract.json',{'media':spec,'task_prompt':clean((run/'task_prompt.txt').read_text()),'rules':clean((workspace/'GENERATION_RULES.md').read_text()),'validation':manifest.get('validation'),'token_usage':usage})
    body+='<p><a href="observed_trace.json">完整可观测事件 JSON</a></p>'
    (target/'index.html').write_text(page('PixelWorld generation trace',body,(ASSET_ROOT/'smoke_player.js').read_text()))
    return {'manifest':manifest,'player':final,'candidates':len(snapshots)}


def build(root: Path, site: Path) -> dict:
    root=root.resolve();site=site.resolve();site.mkdir(parents=True,exist_ok=True)
    inventory=json.loads((root/'inventory.json').read_text())
    cards=[];table=[];published=[]
    for bench in inventory:
        name=bench['id'];runs=sorted((root/'runs'/name).glob('*/*/case_*/run_manifest.json'))
        done=0;running=0;failed=0;tokens=0
        for path in runs:
            manifest=json.loads(path.read_text());state=manifest['status']
            if state=='running':running+=1;continue
            if state!='complete':failed+=1;continue
            done+=1;tokens+=manifest.get('token_usage',{}).get('output_tokens') or 0
            relative=f'{name}/{path.parent.name}'
            result=trace(path.parent,site/relative,'../../index.html');rec=result['player']
            cards.append(f'<div class="card"><h3>{html.escape(bench["name"])} · {html.escape(manifest["case_id"])}</h3>{player(rec,relative+"/final/")}<p>{result["candidates"]} 保存候选 · {manifest.get("token_usage",{}).get("output_tokens","—")} output tokens</p><a href="{relative}/index.html">图文视频生成过程 →</a></div>')
            published.append({'benchmark':name,'case':manifest['case_id'],'path':relative+'/index.html','media':manifest.get('media_contract',DEFAULT_MEDIA),'output_tokens':manifest.get('token_usage',{}).get('output_tokens')})
        sequence = next((root/'runs'/name).glob('*/*/sequence_*/sequence_manifest.json'),None)
        phase=f'{done} 完成 / {running} 运行 / {failed} 失败'
        if sequence:
            seq=json.loads(sequence.read_text());phase+=f' · episode {seq["status"]}'
            completed = [turn for turn in seq['turns'] if turn['status']=='complete']
            if completed:
                spec=json.loads((Path(completed[0]['run'])/'run_manifest.json').read_text()).get('media_contract',DEFAULT_MEDIA)
                tensors=[]
                for turn in completed:
                    with np.load(Path(turn['run'])/'workspace/pixels.npz') as archive:
                        tensors.append(archive['pixels'])
                combined_dir=sequence.parent/'preview_concat'
                combined_dir.mkdir(exist_ok=True)
                np.savez_compressed(combined_dir/'pixels.npz',pixels=np.concatenate(tensors,axis=2))
                relative=f'{name}/combined'
                rec=encode(combined_dir,site/relative,spec|{'frames':spec['frames']*len(completed)})
                action_text=' → '.join(turn['action'] for turn in completed)
                cards.append(f'<div class="card"><h3>{html.escape(bench["name"])} · 多轮连续播放</h3><p>{html.escape(action_text)} · {len(completed)} 轮已完成</p>{player(rec,relative+"/")}<p>每轮使用上一轮末帧作输入；下方单轮页面提供对应候选和工具过程。</p></div>')
        table.append(f'<tr><td><a href="{html.escape(bench["source"])}">{html.escape(bench["name"])}</a></td><td>{html.escape(str(bench["size"]))}</td><td>{html.escape(bench["task"])}</td><td>{phase}</td><td>{tokens:,}</td><td>{html.escape(bench["adaptation"])}</td></tr>')
    body=f'<p><a href="../index.html">← PixelWorld 主入口</a></p><h1>PixelWorld · Benchmark Smoke</h1><p class="muted">GPT-5.6-Sol · Vision-Agent · 更新时间 {utc_now()}。现有 Physics-IQ 全量独立继续运行。</p><p>先检查真实生成效果与各任务接口，再选择全量评测。这里展示 smoke 产物，不报告官方全量分数。<button onclick="location.reload()">刷新进度</button></p><div class="table"><table><thead><tr><th>Benchmark</th><th>集合规模</th><th>能力与任务</th><th>当前状态</th><th>Output tokens</th><th>协议适配</th></tr></thead><tbody>{"".join(table)}</tbody></table></div><h2>可播放的生成结果</h2><div class="grid">{"".join(cards)}</div>'
    (site/'index.html').write_text(page('PixelWorld benchmark smoke',body,(ASSET_ROOT/'smoke_player.js').read_text()))
    atomic_json(site/'status.json',{'updated_utc':utc_now(),'cases':published})
    return {'site':str(site),'cases':len(published)}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True);parser.add_argument('--site',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(build(args.root,args.site)))


if __name__=='__main__':main()
