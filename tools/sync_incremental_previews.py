"""Publish a bounded number of changed case previews and fresh model indexes."""
from pathlib import Path
import html
import json
import shutil

from tools.build_bench_review import build_case, case_page_is_current, document

SUITES = {"physics_iq": "bench_smoke_codex_20261109/physics_iq",
          "physics_iq_gpt_native_v2": "bench_smoke_codex_20261109/physics_iq_gpt_native_v2",
          "physics_iq_seed21_native_v2": "bench_smoke_codex_20261109/physics_iq_seed21_native_v2",
          "robojudge": "bench_smoke_codex_20261109/robojudge",
          "robojudge_seed21_native_v2": "bench_smoke_codex_20261109/robojudge",
          "vbench2_subset_full": "vbench2_subset_full", "phygenbench_full": "phygenbench_full",
          "openve_smoke": "openve_smoke"}


def sync_previews(run_root, heavy_web, pixelworld, limit=16):
    groups = {}
    candidates = []
    for suite, prefix in SUITES.items():
        for path in (run_root / "generations" / suite).glob("*/*/case_*_attempt_*/run_manifest.json"):
            run = path.parent
            try:
                manifest = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
            relative = Path(prefix) / manifest["model_key"] / manifest["track"]
            groups.setdefault(relative, {}).setdefault(manifest["case_id"], []).append((run, manifest))
    for relative, cases in groups.items():
        for history in cases.values():
            valid = [(run, m) for run, m in history if m["status"] == "complete" and m.get("validation", {}).get("pass")]
            selected = min(valid, key=lambda row: row[1]["attempt"]) if valid else max(history, key=lambda row: row[1]["attempt"])
            run, m = selected
            if not case_page_is_current(run, pixelworld / relative / run.name):
                candidates.append((m["status"] == "complete", m.get("completed_utc") or m["started_utc"], relative, run))
    candidates.sort(key=lambda row: row[:2], reverse=True)
    targets, updated = [], []
    complete = [row for row in candidates if row[0]]
    other = [row for row in candidates if not row[0]]
    recent_count = (limit + 1) // 2
    selected = complete[:recent_count]
    selected += [row for row in reversed(complete) if row not in selected][:limit-len(selected)]
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
        updated.append({"path": (relative / run.name / "index.html").as_posix(), **row})
    for relative, cases in groups.items():
        cards = []
        valid_count = prepared_count = 0
        for case, history in sorted(cases.items()):
            valid = [(run, m) for run, m in history if m["status"] == "complete" and m.get("validation", {}).get("pass")]
            selected = min(valid, key=lambda row: row[1]["attempt"]) if valid else max(history, key=lambda row: row[1]["attempt"])
            run, m = selected
            ready = case_page_is_current(run, pixelworld / relative / run.name)
            valid_count += bool(valid)
            prepared_count += bool(valid) and ready
            caption = "已交付" if valid else m["status"]
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
                if case_page_is_current(attempt_run, pixelworld / relative / attempt_run.name):
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
    return {"updated": updated, "targets": targets, "remaining": max(0, len(candidates)-len(updated))}
