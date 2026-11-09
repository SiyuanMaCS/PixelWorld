"""Run a restartable detached matrix against a fixed code checkout."""
from __future__ import annotations
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
import time

def alive(pid):
    try:os.kill(int(pid),0);return True
    except (ValueError,TypeError,ProcessLookupError,PermissionError):return False

def read(path):
    try:return json.loads(path.read_text())
    except (OSError,ValueError):return {}

def write(path,value):
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value,indent=2));temp.replace(path)

def completed_scope(config,status):
    identifiers=config.get('case_ids')
    if not identifiers:
        identifiers=[p.name for p in Path(config['inputs_root']).iterdir() if (p/'prompt.txt').is_file()]
    expected=len(identifiers)*sum(len(m.get('tracks',['text','vision-agent'])) for m in config['models'])
    counts=status.get('totals',{})
    return expected>0 and status.get('total_runs')==expected and counts.get('complete',0)+counts.get('exhausted',0)==expected

def main():
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);p.add_argument('--code-root',type=Path,required=True);p.add_argument('--state',type=Path,required=True);p.add_argument('--resume',action='store_true');a=p.parse_args()
    cfg=read(a.config);root=Path(cfg['runs_root']);root.mkdir(parents=True,exist_ok=True);a.state.parent.mkdir(parents=True,exist_ok=True)
    stop=root/'STOP';managed_stop=a.state.with_name(a.state.stem+'.STOP')
    if a.resume:stop.unlink(missing_ok=True);managed_stop.unlink(missing_ok=True)
    child=None;restarts=0;env=os.environ.copy();env['PYTHONPATH']=str(a.code_root.resolve())
    while not stop.exists() and not managed_stop.exists():
        status=read(root/'status.json');counts=status.get('totals',{});total=status.get('total_runs',0)
        if completed_scope(cfg,status):
            write(a.state,{'phase':'processed_all_requested_tasks','counts':counts,'total':total,'failures_preserved':True,'updated_utc':dt.datetime.now(dt.timezone.utc).isoformat()});return
        owner=status.get('supervisor_pid')
        active=child is not None and child.poll() is None
        if not active and not alive(owner):
            with a.state.with_suffix('.log').open('ab') as log:
                child=subprocess.Popen([sys.executable,'-m','pixelworld.cli','matrix','run','--config',str(a.config.resolve())],cwd=a.code_root,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            owner=child.pid;restarts+=1
        write(a.state,{'phase':'running','manager_pid':os.getpid(),'supervisor_pid':owner,'starts':restarts,'counts':counts,'total':total,'code_root':str(a.code_root.resolve()),'config':str(a.config.resolve()),'updated_utc':dt.datetime.now(dt.timezone.utc).isoformat()})
        time.sleep(30)
    write(a.state,{'phase':'explicitly_stopped','updated_utc':dt.datetime.now(dt.timezone.utc).isoformat()})

if __name__=='__main__':main()
