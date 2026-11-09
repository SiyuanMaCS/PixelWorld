from __future__ import annotations

from pathlib import Path
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import time
import threading

from .audit import canonicalize_tensor, validate
from .config import Benchmark, Model
from .constants import ASSET_ROOT, TRACKS, LEGACY_TRACK_PROTOCOLS
from .util import atomic_json, sha256, utc_now
from .usage import collect_usage, preserve_completed_request_bound
from .events import capture_stream
from .media import contract, task_rules


FILE_CHANGE_STALL_SECONDS = 20 * 60
WATCHDOG_POLL_SECONDS = 10
CLI_TEARDOWN_GRACE_SECONDS = 60


def _toml(value: str) -> str:
    return json.dumps(value)


def codex_command(model: Model, track: str, workspace: Path,
                  codex_binary: str = "codex", has_image: bool = True) -> list[str]:
    if track not in TRACKS or track not in model.tracks:
        raise ValueError(f"Track {track} is not enabled for {model.key}")
    if model.cli_backend == "trae":
        command = [codex_binary, "exec", "-", "--model", model.model,
                   "--ephemeral", "--ignore-user-config", "--ignore-rules",
                   "--skip-git-repo-check", "--sandbox", "workspace-write",
                   "--strict-config", "--json", "-C", str(workspace)]
        for value in ('model_provider="trae"', f'model_reasoning_effort="{model.reasoning_effort}"',
                      'approval_policy="never"', 'sandbox_workspace_write.network_access=false',
                      'sandbox_workspace_write.writable_roots=[]', 'sandbox_workspace_write.exclude_slash_tmp=true',
                      'web_search="disabled"', 'memories.use_memories=false', 'memories.generate_memories=false',
                      'skills.bundled.enabled=false', 'resource_dirs=[]', 'history.persistence="none"',
                      'shell_environment_policy.inherit="none"', 'features.multi_agent_v2.max_concurrent_threads_per_session=1'):
            command += ['-c', value]
        for feature in ('browser_use','computer_use','image_generation','multi_agent','multi_agent_v2',
                        'apps','plugins','memories','skill_search','hooks'):
            command += ['--disable',feature]
        if track in ('text','vision-input'):
            command += ['--disallowed-tool','Read','--disallowed-tool','view_image']
        elif has_image:
            command += ['-i',str(workspace/'first_frame.png')]
        command += ['--shell-tool-timeout','10m']
        return command
    python_bin = str(Path(sys.executable).resolve().parent)
    safe_path = ":".join(dict.fromkeys((python_bin, "/usr/local/bin", "/usr/bin", "/bin")))
    command = [
        codex_binary, "--ask-for-approval", "never", "exec", "-", "--model", model.model,
        "--ephemeral", "--ignore-user-config", "--ignore-rules",
        "--skip-git-repo-check", "--sandbox", "workspace-write",
        "--strict-config", "--json",
        "-C", str(workspace),
        "-c", f"model_reasoning_effort={_toml(model.reasoning_effort)}",
        "-c", "sandbox_workspace_write.network_access=false",
        "-c", "sandbox_workspace_write.writable_roots=[]",
        "-c", "sandbox_workspace_write.exclude_slash_tmp=true",
        "-c", "project_doc_max_bytes=0",
        "-c", "skills.bundled.enabled=false",
        "-c", "shell_environment_policy.inherit=none",
        "-c", f"shell_environment_policy.set.PATH={_toml(safe_path)}",
        "-c", 'web_search="disabled"',
    ]
    if model.provider.type == "responses":
        provider = model.provider
        command.extend([
            "-c", f"model_provider={_toml(provider.id or '')}",
            "-c", f"model_providers.{provider.id}.name={_toml(provider.name or '')}",
            "-c", f"model_providers.{provider.id}.base_url={_toml(provider.base_url or '')}",
            "-c", f"model_providers.{provider.id}.wire_api=\"responses\"",
            "-c", f"model_providers.{provider.id}.env_key={_toml(provider.env_key or '')}",
        ])
        if provider.model_catalog_json:
            command += ['-c',f'model_catalog_json={_toml(provider.model_catalog_json)}']
        if provider.stream_idle_timeout_ms is not None:
            command += ['-c',f'model_providers.{provider.id}.stream_idle_timeout_ms={provider.stream_idle_timeout_ms}']
        command += ['-c',f'model_providers.{provider.id}.request_max_retries=0',
                    '-c',f'model_providers.{provider.id}.stream_max_retries=0']
    elif model.provider.type == "oss":
        command.extend(["--oss"])

    # These are Codex feature gates, not prompt-only requests.
    for feature in ("browser_use", "computer_use", "image_generation", "multi_agent", "multi_agent_v2",
                    "apps", "plugins", "memories", "skill_search", "hooks"):
        command.extend(["--disable", feature])
    if track in ("text", "vision-input"):
        command.extend(["--disable", "view_image"])
    if track != "text" and has_image:
        command.extend(["--image", str(workspace / "first_frame.png")])
    return command


def _last_event(path: Path) -> dict | None:
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            handle.seek(max(0, handle.tell() - 128 * 1024))
            lines = handle.read().decode("utf-8", errors="replace").splitlines()
        for line in reversed(lines):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    except FileNotFoundError:
        pass
    return None


def _wait(agent: subprocess.Popen, events: Path, logs: Path,
          stall_seconds: int = FILE_CHANGE_STALL_SECONDS,
          token_monitor=None,
          teardown_grace_seconds: int = CLI_TEARDOWN_GRACE_SECONDS) -> tuple[int, dict | None]:
    watchdog = None
    last_records = -1
    while agent.poll() is None:
        if token_monitor is not None:
            exhausted = token_monitor.poll()
            if token_monitor.record_count != last_records:
                atomic_json(logs/'token_budget.json', token_monitor.report())
                last_records = token_monitor.record_count
            if exhausted or token_monitor.unavailable:
                watchdog = {'kind': 'token_budget', 'reason': 'output_token_budget_exhausted' if exhausted else 'token_usage_unavailable',
                            'cutoff_utc': token_monitor.crossed_utc or utc_now(),
                            'triggered_utc': utc_now(), 'signal': 'SIGTERM',
                            'token_budget': token_monitor.report()}
                atomic_json(logs/'watchdog.json', watchdog)
                from .token_budget import stop_agent
                stop_agent(agent)
                break
        time.sleep(min(WATCHDOG_POLL_SECONDS, .25) if token_monitor is not None else WATCHDOG_POLL_SECONDS)
        if agent.poll() is not None:
            break
        event = _last_event(events)
        # The model has explicitly finished. Bound CLI teardown only; never
        # use this timer while it is generating, checking or waiting for API.
        if event and event.get('type') == 'turn.completed':
            output = event.get('usage', {}).get('output_tokens')
            idle = time.time() - events.stat().st_mtime
            if isinstance(output, int) and not isinstance(output, bool) and output >= 0 and idle >= teardown_grace_seconds:
                terminal_source = logs/'events.raw.jsonl'
                if not terminal_source.is_file():
                    terminal_source = events
                watchdog = {'kind': 'cli_shutdown', 'reason': 'CLI did not exit after successful terminal event',
                            'triggered_utc': utc_now(), 'idle_seconds': idle,
                            'terminal_completed_utc': event.get('_harness_received', {}).get('utc'),
                            'events_sha256': sha256(events), 'usage_output_tokens': output,
                            'terminal_source': terminal_source.name, 'terminal_sha256': sha256(terminal_source)}
                from .token_budget import stop_agent
                stop_agent(agent)
                watchdog['process_exit_status'] = agent.returncode
                atomic_json(logs/'cli_shutdown.json', watchdog)
                atomic_json(logs/'watchdog.json', watchdog)
                break
        if not event or event.get("type") != "item.started":
            continue
        item = event.get("item", {})
        if item.get("type") != "file_change" or item.get("status") != "in_progress":
            continue
        idle = time.time() - events.stat().st_mtime
        if idle < stall_seconds:
            continue
        watchdog = {
            "triggered_utc": utc_now(),
            "reason": "file_change remained in_progress with no new JSONL event",
            "idle_seconds": idle,
            "item_id": item.get("id"),
            "signal": "SIGTERM",
        }
        atomic_json(logs / "watchdog.json", watchdog)
        agent.terminate()
        try:
            agent.wait(timeout=30)
        except subprocess.TimeoutExpired:
            watchdog["signal"] = "SIGKILL"
            atomic_json(logs / "watchdog.json", watchdog)
            agent.kill()
            agent.wait(timeout=10)
        break
    return agent.returncode, watchdog


def run_path(config: Benchmark, model: Model, track: str, case_id: str, attempt: int) -> Path:
    return config.runs_root / model.key / track / f"case_{case_id}_attempt_{attempt:02d}"


def run_case(config: Benchmark, model_key: str, track: str, case_id: str, attempt: int = 1,
             codex_binary: str | None = None, dry_run: bool = False,
             task_file: Path | None = None, rules_file: Path | None = None,
             extra_inputs: tuple[str,...] = ()) -> dict:
    model = config.model(model_key)
    token_limit = config.output_token_budget
    prior_output, prior_unknown = 0, False
    if token_limit is not None:
        for index in range(1, attempt):
            try:
                previous = json.loads((run_path(config, model, track, case_id, index)/'run_manifest.json').read_text())
                amount = (previous.get('token_usage') or {}).get('output_tokens')
            except (OSError, ValueError):
                amount = None
            if not isinstance(amount, int):
                prior_unknown = True
                break
            prior_output += amount
    source = config.inputs_root / case_id
    spec = contract(source)
    has_image = spec["task_type"] in ("i2v", "v2v")
    if (has_image and not (source / "first_frame.png").is_file()) or not (source / "prompt.txt").is_file():
        raise FileNotFoundError(f"Missing prepared input for case {case_id}: {source}")
    run = run_path(config, model, track, case_id, attempt)
    if run.exists():
        raise FileExistsError(f"Run already exists: {run}")
    workspace, logs, trace = run / "workspace", run / "logs", run / "trace"
    codex_home = run / "empty-codex-home"
    for path in (workspace / ".tmp", logs, trace, codex_home):
        path.mkdir(parents=True, exist_ok=True)
    legacy_contract = config.protocol in LEGACY_TRACK_PROTOCOLS or track == "vision-input"
    task_root = ASSET_ROOT / "legacy_v1" if legacy_contract else ASSET_ROOT
    for origin, target in (
        (source / "first_frame.png", workspace / "first_frame.png"),
        (source / "prompt.txt", workspace / "prompt.txt"),
        (task_root / "GENERATION_RULES.md", workspace / "GENERATION_RULES.md"),
        (ASSET_ROOT / "artifact_io.py", workspace / "artifact_io.py"),
        (ASSET_ROOT / "player_template.html", workspace / "player_template.html"),
    ):
        if origin.is_file():
            shutil.copy2(origin, target)
    if spec['task_type']=='v2v':
        for name in ('conditioning.mp4','conditioning_info.json','conditioning_inspection.png'):
            if not (source/name).is_file():raise FileNotFoundError(f'Missing historical input: {name}')
            shutil.copy2(source/name,workspace/name)
        shutil.copytree(source/'conditioning_frames',workspace/'conditioning_frames')
    for name in extra_inputs:
        if Path(name).is_absolute() or '..' in Path(name).parts:
            raise ValueError('Extra inputs must be relative paths within the prepared case')
        origin=(source/name).resolve()
        origin.relative_to(source.resolve())
        target=workspace/name
        if origin.is_dir():shutil.copytree(origin,target)
        else:shutil.copy2(origin,target)
    task = task_root / {
        "text": "TASK_TEXT.md",
        "vision-input": "TASK_VISION_INPUT.md",
        "vision-agent": "TASK_VISION_AGENT.md",
    }[track]
    atomic_json(run / "media_contract.json", spec)
    if (source / "task_spec.json").is_file():
        if legacy_contract:
            raise ValueError("Legacy contracts cannot override media")
        atomic_json(workspace / "task_spec.json", spec)
        (workspace / "GENERATION_RULES.md").write_text(task_rules(spec))
    if rules_file:
        shutil.copy2(rules_file,workspace/'GENERATION_RULES.md')
    # Keep the exact supplied task text outside the model's workspace for audit.
    task_snapshot = run / "task_prompt.txt"
    task_text = task.read_text()
    if spec['task_type']=='v2v':
        task_text='Generate the future RGB continuation requested in `prompt.txt`, following `GENERATION_RULES.md`. The supplied conditioning video and frames contain only the historical segment. Use the permitted tools and choose your own approach to generation, checking and revision.\n'
    if not has_image:
        task_text = "Generate the RGB video requested in `prompt.txt`, following `GENERATION_RULES.md` and `task_spec.json`. There is no input image. Choose your own approach. " + ("Visual image tools are available; choose whether to inspect your output.\n" if track == "vision-agent" else "Visual image tools are disabled.\n")
    if task_file:
        task_text=task_file.read_text()
    elif token_limit is not None and not legacy_contract:
        task_text += '\nAim for high-quality output while considering efficiency.\n'
    task_snapshot.write_text(task_text)
    # Preserve only the supplied workspace inputs, before the model can edit them.
    # This directory stays outside the agent's visible workspace.
    input_snapshot = run / 'input_snapshot'
    input_snapshot.mkdir()
    for path in workspace.iterdir():
        if path.name == '.tmp':
            continue
        if path.is_dir():
            shutil.copytree(path, input_snapshot/path.name)
        elif path.is_file():
            shutil.copy2(path, input_snapshot/path.name)
    input_snapshot_hashes = {str(p.relative_to(input_snapshot)):sha256(p)
                             for p in input_snapshot.rglob('*') if p.is_file()}
    binary = codex_binary or (os.environ.get("PIXELWORLD_TRAECLI", "traecli") if model.cli_backend == 'trae'
                              else os.environ.get("PIXELWORLD_CODEX", "codex"))
    model_catalog_record = None
    if model.cli_backend=='codex' and model.provider.model_catalog_json:
        from dataclasses import replace
        catalog_source=Path(model.provider.model_catalog_json)
        catalog_snapshot=run/'model_catalog.json'
        shutil.copy2(catalog_source,catalog_snapshot)
        model_catalog_record={'file':'model_catalog.json','sha256':sha256(catalog_snapshot)}
        model=replace(model,provider=replace(model.provider,model_catalog_json=str(catalog_snapshot)))
    command = codex_command(model, track, workspace, binary, has_image)
    # Persist an external full rollout for new runs. Fresh contexts, memory and
    # history-reuse settings stay unchanged; the stdout projection omits some
    # nested tools and image returns. Preserve legacy launch settings.
    full_trace_enabled = not legacy_contract or token_limit is not None
    if full_trace_enabled:
        command.remove('--ephemeral')
    if spec['task_type']=='v2v' and track!='text':
        command += ['-i' if model.cli_backend=='trae' else '--image',str(workspace/'conditioning_inspection.png')]
    try:
        version = subprocess.check_output([binary, "--version"], text=True).strip()
    except Exception:
        version = "unavailable"
    manifest = {
        "status": "dry-run" if dry_run else "running",
        "started_utc": utc_now(),
        "protocol": config.protocol,
        "generation_contract": "legacy-v1" if legacy_contract else "minimal-v2",
        "model_key": model.key,
        "model": model.model,
        "cli_backend": model.cli_backend,
        "provider": model.provider.__dict__,
        "model_catalog_snapshot": model_catalog_record,
        "reasoning_effort": model.reasoning_effort,
        "track": track,
        "initial_image_attached": has_image and track != "text",
        "output_image_tool_enabled": track == "vision-agent",
        "case_id": case_id,
        "attempt": attempt,
        "workspace": str(workspace),
        "codex_version": version,
        "isolated_codex_home": str(codex_home),
        "command": command,
        "task_sha256": sha256(task_snapshot),
        "task_prompt_file": "task_prompt.txt",
        "rules_sha256": sha256(workspace / "GENERATION_RULES.md"),
        "input_image_sha256": sha256(workspace / "first_frame.png") if has_image else None,
        "media_contract": spec,
        "input_prompt_sha256": sha256(workspace / "prompt.txt"),
        "initial_visible_files": sorted(path.name for path in workspace.iterdir() if path.is_file()),
        "initial_input_snapshot": 'input_snapshot/',
        "initial_input_hashes": input_snapshot_hashes,
        "extra_input_files": list(extra_inputs),
        "full_trace_capture_enabled": full_trace_enabled,
        "output_token_budget": token_limit,
        "prior_attempt_output_tokens": prior_output,
        "token_usage": collect_usage(logs / "events.jsonl", finished=False),
    }
    atomic_json(run / "run_manifest.json", manifest)
    if dry_run:
        return manifest
    if token_limit is not None and (prior_unknown or prior_output >= token_limit):
        manifest.update({'status': 'failed', 'retryable': False,
                         'stop_reason': 'prior_token_usage_unavailable' if prior_unknown else 'output_token_budget_exhausted',
                         'completed_utc': utc_now(),
                         'validation': {'pass': False, 'reason': 'No verifiable task token budget remains; model not launched'}})
        atomic_json(run/'run_manifest.json', manifest)
        from .recording import write_bundle
        manifest['recording_bundle'] = write_bundle(run)
        atomic_json(run/'run_manifest.json', manifest)
        return manifest

    started = dt.datetime.now(dt.timezone.utc)
    token_monitor = None
    stop_file = logs / "stop_watcher"
    with (logs / "watcher.log").open("w") as watcher_out, (logs / "watcher.stderr.log").open("w") as watcher_err:
        watcher = subprocess.Popen([
            sys.executable, "-m", "pixelworld.snapshot", "--workspace", str(workspace),
            "--trace", str(trace), "--stop-file", str(stop_file),
            "--spec-file", str(run / "media_contract.json"),
        ], stdout=watcher_out, stderr=watcher_err)
        environment = os.environ.copy()
        environment["TMPDIR"] = str(workspace / ".tmp")
        environment["PIXELWORLD_CLEANROOM"] = "1"
        environment["CODEX_HOME"] = str(codex_home)
        if model.cli_backend == 'trae':
            environment.pop('CODEX_HOME',None)
            environment['TRAE_HOME'] = str(codex_home)
            environment['TRAECLI_HOME'] = os.environ.get('TRAECLI_HOME', str(Path.home()/'.trae/cli'))
        if token_limit is not None:
            from .token_budget import UsageMonitor
            cli_home = Path(environment['TRAECLI_HOME']) if model.cli_backend == 'trae' else codex_home
            token_monitor = UsageMonitor(logs/'events.jsonl', cli_home, started, token_limit, prior_output,
                                         backend=model.cli_backend)
        with task_snapshot.open("rb") as stdin, (logs / "stderr.log").open("wb") as stderr:
            agent = subprocess.Popen(command, stdin=stdin, stdout=subprocess.PIPE, stderr=stderr, env=environment,
                                     start_new_session=token_limit is not None)
            logger = threading.Thread(target=capture_stream, args=(agent.stdout, logs / "events.raw.jsonl", logs / "events.jsonl"), daemon=True)
            logger.start()
            (logs / "agent.pid").write_text(str(agent.pid) + "\n")
            (logs / "supervisor.pid").write_text(str(os.getpid()) + "\n")
            exit_status, watchdog = _wait(agent, logs / "events.jsonl", logs, token_monitor=token_monitor)
            logger.join(timeout=10)
        stop_file.touch()
        try:
            watcher.wait(timeout=30)
        except subprocess.TimeoutExpired:
            watcher.terminate()
            watcher.wait(timeout=10)

    full_trace = {'status': 'not_recorded', 'reason': 'Legacy ephemeral launch settings preserved'}
    if full_trace_enabled:
        from .full_trace import capture_rollout
        cli_home = Path(environment['TRAECLI_HOME']) if model.cli_backend == 'trae' else codex_home
        try:
            full_trace = capture_rollout(cli_home, logs, started)
        except (OSError, ValueError, KeyError) as error:
            full_trace = {'status':'error','reason':str(error)}
        atomic_json(logs / 'full_trace_status.json', full_trace)
    if token_monitor is not None:
        # Capture a final usage record even if the CLI exited between polls.
        crossed = token_monitor.poll()
        atomic_json(logs/'token_budget.json', token_monitor.report())
        if crossed and watchdog is None:
            watchdog = {'kind': 'token_budget', 'reason': 'output_token_budget_exhausted',
                        'cutoff_utc': token_monitor.crossed_utc, 'signal': None,
                        'observed_after_cli_exit': True, 'token_budget': token_monitor.report()}
            atomic_json(logs/'watchdog.json', watchdog)
    budget_stopped = bool(watchdog and watchdog.get('kind') == 'token_budget')
    submission_selection = None
    if budget_stopped and watchdog['reason'] == 'output_token_budget_exhausted':
        from .token_budget import restore_candidate
        submission_selection = restore_candidate(workspace, trace, logs, watchdog['cutoff_utc'],
                                                 exit_status, track, legacy_contract, spec)
    canonicalization = canonicalize_tensor(workspace, logs, spec)
    validation = validate(workspace, logs / "events.jsonl", exit_status, track,
                          require_reports=legacy_contract, media=spec,
                          budget_frozen=submission_selection is not None)
    validation.update({
        "track": track,
        "initial_image_attached": has_image and track != "text",
        "output_image_tool_enabled": track == "vision-agent",
    })
    atomic_json(logs / "validation.json", validation)
    completed = dt.datetime.now(dt.timezone.utc)
    token_usage = preserve_completed_request_bound(collect_usage(logs / "events.jsonl"),
                          token_monitor.report() if token_monitor is not None else None)
    terminal_output = token_usage.get('output_tokens')
    if token_limit is not None and isinstance(terminal_output, int) and terminal_output + prior_output > token_limit and not budget_stopped:
        # Unsupported/late usage reporting cannot silently accept an over-budget output.
        budget_stopped = True
        watchdog = {'kind': 'token_budget', 'reason': 'output_token_budget_exhausted',
                    'signal': None, 'observed_after_cli_exit': True,
                    'accounting': 'terminal_only', 'reported_output_tokens': terminal_output + prior_output}
        validation['pass'] = False
        validation['budget_error'] = 'Over budget without a verified request-level candidate boundary'
        atomic_json(logs/'validation.json', validation)
        atomic_json(logs/'watchdog.json', watchdog)
    if budget_stopped and token_usage['status'] != 'recorded' and token_monitor is not None:
        token_usage.update({'status': 'partial' if token_monitor.record_count else 'missing',
                            'reported_completed_request_output_tokens': token_monitor.output if token_monitor.record_count else None,
                            'inflight_usage_unknown': True,
                            'source_note': 'Completed request tokens are a lower bound after interruption, not a final run total.'})
    atomic_json(logs / "token_usage.json", token_usage)
    manifest.update({
        "status": "complete" if validation["pass"] else "failed",
        "completed_utc": completed.isoformat(),
        "duration_seconds": (completed - started).total_seconds(),
        "exit_status": exit_status,
        "trace_rounds": len(list(trace.glob("round_*"))),
        "validation": validation,
        "token_usage": token_usage,
        "full_trace": full_trace,
        "recording_coverage": {
            "stdout_stream_finished": not logger.is_alive(),
            "full_rollout_status": full_trace.get('status'),
            "unresolved_blobs": full_trace.get('unresolved_blobs'),
            "interrupted_by_budget": budget_stopped,
            "usage_status": token_usage['status'],
            "scope": 'CLI-exposed messages and artifacts; not unreturned provider internals or unfinished responses',
            "candidate_history": 'Stable saved snapshots observed externally; rapid overwrites and unsaved drafts may be absent',
        },
        "token_budget": token_monitor.report() if token_monitor is not None else None,
        "submission_selection": submission_selection,
        "stop_reason": watchdog['reason'] if budget_stopped else None,
        "retryable": not budget_stopped,
    })
    if watchdog:
        manifest["watchdog"] = watchdog
    if canonicalization:
        manifest["tensor_canonicalization"] = canonicalization
    for name, key in (("generate.py", "generate_sha256"), ("pixels.npz", "pixels_sha256")):
        if (workspace / name).is_file():
            manifest[key] = sha256(workspace / name)
    atomic_json(run / "run_manifest.json", manifest)
    try:
        from .recording import write_bundle
        manifest['recording_bundle'] = write_bundle(run)
    except (OSError, ValueError, KeyError) as error:
        manifest['recording_bundle'] = {'schema': 'pixelworld-recording-v1', 'status': 'error',
                                        'reason': str(error), 'training_ready': False}
    atomic_json(run / 'run_manifest.json', manifest)
    return manifest
