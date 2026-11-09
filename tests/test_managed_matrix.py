from tools.manage_matrix import completed_scope

def test_finished_smoke_cannot_complete_full_shared50_matrix():
    cfg={'case_ids':[str(i) for i in range(50)],'models':[{'tracks':['text','vision-agent']} for _ in range(4)]}
    assert not completed_scope(cfg,{'total_runs':8,'totals':{'complete':5,'exhausted':3}})
    assert completed_scope(cfg,{'total_runs':400,'totals':{'complete':390,'exhausted':10}})
    assert not completed_scope(cfg,{'total_runs':400,'totals':{'complete':390,'running':10}})
