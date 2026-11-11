"""Prepare trace pages independently of GitHub publication, within explicit scope."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_bench_review import case_page_is_current
from tools.sync_incremental_previews import SUITES

SCOPE = ('physics_iq', 'physics_iq_gpt_native_v2', 'physics_iq_seed21_native_v2',
         'robojudge', 'robojudge_seed21_native_v2', 'pcve_smoke')


def read(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def active(state, job):
    try:
        pid = state.get('pid') or int(job.with_suffix('.pid').read_text())
        proc = Path('/proc') / str(pid)
        return (proc.joinpath('stat').read_text().rsplit(')', 1)[1].split()[0] != 'Z'
                and any(x.endswith(b'build_one_preview.py')
                        for x in proc.joinpath('cmdline').read_bytes().split(b'\0')))
    except (OSError, ValueError, IndexError):
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-root', type=Path, required=True)
    parser.add_argument('--web-root', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--interval', type=float, default=60)
    args = parser.parse_args()
    root = args.run_root.resolve()
    jobs = root / 'preview_render_jobs'
    jobs.mkdir(exist_ok=True)
    lock = (root / 'preview_renderer.lock').open('a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return
    (root / 'preview_renderer.pid').write_text(str(os.getpid()) + '\n')
    while not (root / 'preview_renderer.STOP').exists():
        states = {job: read(job) for job in jobs.glob('*.json')}
        running = sum(active(state, job) for job, state in states.items())
        rows = []
        # Only terminal attempts are rendered; generating workspaces stay untouched.
        for suite in SCOPE:
            source = root / 'generations' / suite
            if (source / 'STOP').exists():
                continue
            for manifest in source.glob('*/*/case_*_attempt_*/run_manifest.json'):
                value = read(manifest)
                if value.get('status') not in ('complete', 'failed'):
                    continue
                run = manifest.parent
                job = jobs / (hashlib.sha256(str(run).encode()).hexdigest()[:20] + '.json')
                state = states.get(job, {})
                if active(state, job):
                    continue
                if state.get('phase') == 'failed' and time.time() - state.get('updated_at', 0) < 300:
                    continue
                output = args.web_root / SUITES[suite] / run.relative_to(source)
                if state.get('phase') == 'ready' and case_page_is_current(run, output):
                    continue
                rows.append((value['status'] == 'complete',
                             value.get('completed_utc') or value.get('started_utc') or '',
                             run, output, job))
        rows.sort(key=lambda row: row[:2], reverse=True)
        launched = []
        for _, _, run, output, job in rows[:max(0, args.workers - running)]:
            command = [sys.executable, '-u', str(Path(__file__).with_name('build_one_preview.py')),
                       '--run', str(run), '--output', str(output), '--job', str(job)]
            # A competing publisher is safe: build_one_preview owns an output lock.
            with job.with_suffix('.log').open('ab') as log:
                process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log,
                                           stderr=subprocess.STDOUT, start_new_session=True)
            job.with_suffix('.pid').write_text(str(process.pid) + '\n')
            launched.append({'pid': process.pid, 'run': str(run)})
        status = {'pid': os.getpid(), 'updated_at': time.time(), 'scope': list(SCOPE),
                  'active_at_scan': running, 'workers': args.workers,
                  'pending_render_jobs': len(rows), 'launched': launched}
        temporary = root / 'preview_renderer_status.tmp'
        temporary.write_text(json.dumps(status, indent=2))
        temporary.replace(root / 'preview_renderer_status.json')
        time.sleep(args.interval)


if __name__ == '__main__':
    main()
