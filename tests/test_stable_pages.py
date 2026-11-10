import json
from pathlib import Path

from tools import inspect_live_workers, sync_stable_pixelworld_pages as pages


def test_core_refresh_keeps_published_preview_routes_and_heavy_fallback(tmp_path):
    relative = "bench_smoke_codex_20261109/robojudge/model/text/case_1/index.html"
    local = tmp_path / "stable" / relative
    local.parent.mkdir(parents=True)
    local.write_text("playable preview")
    source = tmp_path / "source.html"
    missing = relative.replace("case_1", "case_2")
    source.write_text(f'<a href="{relative}">local</a><a href="{missing}">heavy</a>')
    output = tmp_path / "stable/robojudge.html"
    pages.rewrite_monitor_html(source, output)
    assert f'href="{relative}"' in output.read_text()
    assert f'href="{pages.HEAVY_BASE}{missing}"' in output.read_text()


def test_home_uses_live_workers_instead_of_stale_running_counts(tmp_path, monkeypatch):
    status = tmp_path / "generations/vbench2_subset_full/status.json"
    status.parent.mkdir(parents=True)
    status.write_text(json.dumps({
        "total_runs": 2910,
        "updated_utc": "2026-11-10T02:00:00+00:00",
        "totals": {"complete": 900, "running": 10, "pending": 2000, "exhausted": 10},
        "groups": {"m/text": {"latest_completion": ["2026-11-10T01:59:00+00:00", "case_1"]}},
    }))
    monkeypatch.setattr(inspect_live_workers, "inspect_workers", lambda _: [
        {"kind": "run-case", "bench": "vbench2_subset_full", "stat": "S"},
        {"kind": "run-case", "bench": "vbench2_subset_full", "stat": "Z"},
        {"kind": "orphan-codex", "bench": "vbench2_subset_full", "stat": "S"},
    ])
    output = tmp_path / "index.html"
    pages.write_index_page(output, tmp_path)
    text = output.read_text()
    assert "running · 1 active" in text
    assert "900 / 2,910" in text
    assert "case_1" in text
    assert "configured" not in text
    assert 'name="pixelworld-built-utc"' in text
    for route in ("robojudge.html", "physics_iq_baseline.html", "vbench2_subset.html", "phygenbench.html"):
        assert f'href="{route}"' in text


def test_home_marks_incomplete_terminal_cohort_without_claiming_running(tmp_path, monkeypatch):
    path = tmp_path / "generations/phygenbench_full/status.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"total_runs": 1600, "totals": {"complete": 1590, "exhausted": 10}}))
    monkeypatch.setattr(inspect_live_workers, "inspect_workers", lambda _: [])
    output = tmp_path / "index.html"
    pages.write_index_page(output, tmp_path)
    text = output.read_text()
    assert "生成结束 · 有未交付任务 · 0 active" in text
    assert "1,590 / 1,600" in text
