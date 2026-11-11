from tools.manage_matrix import completed_scope
from pathlib import Path
from tools.manage_matrix import authoritative_scope_complete
from tests.test_failed_retries import fixture, manifest
from pixelworld.retries import authorize_failed

def test_finished_smoke_cannot_complete_full_shared50_matrix():
    cfg={'case_ids':[str(i) for i in range(50)],'models':[{'tracks':['text','vision-agent']} for _ in range(4)]}
    assert not completed_scope(cfg,{'total_runs':8,'totals':{'complete':5,'exhausted':3}})
    assert completed_scope(cfg,{'total_runs':400,'totals':{'complete':390,'exhausted':10}})
    assert not completed_scope(cfg,{'total_runs':400,'totals':{'complete':390,'running':10}})


def test_retry_grant_invalidates_old_terminal_counts(tmp_path):
    config,model=fixture(tmp_path)
    for attempt in (1,2):manifest(config,model,'bad',attempt,{'status':'failed'})
    manifest(config,model,'good',1,{'status':'complete','validation':{'pass':True}})
    assert authoritative_scope_complete(config.source,Path(__file__).resolve().parents[1])
    authorize_failed(config,apply=True)
    assert not authoritative_scope_complete(config.source,Path(__file__).resolve().parents[1])
