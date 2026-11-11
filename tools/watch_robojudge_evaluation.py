"""Wait for each complete shared50 cohort, then run the original9B evaluator."""
from pathlib import Path
import argparse,json,os,subprocess,sys,time,fcntl
from datetime import datetime, timezone

def read(path):
    try:return json.loads(path.read_text())
    except (OSError,ValueError):return {}

def write(path,value):
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(value,indent=2));tmp.replace(path)

def cuda_available():
    remote_python=os.environ.get('ROBOJUDGE_EVAL_PYTHON')
    if remote_python:
        return subprocess.run([remote_python,'-c','import torch; raise SystemExit(0 if torch.cuda.is_available() else 1)'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        return False

def existing_preflight_state(target, output):
    """Retry only an unscored, complete cohort blocked before CUDA inference."""
    execution=read(target/'execution.json');plan=read(target/'plan.json')
    summary=read(target/'summary.json')
    safe=(execution.get('status')=='blocked'
          and execution.get('blockers')==['ValueError: CUDA GPU unavailable']
          and plan.get('scope',{}).get('complete_shared50') is True
          and plan.get('scope',{}).get('prepared_count')==50
          and not (target/'predictions.jsonl').exists()
          and summary.get('valid_paired_count',0)==0
          and not summary.get('complete_shared50'))
    if not safe:
        return {'phase':'existing_incomplete_evaluation_needs_review'}
    if not cuda_available():
        return {'phase':'waiting_for_cuda','blocker':'CUDA GPU unavailable'}
    archive=output/'_infrastructure_failures'/f'{target.parent.name}_{target.name}_{time.time_ns()}'
    archive.parent.mkdir(parents=True,exist_ok=True)
    target.rename(archive)
    write(archive/'retry_receipt.json',{
        'reason':'CUDA preflight previously failed; GPU is now available; no predictions existed',
        'archived_utc':datetime.now(timezone.utc).isoformat(),
        'original_output':str(target),'next_action':'prepare a fresh official evaluation directory',
    })
    return {'phase':'retrying_cuda_preflight','previous_evaluation_archive':str(archive)}

def main():
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--allow-unsupported-bf16',action='store_true');a=p.parse_args()
    config=read(a.config);root=Path(config['runs_root']);a.output.mkdir(parents=True,exist_ok=True);done={};blocked={}
    evaluator=Path(__file__).with_name('evaluate_robojudge_shared50.py')
    while not (a.output/'STOP').exists():
        status=read(root/'status.json');groups=status.get('groups',{})
        for model in config['models']:
            for track in model['tracks']:
                key=model['key']+'/'+track;entry=groups.get(key,{})
                if key in done:continue
                target=a.output/model['key']/track
                previous=read(target/'summary.json')
                if previous.get('complete_shared50'):
                    done[key]={'phase':'full_shared50_scored','means':previous['shared50_means']};blocked.pop(key,None);continue
                if entry.get('counts',{}).get('complete')!=50:continue
                if target.exists():
                    state=existing_preflight_state(target,a.output)
                    if state['phase']=='waiting_for_cuda':
                        blocked[key]=state;continue
                    if state['phase']=='existing_incomplete_evaluation_needs_review':
                        done[key]=state;continue
                    blocked.pop(key,None)
                target.parent.mkdir(parents=True,exist_ok=True)
                python=os.environ.get('ROBOJUDGE_EVAL_PYTHON',sys.executable)
                command=[python,str(evaluator),'prepare','--generations',str(root),'--model',model['key'],'--track',track,'--output',str(target)]
                with (a.output/(model['key']+'_'+track+'.log')).open('ab') as log:
                    code=subprocess.call(command,stdout=log,stderr=subprocess.STDOUT)
                    if code==0:
                        command=[python,str(evaluator),'run','--output',str(target)]
                        if a.allow_unsupported_bf16:command+=['--allow-unsupported-bf16']
                        with (a.output.parent/'gpu_metric.lock').open('a+') as lock:
                            fcntl.flock(lock,fcntl.LOCK_EX)
                            code=subprocess.call(command,stdout=log,stderr=subprocess.STDOUT)
                summary=read(target/'summary.json')
                execution=read(target/'execution.json')
                if (execution.get('status')=='blocked'
                        and execution.get('blockers')==['ValueError: CUDA GPU unavailable']
                        and not (target/'predictions.jsonl').exists()):
                    blocked[key]={'phase':'waiting_for_cuda','blocker':'CUDA GPU unavailable'};continue
                done[key]={'phase':'full_shared50_scored' if code==0 and summary.get('complete_shared50') else 'original_evaluation_failed','exit_status':code,'means':summary.get('shared50_means')}
                blocked.pop(key,None)
        write(a.output/'scheduler.json',{'pid':os.getpid(),'updated_utc':datetime.now(timezone.utc).isoformat(),'phase':'waiting_or_scoring_full_cohorts','groups':groups,'done':done,'blocked':blocked,'partial_scores_are_not_full':True})
        if len(done)==sum(len(m['tracks']) for m in config['models']):return
        time.sleep(60)

if __name__=='__main__':main()
