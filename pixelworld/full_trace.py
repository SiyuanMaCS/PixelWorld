"""Capture full CLI tool history outside the agent's visible workspace."""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import shutil

from .util import atomic_json


def archive_referenced_blobs(rollout: Path, logs: Path, blob_root: Path | None) -> dict:
    """Archive references in every message/return, not only image and call fields."""
    references = set()
    def visit(value):
        if isinstance(value, dict):
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
        elif isinstance(value, str) and re.fullmatch(
                r'traex-rollout-blob:v1:sha256:[0-9a-f]{64}:\d+', value):
            references.add(value)
    for line in rollout.open():
        visit(json.loads(line))
    records = []
    for reference in sorted(references):
        match = re.fullmatch(r'traex-rollout-blob:v1:sha256:([0-9a-f]{64}):(\d+)', reference)
        digest, size = match[1], int(match[2])
        relative = Path('sha256') / digest[:2] / digest
        target = logs / 'rollout-blobs' / relative
        source = target if target.is_file() else (blob_root / relative if blob_root else None)
        record = {'reference': reference, 'sha256': digest, 'bytes': size, 'available': False}
        if source is not None and source.is_file():
            raw = source.read_bytes()
            if len(raw) == size and hashlib.sha256(raw).hexdigest() == digest:
                if source != target:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(raw)
                record.update({'available': True, 'path': str(target.relative_to(logs))})
            else:
                record['error'] = 'Size or SHA256 mismatch'
        else:
            record['error'] = 'Referenced content unavailable'
        records.append(record)
    summary = {'referenced_blobs': len(records),
               'archived_blobs': sum(r['available'] for r in records),
               'unresolved_blobs': sum(not r['available'] for r in records),
               'records': records}
    atomic_json(logs / 'rollout_blob_manifest.json', summary)
    return {k: v for k, v in summary.items() if k != 'records'}


def _resolve_blob(value: str, logs: Path, blob_root: Path | None) -> str | None:
    match=re.fullmatch(r'traex-rollout-blob:v1:sha256:([0-9a-f]{64}):(\d+)',value)
    if not match:return value
    relative=Path('sha256')/match[1][:2]/match[1]
    target=logs/'rollout-blobs'/relative
    source=target if target.is_file() else (blob_root/relative if blob_root else None)
    if source is None or not source.is_file():return None
    raw=source.read_bytes()
    if len(raw)!=int(match[2]) or hashlib.sha256(raw).hexdigest()!=match[1]:
        raise ValueError('Rollout blob failed size/hash verification')
    if source!=target:
        target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
    return raw.decode('utf-8')


def extract_tools(rollout: Path, logs: Path, blob_root: Path | None = None) -> dict:
    blob_summary = archive_referenced_blobs(rollout, logs, blob_root)
    calls = {}
    outputs = {}
    for line in rollout.open():
        event = json.loads(line)
        payload = event.get('payload', {})
        items = payload.get('items', []) if event.get('type') == 'history_mutation' else (
            [payload] if event.get('type') == 'response_item' else [])
        for item in items:
            kind = item.get('type')
            call_id = item.get('call_id')
            if kind in ('custom_tool_call', 'function_call') and call_id:
                source_input=item.get('input') or item.get('arguments') or ''
                resolved_input=_resolve_blob(source_input,logs,blob_root)
                calls[call_id] = {'call_id': call_id, 'tool': item.get('name'),
                    'input': resolved_input if resolved_input is not None else source_input,
                    'utc': event.get('timestamp')}
            elif kind in ('custom_tool_call_output', 'function_call_output') and call_id:
                outputs[call_id] = {'output':item.get('output'),'utc':event.get('timestamp')}
    records = []
    returned_images = 0
    unresolved_images = 0
    for call_id, call in calls.items():
        # Names are syntactic evidence; image delivery is proved separately.
        nested = sorted(set(re.findall(r'\btools\.(\w+)\s*\(', call['input'])))
        record = dict(call, nested_tool_expressions=nested, returned_images=[])
        output_record = outputs.get(call_id,{})
        output = output_record.get('output')
        record['output_utc'] = output_record.get('utc')
        if isinstance(output, list):
            for block in output:
                if block.get('type') not in ('input_image', 'image'):continue
                url = block.get('image_url', '')
                if not isinstance(url,str):continue
                reference=url if url.startswith('traex-rollout-blob:') else None
                resolved=_resolve_blob(url,logs,blob_root)
                if resolved is None:
                    record['returned_images'].append({'path':None,'available':False,
                        'persisted_reference':reference,'source':'actual archived image message; blob unavailable'})
                    returned_images+=1;unresolved_images+=1
                    continue
                url=resolved
                if not url.startswith('data:image/'):continue
                header, encoded = url.split(',', 1)
                image_bytes = base64.b64decode(encoded, validate=True)
                digest = hashlib.sha256(image_bytes).hexdigest()
                suffix = '.jpg' if 'jpeg' in header else '.png' if 'png' in header else '.webp'
                relative = 'tool_images/' + digest + suffix
                target = logs / relative
                target.parent.mkdir(exist_ok=True)
                target.write_bytes(image_bytes)
                record['returned_images'].append({'path': relative, 'sha256': digest,
                    'bytes': len(image_bytes), 'mime_type': header.split(';')[0][5:],
                    'available':True,'persisted_reference':reference})
                returned_images += 1
        record['matched_output'] = call_id in outputs
        records.append(record)
    result = {'status': 'recorded', 'source': 'full CLI rollout, not stdout projection',
        'tool_calls': records, 'returned_images': returned_images,
        'unresolved_images':unresolved_images, **blob_summary,
        'limitations': 'Nested tool names are source expressions. Matched image outputs prove images delivered to the model; source text alone does not prove every expression executed.'}
    atomic_json(logs / 'tool_calls.json', result)
    return result


def capture_rollout(cli_home: Path, logs: Path, started: dt.datetime) -> dict:
    thread_id = None
    for line in (logs / 'events.jsonl').open():
        event = json.loads(line)
        if event.get('type') == 'thread.started':thread_id = event.get('thread_id');break
    if not thread_id or not re.fullmatch(r'[0-9a-f-]{36}', thread_id):
        return {'status': 'missing', 'reason': 'No valid thread id in stdout events'}
    matches = []
    for offset in (-1, 0, 1):
        date = started + dt.timedelta(days=offset)
        folder = cli_home / 'sessions' / date.strftime('%Y/%m/%d')
        matches.extend(folder.glob(f'*{thread_id}.jsonl'))
    if len(matches) != 1:
        return {'status': 'missing', 'thread_id': thread_id,
            'reason': f'Expected one persisted session rollout, found {len(matches)}'}
    target = logs / 'full_rollout.jsonl'
    shutil.copy2(matches[0], target)
    result = extract_tools(target, logs, matches[0].with_suffix('.artifacts')/'rollout-blobs')
    result['thread_id'] = thread_id
    result['rollout_sha256'] = hashlib.sha256(target.read_bytes()).hexdigest()
    # Append actual image delivery to the audit stream without duplicating shell events.
    with (logs / 'events.jsonl').open('a') as handle:
        for call in result['tool_calls']:
            if call['returned_images']:
                handle.write(json.dumps({'type': 'item.completed', 'item': {
                    'type': 'full_trace_image_return', 'call_id': call['call_id'],
                    'returned_images': call['returned_images'],
                    'source': 'matched full-rollout tool output'},
                    '_harness_received': {'utc': call['utc']}}) + '\n')
    return {k:v for k,v in result.items() if k != 'tool_calls'}
