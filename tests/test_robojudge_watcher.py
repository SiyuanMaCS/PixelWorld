import json

from tools import watch_robojudge_evaluation as watcher


def prepared_cuda_failure(tmp_path):
    target=tmp_path/'model-a'/'text'
    target.mkdir(parents=True)
    (target/'execution.json').write_text(json.dumps({
        'status':'blocked','blockers':['ValueError: CUDA GPU unavailable'],
    }))
    (target/'plan.json').write_text(json.dumps({
        'scope':{'complete_shared50':True,'prepared_count':50},
    }))
    (target/'summary.json').write_text(json.dumps({
        'complete_shared50':False,'valid_paired_count':0,
    }))
    (target/'input-evidence.txt').write_text('preserve this original evidence')
    return target


def test_cuda_blocker_remains_retryable_without_touching_existing_directory(tmp_path, monkeypatch):
    target=prepared_cuda_failure(tmp_path)
    monkeypatch.setattr(watcher,'cuda_available',lambda:False)
    for _ in range(2):
        assert watcher.existing_preflight_state(target,tmp_path)['phase']=='waiting_for_cuda'
    assert (target/'input-evidence.txt').read_text()=='preserve this original evidence'
    assert not (tmp_path/'_infrastructure_failures').exists()


def test_gpu_recovery_archives_all_evidence_before_a_fresh_evaluation(tmp_path, monkeypatch):
    target=prepared_cuda_failure(tmp_path)
    original=(target/'execution.json').read_bytes()
    monkeypatch.setattr(watcher,'cuda_available',lambda:True)
    state=watcher.existing_preflight_state(target,tmp_path)
    from pathlib import Path
    archive=Path(state['previous_evaluation_archive'])
    assert not target.exists()
    assert (archive/'execution.json').read_bytes()==original
    assert (archive/'input-evidence.txt').read_text()=='preserve this original evidence'
    assert (archive/'retry_receipt.json').is_file()


def test_existing_predictions_are_never_archived_or_retried_automatically(tmp_path, monkeypatch):
    target=prepared_cuda_failure(tmp_path)
    (target/'predictions.jsonl').write_text('existing prediction evidence')
    monkeypatch.setattr(watcher,'cuda_available',lambda:True)
    assert watcher.existing_preflight_state(target,tmp_path)['phase']=='existing_incomplete_evaluation_needs_review'
    assert (target/'predictions.jsonl').read_text()=='existing prediction evidence'
    assert not (tmp_path/'_infrastructure_failures').exists()
