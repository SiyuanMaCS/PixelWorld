"""Publish a bounded number of changed case previews and fresh model indexes."""
from pathlib import Path
import html
import json
import shutil
import subprocess

from tools.build_bench_review import build_case, case_page_is_current, document

SUITES = {"physics_iq": "bench_smoke_codex_20261109/physics_iq",
          "physics_iq_gpt_native_v2": "bench_smoke_codex_20261109/physics_iq_gpt_native_v2",
          "physics_iq_seed21_native_v2": "bench_smoke_codex_20261109/physics_iq_seed21_native_v2",
          "robojudge": "bench_smoke_codex_20261109/robojudge",
          "robojudge_seed21_native_v2": "bench_smoke_codex_20261109/robojudge",
          "vbench2_subset_full": "vbench2_subset_full", "phygenbench_full": "phygenbench_full",
          "openve_smoke": "openve_smoke", "pcve_smoke": "pcve_smoke"}


def sync_previews(run_root, heavy_web, pixelworld, limit=64):
    published = None
    if (pixelworld.parent / '.git').exists():
        result = subprocess.run(['git','ls-tree','-r','--name-only','HEAD'],cwd=pixelworld.parent,
                                text=True,capture_output=True)
        published = set(result.stdout.splitlines()) if result.returncode == 0 else set()
    def committed(relative):
        return published is None or 'pixelworld/' + relative.as_posix() in published
    groups = {}
    group_statuses = {}
    group_stopped = {}
    candidates = []
    for suite, prefix in SUITES.items():
        status_path = run_root / 'generations' / suite / 'status.json'
        try:
            generation = json.loads(status_path.read_text())
        except (OSError, ValueError):
            generation = {}
        for path in (run_root / "generations" / suite).glob("*/*/case_*_attempt_*/run_manifest.json"):
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
            if (not case_page_is_current(run, pixelworld / relative / run.name)
                    or not committed(relative / run.name / 'index.html')):
                candidates.append((m["status"] == "complete", m.get("completed_utc") or m["started_utc"], relative, run))
    candidates.sort(key=lambda row: row[:2], reverse=True)
    targets, updated = [], []
    complete = [row for row in candidates if row[0]]
    other = [row for row in candidates if not row[0]]
    other_count = min(len(other), max(1, limit // 8))
    complete_budget = limit - other_count
    recent_count = (complete_budget + 1) // 2
    selected = complete[:recent_count]
    selected += [row for row in reversed(complete) if row not in selected][:complete_budget-len(selected)]
    selected += other[:limit-len(selected)]
    for _, _, relative, run in selected:
        staging = heavy_web / relative / run.name
        try:
            row = build_case(run, staging)
            text = (staging / "index.html").read_text().replace('href="../../../../index.html"', 'href="../index.html"').replace("本轮 smoke 总览", "此模型总览")
            (staging / "index.html").write_text(text)
            destination = pixelworld / relative / run.name
            shutil.copytree(staging, destination, dirs_exist_ok=True)
        except (OSError, ValueError, KeyError):
            continue
        targets.append("pixelworld/" + (relative / run.name).as_posix())
        if published is not None:
            published.add('pixelworld/' + (relative / run.name / 'index.html').as_posix())
        updated.append({"path": (relative / run.name / "index.html").as_posix(), **row})
    for relative, cases in groups.items():
        cards = []
        valid_count = prepared_count = 0
        for case, history in sorted(cases.items()):
            valid = [(run, m) for run, m in history if m["status"] == "complete" and m.get("validation", {}).get("pass")]
            selected = min(valid, key=lambda row: row[1]["attempt"]) if valid else max(history, key=lambda row: row[1]["attempt"])
            run, m = selected
            ready = (case_page_is_current(run, pixelworld / relative / run.name)
                     and committed(relative / run.name / 'index.html'))
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
            else:
                cards.append('<p class=note>生成状态已更新，详情与视频资源正在同步。</p>')
            cards.append(f'<details><summary>全部 {len(history)} 次运行记录</summary>')
            for attempt_run, attempt in sorted(history, key=lambda row: row[1]["attempt"]):
                label = f'Attempt {attempt["attempt"]}: {attempt["status"]}'
                if (case_page_is_current(attempt_run, pixelworld / relative / attempt_run.name)
                        and committed(relative / attempt_run.name / 'index.html')):
                    cards.append(f'<p><a href="{attempt_run.name}/index.html">{html.escape(label)}</a></p>')
                else:
                    cards.append(f'<p>{html.escape(label)} · 原始记录保留，预览待同步</p>')
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
            "remaining_complete": max(0, len(complete)-delivered), "batch_limit":limit}
