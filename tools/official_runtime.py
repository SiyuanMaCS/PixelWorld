"""Read-only resource checks and recorded execution for official evaluators.

No generation calls, substitute weights, guessed scores or credential output.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess


def source_check(source: Path, revision: str) -> dict:
    try:
        actual = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True, stderr=subprocess.DEVNULL).strip()
        dirty = subprocess.check_output(['git', '-C', str(source), 'diff', 'HEAD', '--name-only'], text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError) as error:
        return {'expected_revision': revision, 'ok': False, 'error_type': type(error).__name__}
    return {'expected_revision': revision, 'actual_revision': actual, 'tracked_changes': dirty.splitlines(),
            'ok': actual == revision and not dirty}


def python_check(python: str, modules: tuple[str, ...], source: Path) -> dict:
    # Importability is checked without instantiating any neural model.
    code = """import importlib.util,json,sys
names=json.loads(sys.argv[1]);found={}
for name in names:
 try:found[name]=importlib.util.find_spec(name) is not None
 except (ImportError,ValueError,ModuleNotFoundError):found[name]=False
try:
 import torch
 cuda={'available':torch.cuda.is_available(),'devices':torch.cuda.device_count(),'torch':torch.__version__}
except Exception as e:cuda={'available':False,'error_type':type(e).__name__}
print('PIXELWORLD_RUNTIME='+json.dumps({'modules':found,'cuda':cuda,'python':sys.version.split()[0]}))
"""
    env = os.environ.copy()
    paths = [source, source/'third_party/sam2', source/'third_party/depth-anything-3/src']
    env['PYTHONPATH'] = os.pathsep.join(str(p) for p in paths if p.is_dir()) + os.pathsep + env.get('PYTHONPATH', '')
    try:
        result = subprocess.run([python, '-c', code, json.dumps(modules)], env=env,
                                capture_output=True, text=True, timeout=90)
        record = next(line.split('=', 1)[1] for line in result.stdout.splitlines()
                      if line.startswith('PIXELWORLD_RUNTIME='))
        return {**json.loads(record), 'returncode': result.returncode}
    except (OSError, StopIteration, ValueError, subprocess.TimeoutExpired) as error:
        return {'modules': {}, 'cuda': {'available': False}, 'error_type': type(error).__name__}


def weight_check(lock: Path, required: set[str]) -> dict:
    """An operator locks the exact official resource bytes before inference."""
    from hashlib import sha256
    if not lock.is_file():
        return {'ok': False, 'missing_lock': True, 'required': sorted(required)}
    data = json.loads(lock.read_text())
    resources = data.get('resources', [])
    names = [r.get('name') for r in resources]
    errors = []
    if len(names) != len(set(names)):
        errors.append('duplicate resource identity')
    if not required <= set(names):
        errors.append('missing required official resource identities')
    verified = []
    for item in resources:
        path = Path(item.get('path', ''))
        if not path.is_absolute():
            path = lock.parent / path
        if not path.is_file() or len(item.get('sha256', '')) != 64:
            errors.append(f"unlocked or missing resource: {item.get('name')}")
            continue
        digest = sha256()
        with path.open('rb') as handle:
            for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b''):
                digest.update(chunk)
        if digest.hexdigest() != item['sha256']:
            errors.append(f"resource hash mismatch: {item['name']}")
        verified.append({'name': item['name'], 'sha256': digest.hexdigest(), 'bytes': path.stat().st_size,
                         'repo_id': item.get('repo_id'), 'revision': item.get('revision')})
    return {'ok': not errors, 'errors': errors, 'verified_resources': verified}


def preflight(source: Path, revision: str, python: str, modules: tuple[str, ...],
              lock: Path, required: set[str], extra_errors: list[str] | None = None) -> dict:
    pin = source_check(source, revision)
    runtime = python_check(python, modules, source)
    weights = weight_check(lock, required)
    errors = list(extra_errors or [])
    if not pin['ok']:
        errors.append('official tracked source/revision mismatch')
    errors += [f'missing Python module: {name}' for name in modules
               if not runtime.get('modules', {}).get(name)]
    if not runtime.get('cuda', {}).get('available'):
        errors.append('CUDA unavailable in selected evaluator interpreter')
    if not weights['ok']:
        errors.append('official resource lock incomplete or invalid')
    return {'status': 'ready' if not errors else 'blocked', 'blockers': errors,
            'source': pin, 'runtime': runtime, 'weights': weights,
            'models_loaded': False, 'scores_computed': False}


def execute(command: list[str], cwd: Path, output: Path, env: dict[str, str] | None = None) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    record = {'status': 'started', 'command': command, 'source_directory': str(cwd),
              'generation_invoked': False, 'baseline_rescoring': False}
    path = output / 'execution.json'
    path.write_text(json.dumps(record, indent=2))
    with (output / 'stdout.log').open('wb') as out, (output / 'stderr.log').open('wb') as err:
        result = subprocess.run(command, cwd=cwd, env=env, stdout=out, stderr=err)
    record.update(status='process_finished' if result.returncode == 0 else 'failed', returncode=result.returncode,
                  official_total=None, note='Exit status alone is not evidence of complete metric coverage.')
    path.write_text(json.dumps(record, indent=2))
    return record
