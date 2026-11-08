"""Run the pinned official evaluator on explicit smoke videos, never a full score claim."""
import argparse,csv,json,os,subprocess
from pathlib import Path

p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--resource-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--per-view-smoke',action='store_true');a=p.parse_args()
a.run=a.run.resolve();a.output=a.output.resolve()
manifest=json.loads((a.run/'run_manifest.json').read_text())
assert manifest['status']=='complete' and manifest['validation']['pass']
identifier=manifest['case_id'];resource=a.resource_root.resolve()
repo=resource/'upstream/physics-IQ-benchmark';python=resource/'.venv/bin/python';descriptions=resource/'protocol/descriptions_base.csv'
commit=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()
assert commit=='d3f3de16a9c66b4d3bfd6bdb5518570e8b72ad48'
record=next(r for r in csv.DictReader(descriptions.open()) if r['generated_video_name'].startswith(identifier+'_'))
group='smoke-'+manifest['model_key']+'-bpp-run_01';video_dir=a.output/group;video_dir.mkdir(parents=True,exist_ok=True)
ffmpeg=resource/'tools/bin/ffmpeg';spec=manifest['media_contract']
subprocess.run([str(ffmpeg),'-hide_banner','-loglevel','error','-y','-framerate',str(spec['fps']),'-i',str(a.run/'workspace/frames/%02d.png'),'-frames:v',str(spec['frames']),'-c:v','libx264rgb','-crf','0','-pix_fmt','rgb24',str(video_dir/record['generated_video_name'])],check=True)
env=os.environ.copy();env.update(PYTHONPATH=str(repo),PATH=str(resource/'tools/bin')+os.pathsep+env['PATH'],MPLBACKEND='Agg',OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='2')
command=[str(python),'-u','-m','physiq.run_physics_iq','--input_folders',str(video_dir),'--output_folder',str(a.output/'official_results'),'--descriptions_file',str(descriptions),'--benchmark_base_folder',str(resource/'data'),'--n_process','1']
if a.per_view_smoke:
    code='''import json,sys
from pathlib import Path
from physiq.binary_mask_generator import generate_mask
from physiq.calculate_and_write_metrics_to_csv import ViewPaths,process_view
video=Path(sys.argv[1]);dataset=Path(sys.argv[2]);out=Path(sys.argv[3]);fps=int(float(sys.argv[4]))
parts=video.name.split('_');identifier,view=parts[:2];scenario='_'.join(parts[2:])
real=dataset/'split-videos/testing'/f'{fps}FPS';masks=dataset/'video-masks/real'/f'{fps}FPS'
a=next(real.glob(f'{identifier}_*_{view}_take-1_{scenario}'));b=next(real.glob(f'*_{view}_take-2_{scenario}'))
mask_dir=out/'mask';mask_dir.mkdir(exist_ok=True);generate_mask(str(video),str(mask_dir/video.name),False)
paths=ViewPaths(str(a),str(b),str(video),str(masks/a.name.replace('testing-videos','video-masks')),str(masks/b.name.replace('testing-videos','video-masks')),str(next(mask_dir.glob('*.mp4'))))
result=process_view(paths,view,0,5*fps,5*fps)
assert result is not None
(out/'per_view_metrics.json').write_text(json.dumps({'mode':'official per-view smoke; no full leaderboard score','metrics':result},indent=2,default=float))
print('Official per-view metrics complete',len(result))
'''
    command=[str(python),'-c',code,str(video_dir/record['generated_video_name']),str(resource/'data/physics-IQ-benchmark-verified'),str(a.output),str(spec['fps'])]
summary={'mode':'one-case smoke, not official full leaderboard','case_id':identifier,'official_commit':commit,'command':command,'run':str(a.run),'status':'running'}
(a.output/'smoke_status.json').write_text(json.dumps(summary,indent=2))
with (a.output/'official.log').open('w') as log:r=subprocess.run(command,env=env,cwd=repo,stdout=log,stderr=subprocess.STDOUT)
summary.update(status='complete' if r.returncode==0 else 'failed',exit_code=r.returncode)
(a.output/'smoke_status.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary),flush=True);raise SystemExit(r.returncode)
