"""Keep an explicitly listed benchmark service chain alive without changing tasks."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import time


def alive_service(service):
    try:
        pid = int(Path(service['pid_file']).read_text().strip())
        proc = Path('/proc')/str(pid)
        if proc.joinpath('stat').read_text().rsplit(')', 1)[1].split()[0] == 'Z':
            return False
        args = [x.decode(errors='replace') for x in proc.joinpath('cmdline').read_bytes().split(b'\0') if x]
        return all(token in args for token in service['identity'])
    except (OSError, ValueError, IndexError):
        return False


def run(spec_path):
    spec = json.loads(spec_path.read_text())
    root = Path(spec['state_root'])
    root.mkdir(parents=True, exist_ok=True)
    lock = (root/'watchdog.lock').open('a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        return
    (root/'watchdog.pid').write_text(str(os.getpid())+'\n')
    while not (root/'STOP').exists():
        reload_error=None
        try:
            updated=json.loads(spec_path.read_text())
            if Path(updated['state_root']).resolve()!=root.resolve():
                raise ValueError('Restart explicitly before changing the watchdog state directory')
            spec=updated
        except (OSError,ValueError,KeyError) as exc:
            reload_error=str(exc)
        states = {}
        for service in spec['services']:
            name = service['name']
            if service.get('stop_marker') and Path(service['stop_marker']).exists():
                states[name] = {'phase':'paused'}
                continue
            if any(states.get(dep, {}).get('phase') != 'active' for dep in service.get('depends_on', [])):
                states[name] = {'phase':'waiting_dependency'}
                continue
            if not alive_service(service):
                try:
                    environment = os.environ.copy()
                    environment.update(service.get('environment', {}))
                    for key, path in service.get('environment_files', {}).items():
                        environment[key] = Path(path).read_text().strip()
                    log = Path(service['log']); log.parent.mkdir(parents=True, exist_ok=True)
                    with log.open('ab') as stream:
                        process = subprocess.Popen(service['command'], cwd=service['cwd'], env=environment,
                            stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
                    pid_file=Path(service['pid_file']);pid_file.parent.mkdir(parents=True,exist_ok=True)
                    pid_file.write_text(str(process.pid)+'\n')
                    states[name] = {'phase':'starting','pid':process.pid,'started_at':time.time()}
                except (OSError,ValueError) as exc:
                    states[name] = {'phase':'stale','error':f'{type(exc).__name__}: {exc}'}
            else:
                states[name] = {'phase':'active','pid':int(Path(service['pid_file']).read_text().strip())}
        payload = {'pid':os.getpid(),'updated_at':time.time(),'services':states,
                   'scope':spec['scope'],'generation_rules_modified':False,'config_reload_error':reload_error}
        temporary = root/'health.tmp'
        temporary.write_text(json.dumps(payload, indent=2)+'\n')
        temporary.replace(root/'health.json')
        time.sleep(spec.get('interval',30))


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--spec', type=Path, required=True)
    run(parser.parse_args().spec.resolve())
