"""External API-usage monitoring. No prompt hints, tokenization, or wall deadline."""
from __future__ import annotations

import datetime as dt
import json
import os
import re
from pathlib import Path
import shutil
import signal
import subprocess
import time

from .util import atomic_json, sha256, utc_now


class UsageMonitor:
    def __init__(self, events: Path, cli_home: Path, started: dt.datetime,
                 limit: int, prior_output: int = 0, backend: str | None = None):
        self.events, self.cli_home, self.started = events, cli_home, started
        self.limit, self.prior_output = limit, prior_output
        self.backend = backend
        self.thread_id = None
        self.path = None
        self.offset = 0
        self.pending = b''
        self.output = 0
        self.record_count = 0
        self.source = None
        self.crossed_utc = None
        self.seen = set()
        self.last_search = 0.0
        self.stdout_offset = 0
        self.stdout_pending = b''
        self.completed_tools = 0

    def _find(self):
        if self.path is not None or time.monotonic() - self.last_search < .5:
            return
        self.last_search = time.monotonic()
        if self.thread_id is None and self.events.is_file():
            with self.events.open('rb') as handle:
                for line in handle.read(65536).splitlines():
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if event.get('type') == 'thread.started':
                        self.thread_id = event.get('thread_id')
                        break
        if not self.thread_id or not re.fullmatch(r'[0-9a-f-]{36}', self.thread_id):
            return
        matches = []
        for shift in (-1, 0, 1):
            date = self.started + dt.timedelta(days=shift)
            matches.extend((self.cli_home / 'sessions' / date.strftime('%Y/%m/%d')).glob(f'*{self.thread_id}.jsonl'))
        if len(matches) == 1:
            self.path = matches[0]

    def consume(self, event: dict):
        payload = event.get('payload') or {}
        cumulative = None
        if event.get('type') == 'token_usage_record':
            identity = (payload.get('session_id'), payload.get('turn_id'), payload.get('response_id'))
            if identity in self.seen:
                return
            self.seen.add(identity)
            usage = payload.get('thread_token_usage') or payload.get('turn_token_usage')
            if usage:
                cumulative = usage.get('output_tokens')
            else:
                delta = (payload.get('usage') or {}).get('output_tokens')
                if isinstance(delta, int):
                    cumulative = self.output + delta
            source = 'TRAE per-request token_usage_record'
        elif event.get('type') == 'event_msg' and payload.get('type') == 'token_count':
            if self.backend == 'trae':
                return  # The dedicated API records avoid counting the UI projection twice.
            usage = (payload.get('info') or {}).get('total_token_usage') or {}
            cumulative = usage.get('output_tokens')
            source = 'Codex cumulative token_count'
        else:
            return
        if not isinstance(cumulative, int) or isinstance(cumulative, bool) or cumulative < 0:
            return
        self.record_count += 1
        self.output = max(self.output, cumulative)
        self.source = source
        if self.total >= self.limit and self.crossed_utc is None:
            self.crossed_utc = event.get('timestamp') or utc_now()

    @property
    def total(self):
        return self.prior_output + self.output

    def poll(self):
        if self.events.is_file():
            with self.events.open('rb') as handle:
                handle.seek(self.stdout_offset)
                chunk = handle.read()
                self.stdout_offset += len(chunk)
            lines = (self.stdout_pending + chunk).split(b'\n')
            self.stdout_pending = lines.pop()
            for line in lines:
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if event.get('type') == 'item.completed' and event.get('item', {}).get('type') in ('command_execution', 'file_change', 'mcp_tool_call'):
                    self.completed_tools += 1
        self._find()
        if self.path is not None:
            with self.path.open('rb') as handle:
                handle.seek(self.offset)
                data = handle.read()
                self.offset += len(data)
            parts = (self.pending + data).split(b'\n')
            self.pending = parts.pop()
            for line in parts:
                try:
                    self.consume(json.loads(line))
                except ValueError:
                    continue
        return self.crossed_utc is not None

    @property
    def unavailable(self):
        return self.completed_tools >= 8 and self.record_count == 0

    def report(self):
        return {'policy': 'api-output-tokens-v1', 'enforcement': 'after_request_usage',
                'budget_tokens': self.limit, 'prior_output_tokens': self.prior_output,
                'reported_output_tokens': self.total if self.record_count else None,
                'request_usage_records': self.record_count, 'source': self.source,
                'exhausted': self.crossed_utc is not None, 'crossed_utc': self.crossed_utc,
                'observed_overshoot_tokens': max(0, self.total-self.limit) if self.record_count else None}


def stop_agent(agent: subprocess.Popen):
    try:
        group = os.getpgid(agent.pid) == agent.pid
    except ProcessLookupError:
        return
    try:
        os.killpg(agent.pid, signal.SIGTERM) if group else agent.terminate()
        agent.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(agent.pid, signal.SIGKILL) if group else agent.kill()
        agent.wait(timeout=10)
    except ProcessLookupError:
        pass
    if group:
        try:
            os.killpg(agent.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def restore_candidate(workspace: Path, trace: Path, logs: Path, cutoff: str,
                      exit_status: int, track: str, require_reports: bool, spec: dict):
    from .audit import canonicalize_tensor, validate
    names = ('generate.py', 'pixels.npz', 'inspection.png', 'transition_check.png',
             'OBSERVATION.md', 'METHOD.md', 'index.html', 'audio.wav', 'frames')
    backup = logs.parent / 'interrupted_artifacts'
    backup.mkdir()
    def copy_outputs(source_root, target_root):
        for name in names:
            source, target = source_root / name, target_root / name
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()
            if source.is_dir():
                shutil.copytree(source, target)
            elif source.is_file():
                shutil.copy2(source, target)
    copy_outputs(workspace, backup)
    rejected = []
    for folder in sorted(trace.glob('round_*'), reverse=True):
        try:
            record = json.loads((folder / 'snapshot.json').read_text())
            if dt.datetime.fromisoformat(record['utc']) > dt.datetime.fromisoformat(cutoff):
                continue
            if (sha256(folder/'generate.py') != record['generate_sha256'] or
                    sha256(folder/'pixels.npz') != record['pixels_sha256']):
                raise ValueError('Snapshot checksums changed')
            if record.get('media_contract') is not None and record['media_contract'] != spec:
                raise ValueError('Snapshot media contract changed')
            copy_outputs(folder, workspace)
            canonicalize_tensor(workspace, logs, spec)
            audit = validate(workspace, logs/'events.jsonl', exit_status, track,
                             require_reports=require_reports, media=spec, budget_frozen=True)
            if not audit['pass']:
                atomic_json(logs/f'budget_candidate_{folder.name}_audit.json', audit)
                raise ValueError('Snapshot output/tool audit failed')
            selection = {'source': 'last_valid_snapshot_before_token_crossing',
                         'snapshot_round': record['round'], 'snapshot_utc': record['utc'],
                         'cutoff_utc': cutoff, 'canonical_rgb_sha256': record.get('canonical_rgb_sha256'),
                         'rejected': rejected}
            atomic_json(logs/'budget_candidate.json', selection)
            return selection
        except (OSError, ValueError, KeyError) as error:
            rejected.append({'snapshot': folder.name, 'reason': str(error)})
    copy_outputs(backup, workspace)
    atomic_json(logs/'budget_candidate.json', {'source': None, 'rejected': rejected})
    return None
