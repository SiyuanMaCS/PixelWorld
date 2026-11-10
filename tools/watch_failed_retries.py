"""Authorize one bounded extra retry round for terminal failed cases."""
from pathlib import Path
import argparse
import json
import sys
import time
import os
import subprocess

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pixelworld.config import load_config
from pixelworld.retries import authorize_failed
from pixelworld.util import atomic_json, utc_now


def ensure_manager(config, entry):
    def command(pid):
        try:return (Path('/proc')/str(pid)/'cmdline').read_bytes()
        except OSError:return b''
    pid_file=Path(entry['pid_file']);state=Path(entry['state_file']);code=Path(entry['code_root'])
    if pid_file.exists():
        pid=pid_file.read_text().strip();cmdline=command(pid)
        if b'manage_matrix.py' in cmdline and str(config.source).encode() in cmdline:
            return {'phase':'manager_active','pid':int(pid)}
    status_file=config.runs_root/'status.json'
    if status_file.exists():
        status=json.loads(status_file.read_text());cmdline=command(status.get('supervisor_pid'))
        if not (str(config.source).encode() in cmdline and b'matrix' in cmdline):
            status['supervisor_pid']=None;atomic_json(status_file,status)
    state.parent.mkdir(parents=True,exist_ok=True);pid_file.parent.mkdir(parents=True,exist_ok=True)
    cmd=[sys.executable,'-u',str(Path(__file__).with_name('manage_matrix.py')),'--config',str(config.source),
         '--code-root',str(code),'--state',str(state)]
    with state.with_suffix('.retry-manager.log').open('ab') as log:
        process=subprocess.Popen(cmd,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,
                                 start_new_session=True,env=os.environ.copy(),cwd=code)
    pid_file.write_text(str(process.pid)+'\n')
    return {'phase':'manager_restarted','pid':process.pid,'code_root':str(code)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, action="append", required=True)
    parser.add_argument("--extra-attempts", type=int, default=2)
    parser.add_argument("--max-rounds", type=int, default=1)
    parser.add_argument('--continuous',action='store_true',help='Keep requeueing exhausted cases; each round retains its own fixed token budget')
    parser.add_argument('--cooldown',type=float,default=300,help='Minimum seconds between retry grants for a case in continuous mode')
    parser.add_argument('--manager-map',type=Path,help='Runtime config-path to original manager/code checkout map')
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval", type=float, default=60)
    parser.add_argument("--status", type=Path)
    args = parser.parse_args()
    if args.interval < 1:
        raise ValueError("Watch interval must be positive")
    managers=json.loads(args.manager_map.read_text()) if args.manager_map else {}
    while True:
        reports = []
        for path in args.config:
            config = load_config(path)
            if (config.runs_root / "STOP").exists():
                reports.append({"config": str(path), "phase": "explicitly_stopped"})
                continue
            result = authorize_failed(config, args.extra_attempts, None if args.continuous else args.max_rounds,
                                      args.apply, args.cooldown if args.continuous else 0)
            entry=managers.get(str(config.source))
            if result['authorized_cases'] and args.apply and entry:
                result['manager']=ensure_manager(config,entry)
            reports.append({"config": str(path), **result})
        result = {"updated_utc": utc_now(), "reports": reports}
        if args.status:
            atomic_json(args.status, result)
        print(json.dumps({"updated_utc": result["updated_utc"],
                          "configs": [{"config": r["config"], "authorized_cases": r.get("authorized_cases", 0),
                                       "phase": r.get("phase")} for r in reports]}), flush=True)
        if not args.watch:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
