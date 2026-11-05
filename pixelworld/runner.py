from __future__ import annotations

from pathlib import Path
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import time

from .audit import canonicalize_tensor, validate
from .config import Benchmark, Model
from .constants import ASSET_ROOT, TRACKS
from .util import atomic_json, sha256, utc_now


FILE_CHANGE_STALL_SECONDS = 20 * 60
WATCHDOG_POLL_SECONDS = 10


def _toml(value: str) -> str:
    return json.dumps(value)


def codex_command(model: Model, track: str, workspace: Path,
                  codex_binary: str = "codex") -> list[str]:
    if track not in TRACKS or track not in model.tracks:
        raise ValueError(f"Track {track} is not enabled for {model.key}")
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
    elif model.provider.type == "oss":
        command.extend(["--oss"])

    # These are Codex feature gates, not prompt-only requests.
    for feature in ("browser_use", "computer_use", "image_generation", "multi_agent", "multi_agent_v2",
                    "apps", "plugins", "memories", "skill_search", "hooks"):
        command.extend(["--disable", feature])
    if track in ("text", "vision-input"):
        command.extend(["--disable", "view_image"])
    if track != "text":
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
          stall_seconds: int = FILE_CHANGE_STALL_SECONDS) -> tuple[int, dict | None]:
    watchdog = None
    while agent.poll() is None:
        time.sleep(WATCHDOG_POLL_SECONDS)
        event = _last_event(events)
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
             codex_binary: str | None = None, dry_run: bool = False) -> dict:
    model = config.model(model_key)
    source = config.inputs_root / case_id
    if not (source / "first_frame.png").is_file() or not (source / "prompt.txt").is_file():
        raise FileNotFoundError(f"Missing prepared input for case {case_id}: {source}")
    run = run_path(config, model, track, case_id, attempt)
    if run.exists():
        raise FileExistsError(f"Run already exists: {run}")
    workspace, logs, trace = run / "workspace", run / "logs", run / "trace"
    codex_home = run / "empty-codex-home"
    for path in (workspace / ".tmp", logs, trace, codex_home):
        path.mkdir(parents=True, exist_ok=True)
    for origin, target in (
        (source / "first_frame.png", workspace / "first_frame.png"),
        (source / "prompt.txt", workspace / "prompt.txt"),
        (ASSET_ROOT / "GENERATION_RULES.md", workspace / "GENERATION_RULES.md"),
        (ASSET_ROOT / "artifact_io.py", workspace / "artifact_io.py"),
        (ASSET_ROOT / "player_template.html", workspace / "player_template.html"),
    ):
        shutil.copy2(origin, target)
    task = ASSET_ROOT / {
        "text": "TASK_TEXT.md",
        "vision-input": "TASK_VISION_INPUT.md",
        "vision-agent": "TASK_VISION_AGENT.md",
    }[track]
    binary = codex_binary or os.environ.get("PIXELWORLD_CODEX", "codex")
    command = codex_command(model, track, workspace, binary)
    try:
        version = subprocess.check_output([binary, "--version"], text=True).strip()
    except Exception:
        version = "unavailable"
    manifest = {
        "status": "dry-run" if dry_run else "running",
        "started_utc": utc_now(),
        "protocol": config.protocol,
        "model_key": model.key,
        "model": model.model,
        "provider": model.provider.__dict__,
        "reasoning_effort": model.reasoning_effort,
        "track": track,
        "initial_image_attached": track != "text",
        "output_image_tool_enabled": track == "vision-agent",
        "case_id": case_id,
        "attempt": attempt,
        "workspace": str(workspace),
        "codex_version": version,
        "isolated_codex_home": str(codex_home),
        "command": command,
        "task_sha256": sha256(task),
        "rules_sha256": sha256(workspace / "GENERATION_RULES.md"),
        "input_image_sha256": sha256(workspace / "first_frame.png"),
        "input_prompt_sha256": sha256(workspace / "prompt.txt"),
        "initial_visible_files": sorted(path.name for path in workspace.iterdir() if path.is_file()),
    }
    atomic_json(run / "run_manifest.json", manifest)
    if dry_run:
        return manifest

    started = dt.datetime.now(dt.timezone.utc)
    stop_file = logs / "stop_watcher"
    with (logs / "watcher.log").open("w") as watcher_out, (logs / "watcher.stderr.log").open("w") as watcher_err:
        watcher = subprocess.Popen([
            sys.executable, "-m", "pixelworld.snapshot", "--workspace", str(workspace),
            "--trace", str(trace), "--stop-file", str(stop_file),
        ], stdout=watcher_out, stderr=watcher_err)
        environment = os.environ.copy()
        environment["TMPDIR"] = str(workspace / ".tmp")
        environment["PIXELWORLD_CLEANROOM"] = "1"
        environment["CODEX_HOME"] = str(codex_home)
        with task.open("rb") as stdin, (logs / "events.jsonl").open("wb") as stdout, \
                (logs / "stderr.log").open("wb") as stderr:
            agent = subprocess.Popen(command, stdin=stdin, stdout=stdout, stderr=stderr, env=environment)
            (logs / "agent.pid").write_text(str(agent.pid) + "\n")
            (logs / "supervisor.pid").write_text(str(os.getpid()) + "\n")
            exit_status, watchdog = _wait(agent, logs / "events.jsonl", logs)
        stop_file.touch()
        try:
            watcher.wait(timeout=30)
        except subprocess.TimeoutExpired:
            watcher.terminate()
            watcher.wait(timeout=10)

    canonicalization = canonicalize_tensor(workspace, logs)
    validation = validate(workspace, logs / "events.jsonl", exit_status, track)
    validation.update({
        "track": track,
        "initial_image_attached": track != "text",
        "output_image_tool_enabled": track == "vision-agent",
    })
    atomic_json(logs / "validation.json", validation)
    completed = dt.datetime.now(dt.timezone.utc)
    manifest.update({
        "status": "complete" if validation["pass"] else "failed",
        "completed_utc": completed.isoformat(),
        "duration_seconds": (completed - started).total_seconds(),
        "exit_status": exit_status,
        "trace_rounds": len(list(trace.glob("round_*"))),
        "validation": validation,
    })
    if watchdog:
        manifest["watchdog"] = watchdog
    if canonicalization:
        manifest["tensor_canonicalization"] = canonicalization
    for name, key in (("generate.py", "generate_sha256"), ("pixels.npz", "pixels_sha256")):
        if (workspace / name).is_file():
            manifest[key] = sha256(workspace / name)
    atomic_json(run / "run_manifest.json", manifest)
    return manifest
