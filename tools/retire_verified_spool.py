"""Retire a frozen local spool after snapshot and delta readback verification."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.spool_api_logs import atomic_json, copy_record


def signature(path):
    s=path.stat()
    return [s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns]


def retire(source, snapshot, archive, retired_proxy_pid):
    if source.is_symlink() or Path('/proc',str(retired_proxy_pid)).exists():
        raise RuntimeError('Freeze the original writer before retiring its real spool')
    report=json.loads((snapshot/'archive-verification-report.json').read_text())
    if (report['phase']!='completed' or report['sha256_mismatches']
            or report['missing_files'] or report['verified_files']!=report['archived_files']):
        raise RuntimeError('The full snapshot has not passed readback verification')
    inventory=json.loads((snapshot/'source-inventory.json').read_text())
    initial={e['name']:[e['dev'],e['ino'],e['size'],e['mtime_ns'],e['ctime_ns']]
             for e in inventory['entries']}
    current={p.name:signature(p) for p in source.iterdir() if p.is_file() and not p.is_symlink()}
    delta=[source/name for name,s in current.items() if initial.get(name)!=s]
    status_path=archive/'retirement_status.json';archive.mkdir(parents=True,exist_ok=True)
    status={'phase':'archiving_delta','snapshot':str(snapshot),'source':str(source),
            'snapshot_verified_files':report['verified_files'],'delta_files':len(delta),
            'verified_delta_files':0,'released_files':0,'released_bytes':0,
            'retired_proxy_pid':retired_proxy_pid}
    atomic_json(status_path,status)
    receipts={}
    with ThreadPoolExecutor(max_workers=8) as pool:
        jobs={pool.submit(copy_record,p,archive,True):p for p in delta}
        for future in as_completed(jobs):
            p=jobs[future];receipt=future.result()
            if signature(p)!=current[p.name]:raise RuntimeError('Retired spool changed during archival')
            receipts[p.name]=receipt;status['verified_delta_files']=len(receipts)
            atomic_json(status_path,status)
    atomic_json(archive/'delta_receipts.json',receipts)
    status['phase']='releasing_verified_source';atomic_json(status_path,status)
    for name,s in current.items():
        p=source/name
        if signature(p)!=s:raise RuntimeError('Retired spool changed before release')
        p.unlink();status['released_files']+=1;status['released_bytes']+=s[2]
        if status['released_files']%500==0:atomic_json(status_path,status)
    if any(source.iterdir()):raise RuntimeError('Unexpected non-file source entries retained')
    source.rmdir()
    status.update(phase='completed',completed_unix=time.time(),all_bytes_preserved_on_bn=True)
    atomic_json(status_path,status)
    return status


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for flag in ['source','snapshot','archive']:parser.add_argument('--'+flag,type=Path,required=True)
    parser.add_argument('--retired-proxy-pid',type=int,required=True)
    a=parser.parse_args()
    print(json.dumps(retire(a.source,a.snapshot,a.archive,a.retired_proxy_pid)))
