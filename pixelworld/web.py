from __future__ import annotations

from pathlib import Path
import base64
import datetime as dt
import hashlib
import html
import io
import json
import difflib

import mistune
import numpy as np
from PIL import Image, ImageDraw

from .config import Benchmark, Model
from .constants import TRACKS
from .supervisor import case_ids, configurations, inspect, snapshot


MARKDOWN = mistune.create_markdown(escape=True, plugins=["table", "strikethrough"])
CSS = """
:root{color-scheme:dark;--bg:#0c1014;--panel:#171c22;--line:#303943;--muted:#9faab7;--green:#a5ef83;--blue:#83ccff;--orange:#ffc478}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:#f1f5f7;font:14px/1.6 system-ui,sans-serif}main{max-width:1240px;margin:auto;padding:24px 18px 70px}a{color:var(--blue);text-decoration:none}h1{font-size:clamp(30px,5vw,54px);margin:0 0 8px}.muted{color:var(--muted)}.matrix{overflow:auto;border:1px solid var(--line);border-radius:14px}.matrix table{width:100%;min-width:900px;border-collapse:collapse}.matrix th,.matrix td{border:1px solid var(--line);padding:12px;text-align:left}.matrix td a{display:block}.bar{height:6px;background:#090c0f;border-radius:9px;overflow:hidden;margin:7px 0}.bar i{display:block;height:100%;background:var(--green)}.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}.card,.box,.round{background:var(--panel);border:1px solid var(--line);border-radius:13px;overflow:hidden}.card h2{font-size:16px;padding:12px;margin:0}.screen{position:relative;background:#07090b;aspect-ratio:16/9}.screen canvas,.screen img{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;image-rendering:pixelated}.controls{display:flex;align-items:center;gap:8px;padding:10px}.controls button{background:var(--green);color:#142110;border:0;border-radius:7px;padding:8px 12px;font-weight:700}.controls input{flex:1}.meta{display:flex;justify-content:space-between;padding:0 10px 12px;color:var(--muted);font-size:11px}.stats{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin:15px 0}.stats div{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px}.stats strong{display:block;font-size:20px}.rounds{display:grid;gap:10px}.round{display:grid;grid-template-columns:360px 1fr}.round img{width:100%;height:100%;object-fit:contain;background:#080a0c}.round div{padding:12px}.claims{background:#211b12;border:1px solid #59451f;border-radius:11px;padding:14px;margin-top:14px}.evidence{color:var(--blue)}pre{overflow:auto;background:#090c0f;border:1px solid var(--line);border-radius:8px;padding:10px}@media(max-width:760px){.grid,.round{grid-template-columns:1fr}.stats{grid-template-columns:1fr 1fr}}
"""

PLAYER_JS = r"""
const W=256,H=144,N=20;function loadPlayer(root,c){let frames=null,frame=0,playing=false,timer=null,canvas=root.querySelector('canvas'),ctx=canvas.getContext('2d',{willReadFrequently:true}),poster=root.querySelector('img'),seek=root.querySelector('input'),button=root.querySelector('button');async function ensure(){if(frames)return;let r=await fetch(c.asset),blob=await r.blob(),url=URL.createObjectURL(blob),im=await new Promise((ok,no)=>{let x=new Image();x.onload=()=>ok(x);x.onerror=no;x.src=url}),scratch=document.createElement('canvas');scratch.width=W;scratch.height=H*N;let x=scratch.getContext('2d',{willReadFrequently:true});x.drawImage(im,0,0);URL.revokeObjectURL(url);let raw=x.getImageData(0,0,W,H*N).data,size=W*H*4;frames=[];for(let n=0;n<N;n++){let a=new Uint8ClampedArray(size),off=n*size,prev=n?frames[n-1]:null;for(let j=0;j<size;j+=4){a[j]=raw[off+j]^(prev?prev[j]:0);a[j+1]=raw[off+j+1]^(prev?prev[j+1]:0);a[j+2]=raw[off+j+2]^(prev?prev[j+2]:0);a[j+3]=255}frames.push(a)}}function draw(n){frame=n;seek.value=n;if(frames){let d=ctx.createImageData(W,H);d.data.set(frames[n]);ctx.putImageData(d,0,0);poster.hidden=true}}async function play(){if(playing){clearInterval(timer);playing=false;button.textContent='Play';return}await ensure();playing=true;button.textContent='Pause';timer=setInterval(()=>draw((frame+1)%N),250)}button.onclick=play;seek.oninput=async()=>{clearInterval(timer);playing=false;button.textContent='Play';await ensure();draw(+seek.value)}}
"""


def _encode_sprite(workspace: Path, output: Path) -> tuple[int, str]:
    packed = np.load(workspace / "pixels.npz")["pixels"]
    rgb = np.stack([(packed >> 16) & 255, (packed >> 8) & 255, packed & 255], axis=-1)
    rgb = rgb.astype(np.uint8).transpose(2, 0, 1, 3).copy()
    delta = rgb.copy()
    delta[1:] = np.bitwise_xor(rgb[1:], rgb[:-1])
    buffer = io.BytesIO()
    Image.fromarray(delta.reshape(20 * 144, 256, 3)).save(buffer, format="PNG", compress_level=6)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(buffer.getvalue())
    poster = io.BytesIO()
    Image.fromarray(rgb[0]).save(poster, format="WEBP", quality=90, method=6)
    return len(buffer.getvalue()), "data:image/webp;base64," + base64.b64encode(poster.getvalue()).decode()


def _round_preview(round_dir: Path, output: Path) -> None:
    if output.exists():
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    indices = (0, 1, 5, 10, 19)
    sheet = Image.new("RGB", (256 * len(indices), 166), (10, 13, 16))
    draw = ImageDraw.Draw(sheet)
    for column, index in enumerate(indices):
        sheet.paste(Image.open(round_dir / "frames" / f"{index:02d}.png").convert("RGB"), (column * 256, 22))
        draw.text((column * 256 + 6, 5), f"f{index:02d} · {index / 4:.2f}s", fill="white")
    sheet.save(output, format="WEBP", quality=82, method=6)


def _events(run: Path) -> dict:
    counts = {"commands": 0, "file_changes": 0, "view_image": 0}
    path = run / "logs" / "events.jsonl"
    lines = path.read_text(errors="replace").splitlines() if path.is_file() else []
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "item.completed":
            continue
        item = event.get("item", {})
        if item.get("type") == "command_execution":
            counts["commands"] += 1
        if item.get("type") == "file_change":
            counts["file_changes"] += len(item.get("changes") or []) or 1
        if "view_image" in " ".join(str(item.get(key, "")) for key in ("type", "name", "tool")):
            counts["view_image"] += 1
    return counts


def _trace_page(config: Benchmark, model: Model, track: str, case_id: str,
                run: Path, record: dict, output: Path, site: Path) -> None:
    workspace = run / "workspace"
    manifest = json.loads((run / "run_manifest.json").read_text())
    events = _events(run)
    round_html = []
    candidate_hashes = set()
    previous_code = []
    rounds = sorted((run / "trace").glob("round_*"))
    for index, round_dir in enumerate(rounds):
        snapshot_path = round_dir / "snapshot.json"
        snapshot_value = json.loads(snapshot_path.read_text()) if snapshot_path.is_file() else {}
        candidate_hash = snapshot_value.get('canonical_rgb_sha256') or snapshot_value.get('pixels_sha256')
        if candidate_hash:
            candidate_hashes.add(candidate_hash)
        asset = Path("assets") / model.key / track / case_id / f"round_{index:03d}.webp"
        _round_preview(round_dir, site / asset)
        code_path = round_dir / 'generate.py'
        current_code = code_path.read_text(errors='replace').splitlines() if code_path.is_file() else []
        delta = list(difflib.unified_diff(previous_code, current_code, lineterm=''))
        excerpt = '\n'.join(delta[:90]) or 'No code change in this snapshot.'
        if len(delta) > 90:
            excerpt += '\n… additional diff lines omitted …'
        previous_code = current_code
        round_html.append(f'<article class="round"><img loading="lazy" src="../../../../{asset.as_posix()}"><div><h3>Round {index:02d}</h3><p class="muted">pixels {html.escape(snapshot_value.get("pixels_sha256", "")[:16])} · code {html.escape(snapshot_value.get("generate_sha256", "")[:16])}</p><p>Actual frozen frames: 00 / 01 / 05 / 10 / 19. A frozen round is harness evidence, not proof that the model visually inspected it.</p><details><summary>Code changes</summary><pre>{html.escape(excerpt)}</pre></details></div></article>')
    validation = manifest.get("validation", {})
    prompt = html.escape((workspace / "prompt.txt").read_text().strip())
    observation = MARKDOWN((workspace / "OBSERVATION.md").read_text(errors="replace")) if (workspace / "OBSERVATION.md").is_file() else '<p>No optional observation report was written.</p>'
    method = MARKDOWN((workspace / "METHOD.md").read_text(errors="replace")) if (workspace / "METHOD.md").is_file() else '<p>No optional method report was written.</p>'
    stats = [(len(candidate_hashes), "distinct RGB candidates"), (len(rounds), "artifact snapshots"),
             (validation.get("generate_runs", 0), "generator executions"),
             (events["commands"], "commands"), (events["file_changes"], "file changes"),
             (events["view_image"], "view_image events")]
    stats_html = "".join(f"<div><strong>{value}</strong><span>{label}</span></div>" for value, label in stats)
    video_asset = "../../../../" + record["asset"]
    body = f'''<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(case_id)} trace</title><style>{CSS}</style><main><p><a href="../../../gallery_{model.key}__{track}.html">← gallery</a></p><h1>{html.escape(case_id)} · Observable generation trace</h1><p class="muted">{html.escape(model.model)} · {html.escape(track)}. Blue/manifest facts are observable; Agent-authored Markdown is shown separately as a claim.</p><div class="stats">{stats_html}</div><section class="card" id="final"><h2>Final 20-frame RGB video</h2><div class="screen"><canvas width="256" height="144"></canvas><img src="{record['poster']}"></div><div class="controls"><button>Play</button><input type="range" min="0" max="19" value="0"></div></section><section class="box" style="padding:14px;margin-top:14px"><h2>Input and validation evidence</h2><p>{prompt}</p><p class="evidence">frame00 exact: {validation.get('frame0_exact')} · PNG/tensor exact: {validation.get('png_tensor_exact')} · network commands: {len(validation.get('network_commands') or [])} · subagents: {len(validation.get('subagent_commands') or [])}</p></section><h2>Frozen candidate rounds</h2><div class="rounds">{''.join(round_html) or '<p>No intermediate candidate was frozen.</p>'}</div><section class="claims"><h2>Agent-authored OBSERVATION.md (claim)</h2>{observation}<h2>Agent-authored METHOD.md (claim)</h2>{method}</section></main><script>{PLAYER_JS}loadPlayer(document.getElementById('final'),{{asset:{json.dumps(video_asset)}}});window.__pixelTraceReady=true;</script>'''
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(body)


def _gallery(model: Model, track: str, records: list[dict], output: Path) -> None:
    payload = json.dumps(records, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    body = f'''<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(model.model)} · {track}</title><style>{CSS}</style><main><p><a href="index.html">← matrix</a></p><h1>{html.escape(model.model)} · {html.escape(track)}</h1><p class="muted">{len(records)}/198 validated cases · direct RGB · 20 frames · 4 fps · 5 seconds</p><section class="grid" id="grid"></section></main><script>{PLAYER_JS}const CASES={payload};for(const c of CASES){{let card=document.createElement('article');card.className='card';card.innerHTML=`<h2>${{c.id}} · ${{c.title}}</h2><div class="screen"><canvas width="256" height="144"></canvas><img src="${{c.poster}}"></div><div class="controls"><button>Play</button><input type="range" min="0" max="19" value="0"></div><div class="meta"><span>uint32 RGB tensor</span><a href="${{c.trace}}">generation trace →</a></div>`;grid.appendChild(card);loadPlayer(card,c)}}window.__pixelGalleryReady=true;</script>'''
    output.write_text(body)


def build(config: Benchmark, site: Path) -> dict:
    site = site.resolve()
    site.mkdir(parents=True, exist_ok=True)
    status, _ = snapshot(config)
    input_manifest = json.loads((config.inputs_root.parent / "manifest.json").read_text())
    metadata = {case["id"]: case for case in input_manifest["cases"]}
    matrix = {}
    total_records = 0
    for model, track in configurations(config):
        records = []
        for case_id in case_ids(config):
            item = inspect(config, model, track, case_id)
            if item["state"] != "complete":
                continue
            run = Path(item["run"])
            workspace = run / "workspace"
            digest = hashlib.sha256((workspace / "pixels.npz").read_bytes()).hexdigest()[:12]
            asset = Path("assets") / model.key / track / f"{case_id}-{digest}.png"
            size, poster = _encode_sprite(workspace, site / asset)
            trace = Path("traces") / model.key / track / case_id / "index.html"
            record = {"id": case_id, "title": metadata[case_id]["scenario"],
                      "asset": asset.as_posix(), "bytes": size, "poster": poster,
                      "trace": trace.as_posix()}
            _trace_page(config, model, track, case_id, run, record, site / trace, site)
            records.append(record)
        name = f"gallery_{model.key}__{track}.html"
        _gallery(model, track, records, site / name)
        matrix[(model.key, track)] = (name, len(records))
        total_records += len(records)

    rows = []
    active_tracks = [track for track in TRACKS if any(track in model.tracks for model in config.models)]
    for model in config.models:
        cells = []
        for track in active_tracks:
            if (model.key, track) not in matrix:
                cells.append("<td>N/A</td>")
                continue
            name, done = matrix[(model.key, track)]
            cells.append(f'<td><a href="{name}"><strong>{done}/198</strong><div class="bar"><i style="width:{done/198*100:.3f}%"></i></div><span>{track} →</span></a></td>')
        rows.append(f'<tr><th>{html.escape(model.model)}</th>{"".join(cells)}</tr>')
    labels = {"text": "Text", "vision-input": "Vision-Input (legacy)", "vision-agent": "Vision-Agent"}
    track_headers = "".join(f"<th>{labels[t]}</th>" for t in active_tracks)
    index = f'''<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PixelWorld matrix</title><style>{CSS}</style><main><h1>PixelWorld</h1><p class="muted">Coding agents as direct RGB pixel world models. {status['totals'].get('complete',0)}/{status['total_runs']} complete · {status['totals'].get('running',0)} active · {status['totals'].get('exhausted',0)} exhausted.</p><section class="matrix"><table><thead><tr><th>Model ↓ / Track →</th>{track_headers}</tr></thead><tbody>{''.join(rows)}</tbody></table></section></main>'''
    (site / "index.html").write_text(index)
    return {"site": str(site), "players": total_records,
            "configurations": len(configurations(config)), "status": status["totals"]}
