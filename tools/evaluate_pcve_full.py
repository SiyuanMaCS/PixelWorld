"""Export a full cohort and run pinned PCVE code with portable weight paths."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pixelworld import pcve
from pixelworld.config import load_config
from pixelworld.supervisor import inspect
from pixelworld.util import atomic_json, sha256, utc_now


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--track', choices=['text','vision-agent'], required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=ROOT/'data/pcve-rigid')
    parser.add_argument('--evaluator-python', default=os.environ.get('PCVE_EVAL_PYTHON', sys.executable))
    parser.add_argument('--evaluator-source', type=Path, default=Path(os.environ.get('PCVE_EVALUATOR_SOURCE', str(ROOT/'vendor/pcve-rigid-source'))))
    parser.add_argument('--sam2-checkpoint', type=Path, default=Path(os.environ.get('PCVE_SAM2_CHECKPOINT', str(ROOT/'vendor/pcve-eval-models/sam2.1_hiera_large.pt'))))
    parser.add_argument('--i3d-checkpoint', type=Path, default=Path(os.environ.get('PCVE_I3D_CHECKPOINT', str(ROOT/'vendor/pcve-eval-models/i3d_torchscript.pt'))))
    parser.add_argument('--device', default='cuda')
    args = parser.parse_args()
    config = load_config(args.config)
    output = args.output.resolve()
    if output.is_relative_to(config.runs_root) or output.is_relative_to(config.inputs_root):
        raise ValueError('Evaluation and ground truth must stay outside generation')
    output.mkdir(parents=True, exist_ok=True)
    expected = {f'pcve_{i:04d}' for i in range(pcve.TOTAL)}
    if set(config.case_ids or []) != expected:
        raise ValueError('Full evaluation requires all 129 official case IDs')
    model = config.model(args.model)
    if any(inspect(config, model, args.track, case)['state'] != 'complete' for case in expected):
        raise ValueError('Wait for a complete 129-case cohort; no partial-score imputation')
    source = args.evaluator_source.resolve()
    if source.is_relative_to(config.runs_root.resolve()) or source.is_relative_to(config.inputs_root.resolve()):
        raise ValueError('Official evaluator source must remain outside generation inputs and workspaces')
    revision = subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()
    if revision != pcve.EVALUATOR_REVISION:
        raise ValueError('Official evaluator revision mismatch')
    if subprocess.run(['git','-C',str(source),'diff','--quiet','HEAD'],check=False).returncode:
        raise ValueError('Official evaluator source must remain unchanged')
    for checkpoint in [args.sam2_checkpoint, args.i3d_checkpoint]:
        if not checkpoint.is_file():
            atomic_json(output/'prerequisites.json', {'phase':'blocked_evaluation_weights','missing':str(checkpoint),'scores_computed':False,'updated_utc':utc_now()})
            raise FileNotFoundError(checkpoint)
    probe = subprocess.run([args.evaluator_python,'-c',
        "import torch, av, imageio, numpy, PIL, lpips, open_clip, torchmetrics, sam2, transformers; assert torch.cuda.is_available(), 'Original PCVE evaluation needs the configured CUDA worker'"],
        text=True,capture_output=True)
    if probe.returncode:
        atomic_json(output/'prerequisites.json', {'phase':'blocked_evaluation_environment','detail':probe.stderr[-3000:],'scores_computed':False,'updated_utc':utc_now()})
        raise RuntimeError('PCVE evaluation dependencies or CUDA worker are not ready; prerequisites.json retained')
    manifest_path = pcve.fetch(args.data_root, 'benchmark_manifest.json')
    if sha256(manifest_path) != pcve.MANIFEST_SHA256:
        raise ValueError('Official dataset manifest mismatch')
    rows = json.loads(manifest_path.read_text())['edits']
    # These files remain evaluator-side; they are never copied into a workspace.
    for row in rows:
        for key in ['source_video','edited_video','ground_truth']:
            try:
                pcve.fetch(args.data_root, row[key])
            except OSError as exc:
                atomic_json(output/'prerequisites.json', {
                    'phase':'blocked_reference_download', 'missing_relative_path':row[key],
                    'detail':str(exc)[:800], 'dataset_revision':pcve.DATASET_REVISION,
                    'scores_computed':False, 'updated_utc':utc_now()})
                raise
    baseline = f'pixelworld_{args.model}_{args.track}'
    prediction_root = output/'predictions'
    exported = pcve.export(args.config,args.model,args.track,args.data_root,baseline,prediction_root)
    if not exported['full_official_scope']:
        raise ValueError('Export did not produce all 129 videos')
    driver = output/'official_driver.py'
    # Override only author-specific checkpoint paths. Scoring code and all
    # thresholds, frame alignment, tracking and aggregation remain original.
    driver.write_text(
        'import sys,runpy\n'
        + f'sys.path.insert(0,{str(source/"eval")!r})\n'
        + 'from metrics import grounded_sam2_tracker as tracker, fvd\n'
        + f'tracker.GroundedSam2Tracker.__init__.__defaults__=({str(args.sam2_checkpoint.resolve())!r},)+tracker.GroundedSam2Tracker.__init__.__defaults__[1:]\n'
        + f'fvd.I3DFeatures.__init__.__defaults__=({str(args.i3d_checkpoint.resolve())!r},)+fvd.I3DFeatures.__init__.__defaults__[1:]\n'
        + f'sys.argv={[str(source/"eval/compute_metrics.py"),"--benchmark-root",str(args.data_root.resolve()),"--predictions-root",str(prediction_root),"--baseline",baseline,"--device",args.device]!r}\n'
        + f'runpy.run_path({str(source/"eval/compute_metrics.py")!r},run_name="__main__")\n')
    execution = {'phase':'official_evaluation','source_revision':revision,'dataset_revision':pcve.DATASET_REVISION,
                 'source_files_unchanged':True,'checkpoint_paths_only_overridden':True,'updated_utc':utc_now()}
    atomic_json(output/'execution.json',execution)
    code = subprocess.call([args.evaluator_python,str(driver)],cwd=source/'eval')
    execution.update(phase='finished' if code==0 else 'failed',returncode=code,updated_utc=utc_now())
    atomic_json(output/'execution.json',execution)
    if code:
        raise RuntimeError(f'Original PCVE evaluator exited {code}')
    metrics_file = prediction_root/baseline/'metrics.json'
    metrics = json.loads(metrics_file.read_text())
    evaluated = metrics.get('per_case',[])
    if (len(evaluated)!=pcve.TOTAL or len({r['global_id'] for r in evaluated})!=pcve.TOTAL
            or {r['global_id'] for r in evaluated}!={r['global_id'] for r in rows}
            or any(r.get('status')!='completed' for r in evaluated)):
        raise ValueError('Original metrics contain missing, failed, or duplicate cases')
    scores = metrics['aggregate']
    if any(scores.get('overall',{}).get(k) is None for k in ['pes','traj_px','mask_iou','psnr','ssim','lpips','clip_sim']) or scores.get('fvd') is None:
        raise ValueError('Official metrics are incomplete; do not report a full score')
    atomic_json(output/'summary.json', {'benchmark':'PCVE-RigidBench','complete_official129':True,
                'case_count':pcve.TOTAL,'model':args.model,'track':args.track,'scores':scores,
                'official_metrics_sha256':sha256(metrics_file),'source_revision':revision,
                'dataset_revision':pcve.DATASET_REVISION,'fps':24,'frames':96,'resolution':[256,144],
                'no_missing_output_imputation':True,'completed_utc':utc_now()})


if __name__ == '__main__':
    main()
