#!/usr/bin/env python3
"""One-episode original WorldArena Qwen3-VL component smoke; never a Full Total."""
from __future__ import annotations

import argparse
import fcntl
import json
import math
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from evaluate_worldarena import check_source,check_staged,check_video,verify_hf_checkpoint,HF_MODEL_MANIFEST,SOURCE_COMMIT,load_json
from pixelworld.util import atomic_json,sha256,utc_now

METRICS={'Interaction_Quality','Perspectivity','Instruction_Following'}


def check_results(path: Path, expected_video: str) -> dict:
    rows=load_json(path)
    if not isinstance(rows,list) or len(rows)!=1 or rows[0].get('video')!=expected_video:
        raise ValueError('Original VLM did not evaluate the exact one submitted episode')
    row=rows[0]
    if row.get('error') or set(row.get('metrics',{}))!=METRICS:
        raise ValueError('Original VLM inference or response parsing was incomplete')
    for key,item in row['metrics'].items():
        score=item.get('score');normalized=item.get('score_normalized')
        if (type(score) not in (int,float) or not math.isfinite(score) or not 1<=score<=5
                or normalized!=round(score/5,4)):
            raise ValueError(f'Invalid or default-filled original VLM score: {key}')
    return row['metrics']


def execute(source: Path, stage: Path, run: Path, receipt: Path, checkpoint: Path,
            output: Path, model: str='pixelworld_codex', preflight: bool=False) -> dict:
    source,stage,run,checkpoint,output=(p.resolve() for p in (source,stage,run,checkpoint,output))
    if any(output.is_relative_to(p) for p in (run,source,stage)):
        raise ValueError('VLM evaluation output must remain outside generation/source/staging')
    check_source(source);check_staged(stage,model,['episode1'])
    manifest=load_json(run/'run_manifest.json');export=load_json(receipt)
    if (manifest.get('status')!='complete' or manifest.get('validation',{}).get('pass') is not True
            or manifest.get('case_id')!='episode1' or export.get('producer')!='PixelWorld'
            or export.get('run_manifest_sha256')!=sha256(run/'run_manifest.json')
            or export.get('pixels_sha256')!=sha256(run/'workspace/pixels.npz')
            or export.get('model')!=manifest.get('model') or export.get('track')!=manifest.get('track')):
        raise ValueError('Input is not the preserved validated PixelWorld episode1')
    name='fixed_scene_task_episode1.mp4';video=stage/(model+'_test')/name
    media=check_video(video)
    if media['sha256']!=export['export']['sha256'] or export['export'].get('rgb_roundtrip_exact') is not True:
        raise ValueError('Staged video differs from the exact RGB export')
    pin=load_json(HF_MODEL_MANIFEST)['models']['vlm']
    hashes=verify_hf_checkpoint(checkpoint,pin)
    summary={'scope':'one-episode-original-VLM-component-smoke','official_full_score':False,
             'source_commit':SOURCE_COMMIT,'case':'episode1','sample_frames':16,'model':manifest['model'],
             'track':manifest['track'],'video_sha256':media['sha256'],'checkpoint_repo':pin['repo_id'],
             'checkpoint_revision':pin['revision'],'canonical_object_hashes':hashes,'status':'preflight_passed'}
    if preflight:return summary
    if output.exists():raise FileExistsError('Preserve earlier VLM outcomes; do not overwrite or choose by score')
    output.mkdir(parents=True)
    config=output/'original_model_path.yaml'
    # Only a configurable resource path is supplied; original inference is intact.
    config.write_text('ckpt:\n  vlm_model: '+json.dumps(str(checkpoint))+'\n')
    command=[sys.executable,str(source/'video_quality/VLM_judge.py'),'--model_name',model,
             '--video_dir',str(stage/(model+'_test')),'--summary_json',str(stage/'summary_vlm.json'),
             '--output_root',str(output/'original_results'),'--tmp_root',str(output/'original_tmp'),
             '--num_frames','16','--config_path',str(config)]
    env=os.environ.copy();env.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',OMP_NUM_THREADS='2')
    summary.update(status='original_inference_started',command=command,started_utc=utc_now())
    atomic_json(output/'component_smoke.json',summary)
    try:
        with (output.parent/'gpu_metric.lock').open('a+') as gpu_lock:
            fcntl.flock(gpu_lock,fcntl.LOCK_EX)
            with (output/'original_inference.log').open('wb') as log:
                code=subprocess.call(command,cwd=source,env=env,stdout=log,stderr=subprocess.STDOUT)
        if code:raise RuntimeError(f'Original VLM process exited {code}')
        results=output/'original_results'/model/f'{model}_summary_val_all_intern.json'
        metrics=check_results(results,name)
        summary.update(status='complete_original_VLM_component_smoke',metrics=metrics,results_sha256=sha256(results),completed_utc=utc_now())
    except Exception as exc:
        summary.update(status='failed',error_type=type(exc).__name__,error=str(exc))
        raise
    finally:atomic_json(output/'component_smoke.json',summary)
    return summary


def main() -> None:
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['source','stage','run','export-receipt','checkpoint','output']:p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--preflight',action='store_true')
    a=p.parse_args();print(json.dumps(execute(a.source,a.stage,a.run,a.export_receipt,a.checkpoint,a.output,preflight=a.preflight)))


if __name__=='__main__':main()
