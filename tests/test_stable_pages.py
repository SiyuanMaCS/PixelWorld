import json
from pathlib import Path
from types import SimpleNamespace

from tools import inspect_live_workers, sync_stable_pixelworld_pages as pages


def test_protocol_notice_reports_actual_sampling_and_judge_blockers(tmp_path):
    evaluation = tmp_path/'evaluation'
    evaluation.mkdir()
    (evaluation/'vbench2_official_protocol_audit.json').write_text('{}')
    assert pages.protocol_audit_notice(tmp_path, 'vbench2') == ''
    (evaluation/'vbench2_official_protocol_audit.json').write_text('{"standard_videos_per_prompt":3}')
    text = pages.protocol_audit_notice(tmp_path, 'vbench2')
    assert '3 份独立视频' in text and '当前每个只有 1 份' in text
    assert '不复制视频补齐' in text
    (evaluation/'phygenbench_official_protocol_audit.json').write_text('{"prompt_count":160}')
    text = pages.protocol_audit_notice(tmp_path, 'phygenbench')
    assert 'GPT-4o-0513' in text and '开源分支分数不能直接替代' in text


def test_active_deployment_defers_all_rendering_and_git_mutations(tmp_path, monkeypatch):
    busy = {"run_id": 123, "status": "in_progress", "sha": "old"}
    monkeypatch.setattr(pages, "pending_pages_deployment", lambda _: busy)
    monkeypatch.setattr(pages, "run", lambda *_: SimpleNamespace(stdout="current\n"))
    def forbidden(*_):
        raise AssertionError("No render or git mutation while a deployment is active")
    monkeypatch.setattr(pages, "check", forbidden)
    result = pages.sync_once(tmp_path / "runs", tmp_path / "heavy", tmp_path / "site", True)
    assert result["waiting_for_pages_deployment"] == busy
    assert result["changed"] is False
    assert not (tmp_path / "site").exists()


def test_unknown_deployment_state_defers_publication(tmp_path, monkeypatch):
    def unavailable(_):
        raise TimeoutError("API unavailable")
    monkeypatch.setattr(pages, "pending_pages_deployment", unavailable)
    monkeypatch.setattr(pages, "run", lambda *_: SimpleNamespace(stdout="current\n"))
    result = pages.sync_once(tmp_path / "runs", tmp_path / "heavy", tmp_path / "site", True)
    assert result["waiting_for_pages_deployment"]["state_check_error"] == "TimeoutError"
    assert result["changed"] is False


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
    assert "本轮失败 · 等待重试 · 0 active" in text
    assert "1,590 / 1,600" in text


def test_home_does_not_claim_completion_during_retry_transition(tmp_path, monkeypatch):
    path = tmp_path / "generations/pcve_smoke/status.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"total_runs": 10, "totals": {"complete": 8, "running": 2}}))
    monkeypatch.setattr(inspect_live_workers, "inspect_workers", lambda _: [])
    output = tmp_path / "index.html"
    pages.write_index_page(output, tmp_path)
    text = output.read_text()
    card = next(part for part in text.split('<article class="card feature">') if '<h3>PCVE-RigidBench' in part)
    card = card.split('</article>', 1)[0]
    assert "8 / 10" in card
    assert "等待任务状态更新" in card
    assert "生成完成" not in card


def test_pcve_full_page_and_home_report_129_case_scope(tmp_path, monkeypatch):
    path = tmp_path / 'generations/pcve_smoke/status.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'cases':129, 'configurations':10, 'total_runs':1290,
                               'totals':{'complete':8, 'pending':1282}, 'groups':{}}))
    monkeypatch.setattr(inspect_live_workers, 'inspect_workers', lambda _: [])
    output = tmp_path / 'pcve.html'
    pages.write_pcve_page(tmp_path, output)
    text = output.read_text()
    assert 'Full 129' in text and '1,290' in text
    assert '当前为生成 smoke' not in text
    pages.write_index_page(tmp_path / 'index.html', tmp_path)
    text = (tmp_path / 'index.html').read_text()
    assert '8 / 1,290' in text
    assert '主实验固定为五个 benchmark' in text
