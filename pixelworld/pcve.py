"""Pinned PCVE input preparation; target state and outcomes never enter generation."""
from pathlib import Path, PurePosixPath
import json
import math
import urllib.request

import numpy as np
from PIL import Image, ImageDraw

from .openve import sample_video, encode_pixels
from .config import load_config
from .util import atomic_json, sha256

DATASET_ID='ccmoony/PCVE-RigidBench'
DATASET_REVISION='772f7b50c9be0648a5b5598861b70211d8b73907'
EVALUATOR_REVISION='e262f93e9ab69208023413f342adf9d80fa098e5'
TOTAL=129
MANIFEST_SHA256='0b2c92998aa4cf3710b820ff5469cc8c3beb94ce7274a65d63a06f3c16dbc5de'


def fetch(root: Path, relative: str):
    path=PurePosixPath(relative)
    if path.is_absolute() or '..' in path.parts:raise ValueError('Unsafe dataset path')
    target=root/relative
    if target.is_file():return target
    target.parent.mkdir(parents=True,exist_ok=True)
    url=f'https://huggingface.co/datasets/{DATASET_ID}/resolve/{DATASET_REVISION}/{relative}'
    with urllib.request.urlopen(url,timeout=90) as response:data=response.read()
    temp=target.with_suffix(target.suffix+'.part');temp.write_bytes(data);temp.replace(target)
    return target


def evaluation_reference_paths(edits: list[dict]) -> list[str]:
    """All pinned evaluator inputs, including source trajectories used by PES.

    These references belong only in the evaluation dataset, never a workspace.
    """
    paths = {row[key] for row in edits for key in ('source_video', 'edited_video', 'ground_truth')}
    paths.update(f"scenes/{row['scene']}/cases/{row['source_case_id']}/ground_truth_transforms.json"
                 for row in edits)
    return sorted(paths)


def prepare(root: Path, inputs: Path, indices=None):
    manifest=fetch(root,'benchmark_manifest.json');data=json.loads(manifest.read_text())
    if sha256(manifest)!=MANIFEST_SHA256:raise ValueError('PCVE manifest differs from its official dataset revision')
    if len(data['edits'])!=TOTAL:raise ValueError('Expected all 129 official PCVE tasks')
    indices=list(range(TOTAL)) if indices is None else indices
    if len(set(indices))!=len(indices) or any(i<0 or i>=TOTAL for i in indices):raise ValueError('Use unique official zero-based task indices')
    records=[]
    for index in indices:
        row=data['edits'][index];case=f'pcve_{index:04d}';destination=inputs/case
        if destination.exists():raise FileExistsError('Prepared inputs are immutable')
        original=fetch(root,row['source_video'])
        frames,info=sample_video(original,256,24)
        if len(frames)!=96 or abs(info['original_fps']-24)>1e-4 or abs(info['duration_seconds']-4)>1e-4:
            raise ValueError('Official PCVE inputs must be 96 frames at 24 fps, 4 seconds')
        # The released quantitative prompts count source frames from 1.
        execution=int(row['applies_from_frame'])
        info.update({'source_frame_number_base':1,'execution_frame_1based':execution,
                     'execution_time_seconds':(execution-1)/24,
                     'sampled_source_frame_numbers':[i+1 for i in info['original_frame_indices']]})
        destination.mkdir(parents=True)
        import shutil
        shutil.copy2(original,destination/'source_video.mp4')
        np.savez_compressed(destination/'source_pixels.npz',rgb=frames)
        Image.fromarray(frames[0]).save(destination/'first_frame.png')
        selected=np.linspace(0,95,12).round().astype(int)
        n,h,w,_=frames.shape;sheet=Image.new('RGB',(4*w,3*(h+20)), '#141b24');draw=ImageDraw.Draw(sheet)
        for slot,i in enumerate(selected):
            x,y=slot%4*w,slot//4*(h+20);sheet.paste(Image.fromarray(frames[i]),(x,y))
            draw.text((x+4,y+h+3),f'source frame {i+1} · {i/24:.2f}s',fill='white')
        sheet.save(destination/'source_inspection.png')
        atomic_json(destination/'source_info.json',info)
        prompt=row['prompts']['quantitative']['en']
        (destination/'prompt.txt').write_text(prompt+'\n')
        spec={'task_type':'video_edit','benchmark':'pcve-rigidbench-v1','width':w,'height':h,
              'frames':96,'fps':24,'audio':None}
        atomic_json(destination/'task_spec.json',spec)
        # Whitelist public inputs; do not copy edit_summary, physics_diff or GT.
        record={'case_id':case,'row_index':index,'global_id':row['global_id'],
                'scene':row['scene'],'official_case_id':row['case_id'],
                'source_video':row['source_video'],'prompt_flavor':'quantitative','prompt_language':'en',
                'execution_frame_1based':execution,'dataset_revision':DATASET_REVISION,
                'manifest_sha256':sha256(manifest),'source_sha256':sha256(original),
                'prompt_sha256':sha256(destination/'prompt.txt'),'media_contract':spec}
        atomic_json(destination/'preparation_record.json',record);records.append(record)
    return records


def export(config_path: Path, model: str, track: str, benchmark_root: Path, baseline: str,
           predictions_root: Path | None = None):
    config=load_config(config_path);config.model(model);selected={}
    prediction_base = predictions_root or benchmark_root/'predictions'
    for path in (config.runs_root/model/track).glob('case_*/run_manifest.json'):
        m=json.loads(path.read_text())
        if m['status']!='complete' or not m.get('validation',{}).get('pass'):continue
        if m['case_id'] not in selected or m['attempt']<selected[m['case_id']][1]['attempt']:
            selected[m['case_id']]=(path.parent,m)
    rows=[]
    for case,(run,m) in sorted(selected.items()):
        info=json.loads((config.inputs_root/case/'preparation_record.json').read_text())
        output=prediction_base/baseline/'videos'/info['scene']/(info['official_case_id']+'.mp4')
        encode_pixels(run/'workspace',m['media_contract'],output)
        rows.append({'case_id':case,'global_id':info['global_id'],'attempt':m['attempt'],'output':str(output),
                     'frames':96,'fps':24,'source_run':str(run)})
    result={'rows':rows,'exported':len(rows),'full_official_scope':len(rows)==TOTAL,
            'dataset_revision':DATASET_REVISION,'evaluator_revision':EVALUATOR_REVISION,'scores_computed':False}
    folder=prediction_base/baseline;folder.mkdir(parents=True,exist_ok=True)
    atomic_json(folder/'pixelworld_submission.json',result)
    return result
