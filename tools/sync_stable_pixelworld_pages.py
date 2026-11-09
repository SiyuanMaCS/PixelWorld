"""Sync lightweight PixelWorld monitor pages into SiyuanMaCS.github.io.

The full generated videos and trace pages stay in the heavy
physics-iq-pixel-preview Pages repo. This script republishes only the small
benchmark monitor pages under /pixelworld/ and rewrites heavy artifact links to
absolute public URLs.
"""
from __future__ import annotations

import argparse
import fcntl
import html
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path


HEAVY_BASE = "https://siyuanmacs.github.io/physics-iq-pixel-preview/"
TARGETS = (
    "pixelworld/index.html",
    "pixelworld/pixelworld-index.html",
    "pixelworld/physics_iq_baseline.html",
    "pixelworld/robojudge.html",
    "pixelworld/matrix_full.html",
    "pixelworld/vbench2_subset.html",
    "pixelworld/phygenbench.html",
    "pixelworld/vbench2_subset_full",
    "pixelworld/phygenbench_full",
    "pixelworld/robojudge_assets",
)

CSS = """:root{color-scheme:dark;--bg:#0b0f14;--panel:#141b24;--line:#2b3745;--text:#edf2f7;--muted:#a0adbc;--green:#b8ed94;--blue:#94ccff;--amber:#f4cb91}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.6 system-ui,-apple-system,sans-serif}a{color:inherit;text-decoration:none}main{max-width:1160px;margin:auto;padding:32px 24px 64px}.top{position:sticky;top:0;background:#0b0f14f2;border-bottom:1px solid var(--line);z-index:5}.top-inner{max-width:1160px;margin:auto;padding:15px 24px;display:flex;justify-content:space-between;gap:18px;align-items:center}.brand{font-weight:850}.nav{display:flex;gap:18px;color:var(--muted);font-size:13px}.nav a:hover,.link{color:var(--blue)}.hero{margin:18px 0 30px}.eyebrow{font-size:11px;letter-spacing:.1em;color:var(--green);margin:0 0 8px}.hero h1{font-size:clamp(30px,4vw,48px);line-height:1.15;margin:0 0 12px;letter-spacing:-.04em}.muted,.desc{color:var(--muted)}.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:16px}.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:22px}.card.feature{border-color:#52714a;background:linear-gradient(130deg,#1a2b20,var(--panel) 70%)}.badge{display:inline-block;font-size:11px;border:1px solid #465749;border-radius:6px;padding:3px 8px;color:var(--green)}h2{margin:36px 0 14px;font-size:24px}h3{font-size:21px;margin:12px 0 8px}.button{display:inline-flex;margin-top:10px;border:1px solid #425064;border-radius:8px;padding:9px 14px;background:#202b37;font-weight:700;font-size:13px}.primary{background:var(--green);color:#17220f;border-color:var(--green)}.facts{display:flex;gap:18px;margin:14px 0;color:var(--muted);font-size:12px;flex-wrap:wrap}.facts strong{display:block;color:var(--text);font-size:22px}.scroll{overflow:auto;border:1px solid var(--line);border-radius:12px;background:var(--panel);margin:12px 0 22px}table{border-collapse:collapse;width:100%;min-width:680px}th,td{border-bottom:1px solid var(--line);padding:12px 14px;text-align:left;vertical-align:top}th{color:var(--muted);font-size:12px}.note,.status{font-size:12px;color:var(--muted)}.status strong{color:var(--text)}.legacy{border-color:#5b4c31;background:#1c1a15}.warn{color:var(--amber)}@media(max-width:800px){.grid{grid-template-columns:1fr}.top-inner{display:block}.nav{overflow:auto;margin-top:8px}}"""


def run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)


def check(cmd: list[str], cwd: Path) -> None:
    result = run(cmd, cwd)
    if result.returncode:
        raise RuntimeError(
            f"Command failed: {' '.join(cmd)}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )


def rewrite_monitor_html(source: Path, destination: Path) -> None:
    text = source.read_text()
    text = text.replace("bench_smoke_codex_20261109/", HEAVY_BASE + "bench_smoke_codex_20261109/")
    text = re.sub(r'href="(matrix_[^"]+\.html)"', lambda m: f'href="{HEAVY_BASE}{m.group(1)}"', text)
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


def page(title: str, body: str) -> str:
    nav = (
        '<header class="top"><div class="top-inner"><a class="brand" href="index.html">PixelWorld</a>'
        '<nav class="nav"><a href="index.html#benchmarks">Benchmarks</a>'
        '<a href="physics_iq_baseline.html">Physics-IQ</a><a href="robojudge.html">RoboJudge</a>'
        '<a href="matrix_full.html">Legacy</a></nav></div></header>'
    )
    return (
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{html.escape(title)}</title><style>{CSS}</style><body>{nav}<main>{body}</main></body></html>'
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


def write_full_galleries(run_root: Path, pixelworld: Path, benchmark: str, title: str) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root))
    from tools.build_bench_review import build_case, document  # Imported lazily to avoid side effects during help output.

    source = run_root / "generations" / benchmark
    target = pixelworld / benchmark
    target.mkdir(parents=True, exist_ok=True)
    model_labels = {"gpt56-sol": "GPT-5.6-Sol"}
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
                if manifest.get("status") == "complete" and manifest.get("validation", {}).get("pass") is True:
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
                if (gallery.parent / poster).exists():
                    preview = f'<img loading=lazy src="{poster.as_posix()}" alt="{html.escape(case_id)}">'
                else:
                    preview = '<div class=placeholder>尚无可播放结果</div>'
                cards.append(
                    f'<article class=sample><a href="{run_name}/index.html">{preview}'
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
        '<p><a class="button primary" href="smoke.html">查看已完成 smoke 视频 →</a></p></div>'
        "<h2>Full Queue Progress</h2><div class=scroll><table><tr><th>Model / Track</th><th>Complete</th><th>Running</th><th>Exhausted</th><th>Pending</th><th>Latest</th><th>Gallery</th></tr>"
        + group_rows(status, "vbench2_subset_full")
        + "</table></div>"
        "<h2>Smoke Gate</h2>"
        f'<p class="note">Smoke status：{html.escape(json.dumps(smoke.get("totals", {}), ensure_ascii=False))}。'
        'Smoke 页面只用于链路验证，不是正式 VBench-2.0 分数。</p>'
        "<h2>Selected Dimensions</h2><div class=scroll><table><tr><th>Dimension</th><th>Prompt rows</th><th>Official file</th></tr>"
        + dimension_rows
        + "</table></div>"
        '<p class="note">总计 291 dimension rows。不要报告 full 18-dimension VBench-2.0 score；这是 PixelWorld 五维 subset。</p>'
    )
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
        '<p><a class="button primary" href="smoke.html">查看已完成 smoke 视频 →</a></p></div>'
        "<h2>Full Queue Progress</h2><div class=scroll><table><tr><th>Model / Track</th><th>Complete</th><th>Running</th><th>Exhausted</th><th>Pending</th><th>Latest</th><th>Gallery</th></tr>"
        + group_rows(status, "phygenbench_full")
        + "</table></div>"
        "<h2>Smoke Gate</h2>"
        f'<p class="note">Smoke status：{html.escape(json.dumps(smoke.get("totals", {}), ensure_ascii=False))}。'
        "其中 PhyGenBench smoke 的一条 vision-agent case 耗尽，保留为失败，不混入有效视频。</p>"
        "<h2>Reporting Dimensions</h2><div class=scroll><table><tr><th>Report dimension</th><th>Prompts</th></tr>"
        + rows
        + "</table></div><h2>Raw Categories</h2><div class=scroll><table><tr><th>Raw category</th><th>Prompts</th></tr>"
        + raw_rows
        + "</table></div>"
    )
    destination.write_text(page("PhyGenBench · PixelWorld", body))


def write_index_page(destination: Path) -> None:
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
        '<section><h2>Legacy 与探索入口</h2><div class="grid"><article class="card legacy"><h3>Legacy Physics-IQ full matrix</h3>'
        '<p class="desc">早期 legacy-v1 / 旧 Track 结果，只作历史参考，不计入 native_v2 主实验。</p>'
        '<a class="button" href="matrix_full.html">打开 legacy full matrix →</a></article>'
        '<article class="card legacy"><h3>Older smoke gallery</h3><p class="desc">WorldArena、WBench、WorldScore、AVGen 等 smoke 保留在旧页中。</p>'
        f'<a class="button" href="{HEAVY_BASE}bench_smoke_20261106/index.html">打开旧导航 →</a></article></div></section>'
    )
    destination.write_text(page("PixelWorld Index", body))


def sync_once(run_root: Path, heavy_web: Path, stable_repo: Path) -> dict:
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
        ],
        repo_root,
    )

    pixelworld = stable_repo / "pixelworld"
    pixelworld.mkdir(parents=True, exist_ok=True)
    write_index_page(pixelworld / "index.html")
    write_index_page(pixelworld / "pixelworld-index.html")
    rewrite_monitor_html(heavy_web / "physics_iq_baseline.html", pixelworld / "physics_iq_baseline.html")
    rewrite_monitor_html(heavy_web / "robojudge.html", pixelworld / "robojudge.html")
    write_legacy_page(pixelworld / "matrix_full.html")
    write_vbench_page(run_root, pixelworld / "vbench2_subset.html")
    write_phygen_page(run_root, pixelworld / "phygenbench.html")
    write_full_galleries(run_root, pixelworld, "vbench2_subset_full", "VBench-2.0 subset · full")
    write_full_galleries(run_root, pixelworld, "phygenbench_full", "PhyGenBench · full")

    assets_src = heavy_web / "robojudge_assets"
    assets_dst = pixelworld / "robojudge_assets"
    if assets_src.is_dir():
        if assets_dst.exists():
            shutil.rmtree(assets_dst)
        shutil.copytree(assets_src, assets_dst)

    check(["git", "add", *TARGETS], stable_repo)
    staged = run(["git", "diff", "--cached", "--quiet", "--", *TARGETS], stable_repo)
    if staged.returncode == 0:
        return {"changed": False, "commit": None}

    check(["git", "commit", "-m", "Update PixelWorld benchmark monitor pages"], stable_repo)
    commit = run(["git", "rev-parse", "HEAD"], stable_repo).stdout.strip()
    push = run(["git", "push", "origin", "main"], stable_repo)
    if push.returncode:
        raise RuntimeError(f"git push failed\nSTDOUT:\n{push.stdout}\nSTDERR:\n{push.stderr}")
    return {"changed": True, "commit": commit}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--heavy-web", type=Path, required=True)
    parser.add_argument("--stable-repo", type=Path, required=True)
    parser.add_argument("--status", type=Path, required=True)
    parser.add_argument("--interval", type=int, default=600)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    args.status.parent.mkdir(parents=True, exist_ok=True)
    lock_path = args.status.with_suffix(".lock")
    with lock_path.open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        iteration = 0
        while True:
            started = time.time()
            try:
                result = sync_once(args.run_root.resolve(), args.heavy_web.resolve(), args.stable_repo.resolve())
                payload = {
                    "status": "ok",
                    "iteration": iteration,
                    "updated_unix": time.time(),
                    "duration_seconds": time.time() - started,
                    **result,
                }
            except Exception as exc:  # Keep the watcher alive; make failures inspectable.
                payload = {
                    "status": "error",
                    "iteration": iteration,
                    "updated_unix": time.time(),
                    "duration_seconds": time.time() - started,
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
