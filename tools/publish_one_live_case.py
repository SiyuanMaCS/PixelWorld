"""Publish one validated case in bounded asset commits, without agent execution."""
import argparse
import fcntl
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.live_benchmark_data import case_data,referenced_assets,read,save,PUBLIC_SCHEMA,DIAGNOSTICS_VERSION
from pixelworld.config import load_config
from pixelworld.supervisor import snapshot


def publish(config_path,model,track,case,attempt,checkout):
    config=load_config(config_path);checkout=checkout.resolve()
    with (checkout/'.publisher.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if subprocess.check_output(['git','symbolic-ref','--short','HEAD'],cwd=checkout,text=True).strip()!='pixelworld-live':raise ValueError('Use the dedicated live branch')
        run=config.runs_root/model/track/f'case_{case}_attempt_{attempt:02d}'
        manifest=read(run/'run_manifest.json')
        if manifest.get('status')!='complete' or not manifest.get('validation',{}).get('pass'):raise ValueError('Wait for a valid completed case')
        render=checkout/'.render-cache';detail=case_data(run,render)
        identity=config.runs_root.name+'/'+model+'/'+track;relative=identity+'/'+run.name+'.json'
        destination=checkout/'pixelworld';batch=[];size=0
        def push(paths):
            subprocess.run(['git','add','--',*paths],cwd=checkout,check=True)
            if subprocess.run(['git','diff','--cached','--quiet'],cwd=checkout).returncode:
                subprocess.run(['git','commit','-m','Publish native case assets'],cwd=checkout,check=True,stdout=subprocess.DEVNULL)
            for retry in range(3):
                result=subprocess.run(['git','push','origin','pixelworld-live'],cwd=checkout)
                if result.returncode==0:return
                if retry<2:time.sleep(5)
            raise RuntimeError('Case publication failed; all existing commits and files retained')
        for asset in sorted(referenced_assets(detail)):
            target=destination/asset
            if not target.exists():target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(render/asset,target)
            length=target.stat().st_size
            if batch and size+length>16*1024*1024:push(batch);batch=[];size=0
            batch.append('pixelworld/'+asset);size+=length
        if batch:push(batch)
        save(destination/relative,detail)
        budget=run/'logs/token_budget.json';events=run/'logs/events.jsonl'
        stamp=[PUBLIC_SCHEMA,(run/'run_manifest.json').stat().st_mtime_ns,budget.stat().st_mtime_ns if budget.exists()else 0,
               events.stat().st_mtime_ns if events.exists()else 0,
               [(p.parent.name,p.stat().st_mtime_ns)for p in(run/'trace').glob('round_*/snapshot.json')],DIAGNOSTICS_VERSION]
        cache=read(checkout/'.publisher_cache.json')
        cache.setdefault(identity,{})[run.name]={'stamp':stamp,'detail':relative,'case':case,'attempt':attempt,
            'status':'complete','raw_status':'complete','output_tokens':detail['output_tokens'],
            'candidate_count':len(detail['candidates']),'poster':detail['candidates'][-1]['poster']}
        save(checkout/'.publisher_cache.json',cache)
        status,_=snapshot(config);save(config.runs_root/'status.json',status)
        group=status['groups'][model+'/'+track]
        previous=read(destination/(identity+'/index.json'))
        cases=previous.get('cases') or {};cases[case]=[{k:v for k,v in cache[identity][run.name].items()if k!='stamp'}]
        payload={'suite':config.runs_root.name,'model_key':model,'track':track,'counts':group['counts'],
                 'cases_total':status['cases'],'updated_utc':status['updated_utc'],'paused':False,
                 'cases':cases,
                 'mean_duration_seconds':group.get('mean_duration_seconds'),'mean_output_tokens_cached':detail['output_tokens'],'token_mean_cases':1}
        path=identity+'/index.json';save(destination/path,payload)
        catalogue=read(destination/'catalogue.json');catalogue['groups']=[g for g in catalogue.get('groups',[])if g.get('path')!=path]
        catalogue['groups'].append({**{k:v for k,v in payload.items()if k not in ('cases','updated_utc')},'path':path})
        catalogue['updated_utc']=status['updated_utc'];save(destination/'catalogue.json',catalogue)
        push(['pixelworld/'+relative,'pixelworld/'+path,'pixelworld/catalogue.json'])
        return {'case':case,'suite':config.runs_root.name,'native_spec':detail['spec'],'candidates':len(detail['candidates'])}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,required=True)
    p.add_argument('--checkout',type=Path,required=True);p.add_argument('--model',required=True);p.add_argument('--track',required=True)
    p.add_argument('--case',required=True);p.add_argument('--attempt',type=int,default=1);a=p.parse_args()
    print(json.dumps(publish(a.config,a.model,a.track,a.case,a.attempt,a.checkout)))
