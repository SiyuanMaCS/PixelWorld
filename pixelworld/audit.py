from __future__ import annotations

from pathlib import Path
import ast
import io
import json
import re
import shlex
import shutil
import tokenize
import wave

import numpy as np
from PIL import Image

from .constants import FRAMES, HEIGHT, TENSOR_SHAPE, WIDTH
from .util import atomic_json, sha256
from .media import DEFAULT_MEDIA


SUBAGENT_PATTERN = re.compile(
    r"(?:^|&&|\|\||;)\s*(?:env\s+\S+\s+)*(?:\S*/)?(?:codex\s+exec|traecli\s+exec|agent-new)\b",
    re.I | re.M,
)
NETWORK_PATTERN = re.compile(
    r"(?:^|&&|\|\||;)\s*(?:env\s+\S+\s+)*(?:\S*/)?(?:curl|wget|nc|ncat)\b(?!\s*=)|"
    r"\b(?:requests\.(?:get|post|request)|socket\.connect|urllib\.request\.urlopen)\s*\(",
    re.I | re.M,
)
ABSOLUTE_PATH_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_.*])(/[A-Za-z0-9_@%+=:.,-]+/[A-Za-z0-9_@%+=:,./-]*)")
SYSTEM_READ_PREFIXES = ("/bin/", "/usr/", "/lib/", "/lib64/", "/dev/", "/proc/")
PLAYWRIGHT_SOFTWARE_CACHE = str(Path.home() / '.cache/ms-playwright')


def invokes_subagent(command: str) -> bool:
    return bool(SUBAGENT_PATTERN.search(command))


def invokes_network(command: str) -> bool:
    return bool(NETWORK_PATTERN.search(command))


def canonicalize_tensor(workspace: Path, logs: Path, media: dict | None = None) -> dict | None:
    """Losslessly repair only the unambiguous uint32 T,H,W layout."""
    spec = media or DEFAULT_MEDIA
    FRAMES, HEIGHT, WIDTH = (spec[k] for k in ("frames", "height", "width"))
    TENSOR_SHAPE = (HEIGHT, WIDTH, FRAMES)
    tensor_path = workspace / "pixels.npz"
    frame_dir = workspace / "frames"
    if not tensor_path.is_file() or not frame_dir.is_dir():
        return None
    try:
        tensor = np.load(tensor_path)["pixels"]
    except Exception:
        return None
    if tensor.shape == TENSOR_SHAPE and tensor.dtype == np.uint32:
        return None
    if tensor.shape != (FRAMES, HEIGHT, WIDTH) or tensor.dtype != np.uint32:
        return None
    packed = []
    for index in range(FRAMES):
        path = frame_dir / f"{index:02d}.png"
        if not path.is_file():
            return None
        rgb = np.asarray(Image.open(path).convert("RGB"), dtype=np.uint32)
        packed.append((rgb[:, :, 0] << 16) | (rgb[:, :, 1] << 8) | rgb[:, :, 2])
    packed = np.stack(packed)
    if not np.array_equal(tensor, packed):
        return None
    logs.mkdir(parents=True, exist_ok=True)
    original = logs / "pixels_original_t_h_w.npz"
    if not original.exists():
        shutil.copy2(tensor_path, original)
    before = sha256(tensor_path)
    np.savez_compressed(tensor_path, pixels=tensor.transpose(1, 2, 0))
    report = {
        "applied": True,
        "rule": "exact uint32 T,H,W to H,W,T transpose",
        "before_shape": [FRAMES, HEIGHT, WIDTH],
        "after_shape": list(TENSOR_SHAPE),
        "before_sha256": before,
        "after_sha256": sha256(tensor_path),
        "source_matches_all_pngs": True,
        "rgb_frames_changed": False,
    }
    atomic_json(logs / "tensor_canonicalization.json", report)
    return report


def _inside(workspace: Path, value: str) -> bool:
    if not value:
        return True
    path = Path(value)
    path = path if path.is_absolute() else workspace / path
    try:
        path.resolve().relative_to(workspace.resolve())
        return True
    except ValueError:
        return False


def _tool_name(item: dict) -> str:
    values = [item.get("type"), item.get("name"), item.get("tool"), item.get("tool_name")]
    return " ".join(str(value) for value in values if value).lower()


def _unwrap_shell(command: str) -> str:
    try:
        argv = shlex.split(command)
        if (len(argv) == 3 and Path(argv[0]).name in {"bash", "sh", "zsh"}
                and argv[1] in {"-c", "-lc", "-cl"}):
            return argv[2]
    except ValueError:
        pass
    return command


def _python_sections(command: str, include_written: bool = False):
    executable = r"python(?:3)?\s+-"
    written = r"cat\s*>\s*(?:'[^'\n]+\.py'|\"[^\"\n]+\.py\"|[^\s<>;'\"]+\.py)"
    prefix = f"(?:{executable}|{written})" if include_written else executable
    pattern = rf"(?m)^{prefix}\s+<<\s*['\"]?(?P<tag>[A-Za-z_]\w*)['\"]?\s*\n"
    for header in re.finditer(pattern, command):
        tail = command[header.end():]
        end = re.search(r'(?m)^'+re.escape(header.group('tag'))+r'\s*$',tail)
        if end:
            yield header.end(), tail[:end.start()]


def outside_command_paths(command: str, workspace: Path) -> list[str]:
    # Codex logs shell invocations as /bin/bash -lc "<actual script>".
    # Unwrap the script before identifying Python heredoc arithmetic; otherwise
    # the first header is not at line start and division is treated as a path.
    command = _unwrap_shell(command)
    values = []
    workspace_value = str(workspace.resolve()) + "/"
    divisions = set()
    # A slash in an actual Python division expression is not a file path.
    # Restrict lexical parsing to Python heredoc bodies; shell paths and
    # quoted Python filenames remain subject to the original checks.
    for body_start, body in _python_sections(command, include_written=True):
        offsets=[0]
        for line in body.splitlines(keepends=True):offsets.append(offsets[-1]+len(line))
        try:
            tokens=list(tokenize.generate_tokens(io.StringIO(body).readline))
        except (tokenize.TokenError,IndentationError):continue
        for token in tokens:
            if token.type == tokenize.OP and token.string in {"/", "//"}:
                start = body_start + offsets[token.start[0]-1] + token.start[1]
                divisions.update(range(start, start + len(token.string)))
    for match in ABSOLUTE_PATH_PATTERN.finditer(command):
        if match.start() in divisions:continue
        value = match.group(1).rstrip(".,:)")
        if value == str(workspace.resolve()) or value.startswith(workspace_value):
            continue
        if value.startswith(SYSTEM_READ_PREFIXES):
            continue
        # Installed browser binaries/assets are tools, not case conditioning.
        # Profiles, screenshots and outputs must still remain in the workspace.
        if value == PLAYWRIGHT_SOFTWARE_CACHE or value.startswith(PLAYWRIGHT_SOFTWARE_CACHE + '/'):
            continue
        values.append(value)
    if re.search(r"(?:^|[\s'\"])(?:\.\./)+", command):
        values.append("relative-parent-traversal")
    return values


def classify_outside_command_paths(command: str, workspace: Path) -> tuple[list[str], list[str]]:
    """Keep unknown outside paths blocked; record a failed literal cd as a warning.

    Only recognize a nonexistent absolute directory followed immediately by
    an explicit return to this workspace. Preserve the raw command and do not
    exempt file reads, writes, substitutions, or later uses of that path.
    """
    paths = outside_command_paths(command, workspace)
    match = re.match(
        r"\s*cd\s+(?P<outside>/[^\s;'\"`$]+)\s+2>/dev/null;\s*"
        r"cd\s+(?P<inside>/[^\s&;'\"`$]+)\s*&&", command)
    if not match:
        return paths, []
    outside, inside = match.group('outside'), match.group('inside')
    if (outside not in paths or Path(inside).resolve() != workspace.resolve()
            or Path(outside).exists() or command.count(outside) != 1):
        return paths, []
    return [path for path in paths if path != outside], [outside]


def failed_scratch_path(path: str, item: dict) -> bool:
    """Recognize a denied, nonexistent /tmp scratch target from actual output.

    A failing compound shell's final status may be zero. Do not waive existing
    /tmp files, other case/reference paths, or paths without a specific denial.
    """
    if not path.startswith('/tmp/') or Path(path).exists():
        return False
    # It must be a creation/redirection target, not an attempted lookup of an
    # outside input. A missing Python file alone is insufficient evidence.
    command = str(item.get('command',''))
    lines = str(item.get('aggregated_output', '')).splitlines()
    if (re.search(r'>\s*[\"\x27]?' + re.escape(path) + r'[\"\x27]?(?=\s|$|[;&|])', command)
            and any(path in line and 'Read-only file system' in line for line in lines)):
        return True
    return _failed_python_scratch(path, item)


def _failed_python_scratch(path: str, item: dict) -> bool:
    """Recognize narrow, evidenced failed codec probes, not arbitrary Python I/O."""
    output = str(item.get('aggregated_output', ''))
    for _, body in _python_sections(_unwrap_shell(str(item.get('command', '')))):
        try:
            tree = ast.parse(body)
        except SyntaxError:
            continue
        bindings = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                bindings.setdefault(node.targets[0].id, []).append(node.value)
        def target(node):
            if isinstance(node, ast.Constant): return node.value == path
            if isinstance(node, ast.Name) and len(bindings.get(node.id, [])) == 1:
                value = bindings[node.id][0]
                return isinstance(value, ast.Constant) and value.value == path
            return False
        writes = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and n.args and target(n.args[0])
                  and isinstance(n.func, ast.Attribute) and n.func.attr in ('VideoWriter', 'get_writer')]
        if len(writes) != 1:
            continue
        write = writes[0]
        # A traceback before the sole later path expression proves it never ran.
        trace_lines = re.findall(r'File "<stdin>", line (\d+)', output)
        if item.get('exit_code') not in (None, 0) and trace_lines and int(trace_lines[-1]) < write.lineno:
            earlier = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and n.args
                       and target(n.args[0]) and n.lineno <= int(trace_lines[-1])]
            if not earlier:
                return True
        writer = next((name for name, values in bindings.items() if len(values) == 1 and values[0] is write), None)
        def is_opened(node):
            return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == 'isOpened' and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == writer)
        printed_false = any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'print'
                            and len(n.args) == 2 and isinstance(n.args[0], ast.Constant)
                            and n.args[0].value == 'opened' and is_opened(n.args[1]) for n in ast.walk(tree))
        opened_false = write.func.attr == 'VideoWriter' and printed_false and 'opened False' in output.splitlines()
        inactive = {id(n) for branch in ast.walk(tree) if isinstance(branch, ast.If) and opened_false and is_opened(branch.test)
                    for statement in branch.body for n in ast.walk(statement)}
        active = [n for n in ast.walk(tree) if id(n) not in inactive]
        # Existing input reads remain blocked. A codec read under the proven
        # false isOpened branch is unexecuted; other target uses are conservative.
        unsafe = [n for n in active if isinstance(n, ast.Call) and n.args and target(n.args[0])
                  and n is not write and not (isinstance(n.func, ast.Name) and n.func.id == 'print')
                  and not (isinstance(n.func, ast.Attribute) and n.func.attr == 'getsize')]
        if unsafe:
            continue
        if opened_false:
            return True
        missing = any(path in line and 'No such file or directory' in line for line in output.splitlines())
        # Empty ImageIO writers create no file. Do not waive a writer that
        # actually received frames or deleted a previously created output.
        mutates = any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                      and n.func.attr in ('append_data','write','unlink','remove','rename','replace') for n in active)
        if write.func.attr == 'get_writer' and missing and not mutates:
            return True
    return False


def terminal_shutdown_verified(events_path: Path, exit_status: int) -> bool:
    """Accept only a harness-recorded shutdown after the sole successful turn.

    This handles a CLI that hangs during teardown. It does not accept a stopped
    generation, substitute an exit code, or bypass artifact/access validation.
    The receipt lives outside the agent workspace and binds the untouched log.
    """
    try:
        receipt = json.loads((events_path.parent/'cli_shutdown.json').read_text())
        events = [json.loads(line) for line in events_path.read_text().splitlines() if line.strip()]
        if not isinstance(receipt, dict) or any(not isinstance(e, dict) for e in events):
            return False
        source_name = receipt.get('terminal_source', events_path.name)
        if source_name not in (events_path.name, 'events.raw.jsonl'):
            return False
        source = events_path.parent/source_name
        source_events = [json.loads(line) for line in source.read_text().splitlines() if line.strip()]
        if any(not isinstance(e, dict) for e in source_events):
            return False
        if source != events_path:
            # Full-rollout capture appends historical image-return evidence
            # after teardown. All actual CLI events must still match raw stdout.
            projected = [{k:v for k,v in e.items() if k != '_harness_received'}
                         for e in events if e.get('item', {}).get('type') != 'full_trace_image_return']
            if projected != source_events:
                return False
        events = source_events
        terminals = [e.get('type') for e in events if e.get('type') in
                     ('turn.completed', 'turn.failed', 'turn.cancelled')]
        output = events[-1].get('usage', {}).get('output_tokens')
        return (receipt.get('kind') == 'cli_shutdown' and
                receipt.get('process_exit_status') == exit_status and
                receipt.get('terminal_sha256', receipt.get('events_sha256')) == sha256(source) and
                events[-1].get('type') == 'turn.completed' and
                terminals == ['turn.completed'] and
                isinstance(output, int) and not isinstance(output, bool) and output >= 0 and
                receipt.get('usage_output_tokens') == output)
    except (OSError, ValueError, KeyError, IndexError, AttributeError):
        return False


def validate(workspace: Path, events_path: Path, exit_status: int, track: str,
             require_reports: bool = True, media: dict | None = None,
             budget_frozen: bool = False) -> dict:
    spec = media or DEFAULT_MEDIA
    FRAMES, HEIGHT, WIDTH = (spec[k] for k in ("frames", "height", "width"))
    TENSOR_SHAPE = (HEIGHT, WIDTH, FRAMES)
    required = ("generate.py", "pixels.npz", "inspection.png", "transition_check.png",
                "index.html")
    if spec.get("audio"):
        required += ("audio.wav",)
    if require_reports:
        required += ("OBSERVATION.md", "METHOD.md")
    missing = [name for name in required if not (workspace / name).is_file()]
    frame_paths = sorted((workspace / "frames").glob("*.png")) if (workspace / "frames").is_dir() else []
    frame0_exact = False
    # Inputs inside workspace-write can be edited. New runs preserve the
    # original outside the agent workspace; compare RGB to that frozen image.
    initial_image = workspace.parent / "input_snapshot" / "first_frame.png"
    if not initial_image.is_file():
        initial_image = workspace / "first_frame.png"
    tensor_exact = False
    tensor_shape = None
    if not missing and len(frame_paths) == FRAMES:
        try:
            pixels = np.load(workspace / "pixels.npz")["pixels"]
            tensor_shape = list(pixels.shape)
            frame0_exact = spec["task_type"] != "i2v" or np.array_equal(
                np.asarray(Image.open(initial_image).convert("RGB")),
                np.asarray(Image.open(workspace / "frames" / "00.png").convert("RGB")),
            )
            tensor_exact = pixels.shape == TENSOR_SHAPE and pixels.dtype == np.uint32
            if tensor_exact:
                # Lexicographic order breaks once frame indices reach 100.
                for index in range(FRAMES):
                    path = workspace / "frames" / f"{index:02d}.png"
                    rgb = np.asarray(Image.open(path).convert("RGB"), dtype=np.uint32)
                    packed = (rgb[:, :, 0] << 16) | (rgb[:, :, 1] << 8) | rgb[:, :, 2]
                    if rgb.shape != (HEIGHT, WIDTH, 3) or not np.array_equal(packed, pixels[:, :, index]):
                        tensor_exact = False
                        break
        except Exception:
            tensor_exact = False

    audio_check = None
    if spec.get("audio"):
        audio_check = False
        try:
            with wave.open(str(workspace / "audio.wav"), "rb") as handle:
                a = spec["audio"]
                audio_check = (handle.getframerate() == a["sample_rate"] and handle.getnchannels() == a["channels"] and handle.getsampwidth() == 2 and handle.getnframes() == round(FRAMES / spec["fps"] * a["sample_rate"]) and handle.getcomptype() == "NONE")
        except (OSError, wave.Error, EOFError):
            pass
    terminal, commands, reads, failed_reads, file_changes, visual_calls = [], [], [], [], [], []
    failed_file_changes=[]
    command_items, failed_scratch = [], []
    lines = events_path.read_text(errors="replace").splitlines() if events_path.is_file() else []
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") in ("turn.completed", "turn.failed", "turn.cancelled"):
            terminal.append(event.get("type"))
        item = event.get("item", {})
        if event.get("type") == "item.completed" and item.get("type") == "file_change":
            paths=[change.get('path','') for change in item.get('changes') or []]
            (failed_file_changes if item.get('status')=='failed' else file_changes).extend(paths)
        if event.get("type") == "item.completed" and item.get("type") == "command_execution":
            command = item.get("command", "")
            commands.append(command)
            command_items.append(item)
            succeeded = item.get("status") == "completed" and item.get("exit_code") in (None, 0)
            for action in item.get("command_actions") or []:
                if action.get("type") == "read":
                    path = action.get("path", "")
                    (reads if succeeded and not failed_scratch_path(path, item) else failed_reads).append(path)
        tool = _tool_name(item)
        if event.get("type") in ("item.started", "item.completed") and "view_image" in tool:
            visual_calls.append({"event": event.get("type"), "tool": tool,
                                 "path": item.get("path") or item.get("arguments")})
        if event.get('type')=='item.completed' and item.get('type')=='full_trace_image_return':
            visual_calls.append({'event':event['type'],'tool':'actual image delivered in full rollout',
                                 'call_id':item.get('call_id'),'images':item.get('returned_images')})

    outside_reads = [value for value in reads if not _inside(workspace, value)]
    failed_outside_reads = [value for value in failed_reads if not _inside(workspace, value)]
    outside_changes = [value for value in file_changes if not _inside(workspace, value)]
    network_commands = [command for command in commands if invokes_network(command)]
    subagent_commands = [command for command in commands if invokes_subagent(command)]
    path_checks = []
    for item in command_items:
        blocked, warnings = classify_outside_command_paths(item.get('command',''), workspace)
        denied = [path for path in blocked if failed_scratch_path(path, item)]
        failed_scratch.extend(denied)
        path_checks.append(([path for path in blocked if path not in denied], warnings))
    outside_command_values = sorted({value for blocked, _ in path_checks for value in blocked})
    failed_directory_probes = sorted({value for _, warnings in path_checks for value in warnings})
    generate_runs = sum(bool(re.search(r"\bpython(?:3)?\s+(?:\./)?generate\.py\b", command))
                        for command in commands)
    track_violation = None
    if track in ("text", "vision-input") and visual_calls:
        track_violation = "view_image was invoked in a Track that disables output visual tools"
    shutdown_verified = terminal_shutdown_verified(events_path, exit_status)
    completed = (exit_status == 0 and "turn.completed" in terminal) or budget_frozen or shutdown_verified
    passed = (completed and not missing and
              len(frame_paths) == FRAMES and frame0_exact and tensor_exact and
              not outside_reads and not outside_changes and not network_commands and
              not subagent_commands and not outside_command_values and not track_violation and
              audio_check is not False)
    return {
        "exit_status": exit_status,
        "completion_mode": ('budget_frozen' if budget_frozen else
                            'agent_finished_cli_teardown_recovered' if shutdown_verified else 'agent_finished'),
        "terminal_shutdown_verified": shutdown_verified,
        "terminal_events": terminal,
        "missing_required": missing,
        "planning_and_method_reports_required": require_reports,
        "frames": len(frame_paths),
        "tensor_shape": tensor_shape,
        "frame0_exact": frame0_exact if spec["task_type"] == "i2v" else None,
        "first_frame_constraint_satisfied": frame0_exact,
        "audio_contract_exact": audio_check,
        "media_contract": spec,
        "png_tensor_exact": tensor_exact,
        "read_calls": len(reads),
        "outside_workspace_reads": outside_reads,
        "failed_outside_workspace_read_attempts": failed_outside_reads,
        "outside_workspace_file_changes": outside_changes,
        "failed_outside_workspace_file_change_attempts": [value for value in failed_file_changes if not _inside(workspace,value)],
        "network_commands": network_commands,
        "subagent_commands": subagent_commands,
        "outside_workspace_command_paths": outside_command_values,
        "failed_outside_directory_probes": failed_directory_probes,
        "failed_outside_scratch_operations": sorted(set(failed_scratch)),
        "visual_tool_calls": visual_calls,
        "generate_runs": generate_runs,
        "track_violation": track_violation,
        "pass": passed,
    }
