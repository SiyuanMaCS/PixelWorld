"""Sync lightweight PixelWorld monitor pages into SiyuanMaCS.github.io.

The full generated videos and trace pages stay in the heavy
physics-iq-pixel-preview Pages repo. This script republishes only the small
benchmark monitor pages under /pixelworld/ and rewrites heavy artifact links to
absolute public URLs.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


HEAVY_BASE = "https://siyuanmacs.github.io/physics-iq-pixel-preview/"
AUTO_REFRESH = (
    '<script>setTimeout(()=>{if(!document.querySelector("[data-state=playing]")){'
    'const next=new URL(location.href);next.searchParams.set("refresh",String(Date.now()));'
    'location.replace(next.href)}},60000)</script>'
)
CORE_TARGETS = (
    "pixelworld/index.html",
    "pixelworld/pixelworld-index.html",
    "pixelworld/physics_iq_baseline.html",
    "pixelworld/robojudge.html",
    "pixelworld/matrix_full.html",
    "pixelworld/vbench2_subset.html",
    "pixelworld/phygenbench.html",
    "pixelworld/openve.html",
    "pixelworld/openve_smoke",
    "pixelworld/robojudge_assets",
    "pixelworld/bench_smoke_codex_20261109",
)

GALLERY_TARGETS = (
    "pixelworld/vbench2_subset_full",
    "pixelworld/phygenbench_full",
)

TARGETS = CORE_TARGETS + GALLERY_TARGETS

CSS = """:root{color-scheme:dark;--bg:#0b0f14;--panel:#141b24;--line:#2b3745;--text:#edf2f7;--muted:#a0adbc;--green:#b8ed94;--blue:#94ccff;--amber:#f4cb91;--red:#ffaaa0}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.6 system-ui,-apple-system,sans-serif}a{color:inherit;text-decoration:none}main{max-width:1160px;margin:auto;padding:32px 24px 64px}.top{position:sticky;top:0;background:#0b0f14f2;border-bottom:1px solid var(--line);z-index:5}.top-inner{max-width:1160px;margin:auto;padding:15px 24px;display:flex;justify-content:space-between;gap:18px;align-items:center}.brand{font-weight:850}.nav{display:flex;gap:18px;color:var(--muted);font-size:13px}.nav a:hover,.link{color:var(--blue)}.hero{margin:18px 0 30px}.eyebrow{font-size:11px;letter-spacing:.1em;color:var(--green);margin:0 0 8px}.hero h1{font-size:clamp(30px,4vw,48px);line-height:1.15;margin:0 0 12px;letter-spacing:-.04em}.muted,.desc{color:var(--muted)}.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:16px}.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:22px}.card.feature{border-color:#52714a;background:linear-gradient(130deg,#1a2b20,var(--panel) 70%)}.badge{display:inline-block;font-size:11px;border:1px solid #465749;border-radius:6px;padding:3px 8px;color:var(--green)}h2{margin:36px 0 14px;font-size:24px}h3{font-size:21px;margin:12px 0 8px}.button{display:inline-flex;margin-top:10px;border:1px solid #425064;border-radius:8px;padding:9px 14px;background:#202b37;font-weight:700;font-size:13px}.primary{background:var(--green);color:#17220f;border-color:var(--green)}.facts{display:flex;gap:18px;margin:14px 0;color:var(--muted);font-size:12px;flex-wrap:wrap}.facts strong{display:block;color:var(--text);font-size:22px}.scroll{overflow:auto;border:1px solid var(--line);border-radius:12px;background:var(--panel);margin:12px 0 22px}table{border-collapse:collapse;width:100%;min-width:680px}th,td{border-bottom:1px solid var(--line);padding:12px 14px;text-align:left;vertical-align:top}th{color:var(--muted);font-size:12px}.matrix th{text-align:center}.matrix th:first-child,.matrix td:first-child{text-align:left}.run-cell{min-width:270px}.run-top{display:flex;justify-content:space-between;gap:10px;align-items:flex-start}.run-name{font-weight:780}.run-num{font-weight:820}.run-meta{color:var(--muted);font-size:12px;margin-top:6px}.run-links{display:flex;gap:10px;flex-wrap:wrap;margin-top:8px}.ok{color:var(--green)}.bad{color:var(--red)}.live{color:var(--blue)}.note,.status{font-size:12px;color:var(--muted)}.status strong{color:var(--text)}.legacy{border-color:#5b4c31;background:#1c1a15}.warn{color:var(--amber)}@media(max-width:800px){.grid{grid-template-columns:1fr}.top-inner{display:block}.nav{overflow:auto;margin-top:8px}}"""

MODEL_LABELS = {
    "gpt61-sol": "GPT-6.1-Sol",
    "gpt56-sol": "GPT-5.6-Sol",
    "gpt6-astra": "GPT-6-Astra",
    "deepseek-v41": "DeepSeek-V4.1-Flash",
    "seed21-pro": "Seed-2.1-Pro-0915",
}

MODEL_ORDER = ["gpt61-sol", "gpt56-sol", "gpt6-astra", "deepseek-v41", "seed21-pro"]
TRACK_ORDER = ["text", "vision-agent"]


def run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)


def check(cmd: list[str], cwd: Path) -> None:
    result = run(cmd, cwd)
    if result.returncode:
        raise RuntimeError(
            f"Command failed: {' '.join(cmd)}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )


def pending_pages_deployment(stable_repo: Path) -> dict | None:
    credential = subprocess.run(
        ["git", "credential", "fill"], cwd=stable_repo,
        input="protocol=https\nhost=github.com\n\n", text=True, capture_output=True,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "Never"},
        timeout=5,
    )
    values = dict(line.split("=", 1) for line in credential.stdout.splitlines() if "=" in line)
    headers = {"Accept": "application/vnd.github+json"}
    if values.get("password"):
        headers["Authorization"] = "Bearer " + values["password"]
    request = urllib.request.Request(
        "https://api.github.com/repos/SiyuanMaCS/SiyuanMaCS.github.io/actions/runs?per_page=8",
        headers=headers,
    )
    with urllib.request.urlopen(request, timeout=12) as response:
        workflows = json.load(response)["workflow_runs"]
    for workflow in workflows:
        if ("pages" in (workflow.get("name", "") + workflow.get("path", "")).lower()
                and workflow.get("head_branch") == "main"
                and workflow.get("status") != "completed"):
            return {"run_id": workflow["id"], "status": workflow["status"],
                    "sha": workflow["head_sha"], "url": workflow.get("html_url")}
    return None


def publication_wait(stable_repo: Path, core_only: bool) -> dict | None:
    try:
        pending = pending_pages_deployment(stable_repo)
    except Exception as exc:
        # An unknown deployment state must not cancel a running publication.
        pending = {"state_check_error": type(exc).__name__}
    if pending is None:
        return None
    return {"changed": False, "commit": run(["git", "rev-parse", "HEAD"], stable_repo).stdout.strip(),
            "core_only": core_only, "gallery": {"changed": False, "commit": None},
            "waiting_for_pages_deployment": pending}


def rewrite_monitor_html(source: Path, destination: Path) -> None:
    text = source.read_text()
    text = text.replace("bench_smoke_codex_20261109/", HEAVY_BASE + "bench_smoke_codex_20261109/")
    # Small, explicitly published case previews take precedence over missing
    # heavy-site artifacts. Keep this routing on every subsequent core refresh.
    pattern = re.escape(HEAVY_BASE) + r'(bench_smoke_codex_20261109/[^\s\"\'<>]+)'
    def scoped_preview(match):
        relative = match.group(1)
        path = (destination.parent / relative).resolve()
        if path.is_relative_to(destination.parent.resolve()) and path.is_file():
            return relative
        return match.group(0)
    text = re.sub(pattern, scoped_preview, text)
    text = re.sub(r'href="(matrix_[^"]+\.html)"', lambda m: f'href="{HEAVY_BASE}{m.group(1)}"', text)
    text = text.replace('</body>', AUTO_REFRESH + '</body>')
    destination.write_text(text)


def write_legacy_page(destination: Path) -> None:
    destination.write_text(
        """<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Legacy PixelWorld Matrix</title><style>body{margin:0;background:#0b0f14;color:#edf2f7;font:15px/1.6 system-ui,-apple-system,sans-serif}main{max-width:860px;margin:auto;padding:40px 24px}a{color:#94ccff;text-decoration:none}.card{background:#141b24;border:1px solid #2b3745;border-radius:14px;padding:22px}.muted{color:#a0adbc}.button{display:inline-block;margin:8px 10px 0 0;border:1px solid #425064;border-radius:8px;padding:9px 14px;background:#202b37;font-weight:700}.primary{background:#b8ed94;color:#17220f;border-color:#b8ed94}</style><main><p><a href="index.html">← PixelWorld Index</a></p><h1>Legacy Physics-IQ Matrix</h1><div class="card"><p class="muted">这里是早期 legacy-v1 / 旧 track 的完整矩阵入口，只作历史参考，不进入 native_v2 主实验。</p><p><a class="button primary" href="https://siyuanmacs.github.io/physics-iq-pixel-preview/matrix_full.html">打开 legacy full matrix →</a><a class="button" href="physics_iq_baseline.html#legacy">查看当前主实验中的 Legacy 说明 →</a></p></div></main></html>"""
    )


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def fmt_number(value, digits: int = 0) -> str:
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if digits == 0:
        return f"{number:,.0f}"
    return f"{number:,.{digits}f}"


def fmt_seconds(value) -> str:
    if value is None:
        return "—"
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return "—"
    if seconds < 60:
        return f"{seconds:.0f}s"
    return f"{seconds / 60:.1f}m"


def latest_event_status(source: Path, model: str, track: str, case_id: str) -> str:
    attempts = sorted((source / model / track).glob(f"case_{case_id}_attempt_*/logs/events.jsonl"))
    if not attempts:
        return "event: no log yet"
    path = max(attempts, key=lambda p: p.stat().st_mtime)
    age = max(0.0, time.time() - path.stat().st_mtime)
    try:
        lines = path.read_text(errors="ignore").splitlines()
    except OSError:
        return "event: log unreadable"
    events = []
    for line in lines[-12:]:
        try:
            events.append(json.loads(line))
        except ValueError:
            continue
    last = events[-1] if events else {}
    typ = str(last.get("type", "unknown"))
    message = str(last.get("message", ""))
    if "Connection failed" in message or "Reconnecting... waiting for network" in message:
        label = "network retry"
        css = "warn"
    elif typ in {"item.started", "item.completed", "turn.completed"}:
        label = "recent output/tool activity"
        css = "live"
    elif age > 900:
        label = "stale event log"
        css = "warn"
    else:
        label = typ.replace("_", " ")
        css = "live"
    if typ == "turn.failed":
        label = "turn failed"
        css = "bad"
    age_text = fmt_seconds(age)
    return f'<span class="{css}">{html.escape(label)}</span> · {html.escape(age_text)} ago'


def group_manifest_stats(run_root: Path, benchmark: str) -> dict[tuple[str, str], dict]:
    source = run_root / "generations" / benchmark
    stats: dict[tuple[str, str], dict] = {}
    if not source.exists():
        return stats
    for manifest_path in source.glob("*/*/case_*_attempt_*/run_manifest.json"):
        try:
            manifest = json.loads(manifest_path.read_text())
        except (OSError, ValueError):
            continue
        parts = manifest_path.relative_to(source).parts
        if len(parts) < 3:
            continue
        key = (parts[0], parts[1])
        bucket = stats.setdefault(
            key,
            {
                "runs": 0,
                "complete": 0,
                "duration_sum": 0.0,
                "duration_count": 0,
                "output_sum": 0.0,
                "output_count": 0,
                "reasoning_sum": 0.0,
                "reasoning_count": 0,
                "latest_completed": None,
            },
        )
        bucket["runs"] += 1
        if manifest.get("status") == "complete":
            bucket["complete"] += 1
        duration = manifest.get("duration_seconds")
        if isinstance(duration, (int, float)):
            bucket["duration_sum"] += duration
            bucket["duration_count"] += 1
        usage = manifest.get("token_usage") or {}
        output = usage.get("output_tokens")
        if isinstance(output, (int, float)):
            bucket["output_sum"] += output
            bucket["output_count"] += 1
        reasoning = usage.get("reasoning_output_tokens")
        if isinstance(reasoning, (int, float)):
            bucket["reasoning_sum"] += reasoning
            bucket["reasoning_count"] += 1
        completed = manifest.get("completed_utc") or manifest.get("completed_at")
        if completed and (bucket["latest_completed"] is None or completed > bucket["latest_completed"]):
            bucket["latest_completed"] = completed
    for bucket in stats.values():
        bucket["avg_duration"] = bucket["duration_sum"] / bucket["duration_count"] if bucket["duration_count"] else None
        bucket["avg_output_tokens"] = bucket["output_sum"] / bucket["output_count"] if bucket["output_count"] else None
        bucket["avg_reasoning_tokens"] = bucket["reasoning_sum"] / bucket["reasoning_count"] if bucket["reasoning_count"] else None
    return stats


def page(title: str, body: str) -> str:
    nav = (
        '<header class="top"><div class="top-inner"><a class="brand" href="index.html">PixelWorld</a>'
        '<nav class="nav"><a href="index.html#benchmarks">Benchmarks</a>'
        '<a href="physics_iq_baseline.html">Physics-IQ</a><a href="robojudge.html">RoboJudge</a>'
        '<a href="vbench2_subset.html">VBench2</a><a href="phygenbench.html">PhyGenBench</a>'
        '<a href="matrix_full.html">Legacy</a></nav></div></header>'
    )
    return (
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<meta name="pixelworld-built-utc" content="{datetime.now(timezone.utc).isoformat()}">'
        f'<title>{html.escape(title)}</title><style>{CSS}</style><body>{nav}<main>{body}</main>'
        + AUTO_REFRESH +
        '</body></html>'
    )


def group_rows(status: dict, heavy_slug: str) -> str:
    rows = []
    for key, group in status.get("groups", {}).items():
        counts = group.get("counts", {})
        latest = group.get("latest_completion") or ["—", "—"]
        total = sum(counts.values())
        model = group.get("model", group.get("model_key", key.split("/")[0]))
        track = group.get("track", key.split("/")[-1])
        link = f'{heavy_slug}/{group.get("model_key", key.split("/")[0])}/{track}/index.html'
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(model))}<br><span class=status>{html.escape(track)}</span></td>"
            f"<td>{counts.get('complete', 0)} / {total}</td>"
            f"<td>{counts.get('running', 0)}</td>"
            f"<td>{counts.get('exhausted', 0)}</td>"
            f"<td>{counts.get('pending', 0)}</td>"
            f"<td>{html.escape(str(latest[0]))}<br>{html.escape(str(latest[1]))}</td>"
            f'<td><a class="link" href="{link}">视频与 trace →</a></td>'
            "</tr>"
        )
    return "".join(rows)


def model_track_matrix(run_root: Path, benchmark: str, status: dict, slug: str) -> str:
    source = run_root / "generations" / benchmark
    manifest_stats = group_manifest_stats(run_root, benchmark)
    groups = status.get("groups", {})
    seen_models = {key.split("/")[0] for key in groups}
    model_order = [m for m in MODEL_ORDER if m in seen_models] + sorted(seen_models - set(MODEL_ORDER))
    if not model_order:
        return '<p class="note">尚未创建 model/track 状态；等待 supervisor 首次刷新。</p>'
    rows = []
    for model_key in model_order:
        cells = [f"<td><strong>{html.escape(MODEL_LABELS.get(model_key, model_key))}</strong><br><span class=status>{html.escape(model_key)}</span></td>"]
        for track in TRACK_ORDER:
            key = f"{model_key}/{track}"
            group = groups.get(key, {})
            counts = group.get("counts", {})
            total = sum(counts.values()) or status.get("cases") or 0
            complete = counts.get("complete", 0)
            running = counts.get("running", 0)
            exhausted = counts.get("exhausted", 0) + counts.get("failed", 0)
            pending = counts.get("pending", max(total - complete - running - exhausted, 0))
            latest = group.get("latest_completion")
            if isinstance(latest, list) and len(latest) >= 2:
                latest_case, latest_time = latest[0], latest[1]
            else:
                latest_case = "—"
                latest_time = (manifest_stats.get((model_key, track), {}) or {}).get("latest_completed") or "—"
            stats = manifest_stats.get((model_key, track), {})
            gallery = f"{slug}/{model_key}/{track}/index.html"
            running_cases = ", ".join(group.get("running_cases") or [])
            running_activity = ""
            if group.get("running_cases"):
                parts = []
                for case_id in (group.get("running_cases") or [])[:3]:
                    parts.append(
                        f"{html.escape(case_id)}: "
                        f"{latest_event_status(source, model_key, track, case_id)}"
                    )
                running_activity = "<br>".join(parts)
            exhausted_cases = ", ".join((group.get("exhausted_cases") or [])[:3])
            activity = "ACTIVE" if running else ("DONE" if complete >= total and total else "IDLE")
            activity_class = "badge" if activity == "ACTIVE" else "pill"
            cells.append(
                '<td class="run-cell">'
                '<div class="run-top">'
                f'<span><span class="{activity_class}">{activity}</span> <span class="run-name">{html.escape(track)}</span></span>'
                f'<span class="run-num">{complete}/{total}</span>'
                '</div>'
                f'<div class="run-meta"><span class="live">{running} running</span> · {pending} pending · '
                f'<span class="bad">{exhausted} exhausted/failed</span></div>'
                f'<div class="run-meta">latest: {html.escape(str(latest_case))}<br>{html.escape(str(latest_time))}</div>'
                f'<div class="run-meta">avg time {fmt_seconds(stats.get("avg_duration"))} · '
                f'avg output {fmt_number(stats.get("avg_output_tokens"))} tok · '
                f'avg reasoning {fmt_number(stats.get("avg_reasoning_tokens"))} tok</div>'
                + (f'<div class="run-meta">running case: {html.escape(running_cases)}</div>' if running_cases else "")
                + (f'<div class="run-meta">activity: {running_activity}</div>' if running_activity else "")
                + (f'<div class="run-meta warn">recent exhausted: {html.escape(exhausted_cases)}</div>' if exhausted_cases else "")
                + f'<div class="run-links"><a class="link" href="{gallery}">视频与逐轮候选 →</a></div>'
                '</td>'
            )
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return (
        '<div class=scroll><table class=matrix><tr><th>Model</th>'
        '<th>Text</th><th>Vision-Agent</th></tr>'
        + "".join(rows)
        + "</table></div>"
    )


def evaluation_scheduler_table(path: Path) -> str:
    scheduler = read_json(path)
    cohorts = scheduler.get("cohorts", {})
    if not cohorts:
        return '<p class="note">Evaluation watcher has not written a scheduler yet.</p>'
    rows = []
    for key, item in sorted(cohorts.items()):
        blocker = item.get("blocker") or item.get("error") or "—"
        rows.append(
            "<tr>"
            f"<td>{html.escape(key)}</td>"
            f"<td>{html.escape(str(item.get('phase', '—')))}</td>"
            f"<td>{item.get('accepted_videos', 0)} / {item.get('expected_videos', '—')}</td>"
            f"<td>{item.get('running_videos', 0)}</td>"
            f"<td>{item.get('exhausted_videos', 0)}</td>"
            f"<td>{html.escape(str(blocker))}</td>"
            "</tr>"
        )
    return (
        f'<p class="note">Scheduler UTC：{html.escape(str(scheduler.get("updated_utc", "—")))} · '
        f'PID：{html.escape(str(scheduler.get("pid", "—")))}。完整 cohort 前不运行评测；缺 evaluator 时显示 blocker，不补假分。</p>'
        '<div class=scroll><table><tr><th>Model / Track</th><th>Phase</th><th>Accepted</th>'
        '<th>Running</th><th>Exhausted</th><th>Blocker / Note</th></tr>'
        + "".join(rows)
        + "</table></div>"
    )


def case_page_is_current(run: Path, case_dir: Path) -> bool:
    from tools.build_bench_review import case_page_is_current as current
    if not current(run, case_dir):
        return False
    workspace = run / "workspace"
    pixels = workspace / "pixels.npz"
    receipt = case_dir / "final" / "export_receipt.json"
    index = case_dir / "index.html"
    poster = case_dir / "final" / "poster.png"
    if not (pixels.is_file() and receipt.is_file() and index.is_file() and poster.is_file()):
        return False
    try:
        saved = json.loads(receipt.read_text())
    except (OSError, ValueError):
        return False
    expected_hash = saved.get("source_npz_sha256")
    if not expected_hash:
        return False
    try:
        current_hash = hashlib.sha256(pixels.read_bytes()).hexdigest()
    except OSError:
        return False
    return current_hash == expected_hash


def write_full_galleries(run_root: Path, pixelworld: Path, benchmark: str, title: str) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root))
    from tools.build_bench_review import build_case, document  # Imported lazily to avoid side effects during help output.

    source = run_root / "generations" / benchmark
    target = pixelworld / benchmark
    target.mkdir(parents=True, exist_ok=True)
    model_labels = MODEL_LABELS
    track_dirs = []
    for model_dir in sorted([p for p in source.iterdir() if p.is_dir() and not p.name.startswith("_")]) if source.exists() else []:
        for track_dir in sorted([p for p in model_dir.iterdir() if p.is_dir()]):
            entries = []
            for manifest_path in sorted(track_dir.glob("case_*_attempt_*/run_manifest.json")):
                manifest = read_json(manifest_path)
                if not manifest:
                    continue
                run = manifest_path.parent
                case_dir = target / model_dir.name / track_dir.name / run.name
                playable = manifest.get("status") == "complete" and manifest.get("validation", {}).get("pass") is True
                if playable:
                    if not case_page_is_current(run, case_dir):
                        build_case(run, case_dir)
                entries.append((manifest, run.name))
            gallery = target / model_dir.name / track_dir.name / "index.html"
            gallery.parent.mkdir(parents=True, exist_ok=True)
            cards = []
            for manifest, run_name in entries:
                case_id = manifest.get("case_id", run_name)
                status = manifest.get("status", "unknown")
                usage = manifest.get("token_usage") or {}
                tokens = usage.get("output_tokens")
                poster = Path(run_name) / "final/poster.png"
                playable_link = (gallery.parent / run_name / "index.html").exists()
                if (gallery.parent / poster).exists():
                    preview = f'<img loading=lazy src="{poster.as_posix()}" alt="{html.escape(case_id)}">'
                else:
                    preview = '<div class=placeholder>尚无可播放结果</div>'
                href = f'{run_name}/index.html' if playable_link else "#"
                cards.append(
                    f'<article class=sample><a href="{href}">{preview}'
                    f'<div class=sample-body><span class=pill>{html.escape(status)}</span>'
                    f'<h3>{html.escape(case_id)} ↗</h3>'
                    f'<p>{tokens if tokens is not None else "—"} output tokens</p></div></a></article>'
                )
            complete = sum(1 for manifest, _ in entries if manifest.get("status") == "complete")
            model_label = model_labels.get(model_dir.name, model_dir.name)
            body = (
                '<a class=back href="../../../index.html#benchmarks">← PixelWorld Index</a>'
                f'<h1>{html.escape(title)} · {html.escape(model_label)}</h1>'
                f'<div class=case-meta><span class=badge>{html.escape(track_dir.name)}</span>'
                f'<span class=pill>{complete} complete</span><span class=pill>{len(entries)} records</span></div>'
                '<p class=desc>点击样本查看视频、逐轮候选和实际工具记录。失败/运行中的样本保留状态但不计入有效结果。</p>'
                '<div class=video-grid>' + "".join(cards) + "</div>"
            )
            gallery.write_text(document(f"{title} / {track_dir.name}", body, depth=3))
            track_dirs.append(str(gallery.relative_to(pixelworld)))
    index_body = (
        '<a class=back href="../index.html#benchmarks">← PixelWorld Index</a>'
        f'<h1>{html.escape(title)} · generated galleries</h1>'
        '<div class=scroll><table><tr><th>Gallery</th></tr>'
        + "".join(f'<tr><td><a href="{html.escape(path)}">{html.escape(path)}</a></td></tr>' for path in track_dirs)
        + "</table></div>"
    )
    (target / "index.html").write_text(document(f"{title} galleries", index_body, depth=1))


def status_facts(status: dict) -> str:
    totals = status.get("totals", {})
    return (
        '<div class="facts">'
        f'<div><strong>{totals.get("complete", 0)}</strong>complete</div>'
        f'<div><strong>{totals.get("running", 0)}</strong>running</div>'
        f'<div><strong>{totals.get("pending", 0)}</strong>pending</div>'
        f'<div><strong>{totals.get("exhausted", 0)}</strong>exhausted</div>'
        "</div>"
    )


def write_vbench_page(run_root: Path, destination: Path) -> None:
    status = read_json(run_root / "generations/vbench2_subset_full/status.json")
    smoke = read_json(run_root / "generations/vbench2_subset_smoke/status.json")
    provenance = read_json(run_root / "infrastructure/other_bench_protocols/vbench2_subset_full/provenance.json")
    dims = []
    for dim in provenance.get("dimensions", []):
        count = sum(1 for item in provenance.get("cases", []) if item.get("dimension") == dim)
        dims.append((dim, count))
    dimension_rows = "".join(
        f"<tr><td>{html.escape(dim)}</td><td>{count}</td><td>prompts/meta_info/{html.escape(dim)}.json</td></tr>"
        for dim, count in dims
    )
    body = (
        '<section class="hero"><p class="eyebrow">VBENCH-2.0 SUBSET</p>'
        "<h1>VBench-2.0 五维子集</h1>"
        '<p class="muted">五个官方 VBench-2.0 维度，聚焦动态世界状态、物体身份和运动合理性。</p></section>'
        '<div class="card feature"><span class="badge">running · native_v2</span>'
        f"{status_facts(status)}"
        f'<p class="desc">Full queue：{status.get("cases", 291)} cases × {status.get("configurations", 2)} model-track configurations。'
        f'更新时间 UTC：{html.escape(status.get("updated_utc", "—"))}。</p>'
        '<p><a class="button primary" href="vbench2_subset_full/index.html">打开 full 生成画廊 →</a>'
        '<a class="button" href="smoke.html">查看 smoke 视频 →</a></p></div>'
        "<h2>Model × Track Progress</h2>"
        + model_track_matrix(run_root, "vbench2_subset_full", status, "vbench2_subset_full")
        +
        "<h2>Evaluation Watcher</h2>"
        + evaluation_scheduler_table(run_root / "evaluation/vbench2_subset_full_scheduler/scheduler.json")
        +
        "<h2>Smoke Gate</h2>"
        f'<p class="note">Smoke status：{html.escape(json.dumps(smoke.get("totals", {}), ensure_ascii=False))}。'
        'Smoke 页面只用于链路验证，不是正式 VBench-2.0 分数。</p>'
        "<h2>Selected Dimensions</h2><div class=scroll><table><tr><th>Dimension</th><th>Prompt rows</th><th>Official file</th></tr>"
        + dimension_rows
        + "</table></div>"
        '<p class="note">总计 291 dimension rows。不要报告 full 18-dimension VBench-2.0 score；这是 PixelWorld 五维 subset。</p>'
    )
    if (run_root / "generations/vbench2_subset_full/STOP").exists():
        body = body.replace('running · native_v2', '已停止 · T2V 历史实验')
        body = body.replace('<h2>Model × Track Progress</h2>', '<p class="note">本批输入只有文本，无首帧。已按用户要求停止；不属于 I2V 主实验，已有产物保留。</p><h2>Model × Track Progress</h2>')
    destination.write_text(page("VBench-2.0 subset · PixelWorld", body))


def write_phygen_page(run_root: Path, destination: Path) -> None:
    status = read_json(run_root / "generations/phygenbench_full/status.json")
    smoke = read_json(run_root / "generations/phygenbench_smoke/status.json")
    provenance = read_json(run_root / "infrastructure/other_bench_protocols/phygenbench_full/provenance.json")
    buckets: dict[str, int] = {}
    raw: dict[str, int] = {}
    for item in provenance.get("cases", []):
        buckets[item.get("reporting_dimension", "Unknown")] = buckets.get(item.get("reporting_dimension", "Unknown"), 0) + 1
        raw[item.get("main_category", "Unknown")] = raw.get(item.get("main_category", "Unknown"), 0) + 1
    rows = "".join(f"<tr><td>{html.escape(k)}</td><td>{v}</td></tr>" for k, v in sorted(buckets.items()))
    raw_rows = "".join(f"<tr><td>{html.escape(k)}</td><td>{v}</td></tr>" for k, v in sorted(raw.items()))
    body = (
        '<section class="hero"><p class="eyebrow">PHYGENBENCH</p><h1>PhyGenBench 160 prompt</h1>'
        '<p class="muted">小规模、物理概念明确，作为 Physics-IQ 和 VBench-2.0 的物理常识补充。</p></section>'
        '<div class="card feature"><span class="badge">running · native_v2</span>'
        f"{status_facts(status)}"
        f'<p class="desc">Full queue：{status.get("cases", 160)} prompts × {status.get("configurations", 2)} model-track configurations。'
        f'更新时间 UTC：{html.escape(status.get("updated_utc", "—"))}。</p>'
        '<p><a class="button primary" href="phygenbench_full/index.html">打开 full 生成画廊 →</a>'
        '<a class="button" href="smoke.html">查看 smoke 视频 →</a></p></div>'
        "<h2>Model × Track Progress</h2>"
        + model_track_matrix(run_root, "phygenbench_full", status, "phygenbench_full")
        +
        "<h2>Evaluation Watcher</h2>"
        + evaluation_scheduler_table(run_root / "evaluation/phygenbench_full_scheduler/scheduler.json")
        +
        "<h2>Smoke Gate</h2>"
        f'<p class="note">Smoke status：{html.escape(json.dumps(smoke.get("totals", {}), ensure_ascii=False))}。'
        "其中 PhyGenBench smoke 的一条 vision-agent case 耗尽，保留为失败，不混入有效视频。</p>"
        "<h2>Reporting Dimensions</h2><div class=scroll><table><tr><th>Report dimension</th><th>Prompts</th></tr>"
        + rows
        + "</table></div><h2>Raw Categories</h2><div class=scroll><table><tr><th>Raw category</th><th>Prompts</th></tr>"
        + raw_rows
        + "</table></div>"
    )
    if (run_root / "generations/phygenbench_full/STOP").exists():
        body = body.replace('running · native_v2', '已停止 · T2V 历史实验')
        body = body.replace('<h2>Model × Track Progress</h2>', '<p class="note">本批输入只有文本，无首帧。已按用户要求停止；不属于 I2V 主实验，已有产物保留。</p><h2>Model × Track Progress</h2>')
    destination.write_text(page("PhyGenBench · PixelWorld", body))


def write_index_page(destination: Path, run_root: Path) -> None:
    # Labels come from a read-only process snapshot, not hand-written badges.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools.inspect_live_workers import inspect_workers
    workers = inspect_workers(run_root.resolve())
    suites = {
        "robojudge.html": ("robojudge", "robojudge_seed21_native_v2"),
        "physics_iq_baseline.html": ("physics_iq", "physics_iq_gpt_native_v2", "physics_iq_seed21_native_v2"),
        "vbench2_subset.html": ("vbench2_subset_full",),
        "phygenbench.html": ("phygenbench_full",),
    }
    body = (
        '<section class="hero"><p class="eyebrow">PIXELWORLD MAIN BENCHMARKS</p><h1>PixelWorld Index</h1>'
        '<p class="muted">主实验收敛为四个 benchmark：RoboJudge、Physics-IQ、VBench-2.0 subset 和 PhyGenBench。'
        "WorldArena、WBench、WorldScore 等保留为历史/探索入口，不再作为主线。</p></section>"
        '<section id="benchmarks"><h2>四个主 Benchmark</h2><div class="grid">'
        '<article class="card feature"><span class="badge">running</span><h3>RoboJudge shared-50</h3>'
        '<p class="desc">50 shared embodied generation prompts x Text/Vision-Agent</p>'
        '<p class="note">Original RoboJudge-9B scoring; Table8 comparability remains explicitly gated.</p>'
        '<a class="button primary" href="robojudge.html">打开页面 →</a></article>'
        '<article class="card feature"><span class="badge">running</span><h3>Physics-IQ Verified</h3>'
        '<p class="desc">198 official BPP/I2V prompts x Text/Vision-Agent</p>'
        '<p class="note">Native v2 GPT rerun is separate from legacy-v1 reference results.</p>'
        '<a class="button primary" href="physics_iq_baseline.html">打开页面 →</a></article>'
        '<article class="card feature"><span class="badge">running</span><h3>VBench-2.0 five-dimension subset</h3>'
        '<p class="desc">291 selected VBench-2.0 dimension rows x Text/Vision-Agent.</p>'
        '<p class="note">Not the Video-Coder three-dimension setup and not the full 18-dimension VBench-2.0 score.</p>'
        '<a class="button primary" href="vbench2_subset.html">打开页面 →</a></article>'
        '<article class="card feature"><span class="badge">running</span><h3>PhyGenBench</h3>'
        '<p class="desc">160 prompts covering mechanics/optics/thermal/material physical concepts.</p>'
        '<p class="note">Small physically interpretable supplement; model scores from Video-Coder paper are shown only as reference.</p>'
        '<a class="button primary" href="phygenbench.html">打开页面 →</a></article>'
        '</div><p><a class="button primary" href="smoke.html">打开 VBench2 / PhyGenBench smoke 输出 →</a></p></section>'
        '<section><h2>视频编辑</h2><div class="grid"><article class="card"><span class="badge">smoke 配置</span><h3>OpenVE-Bench</h3>'
        '<p class="desc">431 条原视频＋编辑指令，8 类编辑任务。代码直接生成编辑后的 RGB 视频。</p>'
        '<a class="button primary" href="openve.html">查看 smoke 与编辑协议 →</a></article></div></section>'
        '<section><h2>Legacy 与探索入口</h2><div class="grid"><article class="card legacy"><h3>Legacy Physics-IQ full matrix</h3>'
        '<p class="desc">早期 legacy-v1 / 旧 Track 结果，只作历史参考，不计入 native_v2 主实验。</p>'
        '<a class="button" href="matrix_full.html">打开 legacy full matrix →</a></article>'
        '<article class="card legacy"><h3>Older smoke gallery</h3><p class="desc">WorldArena、WBench、WorldScore、AVGen 等 smoke 保留在旧页中。</p>'
        f'<a class="button" href="{HEAVY_BASE}bench_smoke_20261106/index.html">打开旧导航 →</a></article></div></section>'
    )
    cards = re.compile(r'<article class="card feature">.*?</article>', re.DOTALL)
    def with_progress(match):
        card = match.group(0)
        route = next((name for name in suites if f'href="{name}"' in card), None)
        if not route:
            return card
        statuses = [read_json(run_root / "generations" / name / "status.json") for name in suites[route]]
        complete = sum(s.get("totals", {}).get("complete", 0) for s in statuses)
        total = sum(s.get("total_runs", 0) for s in statuses)
        pending = sum(s.get("totals", {}).get("pending", 0) for s in statuses)
        exhausted = sum(s.get("totals", {}).get("exhausted", 0) for s in statuses)
        active = sum(w.get("kind") == "run-case" and w.get("bench") in suites[route]
                     and not w.get("stat", "").startswith("Z") for w in workers)
        explicitly_stopped = all((run_root / "generations" / name / "STOP").exists() for name in suites[route])
        stopped_label = "已停止 · T2V 历史实验" if route in {"vbench2_subset.html", "phygenbench.html"} else "已停止"
        label = stopped_label if explicitly_stopped else ("running" if active else ("待调度" if pending else ("生成结束 · 有未交付任务" if exhausted else "生成完成")))
        card = card.replace('<span class="badge">running</span>', f'<span class="badge">{label} · {active} active</span>')
        updates = [s.get("updated_utc", "") for s in statuses if s.get("updated_utc")]
        latest = [g["latest_completion"] for s in statuses for g in s.get("groups", {}).values()
                  if g.get("latest_completion")]
        stamp = max(updates) if updates else "—"
        last = max(latest) if latest else ("—", "—")
        facts = (f'<div class="facts"><div><strong>{complete:,} / {total:,}</strong>有效视频</div>'
                 f'<div><strong>{active}</strong>正在运行</div><div><strong>{pending:,}</strong>待生成</div>'
                 f'<div><strong>{exhausted:,}</strong>未交付</div></div>'
                 f'<p class="note">状态 UTC：<time>{html.escape(stamp)}</time><br>'
                 f'最近有效交付：{html.escape(str(last[1]))} · {html.escape(str(last[0]))}</p>')
        return card.replace('<a class="button primary"', facts + '<a class="button primary"', 1)
    body = cards.sub(with_progress, body)
    if all((run_root / "generations" / name / "STOP").exists() for name in ("vbench2_subset_full", "phygenbench_full")):
        body = body.replace('四个主 Benchmark', 'I2V 主实验与历史实验')
        body = re.sub(r'<p class="muted">主实验收敛为四个 benchmark：.*?</p>', '<p class="muted">当前 I2V 主实验为 Physics-IQ 与 RoboJudge。VBench-2.0 子集和 PhyGenBench 为已停止的 T2V 历史实验，已有产物保留。</p>', body, flags=re.DOTALL)
    destination.write_text(page("PixelWorld Index", body))


def write_openve_page(run_root: Path, destination: Path) -> None:
    status = read_json(run_root / 'generations/openve_smoke/status.json')
    baselines = [('VACE',1.17),('OmniVideo',1.02),('InsViE',1.40),
                 ('Lucy-Edit',1.95),('ICVE',2.25),('DITTO',2.06),('OpenVE-Edit',2.41)]
    baseline_rows = ''.join(f'<tr><td>{name}</td><td>{score:.2f}</td></tr>' for name,score in baselines)
    body = ('<section class="hero"><p class="eyebrow">OPENVE-BENCH · VIDEO EDITING</p><h1>OpenVE-Bench</h1>'
            '<p class="muted">完整原视频＋编辑指令 → 用代码生成编辑后的 RGB 视频。仅加入 OpenVE，不包含 physics-aware editing / PVIR。</p></section>'
            '<div class="card feature"><span class="badge">单条 smoke · 全量尚未启动</span>'
            + status_facts(status)
            + '<p>当前测试官方第 58 行：把银色轿车换成带蓝色发光细节的未来电动车，保持位置和运动。</p>'
            '<p class="note">输入 1280×720、50 FPS、2.26 秒。PixelWorld 输出 256×144、9 帧、约 3.9823 FPS；保持完整时长与画面比例。4 FPS 是目标采样率，实际帧率根据完整时长计算。</p></div>'
            '<h2>Smoke Model × Track</h2>'
            + model_track_matrix(run_root,'openve_smoke',status,'openve_smoke')
            + '<h2>编辑任务与评测</h2><div class="card"><p>431 条任务：风格 58、背景 59、局部修改 65、添加 67、删除 59、字幕 50、镜头 43、创意 30。</p>'
            '<p>Text 可用代码读取原视频与 RGB 数组，关闭图片检查工具；Vision-Agent 另附首帧和输入接触表，自主决定是否看图与修订。编辑首帧允许改变。每版候选、代码和工具轨迹由 harness 保存。</p>'
            '<p>评测使用官方八类 rubric 与分数解析器。Seed-1.6-VL 按 2 FPS 读取编辑前后的视频；指令遵循、内容与细节保真、画面稳定性按原脚本计算。</p>'
            '<p class="warn">已配好 submission 导出与评测检查接口；Seed-1.6-VL 的评测 API 尚未配置，因此当前没有官方分数。其他 Seed 版本不会自动替代它。</p></div>'
            '<h2>论文参考分数</h2><div class="scroll"><table><tr><th>Model</th><th>Seed-1.6-VL Overall / 5</th></tr>'
            + baseline_rows + '</table></div>'
            '<p class="note">来源：官方论文 v1 Table 2。Runway Aleph 的 3.50 仅来自每类 30 条、共 240 条的子集，单独保留，不作为全 431 条的直接比较。论文模型采用各自官方输入帧数与训练分辨率；PixelWorld 的采样参数另行报告。</p>'
            '<p><a class="button" href="https://arxiv.org/html/2512.07826v1#S3.T2">官方论文 Table 2 ↗</a> '
            '<a class="button" href="https://huggingface.co/datasets/Lewandofski/OpenVE-Bench">官方 431 条数据 ↗</a> '
            '<a class="button" href="https://github.com/SiyuanMaCS/PixelWorld/blob/main/docs/OPENVE_BENCH.md">复现实验说明 ↗</a></p>')
    destination.write_text(page('OpenVE-Bench · PixelWorld',body))


def sync_once(run_root: Path, heavy_web: Path, stable_repo: Path, core_only: bool = False) -> dict:
    waiting = publication_wait(stable_repo, core_only)
    if waiting:
        return waiting
    from tools.sync_incremental_previews import sync_previews
    pixelworld = stable_repo / "pixelworld"
    pixelworld.mkdir(parents=True, exist_ok=True)
    previews = sync_previews(run_root, heavy_web, pixelworld)
    repo_root = Path(__file__).resolve().parents[1]
    legacy_status = heavy_web.parent / "cleanroom_full_matrix_v1/status.json"

    check(
        [
            sys.executable,
            str(repo_root / "tools/build_baseline_monitor.py"),
            "--run-root",
            str(run_root),
            "--web-root",
            str(heavy_web),
            "--legacy-status",
            str(legacy_status),
        ],
        repo_root,
    )
    check(
        [
            sys.executable,
            str(repo_root / "tools/build_robojudge_review.py"),
            "--run-root",
            str(run_root),
            "--web-root",
            str(heavy_web),
            "--case-budget", "0",
        ],
        repo_root,
    )

    pixelworld = stable_repo / "pixelworld"
    pixelworld.mkdir(parents=True, exist_ok=True)
    write_index_page(pixelworld / "index.html", run_root)
    write_index_page(pixelworld / "pixelworld-index.html", run_root)
    rewrite_monitor_html(heavy_web / "physics_iq_baseline.html", pixelworld / "physics_iq_baseline.html")
    rewrite_monitor_html(heavy_web / "robojudge.html", pixelworld / "robojudge.html")
    write_legacy_page(pixelworld / "matrix_full.html")
    write_vbench_page(run_root, pixelworld / "vbench2_subset.html")
    write_phygen_page(run_root, pixelworld / "phygenbench.html")
    write_openve_page(run_root, pixelworld / "openve.html")

    assets_src = heavy_web / "robojudge_assets"
    assets_dst = pixelworld / "robojudge_assets"
    if assets_src.is_dir():
        if assets_dst.exists():
            shutil.rmtree(assets_dst)
        shutil.copytree(assets_src, assets_dst)

    targets = CORE_TARGETS + tuple(previews["targets"])
    gallery = {"changed": False, "commit": None}
    if not core_only:
        write_full_galleries(run_root, pixelworld, "vbench2_subset_full", "VBench-2.0 subset · full")
        write_full_galleries(run_root, pixelworld, "phygenbench_full", "PhyGenBench · full")
        targets = TARGETS

    # A deployment can start during rendering, including one from another project.
    waiting = publication_wait(stable_repo, core_only)
    if waiting:
        return waiting
    targets = tuple(target for target in targets if (stable_repo / target).exists())
    check(["git", "add", *targets], stable_repo)
    staged = run(["git", "diff", "--cached", "--quiet", "--", *targets], stable_repo)
    if staged.returncode == 0:
        return {"changed": False, "commit": None, "core_only": core_only, "gallery": gallery}

    message = "Update PixelWorld benchmark monitor pages" if core_only else "Update PixelWorld benchmark monitor pages and galleries"
    check(["git", "commit", "-m", message], stable_repo)
    commit = run(["git", "rev-parse", "HEAD"], stable_repo).stdout.strip()
    push = run(["git", "push", "origin", "main"], stable_repo)
    if push.returncode:
        raise RuntimeError(f"git push failed\nSTDOUT:\n{push.stdout}\nSTDERR:\n{push.stderr}")
    return {"changed": True, "commit": commit, "core_only": core_only, "gallery": gallery}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--heavy-web", type=Path, required=True)
    parser.add_argument("--stable-repo", type=Path, required=True)
    parser.add_argument("--status", type=Path, required=True)
    parser.add_argument("--interval", type=int, default=600)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--core-only", action="store_true", help="sync only lightweight monitor pages, not full galleries")
    args = parser.parse_args()

    args.status.parent.mkdir(parents=True, exist_ok=True)
    lock_path = args.status.with_suffix(".lock")
    iteration = 0
    while True:
        started = time.time()
        try:
            with lock_path.open("w") as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    payload = {
                        "status": "skipped_lock_busy",
                        "iteration": iteration,
                        "updated_unix": time.time(),
                        "duration_seconds": time.time() - started,
                        "interval_seconds": args.interval,
                        "next_iteration_unix": None if args.once else time.time() + args.interval,
                    }
                    print(json.dumps(payload, ensure_ascii=False), flush=True)
                    if args.once:
                        break
                    iteration += 1
                    time.sleep(args.interval)
                    continue
                result = sync_once(
                    args.run_root.resolve(),
                    args.heavy_web.resolve(),
                    args.stable_repo.resolve(),
                    core_only=args.core_only,
                )
                payload = {
                    "status": "ok",
                    "iteration": iteration,
                    "updated_unix": time.time(),
                    "duration_seconds": time.time() - started,
                    "interval_seconds": args.interval,
                    "next_iteration_unix": None if args.once else time.time() + args.interval,
                    **result,
                }
                args.status.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
        except Exception as exc:  # Keep the watcher alive; make failures inspectable.
            payload = {
                "status": "error",
                "iteration": iteration,
                "updated_unix": time.time(),
                "duration_seconds": time.time() - started,
                "interval_seconds": args.interval,
                "next_iteration_unix": None if args.once else time.time() + args.interval,
                "error": str(exc),
            }
            args.status.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
        print(json.dumps(payload, ensure_ascii=False), flush=True)
        if args.once:
            break
        iteration += 1
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
