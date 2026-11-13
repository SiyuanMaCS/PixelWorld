import json
import numpy as np
from pixelworld import pcve
from pixelworld.media import task_rules
from pixelworld.util import sha256


def test_evaluation_inventory_includes_source_and_edited_ground_truth():
    row={'scene':'ball_block','source_case_id':'baseline',
         'source_video':'source.mp4','edited_video':'edited.mp4','ground_truth':'edit_gt.json'}
    paths=pcve.evaluation_reference_paths([row, row])
    assert paths == ['edit_gt.json', 'edited.mp4',
                     'scenes/ball_block/cases/baseline/ground_truth_transforms.json', 'source.mp4']


def test_pcve_inputs_exclude_ground_truth_outcomes_and_use_original_frame_numbers(tmp_path,monkeypatch):
    root=tmp_path/'data';root.mkdir();source=root/'source.mp4';source.write_bytes(b'original input fixture')
    row={'global_id':'scene/case','scene':'scene','case_id':'case','source_video':'source.mp4',
         'applies_from_frame':49,'prompts':{'quantitative':{'en':'From frame 49, increase the red object mass 4 times.'}},
         'edit_summary':'POISON_COUNTERFACTUAL_OUTCOME','physics_diff':{'target_velocity':'POISON_TARGET_VELOCITY'},
         'ground_truth':'POISON_GT_PATH'}
    manifest=root/'benchmark_manifest.json';manifest.write_text(json.dumps({'edits':[row]*129}))
    monkeypatch.setattr(pcve,'MANIFEST_SHA256',sha256(manifest))
    monkeypatch.setattr(pcve,'fetch',lambda root,name:root/name)
    info={'original_fps':24,'duration_seconds':4,'original_frame_indices':list(range(96))}
    monkeypatch.setattr(pcve,'sample_video',lambda *a:(np.zeros((96,8,16,3),dtype=np.uint8),info))
    inputs=tmp_path/'inputs';pcve.prepare(root,inputs,[0]);case=inputs/'pcve_0000'
    for p in case.iterdir():
        if p.suffix in ['.json','.txt']:assert 'POISON_' not in p.read_text()
    supplied=json.loads((case/'source_info.json').read_text())
    assert supplied['execution_time_seconds']==2 and supplied['source_frame_number_base']==1
    assert supplied['sampled_source_frame_numbers'][0]==1
    spec=json.loads((case/'task_spec.json').read_text())
    assert spec['frames']==96 and spec['fps']==24
    rules=task_rules(spec)
    assert 'other affected objects' in rules and 'frame 1 is time 0' in rules
    assert 'not an appended future continuation' in rules
