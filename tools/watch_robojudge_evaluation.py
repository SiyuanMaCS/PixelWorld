"""Wait for each complete shared50 cohort, then run the original9B evaluator."""
from pathlib import Path
import argparse,json,os,subprocess,sys,time,fcntl

def read(path):
    try:return json.loads(path.read_text())
    except (OSError,ValueError):return {}

def write(path,value):
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(value,indent=2));tmp.replace(path)

def main():
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--allow-unsupported-bf16',action='store_true');a=p.parse_args()
    config=read(a.config);root=Path(config['runs_root']);a.output.mkdir(parents=True,exist_ok=True);done={}
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
                    done[key]={'phase':'full_shared50_scored','means':previous['shared50_means']};continue
                if entry.get('counts',{}).get('complete')!=50:continue
                if target.exists():
                    done[key]={'phase':'existing_incomplete_evaluation_needs_review'};continue
                target.parent.mkdir(parents=True,exist_ok=True)
                command=[sys.executable,str(evaluator),'prepare','--generations',str(root),'--model',model['key'],'--track',track,'--output',str(target)]
                with (a.output/(model['key']+'_'+track+'.log')).open('ab') as log:
                    code=subprocess.call(command,stdout=log,stderr=subprocess.STDOUT)
                    if code==0:
                        command=[sys.executable,str(evaluator),'run','--output',str(target)]
                        if a.allow_unsupported_bf16:command+=['--allow-unsupported-bf16']
                        with (a.output.parent/'gpu_metric.lock').open('a+') as lock:
                            fcntl.flock(lock,fcntl.LOCK_EX)
                            code=subprocess.call(command,stdout=log,stderr=subprocess.STDOUT)
                summary=read(target/'summary.json')
                done[key]={'phase':'full_shared50_scored' if code==0 and summary.get('complete_shared50') else 'original_evaluation_failed','exit_status':code,'means':summary.get('shared50_means')}
        write(a.output/'scheduler.json',{'pid':os.getpid(),'phase':'waiting_or_scoring_full_cohorts','groups':groups,'done':done,'partial_scores_are_not_full':True})
        if len(done)==sum(len(m['tracks']) for m in config['models']):return
        time.sleep(60)

if __name__=='__main__':main()
