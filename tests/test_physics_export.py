"""Unscored RGB/provenance fixtures for the official full-scope handoff."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image
import pytest

from pixelworld import physics_iq as physics
from pixelworld.supervisor import case_ids
from pixelworld.util import sha256
from pixelworld.constants import PHYSICS_IQ_COMMIT,PHYSICS_IQ_DATASET_REVISION,PHYSICS_IQ_DESCRIPTIONS_SHA256
from tools import watch_physics_evaluation as watcher


def fixture_run(tmp_path):
    run = tmp_path/'run'
    snapshot = run/'input_snapshot'
    snapshot.mkdir(parents=True)
    frames = run/'workspace/frames'
    frames.mkdir(parents=True)
    pixels = np.full((144,256,20),0x102030,dtype=np.uint32)
    initial = np.broadcast_to(np.array([16,32,48],dtype=np.uint8),(144,256,3)).copy()
    Image.fromarray(initial).save(snapshot/'first_frame.png')
    (snapshot/'prompt.txt').write_text('official base prompt\n')
    for i in range(20):Image.fromarray(initial).save(frames/f'{i:02d}.png')
    np.savez_compressed(run/'workspace/pixels.npz',pixels=pixels)
    spec={'task_type':'i2v','width':256,'height':144,'frames':20,'fps':4,'audio':None}
    (run/'media_contract.json').write_text(json.dumps(spec))
    manifest={'status':'complete','case_id':'0001','validation':{'pass':True},'media_contract':spec,
              'input_image_sha256':sha256(snapshot/'first_frame.png'),
              'input_prompt_sha256':sha256(snapshot/'prompt.txt'),
              'pixels_sha256':sha256(run/'workspace/pixels.npz')}
    (run/'run_manifest.json').write_text(json.dumps(manifest))
    case={'id':'0001','prompt_sha256':hashlib.sha256(b'official base prompt').hexdigest(),
          'resized_rgb_sha256':hashlib.sha256(initial.tobytes()).hexdigest()}
    return run,case


def test_native_physics_legacy_five_file_input_does_not_need_task_spec(tmp_path):
    run,case=fixture_run(tmp_path)
    rgb,_=physics.validated_rgb(run,case)
    assert rgb.shape==(20,144,256,3)
    assert not (run/'input_snapshot/task_spec.json').exists()


@pytest.mark.parametrize('change',['prompt','conditioning','tensor','png'])
def test_changed_inputs_or_submission_block_physics_export(tmp_path,change):
    run,case=fixture_run(tmp_path)
    if change=='prompt':(run/'input_snapshot/prompt.txt').write_text('other prompt')
    if change=='conditioning':Image.new('RGB',(256,144)).save(run/'input_snapshot/first_frame.png')
    if change=='tensor':np.savez_compressed(run/'workspace/pixels.npz',pixels=np.zeros((144,256,20),dtype=np.uint32))
    if change=='png':Image.new('RGB',(256,144)).save(run/'workspace/frames/01.png')
    with pytest.raises(ValueError):physics.validated_rgb(run,case)


def test_benchmark_inventory_survives_other_benchmarks_shared_manifest(tmp_path):
    inputs=tmp_path/'physics_iq'
    inputs.mkdir()
    (tmp_path/'manifest.json').write_text(json.dumps({'cases':[{'id':'common50_0000'}]}))
    (tmp_path/'physics_iq_manifest.json').write_text(json.dumps({'cases':[{'id':'0001'}]}))
    config=SimpleNamespace(case_ids=None,inputs_root=inputs)
    assert case_ids(config)==['0001']


def test_missing_full_case_blocks_before_any_video_is_encoded(tmp_path,monkeypatch):
    rows=physics.official_cases()
    model=SimpleNamespace(key='test-model')
    config=SimpleNamespace(inputs_root=tmp_path/'physics_iq',model=lambda _:model)
    (tmp_path/'manifest.json').write_text(json.dumps({'cases':[{'id':'robojudge-only'}]}))
    seen=[]
    def inspect(*args):
        seen.append(args[-1]);return {'state':'pending'}
    monkeypatch.setattr(physics,'inspect',inspect)
    monkeypatch.setattr(physics,'_ffmpeg',lambda:pytest.fail('No encoder before full coverage'))
    with pytest.raises(RuntimeError,match='Incomplete case'):
        physics.export_videos(config,model.key,'text',tmp_path/'evaluation')
    assert seen==[rows[0]['id']]
    assert not (tmp_path/'evaluation').exists()


def test_previous_smoke_status_never_terminalizes_new_full_cohort(tmp_path,monkeypatch):
    root=tmp_path/'generations';root.mkdir()
    (root/'status.json').write_text(json.dumps({'groups':{'test-model/text':{'counts':{'complete':1}}}}))
    config=SimpleNamespace(runs_root=root,models=[SimpleNamespace(key='test-model',tracks=['text'])])
    monkeypatch.setattr(watcher,'inspect',lambda *args:pytest.fail('Incomplete progress hint needs no full scan'))
    result=watcher.step(config,tmp_path/'resource',tmp_path/'eval',{})
    assert result['test-model/text']['phase']=='waiting_for_generation'
    assert not result['test-model/text']['official_full_score']


def test_terminal_progress_hint_requires_actual_run_inventory(tmp_path,monkeypatch):
    root=tmp_path/'generations';root.mkdir()
    (root/'status.json').write_text(json.dumps({'groups':{'test-model/text':{'counts':{'complete':197,'exhausted':1}}}}))
    config=SimpleNamespace(runs_root=root,models=[SimpleNamespace(key='test-model',tracks=['text'])])
    # The progress file is stale: actual generation is still pending.
    calls=[]
    def inspect(*args):calls.append(args[-1]);return {'state':'pending'}
    monkeypatch.setattr(watcher,'inspect',inspect)
    result=watcher.step(config,tmp_path/'resource',tmp_path/'eval',{})
    assert len(calls)==198
    assert result['test-model/text']['phase']=='waiting_for_generation'
    assert not result['test-model/text']['official_full_score']


def test_repo_setup_ready_marker_routes_original_eval_without_legacy_host_layout(tmp_path,monkeypatch):
    source=tmp_path/'upstream'
    source.mkdir()
    python=source/'.venv/bin/python';python.parent.mkdir(parents=True);python.write_text('unexecuted fixture')
    parent=tmp_path/'official-data';dataset=parent/'physics-IQ-benchmark-verified';dataset.mkdir(parents=True)
    marker=parent/'PIXELWORLD_EVALUATOR_READY.json'
    record={'upstream':str(source),'python':str(python),'upstream_commit':PHYSICS_IQ_COMMIT,
            'dataset_revision':PHYSICS_IQ_DATASET_REVISION,'benchmark_parent':str(parent),'dataset':str(dataset)}
    marker.write_text(json.dumps(record))
    monkeypatch.setattr(watcher,'sha256',lambda _:PHYSICS_IQ_DESCRIPTIONS_SHA256)
    monkeypatch.setattr(watcher.subprocess,'check_output',lambda argv,**kw: PHYSICS_IQ_COMMIT if 'rev-parse' in argv else '')
    paths=watcher.validate_runtime(evaluator_ready=marker)
    assert paths['source']==source
    assert paths['python']==python
    assert paths['benchmark_parent']==parent
    record['dataset_revision']='unrelated-release';marker.write_text(json.dumps(record))
    with pytest.raises(ValueError,match='different official'):watcher.validate_runtime(evaluator_ready=marker)


def test_ready_marker_cannot_substitute_another_reference_directory(tmp_path):
    marker=tmp_path/'ready.json'
    marker.write_text(json.dumps({'upstream_commit':PHYSICS_IQ_COMMIT,'dataset_revision':PHYSICS_IQ_DATASET_REVISION,
        'upstream':str(tmp_path/'source'),'benchmark_parent':str(tmp_path/'official'),
        'dataset':str(tmp_path/'unrelated')}))
    with pytest.raises(ValueError,match='dataset does not belong'):watcher.validate_runtime(evaluator_ready=marker)
