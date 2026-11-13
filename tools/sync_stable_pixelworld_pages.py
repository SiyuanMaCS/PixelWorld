"""Sync monitor pages and bounded case previews into the stable site repository.

Optional Pages delivery keeps exact media on main and publishes a small HTML
branch. The legacy heavy-site links remain available for historical artifacts.
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
import tempfile
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
    "pixelworld/physics_iq_512w24fps.html",
    "pixelworld/robojudge.html",
    "pixelworld/matrix_full.html",
    "pixelworld/vbench2_subset.html",
    "pixelworld/phygenbench.html",
    "pixelworld/phygen_pixelspace.html",
    "pixelworld/phygen_pixelspace_smoke",
    "pixelworld/phygen_qwen_init",
    "pixelworld/openve.html",
    "pixelworld/openve_smoke",
    "pixelworld/pcve_rigid.html",
    "pixelworld/pcve_smoke",
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

HIDDEN_MODELS = {"gemini38-flash"}
MODEL_ORDER = ["gpt61-sol", "gpt56-sol", "gpt6-astra", "deepseek-v41", "seed21-pro"]
TRACK_ORDER = ["text", "vision-agent"]
TRACK_LABELS = {"text": "Text", "vision-agent": "Vision"}


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
        ["git", "credential", "fill"], cwd=Path(__file__).resolve().parents[1],
        input="protocol=https\nhost=github.com\n\n", text=True, capture_output=True,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "Never"},
        timeout=30,
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


def _quarantine_item_path(item: dict) -> str:
    for key in ("from", "path", "original", "source"):
        value = item.get(key)
        if value:
            return str(value)
    return ""


def _quarantine_root(item: dict) -> str | None:
    if item.get("root"):
        return str(item["root"])
    value = _quarantine_item_path(item)
    if not value:
        return None
    if "generations/" in value:
        value = value.split("generations/", 1)[1]
    value = value.lstrip("/")
    return value.split("/", 1)[0] if value else None


def _quarantine_model_track(item: dict) -> tuple[str | None, str | None]:
    model, track = item.get("model"), item.get("track")
    if model and track:
        return str(model), str(track)
    value = _quarantine_item_path(item)
    if "generations/" in value:
        value = value.split("generations/", 1)[1]
    parts = value.strip("/").split("/")
    if len(parts) >= 3:
        return parts[1], parts[2]
    return (str(model) if model else None, str(track) if track else None)


def quarantine_stats(run_root: Path, roots: set[str] | tuple[str, ...] | list[str]) -> dict:
    wanted = set(roots)
    total = 0
    by_group: dict[tuple[str, str], int] = {}
    reasons: dict[str, int] = {}
    for audit_path in (run_root / "_quarantine").glob("*/audit.json"):
        audit = read_json(audit_path)
        items = audit.get("items") or []
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            if _quarantine_root(item) not in wanted:
                continue
            total += 1
            reason = str(item.get("reason") or audit.get("classification") or "infra_or_recovery")
            reasons[reason] = reasons.get(reason, 0) + 1
            model, track = _quarantine_model_track(item)
            if model and track:
                by_group[(model, track)] = by_group.get((model, track), 0) + 1
    return {"total": total, "by_group": by_group, "reasons": reasons}


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
    try:groups=json.loads((source/'status.json').read_text()).get('groups',{})
    except (OSError,ValueError):groups={}
    immutable=bool(groups) and all(g.get('counts',{}).get('complete',0)>0 and g['counts']['complete']==sum(g['counts'].values()) for g in groups.values())
    signature=[]
    for key, group in sorted(groups.items()):
        model,track=key.split('/',1)
        try:stamp=(source/model/track).stat().st_mtime_ns
        except OSError:stamp=None
        signature.append([key,group.get('counts'),group.get('latest_completion'),stamp])
    cache=run_root/'publication_stats_cache'/f'{benchmark}.json'
    if immutable and cache.is_file():
        try:
            saved=json.loads(cache.read_text())
            if saved['signature']==signature:return {tuple(k.split('/',1)):v for k,v in saved['stats'].items()}
        except (OSError,ValueError,KeyError):pass
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
    if immutable:
        cache.parent.mkdir(exist_ok=True)
        temporary=cache.with_suffix('.tmp')
        temporary.write_text(json.dumps({'signature':signature,'stats':{'/'.join(k):v for k,v in stats.items()}}))
        temporary.replace(cache)
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
            f"<td>{html.escape(str(model))}<br><span class=status>{html.escape(TRACK_LABELS.get(track, track))}</span></td>"
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
    infra_stats = quarantine_stats(run_root, [benchmark])
    groups = status.get("groups", {})
    seen_models = {key.split("/")[0] for key in groups} - HIDDEN_MODELS
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
            infra_count = infra_stats["by_group"].get((model_key, track), 0)
            pending = counts.get("pending", max(total - complete - running - exhausted, 0))
            latest = group.get("latest_completion")
            if isinstance(latest, list) and len(latest) >= 2:
                latest_time, latest_case = latest[0], latest[1]
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
            stopped = (source/'STOP').exists()
            activity = "PAUSED" if stopped else ("ACTIVE" if running else ("DONE" if complete >= total and total else ("RETRY" if exhausted else "QUEUED")))
            activity_class = "badge" if activity == "ACTIVE" else "pill"
            cells.append(
                '<td class="run-cell">'
                '<div class="run-top">'
                f'<span><span class="{activity_class}">{activity}</span> <span class="run-name">{html.escape(TRACK_LABELS.get(track, track))}</span></span>'
                f'<span class="run-num">{complete}/{total}</span>'
                '</div>'
                f'<div class="run-meta"><span class="live">{running} running</span> · {pending} pending · '
                f'<span class="bad">{exhausted} 模型未交付/待重试</span></div>'
                + (f'<div class="run-meta warn">{infra_count} infra/recovery attempts quarantined</div>' if infra_count else "")
                + f'<div class="run-meta">latest: {html.escape(str(latest_case))}<br>{html.escape(str(latest_time))}</div>'
                + f'<div class="run-meta">avg time {fmt_seconds(stats.get("avg_duration"))} · '
                + f'avg output {fmt_number(stats.get("avg_output_tokens"))} tok · '
                + f'avg reasoning {fmt_number(stats.get("avg_reasoning_tokens"))} tok</div>'
                + (f'<div class="run-meta">running case: {html.escape(running_cases)}</div>' if running_cases else "")
                + (f'<div class="run-meta">activity: {running_activity}</div>' if running_activity else "")
                + (f'<div class="run-meta warn">recent exhausted: {html.escape(exhausted_cases)}</div>' if exhausted_cases else "")
                + f'<div class="run-links"><a class="link" href="{gallery}">视频与逐轮候选 →</a></div>'
                + '</td>'
            )
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return (
        '<div class=scroll><table class=matrix><tr><th>Model</th>'
        '<th>Text</th><th>Vision</th></tr>'
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
        if key.split("/", 1)[0] in HIDDEN_MODELS:
            continue
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


def _model_counts(statuses: list[dict], model: str) -> tuple[int, int, int, int]:
    complete = running = exhausted = total = 0
    seen = False
    for status in statuses:
        for key, group in status.get("groups", {}).items():
            if key.split("/")[0] != model:
                continue
            seen = True
            counts = group.get("counts", {})
            complete += counts.get("complete", 0)
            running += counts.get("running", 0)
            exhausted += counts.get("exhausted", 0) + counts.get("failed", 0)
            total += sum(counts.values()) or status.get("cases", 0)
    return (complete, total, running, exhausted) if seen else (0, 0, 0, 0)


def _model_cell(values: tuple[int, int, int, int]) -> str:
    complete, total, running, exhausted = values
    if not total:
        return '<td class="status">—</td>'
    state = "ACTIVE" if running else ("DONE" if complete == total else ("RETRY" if exhausted else "QUEUED"))
    return (f'<td><span class="{"badge" if running else "pill"}">{state}</span> '
            f'<strong>{complete}/{total}</strong>'
            f'<span class=status>{running} running · {exhausted} failed</span></td>')


def model_overview_table(run_root: Path) -> str:
    """One row per model on the main page; model additions should appear here."""
    physics = [
        read_json(run_root / "generations/physics_iq/status.json"),
        read_json(run_root / "generations/physics_iq_gpt_native_v2/status.json"),
        read_json(run_root / "generations/physics_iq_seed21_native_v2/status.json"),
    ]
    robojudge = [
        read_json(run_root / "generations/robojudge/status.json"),
        read_json(run_root / "generations/robojudge_seed21_native_v2/status.json"),
    ]
    pcve = [read_json(run_root / "generations/pcve_smoke/status.json")]
    paired = run_root.parent / "phygen_pixelspace_v2_20261112" / "generations"
    phygen = [read_json(path) for path in paired.glob("*/status.json")]

    all_models = set(MODEL_ORDER)
    for group in (physics + robojudge + pcve + phygen):
        all_models.update(key.split("/")[0] for key in group.get("groups", {})
                          if key.split("/")[0] not in HIDDEN_MODELS)
    order = [m for m in MODEL_ORDER if m in all_models] + sorted(all_models - set(MODEL_ORDER))

    rows = []
    for model in order:
        if model in HIDDEN_MODELS:
            continue
        if model not in MODEL_LABELS and all(not _model_counts(group, model)[1] for group in (physics, robojudge, pcve, phygen)):
            continue
        rows.append(
            '<tr>'
            f'<td><strong>{html.escape(MODEL_LABELS.get(model, model))}</strong><br><span class=status>{html.escape(model)}</span></td>'
            + _model_cell(_model_counts(physics, model))
            + _model_cell(_model_counts(robojudge, model))
            + _model_cell(_model_counts(pcve, model))
            + _model_cell(_model_counts(phygen, model))
            + '</tr>'
        )
    return ('<section><h2>模型 × Benchmark 总览</h2>'
            '<p class=note>主页监控表直接读取各 benchmark 的 status.json；新增模型进入 config 后会自动出现在这里。</p>'
            '<div class=scroll><table><tr><th>Model</th><th>Physics-IQ</th><th>RoboJudge</th><th>PCVE</th><th>PhyGen smoke</th></tr>'
            + ''.join(rows) + '</table></div></section>')


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


def protocol_audit_notice(run_root: Path, benchmark: str) -> str:
    audit = read_json(run_root / f"evaluation/{benchmark}_official_protocol_audit.json")
    if not audit:
        return ""
    if benchmark == "vbench2":
        return ('<div class="card legacy"><h3>官方采样要求待确认</h3>'
                '<p>标准模式每个 prompt 要求 3 份独立视频；当前每个只有 1 份。'
                '现有生成继续保留，当前单样本覆盖不能作为标准三样本结果。'
                '不复制视频补齐；追加生成等待实验负责人决定。</p>'
                '<a class="link" href="https://github.com/SiyuanMaCS/PixelWorld/blob/main/docs/VBENCH2_OFFICIAL_PROTOCOL_AUDIT.md">官方代码审计 →</a></div>')
    return ('<div class="card legacy"><h3>官方评测依赖待配置</h3>'
            '<p>160 条 caption 已与官方逐条核对。主榜组合使用 VQAScore、'
            'GPT-4o-0513、LLaVA-Interleave 和 InternVideo2；当前尚无已确认的 '
            'GPT-4o-0513 接口。开源分支分数不能直接替代主榜组合分数。</p>'
            '<a class="link" href="https://github.com/SiyuanMaCS/PixelWorld/blob/main/docs/PHYGENBENCH_OFFICIAL_PROTOCOL_AUDIT.md">官方代码审计 →</a></div>')


def write_vbench_page(run_root: Path, destination: Path) -> None:
    legacy = run_root / "legacy/t2v_pre_pixelspace_v2_20261112/vbench2_subset_full"
    if legacy.exists():
        destination.write_text(page("VBench-2.0 · legacy", (
            '<section class=hero><p class=eyebrow>LEGACY · VBENCH-2.0</p><h1>VBench-2.0 历史实验</h1>'
            '<p class=muted>此前的 T2V 五维子集已经归档，不再属于当前 PixelWorld 实验。</p></section>'
            '<div class=card><p>归档原因：旧 T2V 条件无法清楚地区分直接 RGB 像素生成与场景/渲染式生成。'
            '保留全部旧产物供审计，但不继续生成、评测或报告分数。</p>'
            '<p><a class="button" href="index.html">返回当前实验 →</a></p></div>'
        )))
        return
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
        + protocol_audit_notice(run_root, "vbench2")
        + "<h2>Model × Track Progress</h2>"
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
    legacy = run_root / "legacy/t2v_pre_pixelspace_v2_20261112/phygenbench_full"
    if legacy.exists():
        destination.write_text(page("PhyGenBench · legacy", (
            '<section class=hero><p class=eyebrow>LEGACY · PHYGENBENCH</p><h1>PhyGenBench 历史 T2V 实验</h1>'
            '<p class=muted>此前纯文本 T2V 运行已归档。当前只使用新的直接 RGB 像素空间 paired T2V/I2V 协议。</p></section>'
            '<div class=card><p>旧视频和轨迹完整保留作历史证据，但不再纳入当前结果或继续调度。</p>'
            '<p><a class="button primary" href="phygen_pixelspace.html">打开当前 paired protocol →</a></p></div>'
        )))
        return
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
        + protocol_audit_notice(run_root, "phygenbench")
        + "<h2>Model × Track Progress</h2>"
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
        body = body.replace('running · native_v2', '已暂停 · 保留已有视频')
        body = body.replace('<h2>Model × Track Progress</h2>', '<p class="note">按用户要求暂停新增生成和评测；已有视频与轨迹继续同步。</p><h2>Model × Track Progress</h2>')
    if (destination.parent/'phygen_quick/index.html').is_file():
        body = '<p><a class="button primary" href="phygen_quick/index.html">▶ 直接看已提交的视频 →</a></p>' + body
    destination.write_text(page("PhyGenBench · PixelWorld", body))


def write_index_page(destination: Path, run_root: Path) -> None:
    # Labels come from a read-only process snapshot, not hand-written badges.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools.inspect_live_workers import inspect_workers
    workers = inspect_workers(run_root.resolve())
    suites = {
        "robojudge.html": ("robojudge", "robojudge_seed21_native_v2"),
        "physics_iq_baseline.html": ("physics_iq", "physics_iq_gpt_native_v2", "physics_iq_seed21_native_v2"),
        "physics_iq_512w24fps.html": ("physics_iq_512w24fps_gpt_native",),
        "vbench2_subset.html": ("vbench2_subset_full",),
        "phygenbench.html": ("phygenbench_full",),
        "openve.html": ("openve_smoke",),
        "pcve_rigid.html": ("pcve_smoke",),
    }
    body = (
        '<section class="hero"><p class="eyebrow">PIXELWORLD MAIN BENCHMARKS</p><h1>PixelWorld Index</h1>'
        '<p class="muted">当前主线是 4+1：Physics-IQ、RoboJudge、PCVE-RigidBench、PhyGenBench 官方 T2V，加上 PhyGenBench paired I2V 扩展。VBench-2.0 已归档。'
        "WorldArena、WBench、WorldScore 等保留为历史/探索入口，不再作为主线。</p></section>"
        '<section id="benchmarks"><h2>主 Benchmark 与进度</h2><div class="grid">'
        '<article class="card feature"><span class="badge">running</span><h3>RoboJudge shared-50</h3>'
        '<p class="desc">50 shared embodied generation prompts x Text/Vision</p>'
        '<p class="note">Original RoboJudge-9B scoring; Table8 comparability remains explicitly gated.</p>'
        '<a class="button primary" href="robojudge.html">打开页面 →</a></article>'
        '<article class="card feature"><span class="badge">running</span><h3>Physics-IQ Verified</h3>'
        '<p class="desc">198 official BPP/I2V prompts x Text/Vision</p>'
        '<p class="note">Native v2 GPT rerun is separate from legacy-v1 reference results.</p>'
        '<a class="button primary" href="physics_iq_baseline.html">打开页面 →</a></article>'
        '<article class="card feature"><span class="badge">running</span><h3>Physics-IQ 512w24fps</h3>'
        '<p class="desc">512×288 · 24 FPS · 120 frames · GPT-6.1-Sol / GPT-5.6-Sol × Text/Vision。</p>'
        '<p class="note">分辨率/FPS敏感性分析 run，不替代主 Physics-IQ Verified 4FPS leaderboard。</p>'
        '<a class="button primary" href="physics_iq_512w24fps.html">打开高质量 run →</a></article>'
        '<article class="card feature"><span class="badge">running</span><h3>PhyGenBench · T2V + I2V</h3>'
        '<p class="desc">160 条官方物理 prompt 的 T2V 正式评测，并补充同 prompt + Qwen-Image-2.1 预动作首帧的 I2V 扩展。</p>'
        '<p class="note">Qwen 仅用于 I2V 初始帧；所有视频帧仍由 coding agent 直接输出 RGB 像素。</p>'
        '<a class="button primary" href="phygen_pixelspace.html">打开 PhyGen 协议与进度 →</a></article>'
        '<article class="card feature"><span class="badge">running</span><h3>PCVE-RigidBench · 必跑</h3>'
        '<p class="desc">129 条官方物理反事实视频编辑 × 五模型 × Text/Vision，共 1,290 条视频；复用已有成功 smoke。</p>'
        '<p class="note">定量英语指令 · 96 帧 / 24 FPS / 4 秒 · 目标视频和物理真值仅用于评测。</p>'
        '<a class="button primary" href="pcve_rigid.html">打开 PCVE 进度 →</a></article>'
        '</div></section>'
        + model_overview_table(run_root) +
        '<section><h2>候选与历史</h2><div class="grid"><article class="card legacy"><span class="badge">optional smoke</span><h3>OpenVE-Bench</h3>'
        '<p class="desc">431 条原视频＋编辑指令，8 类编辑任务。保留已完成的单条 smoke，暂不启动全量。</p>'
        '<a class="button" href="openve.html">查看 smoke 与编辑协议 →</a></article></div></section>'
        '<section><h2>Legacy 与探索入口</h2><div class="grid"><article class="card legacy"><h3>Legacy Physics-IQ full matrix</h3>'
        '<p class="desc">早期 legacy-v1 / 旧 Track 结果，只作历史参考，不计入 native_v2 主实验。</p>'
        '<a class="button" href="matrix_full.html">打开 legacy full matrix →</a></article>'
        '<article class="card legacy"><h3>Archived T2V experiments</h3><p class="desc">VBench-2.0 subset 与 pre-v2 PhyGenBench T2V 完整保留，但不计入当前 4+1 协议。</p>'
        '<a class="button" href="vbench2_subset.html">VBench archive →</a><a class="button" href="phygenbench.html">PhyGen pre-v2 →</a></article>'
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
        infra = quarantine_stats(run_root, suites[route])["total"]
        complete = sum(s.get("totals", {}).get("complete", 0) for s in statuses)
        total = sum(s.get("total_runs", 0) for s in statuses)
        pending = sum(s.get("totals", {}).get("pending", 0) for s in statuses)
        exhausted = sum(s.get("totals", {}).get("exhausted", 0) for s in statuses)
        process_active = sum(w.get("kind") == "run-case" and w.get("bench") in suites[route]
                             and not w.get("stat", "").startswith("Z") for w in workers)
        status_active = sum(s.get("totals", {}).get("running", 0) for s in statuses)
        active = max(process_active, status_active) if route == "physics_iq_512w24fps.html" else process_active
        explicitly_stopped = all((run_root / "generations" / name / "STOP").exists() for name in suites[route])
        stopped_label = "已停止 · T2V 历史实验" if route in {"vbench2_subset.html", "phygenbench.html"} else "已停止"
        label = stopped_label if explicitly_stopped else ("running" if active else ("待调度" if pending else ("模型未交付 · 等待重试" if exhausted else ("生成完成" if total and complete == total else "等待任务状态更新"))))
        if route == 'openve.html' or (route == 'pcve_rigid.html' and not any(s.get('cases', 0) == 129 for s in statuses)):
            label = 'smoke · ' + label
        card = card.replace('<span class="badge">running</span>', f'<span class="badge">{label} · {active} active</span>')
        updates = [s.get("updated_utc", "") for s in statuses if s.get("updated_utc")]
        latest = [g["latest_completion"] for s in statuses for g in s.get("groups", {}).values()
                  if g.get("latest_completion")]
        stamp = max(updates) if updates else "—"
        last = max(latest) if latest else ("—", "—")
        facts = (f'<div class="facts"><div><strong>{complete:,} / {total:,}</strong>有效视频</div>'
                 f'<div><strong>{active}</strong>正在运行</div><div><strong>{pending:,}</strong>待生成</div>'
                 f'<div><strong>{exhausted:,}</strong>模型未交付</div>'
                 f'<div><strong>{infra:,}</strong>infra/recovery</div></div>'
                 f'<p class="note">状态 UTC：<time>{html.escape(stamp)}</time><br>'
                 f'最近有效交付：{html.escape(str(last[1]))} · {html.escape(str(last[0]))}</p>')
        return card.replace('<a class="button primary"', facts + '<a class="button primary"', 1)
    body = cards.sub(with_progress, body)
    preview = read_json(run_root / 'preview_sync_progress.json')
    if preview:
        body += ('<section><h2>视频详情同步</h2><div class="card">'
                 f'<p>本轮处理 {preview.get("prepared_details",0)} 条详情；'
                 f'仍有 {preview.get("remaining_video_details",0)} 条已生成视频的详情等待同步。</p>'
                 f'<p class=note>详情检查时间 UTC：{html.escape(str(preview.get("updated_utc","—")))}。'
                 '生成完成数量与网页详情同步数量分别统计；正在同步的案例保留原始产物和逐轮记录。</p></div></section>')
    destination.write_text(page("PixelWorld Index", body))


def write_phygen_pixelspace_page(run_root: Path, destination: Path) -> None:
    """Publish the current PhyGenBench T2V plus paired I2V protocol."""
    paired = run_root.parent / "phygen_pixelspace_v2_20261112"
    condition_names = {
        "t2v": "T2V official prompt · direct RGB",
        "i2v_qweninit": "I2V-QwenInit extension · direct RGB",
        "t2v_deepseek": "T2V official prompt · direct RGB",
        "i2v_qweninit_deepseek": "I2V-QwenInit extension · direct RGB",
    }
    statuses = {name: read_json(paired / "generations" / name / "status.json")
                for name in condition_names}
    rows = []
    total_valid = 0
    for name, label in condition_names.items():
        status = statuses[name]
        for key, group in sorted(status.get("groups", {}).items()):
            model_key, track = key.split("/", 1)
            if model_key in HIDDEN_MODELS:
                continue
            counts = group.get("counts", {})
            valid = counts.get("complete", 0)
            total_valid += valid
            latest = group.get("latest_completion") or ["—", "—"]
            rows.append(f'<tr><td>{label}</td><td>{html.escape(MODEL_LABELS.get(model_key, model_key))}</td><td>{TRACK_LABELS.get(track, track)}</td>'
                        f'<td>{valid} / 4</td><td>{counts.get("running",0)}</td>'
                        f'<td>{counts.get("pending",0)}</td><td>{counts.get("exhausted",0)}</td>'
                        f'<td>{html.escape(str(latest[1]))}<br>{html.escape(str(latest[0]))}</td></tr>')
    smoke = destination.parent / "phygen_pixelspace_smoke/index.html"
    smoke_link = ('<a class="button primary" href="phygen_pixelspace_smoke/index.html">播放已完成 smoke 视频 →</a>'
                  if total_valid and smoke.is_file() else
                  '<span class="note">尚无格式有效视频；有效视频出现后才会开放播放入口。</span>')
    body = ('<section class=hero><p class=eyebrow>PHYGENBENCH · PIXEL-SPACE T2V + I2V</p>'
            '<h1>PhyGenBench 官方 T2V 与 I2V 扩展</h1>'
            '<p class=muted>正式 T2V 使用 160 条官方物理 prompt；I2V 扩展在同一 prompt 上加入高质量预动作首帧，用来分析初始视觉状态如何改变 direct-RGB coding agent 的生成边界。</p></section>'
            '<div class="card feature"><span class=badge>smoke running</span>'
            '<p>T2V 从文本直接生成全部帧并进入官方 PhyGenBench 评测；I2V 使用 Qwen-Image-2.1 生成并人工核验的预动作首帧。'
            'Qwen 从不参与视频后续帧生成，I2V 分数单独报告为 PixelWorld 扩展。</p><p>两种条件均禁止 3D renderer、物理引擎和外部图像/视频模型；'
            '但允许 Python/NumPy/PIL 的局部像素、纹理、光照、warp 和运动计算。</p>' + smoke_link + '</div>'
            '<h2>Smoke progress</h2><div class=scroll><table><tr><th>Condition</th><th>Model</th><th>Track</th><th>Valid video</th><th>Running</th><th>Pending</th><th>Terminal failure</th><th>Latest</th></tr>'
            + ''.join(rows) + '</table></div>'
            '<h2>已核验的 I2V 初态</h2><div class=card><p>四条 smoke 覆盖失重倒水、镜像、热相变、颜料混合。'
            '首帧均来自 pinned Qwen-Image-2.1 revision，并且下采样后的实际输入已读图复核。</p>'
            '<p><a class="button primary" href="phygen_qwen_init/index.html">查看 Qwen init frames →</a> '
            '<a class="button" href="https://github.com/SiyuanMaCS/PixelWorld/blob/main/docs/PHYGENBENCH_PIXELSPACE_PAIRED_V2.md">完整协议 →</a></p></div>'
            '<h2>旧实验</h2><div class=card><p>旧 PhyGenBench 与 VBench T2V 运行已转入 legacy；它们不参与此处结果。</p>'
            '<a class="button" href="phygenbench.html">旧 PhyGen 说明 →</a> <a class="button" href="vbench2_subset.html">旧 VBench 说明 →</a></div>')
    destination.write_text(page("PhyGenBench paired pixel-space protocol", body))


def write_phygen_qwen_init_page(run_root: Path, destination: Path) -> None:
    """Publish visually selected Qwen-Image initial frames for PhyGenBench I2V."""
    from PIL import Image

    repo_root = run_root.parent.parent
    qwen_root = repo_root / "runs/phygen_i2v_qwen21_20261111"
    paired_root = repo_root / "runs/phygen_pixelspace_v2_20261112"
    destination.parent.mkdir(parents=True, exist_ok=True)
    thumbs = destination.parent / "thumbs"
    thumbs.mkdir(parents=True, exist_ok=True)
    selected = sorted(qwen_root.glob("selected/phygen_*/selection.json"))
    cards = []
    smoke_ids = {"phygen_001", "phygen_061", "phygen_091", "phygen_121"}
    for record_path in selected:
        record = json.loads(record_path.read_text())
        case_id = record["case_id"]
        image_path = record_path.with_name("first_frame.png")
        thumb_name = f"{case_id}.jpg"
        thumb_path = thumbs / thumb_name
        if (not thumb_path.exists()
                or thumb_path.stat().st_mtime_ns < image_path.stat().st_mtime_ns):
            Image.open(image_path).convert("RGB").resize((320, 180), Image.Resampling.LANCZOS).save(
                thumb_path, quality=86, optimize=True)
        badge = '<span class="badge">smoke</span>' if case_id in smoke_ids else ''
        note = html.escape(record.get("review_notes", ""))
        cards.append(
            f'<article class="card"><img src="thumbs/{thumb_name}" '
            'style="width:100%;aspect-ratio:16/9;object-fit:cover;border-radius:8px;background:#080c12">'
            f'<h3>{html.escape(case_id)} {badge}</h3>'
            f'<p class="note">candidate {record.get("selected_candidate", "—")} · sha {html.escape(record.get("image_sha256", "")[:12])}</p>'
            f'<p class="desc">{note}</p></article>')
    contact = paired_root / "i2v_input_contact_sheet.png"
    contact_html = ""
    if contact.is_file():
        shutil.copy2(contact, destination.parent / "smoke_contact_sheet.png")
        contact_html = ('<h2>Smoke 4-frame contact sheet</h2><div class="card">'
                        '<img src="smoke_contact_sheet.png" style="width:100%;height:auto;border-radius:8px"></div>')
    summary = read_json(qwen_root / "selection_complete.json")
    body = (
        '<section class=hero><p class=eyebrow>QWEN-IMAGE INITIAL FRAMES</p>'
        '<h1>PhyGenBench I2V · selected init frames</h1>'
        '<p class=muted>Qwen-Image-2.1 只用于生成动作发生前的静态首帧；PixelWorld 视频后续帧仍由 coding agent 直接输出 RGB。</p></section>'
        f'<div class="card feature"><span class=badge>{len(selected)} / 160 selected</span>'
        f'<p>选择状态：{html.escape(str(summary.get("phase", "unknown")))}。每张图都有 selection.json 和实际读图证据；这里展示下采样缩略图用于快速审核。</p>'
        '<p><a class="button primary" href="../phygen_pixelspace.html">返回 paired protocol →</a> '
        '<a class="button" href="../phygen_pixelspace_smoke/index.html">查看 smoke 视频 →</a></p></div>'
        + contact_html +
        '<h2>All selected frames</h2><div class=grid>' + ''.join(cards) + '</div>')
    destination.write_text(page("PhyGenBench Qwen init frames", body))


def write_openve_page(run_root: Path, destination: Path) -> None:
    status = read_json(run_root / 'generations/openve_smoke/status.json')
    baselines = [('VACE',1.17),('OmniVideo',1.02),('InsViE',1.40),
                 ('Lucy-Edit',1.95),('ICVE',2.25),('DITTO',2.06),('OpenVE-Edit',2.41)]
    baseline_rows = ''.join(f'<tr><td>{name}</td><td>{score:.2f}</td></tr>' for name,score in baselines)
    body = ('<section class="hero"><p class="eyebrow">OPENVE-BENCH · VIDEO EDITING</p><h1>OpenVE-Bench</h1>'
            '<p class="muted">完整原视频＋编辑指令 → 用代码生成编辑后的 RGB 视频。OpenVE 可选，暂不启动全量；PCVE-RigidBench 必跑，PVIR 不测。</p></section>'
            '<div class="card feature"><span class="badge">单条 smoke · 全量尚未启动</span>'
            + status_facts(status)
            + '<p>当前测试官方第 58 行：把银色轿车换成带蓝色发光细节的未来电动车，保持位置和运动。</p>'
            '<p class="note">输入 1280×720、50 FPS、2.26 秒。PixelWorld 输出 256×144、9 帧、约 3.9823 FPS；保持完整时长与画面比例。4 FPS 是目标采样率，实际帧率根据完整时长计算。</p></div>'
            '<h2>Smoke Model × Track</h2>'
            + model_track_matrix(run_root,'openve_smoke',status,'openve_smoke')
            + '<h2>编辑任务与评测</h2><div class="card"><p>431 条任务：风格 58、背景 59、局部修改 65、添加 67、删除 59、字幕 50、镜头 43、创意 30。</p>'
            '<p>Text 可用代码读取原视频与 RGB 数组，关闭图片检查工具；Vision 另附首帧和输入接触表，自主决定是否看图与修订。编辑首帧允许改变。每版候选、代码和工具轨迹由 harness 保存。</p>'
            '<p>评测使用官方八类 rubric 与分数解析器。Seed-1.6-VL 按 2 FPS 读取编辑前后的视频；指令遵循、内容与细节保真、画面稳定性按原脚本计算。</p>'
            '<p class="warn">已配好 submission 导出与评测检查接口；Seed-1.6-VL 的评测 API 尚未配置，因此当前没有官方分数。其他 Seed 版本不会自动替代它。</p></div>'
            '<h2>论文参考分数</h2><div class="scroll"><table><tr><th>Model</th><th>Seed-1.6-VL Overall / 5</th></tr>'
            + baseline_rows + '</table></div>'
            '<p class="note">来源：官方论文 v1 Table 2。Runway Aleph 的 3.50 仅来自每类 30 条、共 240 条的子集，单独保留，不作为全 431 条的直接比较。论文模型采用各自官方输入帧数与训练分辨率；PixelWorld 的采样参数另行报告。</p>'
            '<p><a class="button" href="https://arxiv.org/html/2512.07826v1#S3.T2">官方论文 Table 2 ↗</a> '
            '<a class="button" href="https://huggingface.co/datasets/Lewandofski/OpenVE-Bench">官方 431 条数据 ↗</a> '
            '<a class="button" href="https://github.com/SiyuanMaCS/PixelWorld/blob/main/docs/OPENVE_BENCH.md">复现实验说明 ↗</a></p>')
    destination.write_text(page('OpenVE-Bench · PixelWorld',body))


def write_physics_highres_page(run_root: Path, destination: Path) -> None:
    status = read_json(run_root / "generations/physics_iq_512w24fps_gpt_native/status.json")
    config = read_json(run_root / "physics_iq_512w24fps_gpt_native_full.json")
    manifest = read_json(run_root / "inputs/physics_iq_512w24fps_manifest.json")
    body = (
        '<section class=hero><p class=eyebrow>PHYSICS-IQ · 512W24FPS ANALYSIS</p>'
        '<h1>Physics-IQ 512w24fps</h1>'
        '<p class=muted>高分辨率 / 标准视频帧率分析 run：512×288，24 FPS，120 帧，5 秒。'
        '模型为 GPT-6.1-Sol 与 GPT-5.6-Sol，Text/Vision 两个 Track。</p></section>'
        '<div class="card feature"><span class=badge>analysis run · full 198</span>'
        + status_facts(status) +
        '<p>Scope：198 cases × 2 models × 2 tracks = 792 videos。'
        '这是分辨率/FPS敏感性分析，不替代主 Physics-IQ Verified 4FPS leaderboard。</p>'
        '<p class=note>输出契约：512×288 · 24 FPS · 120 frames。Frame 00 必须严格等于 512×288 的 prepared first_frame.png。</p>'
        '<p><a class="button" href="https://github.com/SiyuanMaCS/PixelWorld/blob/main/docs/HIGH_RES_FPS_ABLATION.md">GitHub 协议说明 ↗</a> '
        '<a class="button" href="https://github.com/SiyuanMaCS/PixelWorld/blob/main/configs/physics-iq-512w24fps.example.json">配置模板 ↗</a></p></div>'
        '<h2>Model × Track Progress</h2>'
        + model_track_matrix(run_root, "physics_iq_512w24fps_gpt_native", status, "physics_iq_512w24fps_gpt_native")
        + '<h2>配置</h2><div class=scroll><table>'
        + f'<tr><th>Protocol</th><td>{html.escape(str(config.get("protocol", "—")))}</td></tr>'
        + f'<tr><th>Inputs</th><td>{html.escape(str(config.get("inputs_root", "—")))}</td></tr>'
        + f'<tr><th>Runs</th><td>{html.escape(str(config.get("runs_root", "—")))}</td></tr>'
        + f'<tr><th>Prepared cases</th><td>{len(manifest.get("cases", [])) or status.get("cases", "—")}</td></tr>'
        + f'<tr><th>Output token budget</th><td>{html.escape(str(config.get("output_token_budget", "—")))}</td></tr>'
        + f'<tr><th>Max total attempts</th><td>{html.escape(str(config.get("max_total_attempts", "—")))}</td></tr>'
        + '</table></div>'
    )
    destination.write_text(page('Physics-IQ 512w24fps · PixelWorld', body))


def write_pcve_page(run_root: Path, destination: Path) -> None:
    status=read_json(run_root/'generations/pcve_smoke/status.json')
    full = status.get('cases') == 129
    scope_label = '全量 · 五模型 × 两个 Track' if full else '五模型 smoke · 全量输入准备中'
    scope_text = ('129 条 × 5 个模型 × Text/Vision，共 1,290 条视频。已有成功 smoke 和逐轮历史原样保留。'
                  if full else '全量已获准，正在准备 129 条官方输入；现有单案例 smoke 结果原样保留。')
    baselines=[('VACE',-0.042,146.26,0.273),('Ditto',-0.120,149.94,0.264),
               ('MiniMax H3',-0.096,152.00,0.250),('Seedance 2.5',-0.087,144.99,0.231),
               ('No edit',0,143.13,0.289),('VideoPhysEdit',0.376,66.70,0.421)]
    rows=''.join(f'<tr><td>{name}</td><td>{pes:.3f}</td><td>{te:.2f}</td><td>{iou:.3f}</td></tr>' for name,pes,te,iou in baselines)
    body=('<section class=hero><p class=eyebrow>PCVE-RIGIDBENCH · PHYSICAL VIDEO EDITING</p><h1>PCVE-RigidBench</h1>'
          '<p class=muted>给定完整源视频和物理干预指令，生成对应的反事实运动与交互。</p></section>'
          '<div class="card feature"><span class=badge>'+scope_label+'</span>'+status_facts(status)+
          '<p>'+scope_text+'</p>'
          '<p class=note>首个案例：三个空气曲棍球槌碰撞；从第 1 帧开始，将红色球槌质量变为原来的 4 倍。其他案例使用各自完整原视频和官方指令。</p>'
          '<p class=note>官方原视频已核验：1280×720、24 FPS、96 帧、4 秒。生成规格：256×144、24 FPS、96 帧、4 秒；保留原生时间轴，无帧率填充。</p></div>'
          '<h2>Model × Track · '+('Full 129' if full else 'Smoke')+'</h2>'+model_track_matrix(run_root,'pcve_smoke',status,'pcve_smoke')+
          '<h2>自动评测状态</h2>'+evaluation_scheduler_table(run_root/'evaluation/pcve_full_scheduler/scheduler.json')+
          '<h2>输入、协议与评测</h2><div class=card><p>正式数据共 129 条、20 个刚体场景：质量 32、摩擦 21、恢复系数 13、初始速度 26、添加 7、删除 30。117 条从首帧干预，12 条在中途干预。</p>'
          '<p>采用官方 quantitative.en。指令帧号从 1 开始，第 1 帧对应 0 秒。编辑前保留事实历史；编辑后生成物理变化引起的运动及其他受影响物体的交互。</p>'
          '<p>Agent 只读原视频、RGB 数组、输入检查图与指令；不提供 edited_video、ground_truth、physics_diff 或 edit_summary。仍用代码直接写 RGB，不调用图像/视频生成模型或外部物理仿真/渲染引擎；允许 Python 数学、几何与像素操作。</p>'
          '<p>官方评测：PES、轨迹误差 TE、Mask IoU，以及 PSNR/SSIM/LPIPS/CLIP/FVD。GroundingDINO＋SAM2、I3D 和真值仅留在评测侧；每个模型/Track 完成 129 条后进入原版评测。尚未报告 PCVE 分数。</p></div>'
          '<h2>官方论文全 129 条参考</h2><div class=scroll><table><tr><th>Model</th><th>PES ↑</th><th>TE ↓</th><th>Mask IoU ↑</th></tr>'+rows+'</table></div>'
          '<p class=note>PES=1 表示匹配反事实变化；0 表示没有优于原视频不编辑；负值表示更差。参考表来自官方论文 Table 1；只将完整 129 条的原版评测与该表比较。</p>'
          '<p><a class=button href="https://videophysedit.github.io/">官方项目 ↗</a> <a class=button href="https://github.com/Hammour-steak/PCVE-RigidBench">官方代码 ↗</a> <a class=button href="https://huggingface.co/datasets/ccmoony/PCVE-RigidBench">官方数据 ↗</a></p>')
    destination.write_text(page('PCVE-RigidBench · PixelWorld',body))


def publish_delivery(stable_repo: Path, delivery_repo: Path, branch: str = 'pixelworld-pages') -> dict:
    from tools.prepare_pages_site import build
    origin = run(['git','remote','get-url','origin'],stable_repo).stdout.strip()
    match = re.search(r'github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$',origin)
    if not match:
        raise ValueError('Pages delivery requires a GitHub source repository')
    repository = match[1]
    remote = 'https://github.com/' + repository + '.git'
    revision = run(['git','rev-parse','HEAD'],stable_repo).stdout.strip()
    marker = delivery_repo / '.git/pixelworld-delivery.json'
    identity = {'repository':repository,'branch':branch}
    if not delivery_repo.exists():
        delivery_repo.mkdir(parents=True)
        check(['git','init','-b',branch],delivery_repo)
        check(['git','remote','add','origin',remote],delivery_repo)
        for key,fallback in [('user.name','PixelWorld publisher'),('user.email','pixelworld-publisher@users.noreply.github.com')]:
            value = run(['git','config',key],stable_repo).stdout.strip() or fallback
            check(['git','config',key,value],delivery_repo)
        marker.write_text(json.dumps(identity))
    if not marker.is_file() or json.loads(marker.read_text()) != identity:
        raise ValueError('Delivery directory must be a dedicated publisher-owned checkout')
    if run(['git','rev-parse','--verify','HEAD'],delivery_repo).returncode:
        existing = run(['git','ls-remote','origin','refs/heads/'+branch],delivery_repo)
        if existing.returncode:
            raise RuntimeError('Cannot verify delivery branch state')
        if existing.stdout.strip():
            check(['git','fetch','--depth=1','origin',branch],delivery_repo)
            check(['git','checkout','-B',branch,'FETCH_HEAD'],delivery_repo)
    if run(['git','symbolic-ref','--short','HEAD'],delivery_repo).stdout.strip() != branch:
        raise ValueError('Unexpected delivery checkout branch')
    tracked = run(['git','ls-files'],delivery_repo).stdout.splitlines()
    with tempfile.TemporaryDirectory(prefix='pixelworld-pages-') as temp:
        artifact = Path(temp)/'site'
        record = build(stable_repo,artifact,repository,revision)
        files = [str(p.relative_to(artifact)) for p in artifact.rglob('*') if p.is_file()]
        for relative in tracked:
            if not (artifact/relative).exists():
                (delivery_repo/relative).unlink(missing_ok=True)
        for relative in files:
            target = delivery_repo/relative
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(artifact/relative,target)
        staging_paths = sorted(set(files + tracked))
        for start in range(0,len(staging_paths),1000):
            check(['git','add','--all','--',*staging_paths[start:start+1000]],delivery_repo)
    changed = run(['git','diff','--cached','--quiet'],delivery_repo).returncode != 0
    if changed:
        check(['git','commit','-m','Publish PixelWorld pages for '+revision[:12]],delivery_repo)
    # Retry a previous failed push even when the generated tree is unchanged.
    check(['git','push','origin',branch],delivery_repo)
    return {'changed':changed,'branch':branch,'commit':run(['git','rev-parse','HEAD'],delivery_repo).stdout.strip(),**record}


def sync_once(run_root: Path, heavy_web: Path, stable_repo: Path, core_only: bool = False,
              delivery_repo: Path | None = None) -> dict:
    waiting = publication_wait(stable_repo, core_only)
    if waiting:
        return waiting
    from tools.sync_incremental_previews import sync_previews
    pixelworld = stable_repo / "pixelworld"
    pixelworld.mkdir(parents=True, exist_ok=True)
    previews = sync_previews(run_root, heavy_web, pixelworld)
    from pixelworld.util import atomic_json, utc_now
    atomic_json(run_root/'preview_sync_progress.json',
                {'updated_utc':utc_now(), 'prepared_details':len(previews['updated']),
                 'remaining_video_details':previews['remaining_complete'],
                 'remaining_all_details':previews['remaining'], 'batch_limit':previews['batch_limit'],
                 'final_video_previews_updated':len(previews.get('quick_updated',[]))})
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
    write_physics_highres_page(run_root, pixelworld / "physics_iq_512w24fps.html")
    rewrite_monitor_html(heavy_web / "robojudge.html", pixelworld / "robojudge.html")
    write_legacy_page(pixelworld / "matrix_full.html")
    if not (run_root/'generations/vbench2_subset_full/STOP').exists() or not (pixelworld/'vbench2_subset.html').is_file():
        write_vbench_page(run_root, pixelworld / "vbench2_subset.html")
    if not (run_root/'generations/phygenbench_full/STOP').exists() or not (pixelworld/'phygenbench.html').is_file():
        write_phygen_page(run_root, pixelworld / "phygenbench.html")
    write_phygen_pixelspace_page(run_root, pixelworld / "phygen_pixelspace.html")
    paired_source = repo_root / "runs/phygen_pixelspace_v2_20261112/web_source"
    if (paired_source / "inventory.json").is_file():
        from pixelworld.smoke_web import build as build_smoke_web
        build_smoke_web(paired_source, pixelworld / "phygen_pixelspace_smoke")
    write_phygen_qwen_init_page(run_root, pixelworld / "phygen_qwen_init/index.html")
    write_openve_page(run_root, pixelworld / "openve.html")
    write_pcve_page(run_root, pixelworld / "pcve_rigid.html")

    assets_src = heavy_web / "robojudge_assets"
    assets_dst = pixelworld / "robojudge_assets"
    if assets_src.is_dir():
        if assets_dst.exists():
            shutil.rmtree(assets_dst)
        shutil.copytree(assets_src, assets_dst)

    # Stage changed previews explicitly; do not traverse every historical media
    # directory just to publish a fresh progress table.
    core_files = tuple(p for p in CORE_TARGETS if (stable_repo/p).is_file())
    targets = core_files + ('pixelworld/robojudge_assets',) + tuple(previews["targets"])
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
        delivery = None
        if delivery_repo:
            check(['git','push','origin','main'],stable_repo)
            delivery = publish_delivery(stable_repo,delivery_repo)
        return {"changed": False, "commit": None, "core_only": core_only, "gallery": gallery, 'delivery':delivery}

    message = "Update PixelWorld benchmark monitor pages" if core_only else "Update PixelWorld benchmark monitor pages and galleries"
    check(["git", "commit", "-m", message], stable_repo)
    commit = run(["git", "rev-parse", "HEAD"], stable_repo).stdout.strip()
    push = run(["git", "push", "origin", "main"], stable_repo)
    if push.returncode:
        raise RuntimeError(f"git push failed\nSTDOUT:\n{push.stdout}\nSTDERR:\n{push.stderr}")
    delivery = publish_delivery(stable_repo,delivery_repo) if delivery_repo else None
    return {"changed": True, "commit": commit, "core_only": core_only, "gallery": gallery, 'delivery':delivery,
            'preview_sync': {'updated':len(previews['updated']), 'remaining':previews['remaining'],
                             'batch_limit':previews['batch_limit'], 'quick_updated':len(previews.get('quick_updated',[]))}}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--heavy-web", type=Path, required=True)
    parser.add_argument("--stable-repo", type=Path, required=True)
    parser.add_argument("--status", type=Path, required=True)
    parser.add_argument("--interval", type=int, default=600)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--core-only", action="store_true", help="sync only lightweight monitor pages, not full galleries")
    parser.add_argument('--delivery-repo',type=Path,help='Dedicated generated HTML checkout on the pixelworld-pages branch; media stays on main')
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
                    delivery_repo=args.delivery_repo.resolve() if args.delivery_repo else None,
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
