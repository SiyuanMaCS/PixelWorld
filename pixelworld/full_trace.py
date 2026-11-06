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


def extract_tools(rollout: Path, logs: Path) -> dict:
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
                calls[call_id] = {'call_id': call_id, 'tool': item.get('name'),
                    'input': item.get('input') or item.get('arguments') or '',
                    'utc': event.get('timestamp')}
            elif kind in ('custom_tool_call_output', 'function_call_output') and call_id:
                outputs[call_id] = {'output':item.get('output'),'utc':event.get('timestamp')}
    records = []
    returned_images = 0
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
                if not isinstance(url, str) or not url.startswith('data:image/'):continue
                header, encoded = url.split(',', 1)
                image_bytes = base64.b64decode(encoded, validate=True)
                digest = hashlib.sha256(image_bytes).hexdigest()
                suffix = '.jpg' if 'jpeg' in header else '.png' if 'png' in header else '.webp'
                relative = 'tool_images/' + digest + suffix
                target = logs / relative
                target.parent.mkdir(exist_ok=True)
                target.write_bytes(image_bytes)
                record['returned_images'].append({'path': relative, 'sha256': digest,
                    'bytes': len(image_bytes), 'mime_type': header.split(';')[0][5:]})
                returned_images += 1
        record['matched_output'] = call_id in outputs
        records.append(record)
    result = {'status': 'recorded', 'source': 'full CLI rollout, not stdout projection',
        'tool_calls': records, 'returned_images': returned_images,
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
    result = extract_tools(target, logs)
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
