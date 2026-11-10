import json

from tools import build_baseline_monitor
from tools.build_bench_review import physics_verified_display


def test_public_monitor_converts_official_fraction_to_score_out_of_100(tmp_path):
    run, web = tmp_path/'run', tmp_path/'web'
    scheduler = run/'evaluation/physics_full_scheduler/scheduler.json'
    scheduler.parent.mkdir(parents=True)
    scheduler.write_text(json.dumps({'cohorts':{'deepseek-v41/vision-agent':{
        'phase':'complete', 'official_full_score':True, 'accepted_cases':198,
        'score':{'verified_score':0.3611811558670115},
    }}}))
    web.mkdir()
    build_baseline_monitor.build(run, web, tmp_path/'missing_legacy.json')
    text = (web/'physics_iq_baseline.html').read_text()
    assert '<th>完整Verified /100</th>' in text
    assert '<td>36.12</td>' in text
    assert '0.3611811558670115' not in text


def test_missing_score_stays_unscored_and_score_boundaries_are_percentages():
    assert physics_verified_display(None) == '—'
    assert physics_verified_display(0.0) == '0.00'
    assert physics_verified_display(1.0) == '100.00'
