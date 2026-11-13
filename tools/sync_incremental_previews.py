"""Publish a bounded number of changed case previews and fresh model indexes."""
from pathlib import Path
import html
import json
import shutil
import subprocess
import hashlib
import sys

from tools.build_bench_review import build_case, case_page_is_current, document, export_pixels, player

SUITES = {"physics_iq": "bench_smoke_codex_20261109/physics_iq",
          "physics_iq_gpt_native_v2": "bench_smoke_codex_20261109/physics_iq_gpt_native_v2",
          "physics_iq_512w24fps_gpt_native": "physics_iq_512w24fps_gpt_native",
          "physics_iq_seed21_native_v2": "bench_smoke_codex_20261109/physics_iq_seed21_native_v2",
          "robojudge": "bench_smoke_codex_20261109/robojudge",
          "robojudge_seed21_native_v2": "bench_smoke_codex_20261109/robojudge",
          "vbench2_subset_full": "vbench2_subset_full", "phygenbench_full": "phygenbench_full",
          "openve_smoke": "openve_smoke", "pcve_smoke": "pcve_smoke"}


def quick_fingerprint(run):
    files = [run/'run_manifest.json', run/'media_contract.json', run/'workspace/pixels.npz']
    return [(p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in files]


def quick_page_is_current(run, output):
    try:
        saved = json.loads((output/'quick_receipt.json').read_text())
        return (output/'quick.html').is_file() and saved['source_stamp'] == [list(x) for x in quick_fingerprint(run)]
    except (OSError, ValueError, KeyError):
        return False


def build_quick_case(run, output):
    manifest = json.loads((run/'run_manifest.json').read_text())
    if manifest.get('status') != 'complete' or manifest.get('validation', {}).get('pass') is not True:
        raise ValueError('Only a validated complete submission can have a final-video preview')
    spec = json.loads((run/'media_contract.json').read_text())
    video = export_pixels(run/'workspace', output/'final', spec)
    if video is None:
        raise ValueError('The final RGB tensor is missing or inconsistent with its contract')
    body = ('<a class=back href="../index.html">← 此模型总览</a>'
            f'<h1>{html.escape(manifest["model"])} · {html.escape(manifest["case_id"])}</h1>'
            '<p class=note>已提交的最终 RGB 视频。逐轮候选与完整生成轨迹独立同步。</p>'
            + player({**video, 'pixels':'final/'+video['pixels_file'], 'poster':'final/poster.png'}))
    if (output/'index.html').is_file():
        body += '<p><a href="index.html">查看生成轨迹与逐轮候选 →</a></p>'
    output.mkdir(parents=True, exist_ok=True)
    (output/'quick.html').write_text(document(manifest['case_id'], body, case_page=True))
    (output/'quick_receipt.json').write_text(json.dumps({'source_stamp':quick_fingerprint(run)}))


def failure_summary(run, manifest):
    validation = manifest.get("validation") or {}
    usage = manifest.get("token_usage") or {}
    budget = manifest.get("token_budget") or {}
    messages = []
    events = run / "logs/events.jsonl"
    if events.is_file():
        for line in events.read_text(errors="replace").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            message = event.get("message") or (event.get("error") or {}).get("message")
            if message:
                messages.append(str(message))
    missing = validation.get("missing_required") or []
    reasons = []
    if messages:
        reasons.append(messages[-1])
    if missing:
        reasons.append("缺失产物：" + ", ".join(map(str, missing[:6])))
    if validation.get("infra_error"):
        reasons.append("infra error: " + str(validation["infra_error"]))
    if validation.get("budget_error"):
        reasons.append(str(validation["budget_error"]))
    if budget.get("exhausted"):
        reasons.append("output token budget exhausted")
    if not reasons:
        reasons.append("validation did not pass")
    fields = []
    if usage.get("output_tokens") is not None:
        fields.append(f'output {usage["output_tokens"]:,} tok')
    elif usage.get("status"):
        fields.append(f'usage {usage["status"]}')
    if validation.get("generate_runs") is not None:
        fields.append(f'generate runs {validation.get("generate_runs")}')
    if validation.get("frames") is not None:
        fields.append(f'frames {validation.get("frames")}')
    if manifest.get("duration_seconds") is not None:
        fields.append(f'{manifest.get("duration_seconds"):.0f}s')
    return "；".join(reasons), " · ".join(fields)


def failure_html(run, manifest):
    reason, fields = failure_summary(run, manifest)
    detail = f'<p class="note"><strong>失败原因：</strong>{html.escape(reason)}</p>'
    if fields:
        detail += f'<p class=status>{html.escape(fields)}</p>'
    return detail


def sync_previews(run_root, heavy_web, pixelworld, limit=8, quick_limit=64):
    import os
    import time
    def progress(phase, **fields):
        path=run_root/'preview_build_status.json'
        temporary=path.with_name(f'{path.name}.tmp.{os.getpid()}')
        temporary.write_text(json.dumps({'phase':phase,'updated_at':time.time(),**fields}))
        temporary.replace(path)
    progress('scanning_active_suites')
    try:
        prioritize_current = json.loads((run_root/'preview_priority.json').read_text()).get('until', 0) > time.time()
    except (OSError, ValueError):
        prioritize_current = False
    published = None
    if (pixelworld.parent / '.git').exists():
        result = subprocess.run(['git','ls-tree','-r','--name-only','HEAD'],cwd=pixelworld.parent,
                                text=True,capture_output=True)
        published = set(result.stdout.splitlines()) if result.returncode == 0 else set()
    def committed(relative):
        return published is None or 'pixelworld/' + relative.as_posix() in published
    try:
        quick_cases = set(json.loads((pixelworld/'phygen_quick/manifest.json').read_text()).get('cases', []))
    except (OSError, ValueError):
        quick_cases = set()
    quick_gallery_ready = committed(Path('phygen_quick/index.html')) and (pixelworld/'phygen_quick/index.html').is_file()
    groups = {}
    group_statuses = {}
    group_stopped = {}
    candidates = []
    current_cache = {}
    def current(run, output):
        key = str(run), str(output)
        if key not in current_cache:
            current_cache[key] = case_page_is_current(run, output)
        return current_cache[key]
    for suite, prefix in SUITES.items():
        # A paused suite's saved pages remain available. Its large historical
        # trace backlog must not delay publication of currently running suites.
        if (run_root/'generations'/suite/'STOP').exists():
            continue
        progress('scanning_suite', suite=suite)
        status_path = run_root / 'generations' / suite / 'status.json'
        try:
            generation = json.loads(status_path.read_text())
        except (OSError, ValueError):
            generation = {}
        source = run_root/'generations'/suite
        folders = []
        if generation.get('groups'):
            for key, state in generation['groups'].items():
                model, track = key.split('/', 1)
                relative=Path(prefix)/model/track
                counts=state.get('counts', {})
                expected=generation.get('cases') or sum(counts.values())
                # Completed cohorts with a published model index are immutable
                # during recovery. Their older trace backlog is lower priority
                # than publishing outputs from currently unfinished cohorts.
                if prioritize_current and expected and counts.get('complete') == expected and committed(relative/'index.html'):
                    continue
                folders.append(source/model/track)
        else:
            folders=list(source.glob('*/*'))
        paths=(path for folder in folders for path in folder.glob('case_*_attempt_*/run_manifest.json'))
        for path in paths:
            run = path.parent
            try:
                manifest = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
            relative = Path(prefix) / manifest["model_key"] / manifest["track"]
            group_statuses[relative] = generation.get('groups', {}).get(f'{manifest["model_key"]}/{manifest["track"]}', {})
            group_stopped[relative] = (run_root/'generations'/suite/'STOP').exists()
            groups.setdefault(relative, {}).setdefault(manifest["case_id"], []).append((run, manifest))
    for relative, cases in groups.items():
        for history in cases.values():
            valid = [(run, m) for run, m in history if m["status"] == "complete" and m.get("validation", {}).get("pass")]
            selected = min(valid, key=lambda row: row[1]["attempt"]) if valid else max(history, key=lambda row: row[1]["attempt"])
            run, m = selected
            if (not current(run, pixelworld / relative / run.name)
                    or not committed(relative / run.name / 'index.html')):
                candidates.append((m["status"] == "complete", m.get("completed_utc") or m["started_utc"], relative, run))
    candidates.sort(key=lambda row: row[:2], reverse=True)
    targets, updated = [], []
    quick_updated = []
    progress('building_final_video_previews', candidates=len(candidates))
    for _, _, relative, run in [row for row in candidates if row[0]]:
        if len(quick_updated) >= quick_limit:
            break
        destination = pixelworld/relative/run.name
        if quick_page_is_current(run, destination) and committed(relative/run.name/'quick.html'):
            continue
        try:
            build_quick_case(run, destination)
        except (OSError, ValueError, KeyError):
            continue
        targets.append('pixelworld/'+(relative/run.name).as_posix())
        if published is not None:
            published.add('pixelworld/'+(relative/run.name/'quick.html').as_posix())
        quick_updated.append((relative/run.name/'quick.html').as_posix())
        progress('building_final_video_previews', completed=len(quick_updated), latest=quick_updated[-1])
    complete = [row for row in candidates if row[0]]
    other = [row for row in candidates if not row[0]]
    other_count = min(len(other), max(1, limit // 8))
    complete_budget = limit - other_count
    recent_count = (complete_budget + 1) // 2
    selected = complete[:recent_count]
    selected += [row for row in reversed(complete) if row not in selected][:complete_budget-len(selected)]
    selected += other[:limit-len(selected)]
    jobs=run_root/'preview_render_jobs'
    jobs.mkdir(exist_ok=True)
    active=0
    ready_rows=[]
    for job in jobs.glob('*.json'):
        try:
            state=json.loads(job.read_text());pid=state.get('pid')
            if pid is None and job.with_suffix('.pid').is_file():pid=int(job.with_suffix('.pid').read_text())
            args=(Path('/proc')/str(pid)/'cmdline').read_bytes().split(b'\0')
            if any(x.endswith(b'build_one_preview.py') for x in args):active+=1
        except (OSError,ValueError):
            pass
        try:
            state=json.loads(job.read_text())
            if state.get('phase')=='ready':
                run=Path(state['run']);output=Path(state['output'])
                relative=output.relative_to(heavy_web).parent
                if run.is_relative_to(run_root/'generations') and not current(run,pixelworld/relative/run.name):
                    ready_rows.append((state.get('row',{}).get('status')=='complete',state.get('updated_at',0),relative,run))
        except (OSError,ValueError,KeyError):pass
    # A rendered result is consumed even if newer completions displaced it
    # from the normal priority list while the renderer was running.
    ready_rows=ready_rows[:limit]
    selected=ready_rows+[row for row in selected if all(row[3]!=ready[3] for ready in ready_rows)][:limit-len(ready_rows)]
    for _, _, relative, run in selected:
        progress('building_rich_trace', case=run.name, quick_ready=len(quick_updated), rich_ready=len(updated))
        staging = heavy_web / relative / run.name
        job=jobs/(hashlib.sha256(str(run).encode()).hexdigest()[:20]+'.json')
        try:state=json.loads(job.read_text())
        except (OSError,ValueError):state={}
        if state.get('phase')!='ready' or not case_page_is_current(run,staging):
            try:
                pid=state.get('pid')
                if pid is None and job.with_suffix('.pid').is_file():pid=int(job.with_suffix('.pid').read_text())
                args=(Path('/proc')/str(pid)/'cmdline').read_bytes().split(b'\0')
                running=any(x.endswith(b'build_one_preview.py') for x in args)
            except (OSError,ValueError):running=False
            cooldown=state.get('phase')=='failed' and time.time()-state.get('updated_at',0)<300
            if not running and not cooldown and active<2:
                command=[sys.executable,'-u',str(Path(__file__).with_name('build_one_preview.py')),
                         '--run',str(run),'--output',str(staging),'--job',str(job)]
                job.write_text(json.dumps({'phase':'queued','pid':None,'run':str(run),'updated_at':time.time()}))
                with job.with_suffix('.log').open('ab') as log:
                    process=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                job.with_suffix('.pid').write_text(str(process.pid)+'\n')
                active+=1
            continue
        try:
            row=state['row']
            destination = pixelworld / relative / run.name
            shutil.copytree(staging, destination, dirs_exist_ok=True)
        except (OSError, ValueError, KeyError):
            continue
        targets.append("pixelworld/" + (relative / run.name).as_posix())
        if published is not None:
            published.add('pixelworld/' + (relative / run.name / 'index.html').as_posix())
        updated.append({"path": (relative / run.name / "index.html").as_posix(), **row})
        current_cache[str(run), str(pixelworld/relative/run.name)] = True
    for relative, cases in groups.items():
        progress('writing_model_index', model_index=str(relative))
        cards = []
        valid_count = prepared_count = 0
        for case, history in sorted(cases.items()):
            valid = [(run, m) for run, m in history if m["status"] == "complete" and m.get("validation", {}).get("pass")]
            selected = min(valid, key=lambda row: row[1]["attempt"]) if valid else max(history, key=lambda row: row[1]["attempt"])
            run, m = selected
            ready = (current(run, pixelworld / relative / run.name)
                     and committed(relative / run.name / 'index.html'))
            final_ready = bool(valid) and quick_page_is_current(run, pixelworld/relative/run.name) and committed(relative/run.name/'quick.html')
            quick_ready = bool(valid) and quick_gallery_ready and f'{m["model_key"]}/{m["track"]}/{case}' in quick_cases
            valid_count += bool(valid)
            prepared_count += bool(valid) and ready
            group = group_statuses.get(relative, {})
            if valid:
                caption = '已交付'
            elif group_stopped.get(relative):
                caption = '调度已暂停'
            elif case in (group.get('running_cases') or []):
                caption = '运行中'
            elif m['status'] == 'failed':
                caption = '本次 attempt 失败 · 等待重试/调度'
            else:
                caption = m['status']
            cards.append(f'<article class=card><h3>{html.escape(case)}</h3><span class=pill>{html.escape(caption)}</span>')
            if ready:
                poster = pixelworld / relative / run.name / "final/poster.png"
                if poster.is_file():
                    cards.append(f'<img loading=lazy src="{run.name}/final/poster.png" style="width:100%;image-rendering:pixelated">')
                cards.append(f'<p><a href="{run.name}/index.html">视频、逐轮候选与生成过程 →</a></p>')
            elif final_ready:
                cards.append(f'<p><a href="{run.name}/quick.html">▶ 播放已提交视频 · 完整轨迹同步中</a></p>')
            elif quick_ready:
                quick_url = '../'*len(relative.parts)+f'phygen_quick/index.html?model={m["model_key"]}&amp;track={m["track"]}&amp;case={case}'
                cards.append(f'<p><a href="{quick_url}">▶ 播放已提交视频 · 完整轨迹同步中</a></p>')
            else:
                cards.append('<p class=note>生成状态已更新，详情与视频资源正在同步。</p>')
                if m.get('status') == 'failed':
                    cards.append(failure_html(run, m))
            cards.append(f'<details><summary>全部 {len(history)} 次运行记录</summary>')
            for attempt_run, attempt in sorted(history, key=lambda row: row[1]["attempt"]):
                label = f'Attempt {attempt["attempt"]}: {attempt["status"]}'
                if (current(attempt_run, pixelworld / relative / attempt_run.name)
                        and committed(relative / attempt_run.name / 'index.html')):
                    cards.append(f'<p><a href="{attempt_run.name}/index.html">{html.escape(label)}</a></p>')
                else:
                    cards.append(f'<div class=box><p>{html.escape(label)} · 原始记录保留，预览待同步</p>{failure_html(attempt_run, attempt) if attempt.get("status")=="failed" else ""}</div>')
            cards.append('</details></article>')
        destination = pixelworld / relative
        destination.mkdir(parents=True, exist_ok=True)
        body = (f'<a class=back href="{"../" * len(relative.parts)}index.html">← PixelWorld 总览</a>'
                f'<h1>{html.escape(relative.parts[-2])} · {html.escape(relative.parts[-1])}</h1>'
                f'<p>{valid_count} 个有效交付 · {prepared_count} 个详情已同步。只开放与当前运行记录一致的详情链接。</p>'
                '<div class=video-grid>' + "".join(cards) + '</div>')
        (destination / "index.html").write_text(document(str(relative), body, depth=len(relative.parts)))
        targets.append("pixelworld/" + (relative / "index.html").as_posix())
    delivered = sum(row.get('status') == 'complete' for row in updated)
    return {"updated": updated, "targets": targets, "remaining": max(0, len(candidates)-len(updated)),
            "remaining_complete": max(0, len(complete)-delivered), "batch_limit":limit,
            "quick_updated":quick_updated, "quick_batch_limit":quick_limit}
