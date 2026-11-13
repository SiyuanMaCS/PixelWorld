"""Build playable final/candidate reviews from externally recorded RGB artifacts.

No model calls, benchmark evaluation or generation feedback. Public pages omit
API records, credentials and provider-internal reasoning. Run logs stay on disk.
"""
from __future__ import annotations

import argparse
import difflib
import gzip
import hashlib
import html
import json
import shutil
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image


CSS = Path(__file__).with_name('bench_theme.css').read_text()
LIVE_VERSION = hashlib.sha256(Path(__file__).with_name('live_refresh.js').read_bytes()).hexdigest()[:12]

PLAYER = """
class PixelPlayer{
 constructor(node,d){this.node=node;this.d=d;this.frames=null;this.frame=0;this.playing=false;this.epoch=0;this.ctx=node.querySelector('canvas').getContext('2d');this.ctx.canvas.width=d.width;this.ctx.canvas.height=d.height;this.seek=node.querySelector('.seek');this.seek.max=d.frames-1;this.note=node.querySelector('.status');node.querySelector('.play').onclick=()=>this.toggle();node.querySelector('.replay').onclick=async()=>{await this.load();this.frame=0;this.start()};this.seek.oninput=async()=>{await this.load();this.frame=+this.seek.value;this.draw();if(this.playing)this.epoch=performance.now()-this.frame*1000/this.d.fps};this.preview=new Image();this.preview.onload=()=>{if(!this.frames)this.ctx.drawImage(this.preview,0,0,d.width,d.height)};this.preview.src=d.poster;}
 async load(){if(this.frames)return;if(this.loading)return this.loading;this.note.textContent='载入像素…';this.loading=(async()=>{try{let r=await fetch(this.d.pixels);if(!r.ok)throw Error('HTTP '+r.status);let decoded=r.body.pipeThrough(new DecompressionStream('gzip'));this.frames=new Uint8Array(await new Response(decoded).arrayBuffer());if(this.frames.length!==this.d.width*this.d.height*this.d.frames*3)throw Error('RGB 长度不匹配');this.draw()}catch(e){this.note.textContent='载入失败：'+e.message;this.loading=null;throw e}})();return this.loading}
 draw(){let n=this.d.width*this.d.height,rgba=new Uint8ClampedArray(n*4);for(let i=0;i<n;i++){let o=this.d.layout==='pixel-time'?(i*this.d.frames+this.frame)*3:(this.frame*n+i)*3;rgba[4*i]=this.frames[o];rgba[4*i+1]=this.frames[o+1];rgba[4*i+2]=this.frames[o+2];rgba[4*i+3]=255}this.ctx.putImageData(new ImageData(rgba,this.d.width,this.d.height),0,0);this.seek.value=this.frame;this.note.textContent=(this.frame/this.d.fps).toFixed(2)+' / '+(this.d.frames/this.d.fps).toFixed(2)+' s · '+(this.frame+1)+'/'+this.d.frames;}
 start(){this.playing=true;this.epoch=performance.now()-this.frame*1000/this.d.fps;this.node.querySelector('.play').textContent='Ⅱ 暂停';let tick=now=>{if(!this.playing)return;this.frame=Math.max(0,Math.min(this.d.frames-1,Math.floor((now-this.epoch)*this.d.fps/1000)));this.draw();if(now-this.epoch>=this.d.frames*1000/this.d.fps){this.pause();return}requestAnimationFrame(tick)};requestAnimationFrame(tick)}
 pause(){this.playing=false;this.node.querySelector('.play').textContent='▶ 播放'}
 async toggle(){try{await this.load();if(this.playing)this.pause();else{if(this.frame>=this.d.frames-1)this.frame=0;this.start()}}catch(e){}}
}
class ChunkedPixelPlayer extends PixelPlayer{
 constructor(node,d){super(node,d);this.buffers=new Map();this.requests=new Map();this.seek.oninput=async()=>{this.pause();this.frame=+this.seek.value;await this.ensureFrame(this.frame);this.draw()};}
 chunkIndex(frame){return this.d.chunks.findIndex(c=>frame>=c.first_frame&&frame<c.first_frame+c.frames)}
 async ensureFrame(frame){const index=this.chunkIndex(frame);if(index<0)throw Error('missing RGB chunk');if(!this.buffers.has(index)){
  if(!this.requests.has(index)){const chunk=this.d.chunks[index];this.requests.set(index,(async()=>{const response=await fetch(chunk.pixels);if(!response.ok)throw Error('HTTP '+response.status);const bytes=new Uint8Array(await new Response(response.body.pipeThrough(new DecompressionStream('gzip'))).arrayBuffer());if(bytes.length!==this.d.width*this.d.height*chunk.frames*3)throw Error('RGB chunk length mismatch');this.buffers.set(index,bytes);this.frames=true;for(const key of this.buffers.keys())if(key!==index&&key!==index-1)this.buffers.delete(key)})().finally(()=>this.requests.delete(index)));}
  await this.requests.get(index);
 }return index;}
 async load(){try{await this.ensureFrame(this.frame);this.draw()}catch(error){this.note.textContent='载入失败：'+error.message;throw error}}
 draw(){const index=this.chunkIndex(this.frame),bytes=this.buffers.get(index);if(!bytes)return;const chunk=this.d.chunks[index],local=this.frame-chunk.first_frame,n=this.d.width*this.d.height,rgba=new Uint8ClampedArray(n*4);for(let i=0;i<n;i++){const offset=(i*chunk.frames+local)*3;rgba[4*i]=bytes[offset];rgba[4*i+1]=bytes[offset+1];rgba[4*i+2]=bytes[offset+2];rgba[4*i+3]=255}this.ctx.putImageData(new ImageData(rgba,this.d.width,this.d.height),0,0);this.seek.value=this.frame;this.note.textContent=(this.frame/this.d.fps).toFixed(2)+' / '+(this.d.frames/this.d.fps).toFixed(2)+' s · '+(this.frame+1)+'/'+this.d.frames+' · 原生像素分块';}
 start(){this.playing=true;this.epoch=performance.now()-this.frame*1000/this.d.fps;this.node.querySelector('.play').textContent='Ⅱ 暂停';const tick=async now=>{if(!this.playing)return;this.frame=Math.max(0,Math.min(this.d.frames-1,Math.floor((now-this.epoch)*this.d.fps/1000)));const before=performance.now();try{await this.ensureFrame(this.frame)}catch(error){this.note.textContent='载入失败：'+error.message;this.pause();return}this.epoch+=performance.now()-before;if(!this.playing)return;this.draw();if(now-this.epoch>=this.d.frames*1000/this.d.fps){this.pause();return}requestAnimationFrame(tick)};requestAnimationFrame(tick)}
}
window.__benchPlayers=[];document.querySelectorAll('.player').forEach(n=>{const data=JSON.parse(n.dataset.video);let p=data.chunks?new ChunkedPixelPlayer(n,data):new PixelPlayer(n,data);n.dataset.state='idle';let start=p.start.bind(p),pause=p.pause.bind(p);p.start=()=>{n.dataset.state='playing';start()};p.pause=()=>{n.dataset.state='paused';pause()};n.querySelector('canvas').onclick=()=>p.toggle();let overlay=n.querySelector('.play-overlay');if(overlay)overlay.onclick=()=>p.toggle();window.__benchPlayers.push(p)});window.__benchReady=true;
document.querySelectorAll('[data-panel]').forEach(b=>b.onclick=()=>{document.querySelectorAll('[data-panel]').forEach(x=>x.setAttribute('aria-selected',String(x===b)));document.querySelectorAll('.benchmark-panel').forEach(x=>x.hidden=x.id!==b.dataset.panel)});
"""


def physics_verified_display(score):
    """Official Physics-IQ stores a fraction; public tables display /100."""
    return '—' if score is None else f'{float(score) * 100:.2f}'


def document(title, body, depth=0, case_page=False):
    overview = '../'*depth+'index.html'
    home = '../'*(depth+1)+'index.html'
    nav = ((('视频','#video'),('逐轮候选','#candidates'),('工具记录','#trace')) if case_page else
           (('模型对照',overview+'#models'),('评测结果',overview+'#evaluation'),('参数与协议','../'*depth+'protocol.html')))
    header = ('<header class=top><div class=top-inner><a class=brand href="'+home+'">'
              '<span class=pixel aria-hidden=true></span>PixelWorld</a><nav class=nav aria-label="实验导航">'
              + ''.join(f'<a href="{href}">{label}</a>' for label,href in nav)+'</nav></div></header>')
    if '<h1>' in body and '<section class=hero>' not in body:
        before,after=body.split('<h1>',1)
        heading,rest=after.split('</h1>',1)
        body=before+'<section class=hero><p class=eyebrow>CODING AGENTS AS PIXEL WORLD MODELS</p><h1>'+heading+'</h1></section>'+rest
    return ("<!doctype html><html lang=zh data-theme=pixelworld><meta charset=utf-8>"
            "<meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>{html.escape(title)}</title><style>{CSS}</style><body>{header}<main>{body}"
            '<footer><span>PixelWorld · 研究预览</span><span>视频 · 候选版本 · 可观测生成过程</span></footer></main>'
            f"<script>{PLAYER}</script><script defer src='/pixelworld/live_refresh.js?v={LIVE_VERSION}'></script></body></html>")


def player(data):
    if data.get('chunks'):
        data={**data,'chunks':[{**c,'pixels':c.get('pixels',c['pixels_file'])}for c in data['chunks']]}
    return (f"<div class=player data-video='{html.escape(json.dumps(data), quote=True)}'>"
            '<div class=player-frame><canvas aria-label="生成视频"></canvas><button class=play-overlay aria-label="播放视频">▶</button></div>'
            "<div class=controls><button class=play>▶ 播放</button>"
            "<button class=replay>↻ 重播</button><input class=seek type=range min=0 step=1 value=0>"
            "</div><p class=status>点击播放 · 原生 RGB 像素</p></div>")


def video_paths(video,prefix):
    result={**video,'poster':prefix+'/poster.png'}
    if video.get('chunks'):
        result['chunks']=[{**c,'pixels':prefix+'/'+c['pixels_file']}for c in video['chunks']]
    else:result['pixels']=prefix+'/'+video['pixels_file']
    return result


def export_pixels(source, target, spec, chunk_bytes=96*1024*1024):
    target.mkdir(parents=True, exist_ok=True)
    path = source / "pixels.npz"
    if not path.is_file():
        return None
    from pixelworld.util import sha256
    source_hash = sha256(path)
    receipt = target / 'export_receipt.json'
    media = {k: spec[k] for k in ('width', 'height', 'frames', 'fps')}
    cached = None
    if receipt.exists():
        try:
            saved = json.loads(receipt.read_text())
            data = saved['video']
            if (saved.get('source_npz_sha256') == source_hash and saved.get('media') == media
                    and all((target/name).is_file() for name in
                            ([data['pixels_file']] if data.get('pixels_file') else [c['pixels_file'] for c in data.get('chunks',[])]))
                    and (target/'poster.png').is_file()):
                cached = data
        except (ValueError, KeyError, TypeError):
            pass
    if cached is not None:
        for name in ('inspection.png', 'transition_check.png'):
            if (source/name).is_file():
                shutil.copy2(source/name, target/name)
        return cached
    with np.load(path, allow_pickle=False) as d:
        packed = d["pixels"]
        if packed.shape != (spec["height"], spec["width"], spec["frames"]):
            return None
        if spec['width']*spec['height']*spec['frames']*3>chunk_bytes:
            count=max(1,chunk_bytes//(spec['width']*spec['height']*3));chunks=[];last_hash=None
            for start in range(0,spec['frames'],count):
                end=min(start+count,spec['frames'])
                block=np.empty((spec['height'],spec['width'],end-start,3),dtype=np.uint8)
                for channel,shift in enumerate((16,8,0)):block[...,channel]=(packed[:,:,start:end]>>shift)&255
                payload=gzip.compress(block.tobytes(),compresslevel=6,mtime=0)
                name='pixels_'+hashlib.sha256(payload).hexdigest()[:16]+'.rgb.gz'
                (target/name).write_bytes(payload)
                chunks.append({'first_frame':start,'frames':end-start,'pixels_file':name,'layout':'pixel-time'})
                if start==0:Image.fromarray(block[:,:,0,:]).save(target/'poster.png')
                if end==spec['frames']:last_hash=hashlib.sha256(block[:,:,-1,:].tobytes()).hexdigest()
            video={**media,'chunks':chunks,'layout':'pixel-time-chunks','last_rgb_sha256':last_hash}
            for name in ('inspection.png','transition_check.png'):
                if (source/name).is_file():shutil.copy2(source/name,target/name)
            receipt.write_text(json.dumps({'source_npz_sha256':source_hash,'media':media,'video':video}))
            return video
        packed = packed.transpose(2, 0, 1).astype(np.uint32,copy=False)
        rgb = np.stack([(packed >> shift) & 255 for shift in (16, 8, 0)], axis=-1).astype(np.uint8)
    # Pixel/time-major layout compresses stationary pixels across time, even
    # when a whole RGB frame exceeds gzip's 32KB spatial history window.
    payload = gzip.compress(rgb.transpose(1, 2, 0, 3).tobytes(), compresslevel=6, mtime=0)
    filename = "pixels_" + hashlib.sha256(payload).hexdigest()[:16] + ".rgb.gz"
    (target / filename).write_bytes(payload)
    Image.fromarray(rgb[0]).save(target / "poster.png")
    for name in ("inspection.png", "transition_check.png"):
        if (source / name).is_file():
            shutil.copy2(source / name, target / name)
    video = {**media, "pixels_file": filename, "layout": "pixel-time", "last_rgb_sha256": hashlib.sha256(rgb[-1].tobytes()).hexdigest()}
    receipt.write_text(json.dumps({'source_npz_sha256':source_hash, 'media':media, 'video':video}))
    return video


def case_render_fingerprint(run):
    paths = [run / "run_manifest.json", run / "media_contract.json", run / "workspace/pixels.npz",
             run / "workspace/generate.py", run / "workspace/inspection.png",
             run / "workspace/transition_check.png", run / "logs/events.jsonl"]
    paths += sorted((run / "trace").glob("round_*/snapshot.json"))
    stamp = []
    for path in paths:
        if path.is_file():
            stat = path.stat()
            stamp.append((str(path.relative_to(run)), stat.st_mtime_ns, stat.st_size))
    return hashlib.sha256(json.dumps([2, stamp]).encode()).hexdigest()


def case_page_is_current(run, output):
    try:
        saved = json.loads((output / "render_receipt.json").read_text())
        return ((output / "index.html").is_file()
                and saved.get("fingerprint") == case_render_fingerprint(run))
    except (OSError, ValueError):
        return False


def failure_summary(run, manifest):
    validation = manifest.get("validation") or {}
    usage = manifest.get("token_usage") or {}
    budget = manifest.get("token_budget") or {}
    events_path = run / "logs/events.jsonl"
    terminal = []
    messages = []
    if events_path.is_file():
        for line in events_path.read_text(errors="replace").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            typ = event.get("type")
            if typ in ("turn.failed", "turn.cancelled", "turn.completed", "error"):
                terminal.append(typ)
            err = event.get("error") or {}
            message = event.get("message") or err.get("message")
            if message:
                messages.append(str(message))
    missing = validation.get("missing_required") or []
    reasons = []
    if messages:
        reasons.append(messages[-1])
    if missing:
        reasons.append("missing required artifacts: " + ", ".join(map(str, missing[:8])))
    if validation.get("infra_error"):
        reasons.append("infra error: " + str(validation["infra_error"]))
    if validation.get("budget_error"):
        reasons.append(str(validation["budget_error"]))
    if manifest.get("stop_reason"):
        reasons.append("stop reason: " + str(manifest["stop_reason"]))
    if budget.get("exhausted"):
        reasons.append("output token budget exhausted")
    if not reasons:
        reasons.append("validation did not pass")
    fields = [
        ("exit status", manifest.get("exit_status")),
        ("terminal events", ", ".join(terminal[-4:]) if terminal else None),
        ("duration", f'{manifest.get("duration_seconds", 0):.0f}s' if manifest.get("duration_seconds") is not None else None),
        ("output tokens", usage.get("output_tokens") or usage.get("reported_completed_request_output_tokens")),
        ("usage status", usage.get("status")),
        ("generate runs", validation.get("generate_runs")),
        ("saved frames", validation.get("frames")),
        ("candidate snapshots", len(list((run / "trace").glob("round_*")))),
    ]
    return {
        "reason": "；".join(str(x) for x in reasons if x),
        "fields": [(name, value) for name, value in fields if value not in (None, "")],
        "missing": missing,
        "messages": messages[-5:],
    }


def build_case(run, output):
    fingerprint = case_render_fingerprint(run)
    manifest = json.loads((run / "run_manifest.json").read_text())
    spec = json.loads((run / "media_contract.json").read_text())
    ws = run / "workspace"
    output.mkdir(parents=True, exist_ok=True)
    prompt = (run / "input_snapshot/prompt.txt").read_text()
    title = f'{manifest["model"]} · {manifest["case_id"]}'
    usage = manifest.get("token_usage") or {}
    count = usage.get("output_tokens")
    if count is None:
        count = usage.get("reported_completed_request_output_tokens")
    body = f'<a class=back href="../../../../index.html">← 本轮 smoke 总览</a><h1>{html.escape(title)}</h1>'
    body += (f'<div class=case-meta><span class=badge>{manifest["track"]}</span>'
             f'<span class=pill>{spec["width"]}×{spec["height"]}</span><span class=pill>{spec["fps"]} FPS · {spec["frames"]} 帧</span>'
             f'<span class=pill>{html.escape(manifest["status"])}</span></div>')
    failure = None
    if manifest.get("status") != "complete" or manifest.get("validation", {}).get("pass") is not True:
        failure = failure_summary(run, manifest)
        body += '<section class="card" id="failure"><h2>失败诊断</h2>'
        body += f'<p class=desc>{html.escape(failure["reason"])}</p>'
        if failure["fields"]:
            body += '<div class=facts>' + ''.join(
                f'<div><strong>{html.escape(str(value))}</strong>{html.escape(name)}</div>'
                for name, value in failure["fields"]
            ) + '</div>'
        if failure["missing"]:
            body += '<p class=note>缺失产物：' + html.escape(", ".join(map(str, failure["missing"]))) + '</p>'
        if failure["messages"]:
            body += '<details open><summary>终止/错误消息</summary><pre>' + html.escape("\n".join(failure["messages"])) + '</pre></details>'
        body += '</section>'
    video = export_pixels(ws, output / "final", spec)
    if video:
        body += '<div class=case-layout id=video><div>'+player(video_paths(video,'final'))+'</div>'
        task_label = {'t2v':'文本生成','i2v':'首帧续写','v2v':'视频续写','video_edit':'视频编辑'}.get(spec.get('task_type'),'视频生成')
        body += (f'<aside class=card><span class=badge>{task_label}</span><h3 style="margin-top:14px">原始任务</h3>'
                 f'<p>{html.escape(prompt)}</p><div class=facts><div><strong>{spec["frames"]/spec["fps"]:.2f}s</strong>视频时长</div>'
                 f'<div><strong>{count if count is not None else "—"}</strong>输出 tokens</div></div>'
                 '<p class=tiny>下方可播放每次保存的候选，查看检查图与代码变化。</p></aside></div>')
        if manifest["status"] != "complete":
            body += '<p class=muted>此结果可播放，但该运行尚未通过最终提交审核。页面展示不代表评测通过。</p>'
    else:
        body += f'<div class=box id=video><h3>尚未保存可播放视频</h3><p class=desc>{html.escape(prompt)}</p><span class=pill>{html.escape(manifest["status"])}</span></div>'
    if spec.get('task_type')=='video_edit':
        source = run/'input_snapshot/source_video.mp4'
        if source.is_file():
            shutil.copy2(source,output/'source_video.mp4')
            body += '<div class=card><h2>编辑前的完整原视频</h2><video controls preload=metadata src="source_video.mp4" style="width:100%;max-height:480px"></video><p class=note>上方为编辑结果；原视频是模型获准使用的输入。下方为逐轮保存的编辑候选。</p></div>'
    rounds = sorted((run / "trace").glob("round_*"))
    rounds += [p for recovery in sorted(run.glob('recovery_*')) for p in sorted((recovery/'trace').glob('round_*'))]
    body += ('<div class=section-head id=candidates><h2>逐轮保存的候选</h2><p>回放视频、检查图与代码变化。</p></div>'
             '<p class=note>每份候选均可单独播放。实际图片检查记录在下方工具轨迹中。</p>')
    previous = ""
    valid_rounds = 0
    for i, source in enumerate(rounds):
        data = export_pixels(source, output / f"candidate_{i:02d}", spec)
        if not data:
            continue
        valid_rounds += 1
        stamp = ""
        if (source / "snapshot.json").exists():
            stamp = json.loads((source / "snapshot.json").read_text()).get("utc", "")
        code = (source / "generate.py").read_text() if (source / "generate.py").exists() else ""
        diff = "".join(difflib.unified_diff(previous.splitlines(True), code.splitlines(True),
                                          fromfile="上一保存版本", tofile="本次保存版本"))
        previous = code
        prefix = f"candidate_{i:02d}"
        body += (f'<details class=candidate{" open" if i==0 else ""}><summary><strong>候选 {i+1:02d}</strong><span class=status>播放与检查图</span><time>{html.escape(stamp)}</time></summary><div class=candidate-content>'
                 + player(video_paths(data,prefix)))
        body += '<div class=checks>'
        for name in ("inspection.png", "transition_check.png"):
            if (output / prefix / name).exists():
                label = '时间点检查图' if name=='inspection.png' else '首帧与过渡检查'
                body += f'<figure><a href="{prefix}/{name}" target=_blank><img loading=lazy src="{prefix}/{name}"></a><figcaption>{label} · 点击查看原图</figcaption></figure>'
        body += f'</div><details class=code><summary>展开代码变化</summary><pre>{html.escape(diff or "代码未变化；重新保存了产物。")}</pre></details></div></details>'
    body += '<div class=section-head id=trace><h2>可观测工具轨迹</h2><p>实际执行的命令与返回图片。</p></div>'
    files = [run / "logs/events.jsonl"]+[recovery/'logs/events.jsonl' for recovery in sorted(run.glob('recovery_*'))]
    commands = images = 0
    seen_calls = set()
    terminal_events = []
    for path in files:
        if not path.is_file():
            continue
        for line in path.read_text().splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            item = event.get("item", {})
            if event.get("type") in ("thread.started", "turn.started", "turn.failed", "turn.completed", "turn.cancelled", "error"):
                message = event.get("message") or (event.get("error") or {}).get("message") or ""
                terminal_events.append({
                    "type": event.get("type"),
                    "utc": (event.get("_harness_received") or {}).get("utc"),
                    "message": message,
                })
            if event.get("type") != "item.completed":
                continue
            stamp = event.get("_harness_received", {}).get("utc", "")
            if item.get("type") == "command_execution":
                commands += 1
                command = item.get("command", "").replace(str(ws), ".")
                body += (f'<details class=command><summary><strong>命令 {commands}</strong><time>{html.escape(stamp)}</time>'
                         f'<span class=pill>exit {item.get("exit_code")}</span></summary><pre>{html.escape(command)}</pre></details>')
            if item.get("type") == "full_trace_image_return" and item.get("call_id") not in seen_calls:
                seen_calls.add(item.get("call_id"))
                for image in item.get("returned_images", []):
                    name = image.get('path')
                    if not isinstance(name, str) or image.get('available') is False:
                        continue
                    source = (path.parent / name).resolve()
                    if not source.is_relative_to(path.parent.resolve()) or not source.is_file():
                        continue
                    images += 1
                    target = output / f"tool_view_{images:02d}.png"
                    shutil.copy2(source, target)
                    body += (f'<details class=tool-image><summary>视觉工具实际返回图片 {images}</summary>'
                             f'<img loading=lazy src="{target.name}"></details>')
    body += f'<p class=muted>保存候选 {valid_rounds} 份；完成命令 {commands} 次；可验证图片返回 {images} 张。原始 API 响应与完整日志保留在本地。</p>'
    if terminal_events:
        body += '<details open><summary>运行生命周期事件</summary><pre>' + html.escape(
            "\n".join(
                f'{x.get("utc") or ""} · {x.get("type")} · {x.get("message") or ""}'
                for x in terminal_events[-20:]
            )
        ) + '</pre></details>'
    page = document(title, body, depth=4, case_page=True)
    (output / "index.html").write_text(page)
    row = {"model": manifest["model"], "model_key": manifest["model_key"], "track": manifest["track"],
            "case_id": manifest["case_id"], "status": manifest["status"], "output_tokens": count,
            "candidates": valid_rounds, "visual_returns": images, "playable": bool(video),
            "latest": manifest.get("completed_utc") or manifest["started_utc"], "spec": spec}
    (output / "render_receipt.json").write_text(json.dumps(
        {"fingerprint": fingerprint, "row": row}))
    return row


BASELINES = [
    ("Physics-IQ Verified · I2V/BPP", "Seedance 2.5", "42.43 ± 0.76 /100", "198 cases · 保留旧协议有效结果"),
    ("Physics-IQ Verified · I2V/BPP", "Wan2.2 14B", "32.20 ± 0.60 /100", "官方完整评测"),
    ("RoboJudge shared-50", "Wan2.6 Flash", "PA 3.827 · IA 4.027 · Overall 3.927 /5", "50 prompts · RoboJudge-9B"),
    ("RoboJudge shared-50", "Veo3.1 Lite", "3.580 / 3.780 / 3.680", "PA / IA / Overall"),
    ("VBench-I2V / VBench++", "Wan2.2 I2V A14B", "Total 88.16 /100", "1,118 pairs × 5 samples · 非 VBench-2.0 T2V"),
    ("WorldArena Track 1", "Veo3.1", "Image 0.6557 · Instruction 0.9714", "只比较官方 Track 1"),
    ("WBench Full", "Kling 3.0", "79.4 /100", "原始 Doubao judge；替换 judge 不可混比"),
    ("WorldScore", "UniWorld-View", "Static 85.53 · Dynamic 76.09", "团队自评公开分数"),
    ("PVBench I2V", "Seedance 2.5", "GS 50.3 · MFS 43.4 · KP 54.4 · MC 29.0", "全量数据/评测资源未确认公开"),
]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    root, output = args.root.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    for path in sorted((root / "generations").glob("*/*/*/case*/run_manifest.json")):
        relative = path.parent.relative_to(root / "generations")
        try:
            row = build_case(path.parent, output / relative)
            row.update(benchmark=relative.parts[0], generation_model_key=row["model_key"], model_key=relative.parts[1], url=str(relative / "index.html"))
            rows.append(row)
        except (OSError, ValueError, KeyError, EOFError, zipfile.BadZipFile) as error:
            rows.append({"benchmark": relative.parts[0], "status": "export_pending", "run": str(relative),
                         "error": type(error).__name__})
    good = [r for r in rows if "model_key" in r]
    model_names = {'gpt61-sol':'GPT-6.1-Sol', 'gpt56-sol':'GPT-5.6-Sol',
                   'gpt6-astra':'GPT-6-Astra', 'deepseek-v41':'DeepSeek-V4.1-Flash',
                   'seed21-pro':'Seed-2.1-Pro-0915'}
    bench_names = {'physics_iq':'Physics-IQ', 'vbench_i2v':'VBench-I2V · VBench++',
                   'robojudge':'RoboJudge', 'worldarena':'WorldArena', 'worldscore':'WorldScore', 'wbench':'WBench',
                   'vbench2_subset_full':'VBench-2.0 subset · full',
                   'vbench2_subset_smoke':'VBench-2.0 subset · smoke',
                   'phygenbench_full':'PhyGenBench · full',
                   'phygenbench_smoke':'PhyGenBench · smoke'}
    unique = {}
    for row in good:
        key = (row['benchmark'], row['model_key'], row['track'], row['case_id'])
        if key not in unique or (unique[key]['status'] != 'complete' and row['status'] == 'complete'):
            unique[key] = row
    complete = sum(row['status']=='complete' for row in unique.values())
    example = next((r for r in good if r['benchmark']=='robojudge' and r['model_key']=='gpt61-sol'
                    and r['track']=='text' and r['status']=='complete'), None)
    body = ('<a class=back href="../index.html">← 实验导航</a><h1>视频生成与模型对照</h1>'
            '<p class=muted>从首帧续写视频，比较不同模型与输入条件，查看每轮候选和实际工具记录。</p>'
            '<div class=experiment-grid><article class="card feature"><span class=badge>当前批次 · I2V</span>'
            '<h3>多模型像素视频生成</h3><p class=desc>按 benchmark 切换，进入每个模型的 Text 与 Vision-Agent 视频画廊。</p>'
            f'<div class=facts><div><strong>4</strong>模型</div><div><strong>2</strong>Tracks</div><div><strong>{complete}</strong>有效交付</div></div>'
            '<div class=actions><a class="button primary" href="#models">查看模型对照 →</a>'
            '<a class=button href="#progress">全量运行进度</a></div></article>'
            '<article class=card><span class=pill>视频 · 检查图 · 代码</span><h3 style="margin-top:14px">查看 Agent 的生成过程</h3>'
            '<p class=desc>每次保存的结果都可以播放。展开候选查看时间点检查图，以及前后代码变化。</p>'
            f'<div class=actions><a class=button href="{example["url"] if example else "#models"}">▶ 打开一个示例</a>'
            '<a class=button href="readiness.html">实验与参数方案</a></div><p class=tiny>少量样本的评分标注为 smoke；完整官方成绩单独展示。</p></article></div>')
    progress = ''
    for bench, label in [('physics_iq', 'Physics-IQ'), ('vbench_i2v', 'VBench-I2V')]:
        status_path = root/'generations'/bench/'status.json'
        if not status_path.exists():
            continue
        status = json.loads(status_path.read_text())
        counts = status.get('totals', {})
        progress += f'<details class=report><summary>{label} <span class=status>· {counts.get("complete",0)} 有效交付 · {counts.get("running",0)} 运行中</span></summary><p>状态更新 UTC：{html.escape(status.get("updated_utc", "未知"))}。生成进度不代表完整官方评分。</p><div class=scroll><table><tr><th>模型 / Track</th><th>完成 / 总数</th><th>运行中</th><th>预算或尝试耗尽</th><th>最新完成 UTC / Case</th></tr>'
        for key, group in status.get('groups', {}).items():
            counts = group.get('counts', {})
            latest = group.get('latest_completion') or ['—', '—']
            total = sum(counts.values())
            display_key = model_names.get(group.get('model_key'), key.split('/')[0])+' / '+group.get('track',key.split('/')[-1])
            progress += (f'<tr><td>{html.escape(display_key)}</td><td>{counts.get("complete", 0)} / {total}</td>'
                     f'<td>{counts.get("running", 0)}</td><td>{counts.get("exhausted", 0)}</td>'
                     f'<td>{html.escape(str(latest[0]))}<br>{html.escape(str(latest[1]))}</td></tr>')
        progress += '</table></div></details>'
    benchmarks = sorted({r['benchmark'] for r in good}, key=lambda x:(x!='robojudge',x))
    body += '<div class=section-head id=models><h2>模型与 Track 对照</h2><p>行是模型，列是输入条件。点击进入整组视频。</p></div><div class=tabs role=tablist aria-label="Benchmark">'
    for i,benchmark in enumerate(benchmarks):
        body += f'<button role=tab aria-selected={str(i==0).lower()} data-panel="panel-{benchmark}">{html.escape(bench_names.get(benchmark,benchmark))}</button>'
    body += '</div>'
    for i,benchmark in enumerate(benchmarks):
        body += f'<section class=benchmark-panel id="panel-{benchmark}"{ " hidden" if i else ""}><h3>{html.escape(bench_names.get(benchmark,benchmark))}</h3><div class=scroll><table class=matrix><tr><th>模型</th><th>Text</th><th>Vision-Agent</th></tr>'
        preferred_models = ["gpt61-sol", "gpt56-sol", "gpt6-astra", "deepseek-v41", "seed21-pro"]
        present_models = sorted({r["model_key"] for r in good if r["benchmark"] == benchmark})
        models = [model for model in preferred_models if model in present_models]
        models += [model for model in present_models if model not in models]
        for model in models:
            label = model_names.get(model, model)
            body += f'<tr><th>{html.escape(label)}</th>'
            for track in ("text", "vision-agent"):
                entries = [r for r in good if (r["benchmark"], r["model_key"], r["track"]) == (benchmark, model, track)]
                cell = "本轮尚未启动"
                if entries:
                    # One compact cell per model/track; case browsing belongs
                    # in its own gallery rather than hundreds of links here.
                    cases = {}
                    for entry in entries:
                        current = cases.get(entry['case_id'])
                        if current is None or (current['status'] != 'complete' and entry['status'] == 'complete'):
                            cases[entry['case_id']] = entry
                    completed = sum(e['status'] == 'complete' for e in cases.values())
                    gallery_url = f'{benchmark}/{model}/{track}/index.html'
                    cell = f'<a href="{gallery_url}">打开本组全部生成 →</a><br><span class=status>{completed} 已完成 · {len(cases)} 已有记录</span>'
                    cards = []
                    for entry in sorted(cases.values(), key=lambda e: e['case_id']):
                        case_dir = Path(entry['url']).parent.name
                        poster = f'{case_dir}/final/poster.png'
                        picture = f'<img loading=lazy src="{poster}" alt="{entry["case_id"]}">' if entry['playable'] else '<div class=placeholder>尚无可播放结果</div>'
                        attempts = [e for e in entries if e['case_id']==entry['case_id']]
                        history = ('<details class=attempts><summary>查看全部 '+str(len(attempts))+' 次运行记录</summary>'+
                                   ''.join(f'<a href="{Path(e["url"]).parent.name}/index.html">{Path(e["url"]).parent.name.rsplit("attempt_",1)[-1]} · {html.escape(e["status"])} · {e["candidates"]} 保存候选</a>' for e in attempts)+'</details>') if len(attempts)>1 else ''
                        cards.append(f'<article class=sample><a href="{case_dir}/index.html">{picture}<div class=sample-body><span class=pill>{entry["status"]}</span><h3>{entry["case_id"]} ↗</h3><p>{entry["candidates"]} 保存候选 · {entry["output_tokens"] if entry["output_tokens"] is not None else "—"} 输出 tokens</p></div></a>{history}</article>')
                    gallery = output / benchmark / model / track / 'index.html'
                    gallery.parent.mkdir(parents=True, exist_ok=True)
                    gallery.write_text(document(f'{label} / {track}',
                        '<a class=back href="../../../index.html#models">← 模型对照</a>'
                        f'<h1>{bench_names.get(benchmark,benchmark)} · {label}</h1><div class=case-meta><span class=badge>{track}</span><span class=pill>{completed} 有效交付</span><span class=pill>{len(cases)} 个任务已有记录</span></div><p class=desc>点击样本查看视频、逐轮候选和实际工具记录。</p><div class=video-grid>'
                        + ''.join(cards) + '</div>',depth=3))
                elif benchmark == 'physics_iq' and model in ('gpt61-sol', 'gpt56-sol'):
                    slug = 'gpt-6-1' if model == 'gpt61-sol' else 'gpt-5-6'
                    cell = f'<a href="../matrix_{slug}-{track}.html">已有全量 198/198 →</a><br><span class=status>复用旧协议；不重复生成</span>'
                body += f'<td>{cell}</td>'
            body += '</tr>'
        body += '</table></div></section>'
    body += '<h2 id=progress>全量运行进度</h2>'+progress
    body += '<h2 id=evaluation>评分与评测状态</h2><details class=report><summary>展开原版评测结果与运行阶段</summary><div class=scroll><table><tr><th>评测</th><th>本轮状态</th><th>范围与数值</th></tr>'
    physics = root / 'evaluation/physics_deepseek_per_view/per_view_metrics.json'
    if physics.exists():
        d = json.loads(physics.read_text())['metrics']
        values = ' / '.join(f'{d[k]:.4f}' for k in ('weighted_spatial_iou_v1_perspective-center', 'weighted_spatial_iou_v2_perspective-center'))
        body += f'<tr><td>Physics-IQ</td><td>官方函数 smoke 已通过</td><td>单 view；weighted spatial IoU v1/v2 {values}，不是 Verified 总分</td></tr>'
    physics_scheduler = root/'evaluation/physics_full_scheduler/scheduler.json'
    if physics_scheduler.exists():
        report = json.loads(physics_scheduler.read_text())
        for key, entry in report.get('cohorts', {}).items():
            score = entry.get('score', {})
            result = (f'完整198-case Verified {physics_verified_display(score["verified_score"])} /100；单轮，非组织者发布'
                      if entry.get('official_full_score') and 'verified_score' in score else
                      f'{entry.get("accepted_cases", 0)} /198 有效；{entry.get("exhausted_cases", 0)} 预算/尝试耗尽；未计算完整分数')
            body += (f'<tr><td>Physics-IQ · {html.escape(key)}</td><td>{html.escape(entry.get("phase", "未知"))}</td>'
                     f'<td>{result}</td></tr>')
    vbench = root / 'evaluation/vbench_subject_smoke/pixelworld_eval_results.json'
    if vbench.exists():
        d = json.loads(vbench.read_text())
        body += f'<tr><td>VBench-I2V</td><td>官方 i2v_subject 已评分</td><td>1 pair × 5 独立样本；原始 i2v_subject {d["i2v_subject"][0]:.4f}，不是全量 Total</td></tr>'
    else:
        body += '<tr><td>VBench-I2V</td><td>生成 / 评分准备中</td><td>须齐备五份独立样本</td></tr>'
    quality = root / 'evaluation/vbench_quality_smoke/pixelworld_eval_results.json'
    if quality.exists():
        d = json.loads(quality.read_text())
        values = ' · '.join(f'{html.escape(k)} {v[0]:.4f}' for k, v in d.items())
        body += f'<tr><td>VBench 补充维度</td><td>官方函数已评分</td><td>同一 pair 的五份样本；原始值：{values}</td></tr>'
    model_names = {'gpt61-sol':'GPT-6.1-Sol', 'gpt56-sol':'GPT-5.6-Sol',
                   'gpt6-astra':'GPT-6-Astra', 'deepseek-v41':'DeepSeek-V4.1-Flash'}
    single_case_scores = {}
    for model, label in model_names.items():
        for track, pattern in (
            ('text', f'robojudge_{model}_text_gpu_smoke*/summary.json'),
            ('vision-agent', f'robojudge_{model}_gpu_smoke*/summary.json'),
        ):
            summaries = sorted((root/'evaluation').glob(pattern))
            scored = []
            for path in summaries:
                record = json.loads(path.read_text())
                if record.get('valid_paired_count'):
                    scored.append(record)
            if scored:
                record = scored[0]
                values = record.get('shared50_means') or record.get('partial_paired_means')
                scope = 'shared50 完整均分' if record.get('complete_shared50') else '单例/部分 smoke；不是 shared50 均分'
                case_ids = ', '.join(str(item['case_id']) for item in record.get('items', [])
                                     if 'case_id' in item)
                if record['valid_paired_count']==1 and case_ids=='common50_0001':
                    single_case_scores[(model,track)] = values
                body += (f'<tr><td>RoboJudge · {html.escape(label)} / {track}</td><td>原始 9B judge 已评分</td>'
                         f'<td>{scope}；n={record["valid_paired_count"]}；'
                         f'PA {values["PA"]:.2f} / IA {values["IA"]:.2f}（1–5）'
                         f'<br>Cases：{html.escape(case_ids)}</td></tr>')
    if single_case_scores:
        summary = '<h3>RoboJudge · 同一示例的评分</h3><p class=desc>common50_0001 · 原始 9B judge · 单例 smoke，非 shared50 全量均分。</p><div class=scroll><table class=matrix><tr><th>模型</th><th>Text · PA / IA</th><th>Vision-Agent · PA / IA</th></tr>'
        for model,label in model_names.items():
            summary += f'<tr><th>{html.escape(label)}</th>'
            for track in ('text','vision-agent'):
                value = single_case_scores.get((model,track))
                summary += f'<td>{value["PA"]:.0f} / {value["IA"]:.0f}</td>' if value else '<td class=muted>—</td>'
            summary += '</tr>'
        summary += '</table></div>'
        body = body.replace('<h2 id=evaluation>评分与评测状态</h2>', '<h2 id=evaluation>评分与评测状态</h2>'+summary)
    worldscore = root/'evaluation/worldscore_scheduler.json'
    if worldscore.exists():
        record = json.loads(worldscore.read_text())
        errors = record.get('reported_metric_errors', [])
        # Old scheduler outputs may predate explicit error reporting. The
        # original scorer catches exceptions and writes finite penalty values.
        log = root/'evaluation/worldscore_case80_original_metrics/stdout.log'
        if not errors and log.exists():
            errors = [line for line in log.read_text(errors='replace').splitlines()
                      if line.startswith('Error in ')]
        state = '部分指标有执行异常；原始默认惩罚值保留' if errors else str(record.get('status','评分准备中'))
        body += (f'<tr><td>WorldScore · Case80 /256×144</td><td>{html.escape(state)}</td>'
                 '<td>三段、148帧；原始逐指标结果；无全量 Total。原生512×288 的结果在下方单列。</td></tr>')
        if record.get('raw_metrics'):
            content = '<table><tr><th>Metric</th><th>Raw</th><th>Normalized</th></tr>'
            for aspect, metrics in record['raw_metrics'].items():
                for name, item in metrics.items():
                    raw = html.escape(json.dumps(item.get('score'),ensure_ascii=False))
                    value = item.get('score_normalized')
                    normal = f'{value:.4f}' if isinstance(value,(int,float)) else str(value)
                    suffix = ' · 原始异常默认值' if name == 'optical_flow_aepe' and errors else ''
                    content += f'<tr><td>{html.escape(aspect+"/"+name+suffix)}</td><td>{raw}</td><td>{normal}</td></tr>'
            (output/'worldscore_metrics.html').write_text(document('WorldScore Case80 metric smoke',
                '<a href="index.html">← 总览</a><h1>WorldScore Case80 · 原始逐指标结果</h1>'
                '<p>256×144 原生生成。光流发生尺寸异常，100是官方 scorer 的默认惩罚值；没有成功计算该项。其余原始结果保留，不合成全量 Total。</p>'
                '<p><a href="worldscore_case80_complete/index.html">▶ 播放完整三段 RGB</a></p>'+content+'</table>'))
            body += '<tr><td>WorldScore 详细结果</td><td>原始数值与异常分开</td><td><a href="worldscore_metrics.html">查看逐指标数值与完整播放 →</a></td></tr>'
    for benchmark, label in [('worldarena', 'WorldArena'), ('other_bench_protocols', 'WBench / 其他资源')]:
        report = root / 'infrastructure' / benchmark / 'setup_status.json'
        state = '适配与资源检查中'
        if report.exists():
            info = json.loads(report.read_text())
            state = str(info.get('status') or info.get('overall_status') or '详见官方适配报告')
        body += f'<tr><td>{label}</td><td>{html.escape(state)}</td><td>未完成全量官方评分；不填造分数</td></tr>'
    native512 = root/'evaluation/worldscore_512_scheduler.json'
    if native512.exists():
        record = json.loads(native512.read_text())
        state = record.get('status','准备中')
        passed = state == 'complete_native512_case_metric_smoke'
        body += (f'<tr><td>WorldScore · 原生512×288</td><td>{"八项原始指标 smoke 通过" if passed else html.escape(state)}</td>'
                 '<td>完整三段148帧 /14.8秒；不是2000-case全量分。'
                 '<a href="worldscore_case80_512_complete/index.html">▶ 原生512完整播放 →</a></td></tr>')
        if record.get('raw_metrics'):
            content = '<table><tr><th>Metric</th><th>Raw</th><th>Normalized</th></tr>'
            for aspect, metrics in record['raw_metrics'].items():
                for name,item in metrics.items():
                    content += ('<tr><td>'+html.escape(aspect+'/'+name)+'</td><td>'
                                +html.escape(json.dumps(item.get('score')))+ '</td><td>'
                                +html.escape(str(item.get('score_normalized')))+ '</td></tr>')
            (output/'worldscore_512_metrics.html').write_text(document('WorldScore native512 metric smoke',
                '<a href="index.html">← 总览</a><h1>WorldScore Case80 · 原生512×288</h1>'
                '<p>三个独立生成片段顺序衔接；八项原始函数已运行。单例结果不合成全量Total。</p>'
                '<p><a href="worldscore_case80_512_complete/index.html">▶ 完整RGB播放与逐段trace</a></p>'+content+'</table>'))
            body += '<tr><td>WorldScore512逐指标</td><td>原始数值与范围明确</td><td><a href="worldscore_512_metrics.html">查看原始八项结果 →</a></td></tr>'
    body += '</table></div></details><p class=desc><a href="protocol.html">主实验参数与 FPS／分辨率消融方案 →</a> · <a href="baseline_audit.html">公开模型分数与比较条件 →</a></p>'
    cohort_scores = []
    for path in sorted((root/'evaluation').glob('vbench_matrix_*_0872/pixelworld_eval_results.json')):
        provenance = path.parent/'evaluation_provenance.json'
        if not provenance.exists() or json.loads(provenance.read_text()).get('status') != 'complete':
            continue
        name = path.parent.name.removeprefix('vbench_matrix_').removesuffix('_0872')
        metrics = json.loads(path.read_text())
        cohort_scores.append('<tr><td>'+html.escape(name)+'</td>' + ''.join(
            f'<td>{metrics[key][0]:.4f}</td>' for key in
            ('i2v_subject','subject_consistency','motion_smoothness','dynamic_degree','aesthetic_quality','imaging_quality'))+'</tr>')
    if cohort_scores:
        body += ('<details class=report><summary>VBench-I2V · 五样本 smoke 对比</summary><p>同一官方 pair872，每组五个独立完成的会话。只展示适用维度原始均值，不计算全量Total或排行榜排名。</p>'
                 '<div class=scroll><table><tr><th>Model / Track</th><th>I2V subject</th><th>Subject consistency</th>'
                 '<th>Motion smoothness</th><th>Dynamic degree</th><th>Aesthetic</th><th>Imaging</th></tr>'
                 +''.join(cohort_scores)+'</table></div></details>')
    scheduler = root/'evaluation/vbench_full_scheduler/scheduler.json'
    if scheduler.exists():
        data = json.loads(scheduler.read_text())
        body += ('<details class=report><summary>VBench-I2V · 完整评测交接</summary><p>每组齐备1118×5独立有效结果后自动导出并运行原始评测。缺失样本会阻止完整评分。</p>'
                 '<div class=scroll><table><tr><th>模型 / Track</th><th>有效样本</th><th>阶段</th><th>完整官方 Total</th></tr>')
        for key, entry in data.get('cohorts', {}).items():
            aggregate = entry.get('aggregate', {})
            total = f'{aggregate["total_score"]:.2f}' if entry.get('official_full_score') and 'total_score' in aggregate else '—'
            body += (f'<tr><td>{html.escape(key)}</td><td>{entry.get("accepted_samples", 0)} / {entry.get("expected_samples", 5590)}</td>'
                     f'<td>{html.escape(entry.get("phase", "未知"))}</td><td>{total}</td></tr>')
        body += '</table></div></details>'
    if (output/'worldscore_case80_complete/index.html').exists():
        body += '<p><a href="worldscore_case80_complete/index.html">▶ WorldScore Case 80：三段合并完整播放</a></p>'
    body += '<h2>公开模型参考</h2><details class=report><summary>展开已调查的公开 baseline</summary><p>直接引用公开分数；各模型的比较条件单独标注。</p><div class=scroll><table><tr><th>官方 setting</th><th>模型</th><th>公开分数</th><th>比较条件</th></tr>'
    for row in BASELINES:
        body += '<tr>' + ''.join(f'<td>{html.escape(cell)}</td>' for cell in row) + '</tr>'
    body += ('</table></div></details><p class=desc><a href="https://github.com/SiyuanMaCS/PixelWorld">PixelWorld 代码库</a> · '
             '<a href="https://github.com/google-deepmind/physics-IQ-benchmark#physics-iq-verified-leaderboard">Physics-IQ 官方榜</a> · '
             '<a href="https://huggingface.co/spaces/Vchitect/VBench_Leaderboard">VBench 官方榜</a></p>')
    latest = max((r["latest"] for r in good), default="")
    body += f'<p class=muted>最近一条运行记录：{html.escape(latest)}。生成中间保存历史属于外部记录；不向 agent 提供评测反馈。</p>'
    (output / "index.html").write_text(document("PixelWorld Codex smoke", body))
    (output / "status.json").write_text(json.dumps({"runs": rows, "latest_run": latest}, indent=2))
    # These merged sequence pages are built separately from per-case exports.
    # Retheme their existing player and links without changing pixel artifacts.
    for name in ('worldscore_case80_complete','worldscore_case80_512_complete'):
        page = output/name/'index.html'
        if not page.is_file():
            continue
        saved = page.read_text()
        if saved.split('<style>',1)[-1].split('</style>',1)[0] == CSS:
            continue
        if '<main>' in saved:
            content = saved.split('<main>',1)[1].split('</main>',1)[0].split('<footer>',1)[0]
            title = html.unescape(saved.split('<title>',1)[1].split('</title>',1)[0])
            page.write_text(document(title,content,depth=1))
    print(json.dumps({"runs": len(rows), "complete": sum(r["status"] == "complete" for r in rows),
                      "playable": sum(r.get("playable", False) for r in rows), "output": str(output)}))


if __name__ == "__main__":
    main()
