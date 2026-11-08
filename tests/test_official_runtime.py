import hashlib
import json

from tools import official_runtime as runtime


def test_resource_lock_verifies_bytes_and_complete_identities(tmp_path):
    weights = tmp_path/'weights.bin'
    weights.write_bytes(b'unit-fixture-not-model-weights')
    lock = tmp_path/'lock.json'
    lock.write_text(json.dumps({'resources': [{'name':'example', 'path':weights.name,
                       'sha256':hashlib.sha256(weights.read_bytes()).hexdigest()}]}))
    assert runtime.weight_check(lock, {'example'})['ok']
    assert not runtime.weight_check(lock, {'example','missing'})['ok']
    weights.write_bytes(b'changed')
    assert not runtime.weight_check(lock, {'example'})['ok']


def test_preflight_is_real_gate_and_can_become_ready(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, 'source_check', lambda *a: {'ok':True})
    monkeypatch.setattr(runtime, 'python_check', lambda *a: {'modules':{'torch':True},'cuda':{'available':True}})
    monkeypatch.setattr(runtime, 'weight_check', lambda *a: {'ok':True})
    assert runtime.preflight(tmp_path, 'fixture', 'python', ('torch',), tmp_path/'lock', set())['status']=='ready'
    monkeypatch.setattr(runtime, 'python_check', lambda *a: {'modules':{'torch':True},'cuda':{'available':False}})
    result=runtime.preflight(tmp_path, 'fixture', 'python', ('torch',), tmp_path/'lock', set())
    assert result['status']=='blocked' and any('CUDA' in e for e in result['blockers'])
    assert result['scores_computed'] is False


def test_missing_official_checkout_is_reported(tmp_path):
    assert runtime.source_check(tmp_path/'absent', 'fixture')['ok'] is False


def test_worldscore_inapplicable_intra_scene_alignment_is_not_missing_score():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parents[1]/'tools'))
    from evaluate_worldscore import STATIC, strict_aggregate
    def record():
        return {aspect:{metric:{'score':.5,'score_normalized':.5} for metric in metrics}
                for aspect,metrics in STATIC.items()}
    intra, inter=record(),record()
    del intra['content_alignment']
    scores=strict_aggregate({'intra':intra,'inter':inter},None,['intra','inter'],[],
                            {'content_alignment':{'inter'}})
    assert scores['WorldScore-Static']==50.0
