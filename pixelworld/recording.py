"""Versioned, local exports for trajectory analysis and later agentic SFT.

The raw CLI archive remains authoritative. Normalized events do not claim to
reconstruct unexposed provider context or hidden reasoning.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
from pathlib import Path
import re

from .util import atomic_json, sha256

SCHEMA = 'pixelworld-recording-v1'
FIELDS = ('input_tokens', 'cached_input_tokens', 'cache_creation_input_tokens',
          'output_tokens', 'reasoning_output_tokens', 'total_tokens')


def _json(path, default=None):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {} if default is None else default


def _jsonl(path):
    rows, malformed = [], 0
    if path.is_file():
        for index, line in enumerate(path.open()):
            try:
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError('Not an event')
                rows.append((index, value))
            except ValueError:
                malformed += 1
    return rows, malformed


def _write_jsonl(path, rows):
    path.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows))


def write_bundle(run: Path) -> dict:
    """Export already-recorded data outside the model workspace; no model calls."""
    manifest = _json(run/'run_manifest.json')
    target = run/'recording';target.mkdir(exist_ok=True)
    logs = run/'logs'
    raw, malformed = _jsonl(logs/'full_rollout.jsonl')
    events, event_errors = _jsonl(logs/'events.jsonl')
    workspace = run/'workspace'
    problems = []
    missing_blobs = set()

    def resolve(value):
        if isinstance(value, dict):
            return {k: resolve(v) for k, v in value.items()}
        if isinstance(value, list):
            return [resolve(v) for v in value]
        if isinstance(value, str):
            match = re.fullmatch(r'traex-rollout-blob:v1:sha256:([0-9a-f]{64}):(\d+)', value)
            if match:
                digest, count = match[1], int(match[2])
                file = logs/'rollout-blobs/sha256'/digest[:2]/digest
                if not file.is_file():
                    missing_blobs.add(value);return {'unavailable_blob': value}
                data = file.read_bytes()
                if len(data) != count or hashlib.sha256(data).hexdigest() != digest:
                    missing_blobs.add(value);return {'invalid_blob': value}
                return data.decode('utf-8')
        return value

    def portable(value):
        if isinstance(value, str):
            return value.replace(str(workspace), '{WORKSPACE}')
        if isinstance(value, list):
            return [portable(v) for v in value]
        if isinstance(value, dict):
            return {k: portable(v) for k, v in value.items()}
        return value

    def image_block(block):
        if not isinstance(block, dict):
            return block
        if block.get('type') not in ('input_image', 'image', 'image_url'):
            return portable(block)
        url = block.get('image_url', block.get('url'))
        if isinstance(url, dict):url = url.get('url')
        if isinstance(url, str) and url.startswith('data:image/'):
            head, encoded = url.split(',', 1)
            content = base64.b64decode(encoded, validate=True)
            digest = hashlib.sha256(content).hexdigest()
            extension = '.jpg' if 'jpeg' in head else '.webp' if 'webp' in head else '.png'
            image = target/'media'/(digest+extension);image.parent.mkdir(exist_ok=True)
            if not image.exists():image.write_bytes(content)
            return {'type': 'image', 'path': 'media/'+image.name, 'sha256': digest,
                    'mime_type': head.split(';')[0][5:], 'native_type': block['type']}
        return portable(block)

    # Keep the latest contents of each stable item id at its first-seen position.
    # Exact history mutations remain in full_rollout.jsonl for context replay.
    items = {};order = []
    for index, event in raw:
        payload = event.get('payload') or {}
        values = payload.get('items', []) if event.get('type') == 'history_mutation' else (
            [payload] if event.get('type') == 'response_item' else [])
        for offset, item in enumerate(values):
            kind = item.get('type')
            if kind not in ('message', 'function_call', 'custom_tool_call',
                            'function_call_output', 'custom_tool_call_output', 'reasoning'):
                continue
            key = item.get('id') or (kind, item.get('call_id')) if item.get('id') or item.get('call_id') else ('position', index, offset)
            if key not in items:order.append(key)
            first = items.get(key) or {'source_event_index': index, 'source_utc': event.get('timestamp')}
            items[key] = {'item': item, 'source_event_index': first['source_event_index'],
                          'source_utc': first['source_utc'], 'last_update_event_index': index}
    conversation = []
    for key in order:
        original = items[key];item = resolve(original['item']);kind = item['type']
        common = {'native_type': kind, 'source_item_id': item.get('id'),
                  'source_event_index': original['source_event_index'], 'source_utc': original['source_utc'],
                  'last_update_event_index': original['last_update_event_index']}
        if kind == 'message':
            common.update({'kind': 'message', 'role': item['role'],
                           'content': [image_block(b) for b in item.get('content', [])],
                           'phase': item.get('phase'),
                           'supervision_candidate': item['role'] == 'assistant'})
        elif kind in ('function_call', 'custom_tool_call'):
            common.update({'kind': 'tool_call', 'role': 'assistant', 'call_id': item.get('call_id'),
                           'name': item.get('name'), 'input': portable(item.get('input', item.get('arguments'))),
                           'input_format': 'freeform' if kind == 'custom_tool_call' else 'json',
                           'supervision_candidate': True})
        elif kind in ('function_call_output', 'custom_tool_call_output'):
            output = item.get('output')
            common.update({'kind': 'tool_result', 'role': 'tool', 'call_id': item.get('call_id'),
                           'content': [image_block(b) for b in output] if isinstance(output, list) else portable(output),
                           'supervision_candidate': False})
        else:
            common.update({'kind': 'visible_reasoning', 'role': 'assistant',
                           'content': portable(item.get('content') or []), 'summary': portable(item.get('summary') or []),
                           'encrypted_content_present': bool(item.get('encrypted_content')),
                           'supervision_candidate': False})
        conversation.append(common)

    ledger = [];seen = set();totals = {k: 0 for k in FIELDS}
    api_rows = [(i,e) for i,e in raw if e.get('type') == 'token_usage_record']
    for index, event in api_rows:
        payload = event['payload'];identity = (payload.get('session_id'), payload.get('turn_id'), payload.get('response_id'))
        if identity in seen:continue
        seen.add(identity);usage = payload.get('usage') or {}
        for field in FIELDS:
            amount = usage.get(field)
            if isinstance(amount, int):totals[field] += amount
        cumulative = payload.get('thread_token_usage') or payload.get('turn_token_usage') or totals.copy()
        ledger.append({'record_kind': 'api_request_usage', 'response_id': payload.get('response_id'),
                       'utc': event.get('timestamp'), 'source_event_index': index,
                       'usage': {k: usage.get(k) for k in FIELDS},
                       'cumulative': {k: cumulative.get(k) for k in FIELDS}})
    if not ledger:
        for index, event in raw:
            payload = event.get('payload') or {}
            if event.get('type') == 'event_msg' and payload.get('type') == 'token_count':
                cumulative = (payload.get('info') or {}).get('total_token_usage') or {}
                ledger.append({'record_kind': 'cumulative_usage_observation', 'response_id': None,
                               'utc': event.get('timestamp'), 'source_event_index': index,
                               'usage': None, 'cumulative': {k: cumulative.get(k) for k in FIELDS}})
    if not ledger:
        for index, event in events:
            if event.get('type') in ('turn.completed', 'turn.failed', 'turn.cancelled') and event.get('usage'):
                ledger.append({'record_kind': 'terminal_turn_usage', 'response_id': None,
                               'utc': (event.get('_harness_received') or {}).get('utc'),
                               'source_event_index': index, 'usage': event['usage'], 'cumulative': None})

    candidates = []
    for folder in sorted((run/'trace').glob('round_*')):
        record = _json(folder/'snapshot.json')
        if not record:continue
        stamp = record.get('utc');prior = []
        if stamp:
            for item in ledger:
                if item.get('utc') and dt.datetime.fromisoformat(item['utc']) <= dt.datetime.fromisoformat(stamp):
                    prior.append(item)
        water = prior[-1].get('cumulative') if prior else None
        candidates.append({'snapshot': folder.name, 'path': '../trace/'+folder.name,
                           'utc': stamp, 'code_sha256': record.get('generate_sha256'),
                           'rgb_sha256': record.get('canonical_rgb_sha256'),
                           'tensor_sha256': record.get('pixels_sha256'),
                           'media_contract': record.get('media_contract'),
                           'reported_usage_at_snapshot': water,
                           'timing_note': 'Usage watermark at observer snapshot time, not a render-completion claim'})

    assets = []
    initial = run/'input_snapshot'
    asset_root = initial if initial.is_dir() else workspace
    for file in sorted(asset_root.rglob('*')):
        if not file.is_file() or '.tmp' in file.relative_to(asset_root).parts:
            continue
        if asset_root == workspace and len(file.relative_to(asset_root).parts) != 1:
            continue  # Legacy fallback must not pretend generated files were initial inputs.
        if asset_root == workspace and file.name not in ('first_frame.png','prompt.txt','GENERATION_RULES.md',
                                                         'artifact_io.py','player_template.html','task_spec.json'):
            continue
        relative = str(file.relative_to(asset_root))
        assets.append({'name':relative,'path':'../'+asset_root.name+'/'+relative,'sha256':sha256(file)})
    if (run/'task_prompt.txt').is_file():
        assets.append({'name':'task_prompt.txt','path':'../task_prompt.txt','sha256':sha256(run/'task_prompt.txt')})
    for name, expected in (manifest.get('initial_input_hashes') or {}).items():
        file = initial/name
        if not file.is_file() or sha256(file) != expected:
            problems.append('initial_snapshot_missing_or_changed:'+name)
    for name, field in [('first_frame.png','input_image_sha256'),('prompt.txt','input_prompt_sha256'),
                        ('GENERATION_RULES.md','rules_sha256')]:
        expected = manifest.get(field)
        if expected and (not (workspace/name).is_file() or sha256(workspace/name) != expected):
            problems.append('initial_asset_changed:'+name)
    terminal = manifest.get('token_usage') or {}
    if api_rows and isinstance(terminal.get('output_tokens'), int) and totals['output_tokens'] != terminal['output_tokens']:
        problems.append('api_usage_sum_differs_from_terminal')
    if not raw:problems.append('full_rollout_unavailable')
    if malformed or event_errors:problems.append('malformed_recorded_events')
    if missing_blobs:problems.append('unavailable_blob_content')
    calls = {e['call_id'] for e in conversation if e['kind']=='tool_call'}
    returned = {e['call_id'] for e in conversation if e['kind']=='tool_result'}
    unmatched = sorted(calls-returned)
    if unmatched:problems.append('unmatched_tool_calls')
    orphan_returns = sorted(returned-calls)
    if orphan_returns:problems.append('tool_returns_without_calls')
    interrupted = bool(manifest.get('stop_reason'))
    if interrupted:problems.append('interrupted_trajectory')
    if (manifest.get('recording_coverage') or {}).get('stdout_stream_finished') is False:
        problems.append('stdout_stream_not_finished')
    if manifest.get('status') != 'complete' or not (manifest.get('validation') or {}).get('pass'):
        problems.append('generation_or_audit_not_passed')
    if not conversation:problems.append('no_conversation_events')
    provenance = {k:manifest.get(k) for k in ('model','model_key','cli_backend','reasoning_effort','track',
        'case_id','case_id_external','protocol','generation_contract','input_image_sha256',
        'input_prompt_sha256','task_sha256','rules_sha256','artifact_io_sha256','output_token_budget')}
    provenance.update({'source_split':'unassigned','quality_review':'unreviewed',
                       'source_usage':'prepared-task trajectory; benchmark test origins must remain distinguishable'})
    index = {'schema':SCHEMA,'provenance':provenance,'initial_assets':assets,
             'initial_image_attachment_configured':bool(manifest.get('initial_image_attached')),
             'raw_rollout':'../logs/full_rollout.jsonl','conversation_events':'conversation_events.jsonl',
             'api_usage':'api_usage.jsonl','candidates':'candidates.jsonl','media_files':len(list((target/'media').glob('*'))),
             'status':manifest.get('status'),'stop_reason':manifest.get('stop_reason'),
             'sft_full_trajectory_candidate':not problems,'training_ready':False,
             'training_gate':'Requires quality selection, split assignment and target tool/chat-template adapter',
             'completeness_issues':problems,'unmatched_tool_calls':unmatched,
             'tool_returns_without_calls':orphan_returns,
             'initial_asset_coverage':'immutable_before_run' if initial.is_dir() else 'legacy_workspace_fallback',
             'analysis_eligible':True,'candidate_history_coverage':'observed saved snapshots, not every file write',
             'raw_rollout_sha256':sha256(logs/'full_rollout.jsonl') if (logs/'full_rollout.jsonl').is_file() else None,
             'api_usage_records':len(ledger),'conversation_event_count':len(conversation),
             'candidate_count':len(candidates)}
    index['usage_coverage'] = 'per_request' if api_rows else (
        'cumulative_observations' if ledger and ledger[0]['record_kind']=='cumulative_usage_observation' else
        'terminal_only' if ledger else 'missing')
    index['api_request_count'] = len(ledger) if api_rows else None
    index['normalization_scope'] = 'Native types and freeform inputs retained; latest item contents at first-seen position. Exact history and request context remain in the raw archive.'
    _write_jsonl(target/'conversation_events.jsonl',conversation)
    _write_jsonl(target/'api_usage.jsonl',ledger)
    _write_jsonl(target/'candidates.jsonl',candidates)
    atomic_json(target/'index.json',index)
    return {k:index[k] for k in ('schema','sft_full_trajectory_candidate','training_ready',
                               'completeness_issues','api_usage_records','conversation_event_count','candidate_count')}
