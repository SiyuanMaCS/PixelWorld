"""Move proxy logging to a local durable spool and archive off the request path.

The running proxy keeps its original path and key. Old files are retained in a
legacy directory; an independent worker copies changed spool files to BN shards.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import shutil
import signal
import time


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(value, indent=2))
    tmp.replace(path)


def cutover(log_dir: Path, spool: Path, pid: int | None = None):
    log_dir = log_dir.absolute()
    spool = spool.resolve()
    if log_dir.is_symlink():
        if log_dir.resolve() != spool:
            raise ValueError('Proxy log path points to another spool')
        return json.loads((spool / 'cutover.json').read_text())
    if not log_dir.is_dir() or spool == log_dir.resolve():
        raise ValueError('Use an existing log directory and a separate local spool')
    spool.mkdir(parents=True, exist_ok=True)
    spool.chmod(0o700)
    if any(spool.iterdir()):
        raise ValueError('New spool must be empty')
    for name in ('local.key', 'mux.key'):
        path = log_dir / name
        if path.exists():
            shutil.copy2(path, spool / name)
            (spool / name).chmod(0o600)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    legacy = log_dir.with_name(log_dir.name + '_legacy_' + stamp)
    link = log_dir.with_name(log_dir.name + '.cutover-link')
    if legacy.exists() or link.exists():
        raise FileExistsError('A prior cutover path already exists')
    link.symlink_to(spool, target_is_directory=True)
    stopped = False
    try:
        if pid is not None:
            args = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
            if not any(arg.endswith(b'/responses_proxy.py') for arg in args):
                raise ValueError('Proxy PID identity does not match')
            os.kill(pid, signal.SIGSTOP)
            stopped = True
        log_dir.rename(legacy)
        try:
            link.replace(log_dir)
        except BaseException:
            legacy.rename(log_dir)
            raise
    finally:
        if stopped:
            os.kill(pid, signal.SIGCONT)
        link.unlink(missing_ok=True)
    result = {'original_log_path': str(log_dir), 'spool': str(spool),
              'legacy': str(legacy), 'completed_unix': time.time(),
              'existing_requests_and_credentials_preserved': True}
    atomic_json(spool / 'cutover.json', result)
    return result


def allowed(path):
    return (path.name == 'requests.jsonl' or
            (path.name.startswith('resp_') and path.name.endswith(
                ('.input.json', '.native.json', '.events.json', '.response.json', '.error.txt'))))


def copy_record(path, archive):
    st = path.stat()
    day = datetime.fromtimestamp(st.st_mtime, timezone.utc).strftime('%Y-%m-%d')
    shard = path.name[5:7] if path.name.startswith('resp_') else 'summary'
    destination = archive / day / shard / path.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_name(destination.name + '.tmp')
    shutil.copyfile(path, tmp)
    tmp.chmod(0o600)
    tmp.replace(destination)
    return {'stamp': [st.st_mtime_ns, st.st_size],
            'archive': str(destination.relative_to(archive))}


def watch(spool, archive, interval=30, workers=4):
    lock = (spool / '.archive.lock').open('a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return
    receipt_path = spool / 'archive_receipts.json'
    receipts = json.loads(receipt_path.read_text()) if receipt_path.exists() else {}
    pending = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        while True:
            errors = []
            for name, future in list(pending.items()):
                if future.done():
                    try:
                        receipts[name] = future.result()
                    except Exception as exc:
                        errors.append(f'{name}: {type(exc).__name__}: {exc}')
                    del pending[name]
            changed = []
            for path in spool.iterdir():
                if not allowed(path) or path.name in pending:
                    continue
                st = path.stat()
                if path.name != 'requests.jsonl' and time.time() - st.st_mtime < 3:
                    continue
                if receipts.get(path.name, {}).get('stamp') != [st.st_mtime_ns, st.st_size]:
                    changed.append(path)
            for path in changed[:max(0, workers * 16 - len(pending))]:
                pending[path.name] = pool.submit(copy_record, path, archive)
            atomic_json(receipt_path, receipts)
            atomic_json(spool / 'archive_status.json', {
                'pid': os.getpid(), 'updated_unix': time.time(),
                'archived_files': len(receipts), 'pending_files': len(changed),
                'active_copies': len(pending), 'errors': errors,
                'inference_waits_for_archive': False,
            })
            time.sleep(interval)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('action', choices=['cutover', 'watch'])
    p.add_argument('--spool', type=Path, required=True)
    p.add_argument('--log-dir', type=Path)
    p.add_argument('--archive', type=Path)
    p.add_argument('--proxy-pid', type=int)
    p.add_argument('--interval', type=float, default=30)
    args = p.parse_args()
    if args.action == 'cutover':
        print(json.dumps(cutover(args.log_dir, args.spool, args.proxy_pid)))
    else:
        watch(args.spool, args.archive, args.interval)


if __name__ == '__main__':
    main()
