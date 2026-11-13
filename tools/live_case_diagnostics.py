"""Observable termination facts for public case pages; no provider internals."""
import re
from pathlib import Path

from pixelworld.retries import infrastructure_failure
from pixelworld.smoke_web import clean

VERSION = 1


def public_text(value):
    text=clean(str(value or ''))
    text=re.sub(r'(?i)\bBearer\s+[^\s\"\x27]+','Bearer [redacted]',text)
    text=re.sub(r'\b(?:sk-|ghp_|github_pat_)[A-Za-z0-9_-]+','[redacted]',text)
    text=re.sub(r'(?i)(\b(?:api[_ -]?key|access_token|password|authorization)\b\s*[=:]\s*)[^\s,;]+',r'\1[redacted]',text)
    return text


def diagnostics(run: Path, manifest: dict, budget: dict, events: list):
    validation=manifest.get('validation') or {}
    if manifest.get('status')!='failed':return None
    terminal=[e for e in events if e.get('kind') in ('turn.completed','turn.failed','turn.cancelled','error')]
    errors=[e.get('text') for e in terminal if e.get('text')]
    missing=validation.get('missing_required') or []
    if infrastructure_failure(manifest):
        kind='infra_failure';reason=validation.get('infra_error') or manifest.get('stop_reason') or 'Recorded provider interruption'
    elif manifest.get('stop_reason')=='output_token_budget_exhausted' or budget.get('exhausted'):
        kind='token_budget_exhausted';reason='Output token budget exhausted before successful submission'
    elif (run/'workspace/pixels.npz').is_file() or validation.get('frames',0):
        kind='submitted_but_unrecognized';reason='Saved output did not pass final validation'
    else:
        kind='ended_without_submission';reason='Run terminated without a saved RGB video submission'
    agents=[e.get('text') for e in events if e.get('kind')=='agent_message' and e.get('text')]
    commands=[e for e in events if e.get('kind')=='command_execution']
    stderr='';path=run/'logs/stderr.log'
    if path.is_file():
        with path.open('rb') as stream:
            stream.seek(max(0,path.stat().st_size-12000));stderr=stream.read().decode('utf-8',errors='replace')
    return {'kind':kind,'reason':public_text(reason),
            'exit_status':manifest.get('exit_status',validation.get('exit_status')),
            'completion_mode':validation.get('completion_mode'),'stop_reason':manifest.get('stop_reason'),
            'terminal_events':[e['kind'] for e in terminal],
            'generate_runs':validation.get('generate_runs'),'frames':validation.get('frames'),
            'candidate_snapshots':manifest.get('trace_rounds'),
            'missing_required':[public_text(name) for name in missing],
            'validation_detail':{key:public_text(validation[key]) for key in
                ('reason','budget_error','track_violation','tensor_error') if validation.get(key)},
            'terminal_messages':[public_text(text)[:4000] for text in errors[-3:]],
            'last_agent_message':public_text(agents[-1])[:8000] if agents else '',
            'last_command':public_text(commands[-1].get('command')) if commands else '',
            'last_command_exit_code':commands[-1].get('exit_code') if commands else None,
            'stderr_excerpt':public_text(stderr),'diagnostics_version':VERSION}
