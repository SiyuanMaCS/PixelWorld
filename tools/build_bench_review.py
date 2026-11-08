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


CSS = """
:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:#10151b;color:#e6edf3;font:15px/1.65 system-ui,sans-serif}main{max-width:1180px;margin:auto;padding:28px 22px}a{color:#a7d6ff}h1{font-size:29px}h2{font-size:22px}p{max-width:900px}.muted{color:#9bacbe}.box,details{background:#19212b;border:1px solid #354151;border-radius:10px;padding:18px;margin:18px 0}table{border-collapse:collapse;width:100%;margin:15px 0}th,td{text-align:left;padding:13px;border:1px solid #354151;vertical-align:top}th{background:#213044}.scroll{overflow:auto}img{max-width:100%;object-fit:contain}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:12px/1.5 ui-monospace,monospace;max-height:600px;overflow:auto}.player{max-width:850px}canvas{width:100%;height:auto;background:#070b10;image-rendering:pixelated;border:1px solid #354151}.controls{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:12px 0}button,select{background:#26394c;color:white;border:1px solid #657789;border-radius:6px;padding:9px;cursor:pointer}input[type=range]{flex:1;min-width:150px}.strip{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}.step{border-left:3px solid #78b894;padding-left:15px;margin:22px 0}.badge{color:#bbedac}.status{font-size:12px;color:#b5c6d7}.pill{display:inline-block;padding:2px 8px;background:#293645;border-radius:5px}.back{display:inline-block;margin-bottom:20px}@media(max-width:600px){main{padding:15px}td,th{padding:8px;font-size:12px}}
"""

PLAYER = """
class PixelPlayer{
 constructor(node,d){this.node=node;this.d=d;this.frames=null;this.frame=0;this.playing=false;this.epoch=0;this.ctx=node.querySelector('canvas').getContext('2d');this.ctx.canvas.width=d.width;this.ctx.canvas.height=d.height;this.seek=node.querySelector('.seek');this.seek.max=d.frames-1;this.note=node.querySelector('.status');node.querySelector('.play').onclick=()=>this.toggle();node.querySelector('.replay').onclick=async()=>{await this.load();this.frame=0;this.start()};this.seek.oninput=async()=>{await this.load();this.frame=+this.seek.value;this.draw();if(this.playing)this.epoch=performance.now()-this.frame*1000/this.d.fps};this.preview=new Image();this.preview.onload=()=>{if(!this.frames)this.ctx.drawImage(this.preview,0,0,d.width,d.height)};this.preview.src=d.poster;}
 async load(){if(this.frames)return;if(this.loading)return this.loading;this.note.textContent='载入像素…';this.loading=(async()=>{try{let r=await fetch(this.d.pixels);if(!r.ok)throw Error('HTTP '+r.status);let decoded=r.body.pipeThrough(new DecompressionStream('gzip'));this.frames=new Uint8Array(await new Response(decoded).arrayBuffer());if(this.frames.length!==this.d.width*this.d.height*this.d.frames*3)throw Error('RGB 长度不匹配');this.draw()}catch(e){this.note.textContent='载入失败：'+e.message;this.loading=null;throw e}})();return this.loading}
 draw(){let n=this.d.width*this.d.height,rgba=new Uint8ClampedArray(n*4);for(let i=0;i<n;i++){let o=this.d.layout==='pixel-time'?(i*this.d.frames+this.frame)*3:(this.frame*n+i)*3;rgba[4*i]=this.frames[o];rgba[4*i+1]=this.frames[o+1];rgba[4*i+2]=this.frames[o+2];rgba[4*i+3]=255}this.ctx.putImageData(new ImageData(rgba,this.d.width,this.d.height),0,0);this.seek.value=this.frame;this.note.textContent=(this.frame/this.d.fps).toFixed(2)+' / '+(this.d.frames/this.d.fps).toFixed(2)+' s · '+(this.frame+1)+'/'+this.d.frames;}
 start(){this.playing=true;this.epoch=performance.now()-this.frame*1000/this.d.fps;this.node.querySelector('.play').textContent='Ⅱ 暂停';let tick=now=>{if(!this.playing)return;this.frame=Math.min(this.d.frames-1,Math.floor((now-this.epoch)*this.d.fps/1000));this.draw();if(now-this.epoch>=this.d.frames*1000/this.d.fps){this.pause();return}requestAnimationFrame(tick)};requestAnimationFrame(tick)}
 pause(){this.playing=false;this.node.querySelector('.play').textContent='▶ 播放'}
 async toggle(){try{await this.load();if(this.playing)this.pause();else{if(this.frame>=this.d.frames-1)this.frame=0;this.start()}}catch(e){}}
}
window.__benchPlayers=[];document.querySelectorAll('.player').forEach(n=>window.__benchPlayers.push(new PixelPlayer(n,JSON.parse(n.dataset.video))));window.__benchReady=true;
"""


def document(title, body):
    return ("<!doctype html><html lang=zh><meta charset=utf-8>"
            "<meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>{html.escape(title)}</title><style>{CSS}</style><main>{body}</main>"
            f"<script>{PLAYER}</script></html>")


def player(data):
    return (f"<div class=player data-video='{html.escape(json.dumps(data), quote=True)}'>"
            "<canvas></canvas><div class=controls><button class=play>▶ 播放</button>"
            "<button class=replay>↻ 重播</button><input class=seek type=range min=0 step=1 value=0>"
            "</div><p class=status>点击播放 · 原生 RGB 像素</p></div>")


def export_pixels(source, target, spec):
    target.mkdir(parents=True, exist_ok=True)
    path = source / "pixels.npz"
    if not path.is_file():
        return None
    with np.load(path, allow_pickle=False) as d:
        packed = d["pixels"]
        if packed.shape != (spec["height"], spec["width"], spec["frames"]):
            return None
        packed = packed.transpose(2, 0, 1).astype(np.uint32)
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
    return {**{k: spec[k] for k in ("width", "height", "frames", "fps")}, "pixels_file": filename, "layout": "pixel-time", "last_rgb_sha256": hashlib.sha256(rgb[-1].tobytes()).hexdigest()}


def build_case(run, output):
    manifest = json.loads((run / "run_manifest.json").read_text())
    spec = json.loads((run / "media_contract.json").read_text())
    ws = run / "workspace"
    output.mkdir(parents=True, exist_ok=True)
    prompt = (run / "input_snapshot/prompt.txt").read_text()
    title = f'{manifest["model"]} · {manifest["case_id"]}'
    usage = manifest.get("token_usage") or {}
    count = usage.get("output_tokens") or usage.get("reported_completed_request_output_tokens")
    body = f'<a class=back href="../../../../index.html">← 本轮 smoke 总览</a><h1>{html.escape(title)}</h1>'
    body += (f'<p class=muted>{manifest["track"]} · {spec["width"]}×{spec["height"]} · '
             f'{spec["fps"]} FPS · {spec["frames"]} 帧 · 状态 {manifest["status"]} · 输出 tokens {count}</p>'
             f'<div class=box><strong>原始任务</strong><p>{html.escape(prompt)}</p></div>')
    video = export_pixels(ws, output / "final", spec)
    if video:
        body += '<h2>当前保存结果</h2>' + player({**video, "pixels": "final/" + video["pixels_file"], "poster": "final/poster.png"})
        if manifest["status"] != "complete":
            body += '<p class=muted>此结果可播放，但该运行尚未通过最终提交审核。页面展示不代表评测通过。</p>'
    else:
        body += '<p class=box>尚无格式正确的 RGB 视频；保留真实执行状态。</p>'
    rounds = sorted((run / "trace").glob("round_*"))
    rounds += sorted((run / "recovery_01/trace").glob("round_*"))
    body += ('<h2>已保存候选与代码修改</h2><p class=muted>这里按时间展示外部捕获的候选，'
             '每份均可单独播放。保存新版本不等于完成视觉检查；下方工具证据记录实际看过的图。</p>')
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
        body += (f'<details><summary>候选 {i+1:02d} · {html.escape(stamp)} · 点开播放与检查图</summary>'
                 + player({**data, "pixels": f"{prefix}/{data['pixels_file']}", "poster": f"{prefix}/poster.png"}))
        for name in ("inspection.png", "transition_check.png"):
            if (output / prefix / name).exists():
                body += f'<p>{name}</p><img loading=lazy src="{prefix}/{name}">'
        body += f'<details><summary>代码变化</summary><pre>{html.escape(diff or "代码未变化；重新保存了产物。")}</pre></details></details>'
    body += '<h2>可观测工具行为</h2>'
    files = [run / "logs/events.jsonl", run / "recovery_01/logs/events.jsonl"]
    commands = images = 0
    seen_calls = set()
    for path in files:
        if not path.is_file():
            continue
        for line in path.read_text().splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            item = event.get("item", {})
            if event.get("type") != "item.completed":
                continue
            stamp = event.get("_harness_received", {}).get("utc", "")
            if item.get("type") == "command_execution":
                commands += 1
                command = item.get("command", "").replace(str(ws), ".")
                body += (f'<div class=step><strong>命令 {commands} · {html.escape(stamp)}</strong>'
                         f'<pre>{html.escape(command)}</pre><span class=pill>exit {item.get("exit_code")}</span></div>')
            if item.get("type") == "full_trace_image_return" and item.get("call_id") not in seen_calls:
                seen_calls.add(item.get("call_id"))
                for image in item.get("returned_images", []):
                    source = path.parent / image["path"]
                    if not source.is_file():
                        continue
                    images += 1
                    target = output / f"tool_view_{images:02d}.png"
                    shutil.copy2(source, target)
                    body += (f'<details><summary>视觉工具实际返回图片 {images}</summary>'
                             f'<img loading=lazy src="{target.name}"></details>')
    body += f'<p class=muted>保存候选 {valid_rounds} 份；完成命令 {commands} 次；可验证图片返回 {images} 张。原始 API 响应与完整日志保留在本地。</p>'
    (output / "index.html").write_text(document(title, body))
    return {"model": manifest["model"], "model_key": manifest["model_key"], "track": manifest["track"],
            "case_id": manifest["case_id"], "status": manifest["status"], "output_tokens": count,
            "candidates": valid_rounds, "visual_returns": images, "playable": bool(video),
            "latest": manifest.get("completed_utc") or manifest["started_utc"], "spec": spec}


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
    body = ('<a class=back href="../hub.html">← PixelWorld 总入口</a><h1>Codex benchmark smoke 与官方协议</h1>'
            '<p>本轮先验证输入、原生生成、评测与可视化链路。所有下列少量样本均为 smoke，不能作为完整榜单分数。</p>')
    good = [r for r in rows if "model_key" in r]
    for benchmark in sorted({r["benchmark"] for r in good}):
        body += f'<h2>{html.escape(benchmark)}</h2><div class=scroll><table><tr><th>模型</th><th>Text</th><th>Vision-Agent</th></tr>'
        models = ["gpt61-sol", "gpt56-sol", "gpt6-astra", "deepseek-v41"]
        for model in models:
            body += f'<tr><th>{model}</th>'
            for track in ("text", "vision-agent"):
                entries = [r for r in good if (r["benchmark"], r["model_key"], r["track"]) == (benchmark, model, track)]
                cell = "本轮尚未启动"
                if entries:
                    # One compact cell per model/track; case browsing belongs
                    # in its own gallery rather than hundreds of links here.
                    cases = {}
                    for entry in entries:
                        current = cases.get(entry['case_id'])
                        if current is None or entry['status'] == 'complete':
                            cases[entry['case_id']] = entry
                    completed = sum(e['status'] == 'complete' for e in cases.values())
                    gallery_url = f'{benchmark}/{model}/{track}/index.html'
                    cell = f'<a href="{gallery_url}">打开本组全部生成 →</a><br><span class=status>{completed} 已完成 · {len(cases)} 已有记录</span>'
                    cards = []
                    for entry in sorted(cases.values(), key=lambda e: e['case_id']):
                        case_dir = Path(entry['url']).parent.name
                        poster = f'{case_dir}/final/poster.png'
                        picture = f'<img loading=lazy src="{poster}" alt="{entry["case_id"]}">' if entry['playable'] else ''
                        cards.append(f'<div class=box><a href="{case_dir}/index.html">{picture}<strong>{entry["case_id"]}</strong> · {entry["status"]}</a><p class=status>{entry["candidates"]} 候选 · {entry["output_tokens"]} output tokens</p></div>')
                    gallery = output / benchmark / model / track / 'index.html'
                    gallery.parent.mkdir(parents=True, exist_ok=True)
                    gallery.write_text(document(f'{model} / {track}',
                        '<a href="../../../index.html">← 本轮总览</a>'
                        f'<h1>{benchmark} · {model} · {track}</h1><p>{completed} 已完成 · {len(cases)} 已有记录。点击 case 查看最终视频、候选和工具 Trace。</p><div class=strip>'
                        + ''.join(cards) + '</div>'))
                elif benchmark == 'physics_iq' and model in ('gpt61-sol', 'gpt56-sol'):
                    slug = 'gpt-6-1' if model == 'gpt61-sol' else 'gpt-5-6'
                    cell = f'<a href="../matrix_{slug}-{track}.html">已有全量 198/198 →</a><br><span class=status>复用旧协议；不重复生成</span>'
                body += f'<td>{cell}</td>'
            body += '</tr>'
        body += '</table></div>'
    body += '<h2>官方评测链路状态</h2><div class=scroll><table><tr><th>评测</th><th>本轮状态</th><th>范围与数值</th></tr>'
    physics = root / 'evaluation/physics_deepseek_per_view/per_view_metrics.json'
    if physics.exists():
        d = json.loads(physics.read_text())['metrics']
        values = ' / '.join(f'{d[k]:.4f}' for k in ('weighted_spatial_iou_v1_perspective-center', 'weighted_spatial_iou_v2_perspective-center'))
        body += f'<tr><td>Physics-IQ</td><td>官方函数 smoke 已通过</td><td>单 view；weighted spatial IoU v1/v2 {values}，不是 Verified 总分</td></tr>'
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
    for model, label in model_names.items():
        summaries = sorted((root/'evaluation').glob(f'robojudge_{model}_gpu_smoke*/summary.json'))
        scored = []
        for path in summaries:
            record = json.loads(path.read_text())
            if record.get('valid_paired_count'):
                scored.append(record)
        if scored:
            record = scored[0]
            values = record.get('shared50_means') or record.get('partial_paired_means')
            scope = 'shared50 完整均分' if record.get('complete_shared50') else '单例/部分 smoke；不是 shared50 均分'
            body += (f'<tr><td>RoboJudge · {html.escape(label)}</td><td>原始 9B judge 已评分</td>'
                     f'<td>{scope}；n={record["valid_paired_count"]}；'
                     f'PA {values["PA"]:.2f} / IA {values["IA"]:.2f}（1–5）</td></tr>')
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
                 '<td>三段、148帧；原始逐指标结果；无全量 Total。512×288 新生成规格正在单独验证。</td></tr>')
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
    body += '</table></div><p><a href="protocol.html">主实验参数与 FPS／分辨率消融方案</a> · <a href="baseline_audit.html">baseline 来源与可比较条件</a></p>'
    if (output/'worldscore_case80_complete/index.html').exists():
        body += '<p><a href="worldscore_case80_complete/index.html">▶ WorldScore Case 80：三段合并完整播放</a></p>'
    body += '<h2>已调查的公开 baseline</h2><p class=muted>直接引用公开分数；未生成或重评 baseline 视频。</p><div class=scroll><table><tr><th>官方 setting</th><th>模型</th><th>公开分数</th><th>比较条件</th></tr>'
    for row in BASELINES:
        body += '<tr>' + ''.join(f'<td>{html.escape(cell)}</td>' for cell in row) + '</tr>'
    body += ('</table></div><p><a href="https://github.com/SiyuanMaCS/PixelWorld">PixelWorld 代码库</a> · '
             '<a href="https://github.com/google-deepmind/physics-IQ-benchmark#physics-iq-verified-leaderboard">Physics-IQ 官方榜</a> · '
             '<a href="https://huggingface.co/spaces/Vchitect/VBench_Leaderboard">VBench 官方榜</a></p>')
    latest = max((r["latest"] for r in good), default="")
    body += f'<p class=muted>最近一条运行记录：{html.escape(latest)}。生成中间保存历史属于外部记录；不向 agent 提供评测反馈。</p>'
    (output / "index.html").write_text(document("PixelWorld Codex smoke", body))
    (output / "status.json").write_text(json.dumps({"runs": rows, "latest_run": latest}, indent=2))
    print(json.dumps({"runs": len(rows), "complete": sum(r["status"] == "complete" for r in rows),
                      "playable": sum(r.get("playable", False) for r in rows), "output": str(output)}))


if __name__ == "__main__":
    main()
