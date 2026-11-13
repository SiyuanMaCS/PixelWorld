"""Publish incremental live metadata and saved RGB candidates independently of Pages.

Only public case artifacts are exported. API records, secrets, private paths and
provider reasoning stay private. Sources are read; agent workspaces are untouched.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from zipfile import BadZipFile
import shutil
import subprocess
import time
import fcntl
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_bench_review import export_pixels
from pixelworld.smoke_web import clean
from tools.live_evaluation_data import collect as collect_evaluation
from tools.live_case_diagnostics import diagnostics as case_diagnostics, VERSION as DIAGNOSTICS_VERSION

PUBLIC_SCHEMA = 2


def read(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def save(path, value):
    text = json.dumps(value, ensure_ascii=False, separators=(',', ':'))
    if path.exists() and path.read_text() == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(text)
    tmp.replace(path)
    return True


def save_head_pointer(destination, revision, now=None):
    """Publish an immutable time-bucket pointer to an already-pushed commit."""
    bucket = int(time.time() if now is None else now) // 30 * 30
    day = datetime.fromtimestamp(bucket, timezone.utc).date().isoformat()
    path = destination / 'live-heads' / day / f'{bucket}.json'
    if not path.exists():
        save(path, {'revision': revision, 'bucket_unix': bucket})
    return path


def image_asset(source, destination):
    if not source.is_file():
        return None
    data = source.read_bytes()
    key = hashlib.sha256(data).hexdigest()[:20]
    name = 'assets/' + key + source.suffix
    target = destination / name
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary=target.with_name(target.name+'.'+uuid.uuid4().hex+'.tmp')
        temporary.write_bytes(data)
        temporary.replace(target)
    return name


def export_candidate(source, destination, spec, label, utc):
    pixels = source / 'pixels.npz'
    if not pixels.is_file():
        return None
    digest = hashlib.sha256(pixels.read_bytes()).hexdigest()[:20]
    prefix = 'assets/' + digest
    target = destination / prefix
    locks=destination/'.asset-locks';locks.mkdir(parents=True,exist_ok=True)
    with (locks/(digest+'.lock')).open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        video = export_pixels(source, target, spec)
    if not video:
        return None
    value = {**video, 'label': label, 'utc': utc,
             'pixels': prefix + '/' + video['pixels_file'],
             'poster': prefix + '/poster.png'}
    for name in ('inspection.png', 'transition_check.png'):
        if (source / name).is_file():
            value[name.split('.')[0]] = image_asset(source / name, destination)
    if (source / 'generate.py').is_file():
        value['code'] = clean((source / 'generate.py').read_text())
    return value


def case_data(run, destination, previous=None):
    manifest = read(run / 'run_manifest.json')
    spec = read(run / 'media_contract.json')
    budget = read(run / 'logs/token_budget.json')
    usage = manifest.get('token_usage') or {}
    prompt = run / 'input_snapshot/prompt.txt'
    if not prompt.is_file():
        prompt = run / 'workspace/prompt.txt'
    snapshots = sorted((run / 'trace').glob('round_*/snapshot.json'))
    pixels = run / 'workspace/pixels.npz'
    media_stamp = ([pixels.stat().st_mtime_ns, pixels.stat().st_size] if pixels.exists() else []) + [
        [p.parent.name, p.stat().st_mtime_ns] for p in snapshots]
    versions = []
    reused = (previous is not None and previous.get('schema_version') == PUBLIC_SCHEMA
              and previous.get('media_stamp') == media_stamp)
    if reused:
        versions = previous.get('candidates', [])
    for path in ([] if reused else snapshots):
        record = read(path)
        try:
            video = export_candidate(path.parent, destination, spec,
                                     f'候选 {len(versions) + 1}', record.get('utc'))
            if video:
                versions.append(video)
        except (OSError, ValueError, KeyError, EOFError, BadZipFile):
            # A snapshot can still be completing. Keep earlier versions visible.
            continue
    if not reused and (not versions or manifest.get('status') == 'complete'):
        try:
            final = export_candidate(run / 'workspace', destination, spec,
                                     '当前保存结果', manifest.get('completed_utc'))
            if final and (not versions or versions[-1]['pixels'] != final['pixels']):
                versions.append(final)
        except (OSError, ValueError, KeyError, EOFError, BadZipFile):
            pass
    events = []
    event_path = run / 'logs/events.jsonl'
    if event_path.is_file():
        for line in event_path.read_text(errors='replace').splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            item = event.get('item') or {}
            if event.get('type') == 'item.completed' and item.get('type') != 'reasoning':
                value = {'kind': item.get('type'),
                         'utc': (event.get('_harness_received') or {}).get('utc')}
                for key in ('command', 'aggregated_output', 'text', 'exit_code', 'status'):
                    if key in item:
                        raw = item[key]
                        value[key] = clean(raw) if isinstance(raw, str) else raw
                if item.get('type') == 'full_trace_image_return':
                    value['images'] = []
                    for returned in item.get('returned_images') or []:
                        name = returned.get('path')
                        if not name or returned.get('available') is False:
                            continue
                        source = (event_path.parent / name).resolve()
                        if source.is_relative_to(event_path.parent.resolve()) and source.is_file():
                            image = image_asset(source, destination)
                            if image:
                                value['images'].append(image)
                if len(value.get('aggregated_output', '')) > 30000:
                    value['aggregated_output'] = value['aggregated_output'][:30000] + '\n[网页截取；完整原始输出保留在实验记录中]'
                events.append(value)
            elif event.get('type') in ('turn.failed', 'turn.completed', 'error', 'turn.cancelled'):
                events.append({'kind': event['type'],
                               'utc': (event.get('_harness_received') or {}).get('utc'),
                               'text': clean(str(event.get('message') or event.get('error') or ''))})
    return {'case_id': manifest['case_id'], 'model_key': manifest['model_key'],
            'model': manifest['model'], 'track': manifest['track'],
            'attempt': manifest['attempt'], 'status': manifest['status'],
            'delivery_status': 'stale' if (manifest.get('validation') or {}).get('infra_error') else manifest['status'],
            'started_utc': manifest.get('started_utc'),
            'completed_utc': manifest.get('completed_utc'),
            'output_tokens': budget.get('reported_output_tokens', usage.get('output_tokens')),
            'budget_exhausted': budget.get('exhausted', False),
            'diagnostics':case_diagnostics(run,manifest,budget,events),
            'validation': {k: v for k, v in (manifest.get('validation') or {}).items()
                           if k in ('pass', 'missing_required', 'generate_runs', 'frames')},
            'spec': spec, 'prompt': clean(prompt.read_text()) if prompt.exists() else '',
            'first_frame': image_asset(run / 'input_snapshot/first_frame.png', destination),
            'source_video': image_asset(run / 'input_snapshot/source_video.mp4', destination),
            'candidates': versions, 'events': events, 'media_stamp': media_stamp,
            'schema_version': PUBLIC_SCHEMA}


def sources(run_root):
    primary = ('physics_iq_512w24fps_gpt_native', 'physics_iq', 'physics_iq_gpt_native_v2',
               'physics_iq_seed21_native_v2', 'robojudge', 'robojudge_seed21_native_v2', 'pcve_smoke')
    values = [(name, run_root / 'generations' / name) for name in primary]
    paired = run_root.parent / 'phygen_pixelspace_v2_20261112/generations'
    paired_values = [('phygen_' + name, paired / name) for name in
                     ('t2v', 'i2v_qweninit', 't2v_deepseek', 'i2v_qweninit_deepseek')]
    values = values[:1] + paired_values + values[1:]
    return [(key, path) for key, path in values if (path / 'status.json').is_file()]


def update(run_root, destination, cache, initial_limit=2, suites=None):
    catalogue = {'groups': [], 'updated_utc': datetime.now(timezone.utc).isoformat()}
    for suite, source in sources(run_root):
        if suites is not None and suite not in suites:
            continue
        status = read(source / 'status.json')
        for key, group in status.get('groups', {}).items():
            model, track = key.split('/', 1)
            if model == 'gemini38-flash':
                continue
            identity = suite + '/' + key
            stored = cache.setdefault(identity, {})
            # Current attempts are always first, before any old trace backlog.
            priority = set(group.get('running_cases') or [])
            if group.get('latest_completion'):
                priority.add(group['latest_completion'][1])
            already_complete = (status.get('cases', 0) > 4 and
                                group.get('counts', {}).get('complete') == status.get('cases'))
            folder = source / model / track
            manifests = ([] if already_complete and not stored or not folder.exists() else
                         [p / 'run_manifest.json' for p in folder.iterdir()
                          if p.name.startswith('case_') and '_attempt_' in p.name])
            manifests.sort(key=lambda p: (p.parent.name.rsplit('_attempt_', 1)[0][5:] not in priority, p.parent.name))
            missed = 0
            for path in manifests:
                run = path.parent
                case = run.name.rsplit('_attempt_', 1)[0][5:]
                if case not in priority and run.name not in stored:
                    if missed >= initial_limit:
                        continue
                    missed += 1
                if not path.is_file():
                    continue
                token = run / 'logs/token_budget.json'
                stamp = [PUBLIC_SCHEMA, path.stat().st_mtime_ns,
                         token.stat().st_mtime_ns if token.exists() else 0,
                         [(p.name, p.stat().st_mtime_ns) for p in (run / 'trace').glob('round_*/snapshot.json')],
                         (run / 'logs/events.jsonl').stat().st_mtime_ns if (run / 'logs/events.jsonl').exists() else 0]
                if stored.get(run.name, {}).get('stamp') != stamp:
                    try:
                        relative = identity + '/' + run.name + '.json'
                        detail = case_data(run, destination, previous=read(destination / relative))
                    except (OSError, ValueError, KeyError, EOFError, BadZipFile):
                        continue
                    relative = identity + '/' + run.name + '.json'
                    save(destination / relative, detail)
                    stored[run.name] = {'stamp': stamp, 'detail': relative, 'case': case,
                                        'attempt': detail['attempt'], 'status': detail['delivery_status'],
                                        'raw_status': detail['status'],
                                        'output_tokens': detail['output_tokens'],
                                        'candidate_count': len(detail['candidates']),
                                        'poster': detail['candidates'][-1]['poster'] if detail['candidates'] else detail['first_frame']}
            cases = {}
            for value in stored.values():
                cases.setdefault(value['case'], []).append({k: v for k, v in value.items() if k != 'stamp'})
            for history in cases.values():
                newest = max(a['attempt'] for a in history)
                for attempt in history:
                    if attempt['status'] == 'running' and attempt['attempt'] < newest:
                        attempt['status'] = 'stale'
            completed = [min([a for a in history if a['status'] == 'complete'], key=lambda a: a['attempt'])
                         for history in cases.values() if any(a['status'] == 'complete' for a in history)]
            measured = [a['output_tokens'] for a in completed if a.get('output_tokens') is not None]
            payload = {'suite': suite, 'model_key': model, 'track': track,
                       'counts': group.get('counts') or {}, 'cases_total': status.get('cases'),
                       'mean_duration_seconds': group.get('mean_duration_seconds'),
                       'mean_output_tokens_cached': sum(measured) / len(measured) if measured else None,
                       'token_mean_cases': len(measured),
                       'updated_utc': status.get('updated_utc'), 'cases': cases}
            relative = identity + '/index.json'
            save(destination / relative, payload)
            catalogue['groups'].append({k: payload[k] for k in ('suite', 'model_key', 'track', 'counts', 'cases_total', 'mean_duration_seconds', 'mean_output_tokens_cached', 'token_mean_cases')})
            catalogue['groups'][-1]['path'] = relative
    save(destination / 'catalogue.json', catalogue)


def render_case_set(folder, case, identity, render_root, saved):
    """All potentially slow case I/O stays off the publication thread."""
    locks=render_root/'.case-locks';locks.mkdir(parents=True,exist_ok=True)
    key=hashlib.sha256((identity+'/'+str(case)).encode()).hexdigest()
    with (locks/(key+'.lock')).open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        return _render_case_set(folder,case,identity,render_root,saved)


def _render_case_set(folder, case, identity, render_root, saved):
    rows = []
    paths = list(folder.glob(f'case_{case}_attempt_*')) if case else list(folder.glob('case_*_attempt_*'))
    for run in paths:
        manifest = run / 'run_manifest.json'
        if not manifest.is_file():
            continue
        relative = identity + '/' + run.name + '.json'
        token = run / 'logs/token_budget.json'
        events = run / 'logs/events.jsonl'
        stamp = [PUBLIC_SCHEMA, manifest.stat().st_mtime_ns,
                 token.stat().st_mtime_ns if token.exists() else 0,
                 events.stat().st_mtime_ns if events.exists() else 0,
                 [(p.parent.name,p.stat().st_mtime_ns) for p in (run/'trace').glob('round_*/snapshot.json')],
                 DIAGNOSTICS_VERSION]
        if saved.get(run.name,{}).get('stamp') == stamp:
            continue
        try:
            detail = case_data(run, render_root, previous=read(render_root/relative))
        except (OSError,ValueError,KeyError,EOFError,BadZipFile):
            continue
        save(render_root/relative,detail)
        rows.append((run.name,relative,stamp,detail))
    return rows


def referenced_assets(detail):
    values = [detail.get('first_frame'), detail.get('source_video')]
    for video in detail.get('candidates',[]):
        values += [video.get(k) for k in ('pixels','poster','inspection','transition_check')]
    for event in detail.get('events',[]):
        values += event.get('images',[])
    return set(path for path in values if path)


def render_backfill_set(folder,identity,render_root,saved,excluded=(),limit=4):
    """Export a bounded historical batch in workers reserved for old cases."""
    cases=set()
    for run in folder.glob('case_*_attempt_*'):
        case=run.name[5:].rsplit('_attempt_',1)[0]
        if case in excluded:continue
        manifest=run/'run_manifest.json'
        try:
            stamp=manifest.stat().st_mtime_ns
        except OSError:continue
        cached=saved.get(run.name,{}).get('stamp') or []
        if len(cached)<2 or cached[0]!=PUBLIC_SCHEMA or cached[1]!=stamp or cached[-1]!=DIAGNOSTICS_VERSION:
            cases.add(case)
    rows=[]
    for case in sorted(cases)[:limit]:
        rows.extend(render_case_set(folder,case,identity,render_root,saved))
    return rows


def merge_render_jobs(destination,cache,pending,render_root):
    for key,future in list(pending.items()):
        if not future.done():
            continue
        identity,_ = key
        try:
            rows = future.result()
        except Exception:
            rows = []
        for name,relative,stamp,detail in rows:
            for asset in referenced_assets(detail):
                target=destination/asset
                if not target.exists():
                    target.parent.mkdir(parents=True,exist_ok=True)
                    temp=target.with_name(target.name+'.tmp')
                    shutil.copyfile(render_root/asset,temp)
                    temp.replace(target)
            save(destination/relative,detail)
            cache.setdefault(identity,{})[name]={'stamp':stamp,'detail':relative,
                'case':detail['case_id'],'attempt':detail['attempt'],
                'status':detail['delivery_status'],'raw_status':detail['status'],
                'output_tokens':detail['output_tokens'],'candidate_count':len(detail['candidates']),
                'poster':detail['candidates'][-1]['poster'] if detail['candidates'] else detail['first_frame']}
        del pending[key]


def async_update(run_root,destination,cache,pool,pending,render_root,
                 history_pool=None,history_pending=None,history_cursor=None):
    merge_render_jobs(destination,cache,pending,render_root)
    if history_pending is not None:
        merge_render_jobs(destination,cache,history_pending,render_root)
    catalogue={'groups':[],'updated_utc':datetime.now(timezone.utc).isoformat()}
    historical=[]
    for suite,source in sources(run_root):
        status=read(source/'status.json')
        for key,group in status.get('groups',{}).items():
            model,track=key.split('/',1)
            if model=='gemini38-flash':
                continue
            identity=suite+'/'+key;stored=cache.setdefault(identity,{})
            desired=list(group.get('running_cases') or [])
            if group.get('latest_completion'):
                desired.append(group['latest_completion'][1])
            if suite.startswith('phygen_'):
                # Four-case smoke discovery also runs in the I/O worker.
                desired=[None]
            for case in desired:
                job=(identity,case)
                if job not in pending and (history_pending is None or job not in history_pending) and len(pending)<48:
                    pending[job]=pool.submit(render_case_set,source/model/track,case,identity,render_root,dict(stored))
            if (history_pool is not None and status.get('cases',0)>4):
                historical.append((identity,source/model/track,dict(stored),desired))
            cases={}
            for value in stored.values():
                cases.setdefault(value['case'],[]).append({k:v for k,v in value.items() if k!='stamp'})
            for history in cases.values():
                newest=max(a['attempt'] for a in history)
                for attempt in history:
                    if attempt['status']=='running' and attempt['attempt']<newest:attempt['status']='stale'
            completed=[min([a for a in h if a['status']=='complete'],key=lambda a:a['attempt'])
                       for h in cases.values() if any(a['status']=='complete' for a in h)]
            measured=[a['output_tokens'] for a in completed if a.get('output_tokens') is not None]
            payload={'suite':suite,'model_key':model,'track':track,'counts':group.get('counts') or {},
                'cases_total':status.get('cases'),'updated_utc':status.get('updated_utc'),'cases':cases,
                'mean_duration_seconds':group.get('mean_duration_seconds'),
                'mean_output_tokens_cached':sum(measured)/len(measured) if measured else None,
                'token_mean_cases':len(measured)}
            relative=identity+'/index.json';save(destination/relative,payload)
            catalogue['groups'].append({k:v for k,v in payload.items() if k not in ('cases','updated_utc')})
            catalogue['groups'][-1]['path']=relative
    save(destination/'catalogue.json',catalogue)
    if history_pool is not None and history_pending is not None and historical:
        start=history_cursor[0] % len(historical) if history_cursor is not None else 0
        ordered=historical[start:]+historical[:start]
        for index,(identity,folder,saved,desired) in enumerate(ordered):
            if len(history_pending)>=2:break
            job=(identity,'_history')
            if job in history_pending:continue
            excluded=set(desired)|{case for (name,case) in pending if name==identity}
            history_pending[job]=history_pool.submit(render_backfill_set,folder,identity,render_root,saved,excluded)
            if history_cursor is not None:history_cursor[0]=(start+index+1)%len(historical)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--run-root', type=Path, required=True)
    p.add_argument('--checkout', type=Path, required=True)
    p.add_argument('--interval', type=float, default=30)
    p.add_argument('--once', action='store_true')
    args = p.parse_args()
    root = args.checkout.resolve()
    root.mkdir(parents=True, exist_ok=True)
    lock = (root / '.publisher.lock').open('a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return
    destination = root / 'pixelworld'
    cache_path = root / '.publisher_cache.json'
    cache = read(cache_path)
    pool=ThreadPoolExecutor(max_workers=4)
    evaluation_pool=ThreadPoolExecutor(max_workers=1)
    history_pool=ThreadPoolExecutor(max_workers=2)
    history_pending={}
    history_cursor=[0]
    evaluation_future=None
    evaluation_error=None
    pending={}
    render_root=root/'.render-cache'
    render_root.mkdir(exist_ok=True)
    while True:
        start = time.monotonic()
        try:
            published_revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
            async_update(args.run_root.resolve(),destination,cache,pool,pending,render_root,
                         history_pool,history_pending,history_cursor)
            if evaluation_future is not None and evaluation_future.done():
                try:
                    save(destination/'evaluation.json',evaluation_future.result())
                    evaluation_error=None
                except Exception as exc:
                    evaluation_error=str(exc)
                evaluation_future=None
            if evaluation_future is None:
                evaluation_future=evaluation_pool.submit(collect_evaluation,args.run_root.resolve())
            save_head_pointer(destination, published_revision)
            save(cache_path, cache)
            subprocess.run(['git', 'add', '--', 'pixelworld', ':(exclude)pixelworld/**/*.tmp'], cwd=root, check=True)
            if subprocess.run(['git', 'diff', '--cached', '--quiet'], cwd=root).returncode:
                subprocess.run(['git', 'commit', '-m', 'Refresh live PixelWorld progress and saved candidates'], cwd=root, check=True,
                               stdout=subprocess.DEVNULL)
            subprocess.run(['git', 'push', 'origin', 'pixelworld-live'], cwd=root, check=True, timeout=60)
            save(root / '.publisher_status.json', {'pid': __import__('os').getpid(), 'updated_unix': time.time(),
                 'duration_seconds': time.monotonic() - start, 'groups': len(cache), 'status': 'ok',
                 'pending_case_reads':len(pending),'pending_history_batches':len(history_pending),
                 'evaluation_reader_error':evaluation_error})
        except Exception as exc:
            save(root / '.publisher_status.json', {'pid': __import__('os').getpid(), 'updated_unix': time.time(),
                 'status': 'error', 'error': str(exc)})
        if args.once:
            break
        time.sleep(args.interval)


if __name__ == '__main__':
    main()
