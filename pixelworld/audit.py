from __future__ import annotations

from pathlib import Path
import io
import json
import re
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


def outside_command_paths(command: str, workspace: Path) -> list[str]:
    values = []
    workspace_value = str(workspace.resolve()) + "/"
    divisions = set()
    # A slash in an actual Python division expression is not a file path.
    # Restrict lexical parsing to Python heredoc bodies; shell paths and
    # quoted Python filenames remain subject to the original checks.
    for header in re.finditer(r"(?m)^python(?:3)?\s+-\s+<<\s*['\"]?(?P<tag>[A-Za-z_]\w*)['\"]?\s*\n", command):
        tail=command[header.end():]
        end=re.search(r'(?m)^'+re.escape(header.group('tag'))+r'\s*$',tail)
        if not end:continue
        body=tail[:end.start()]
        offsets=[0]
        for line in body.splitlines(keepends=True):offsets.append(offsets[-1]+len(line))
        try:
            tokens=list(tokenize.generate_tokens(io.StringIO(body).readline))
        except (tokenize.TokenError,IndentationError):continue
        divisions.update(header.end()+offsets[token.start[0]-1]+token.start[1]
                         for token in tokens if token.type==tokenize.OP and token.string=='/')
    for match in ABSOLUTE_PATH_PATTERN.finditer(command):
        if match.start() in divisions:continue
        value = match.group(1).rstrip(".,:)")
        if value == str(workspace.resolve()) or value.startswith(workspace_value):
            continue
        if value.startswith(SYSTEM_READ_PREFIXES):
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


def validate(workspace: Path, events_path: Path, exit_status: int, track: str,
             require_reports: bool = True, media: dict | None = None) -> dict:
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
    tensor_exact = False
    tensor_shape = None
    if not missing and len(frame_paths) == FRAMES:
        try:
            pixels = np.load(workspace / "pixels.npz")["pixels"]
            tensor_shape = list(pixels.shape)
            frame0_exact = spec["task_type"] != "i2v" or np.array_equal(
                np.asarray(Image.open(workspace / "first_frame.png").convert("RGB")),
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
            succeeded = item.get("status") == "completed" and item.get("exit_code") in (None, 0)
            for action in item.get("command_actions") or []:
                if action.get("type") == "read":
                    (reads if succeeded else failed_reads).append(action.get("path", ""))
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
    path_checks = [classify_outside_command_paths(command, workspace) for command in commands]
    outside_command_values = sorted({value for blocked, _ in path_checks for value in blocked})
    failed_directory_probes = sorted({value for _, warnings in path_checks for value in warnings})
    generate_runs = sum(bool(re.search(r"\bpython(?:3)?\s+(?:\./)?generate\.py\b", command))
                        for command in commands)
    track_violation = None
    if track in ("text", "vision-input") and visual_calls:
        track_violation = "view_image was invoked in a Track that disables output visual tools"
    passed = (exit_status == 0 and "turn.completed" in terminal and not missing and
              len(frame_paths) == FRAMES and frame0_exact and tensor_exact and
              not outside_reads and not outside_changes and not network_commands and
              not subagent_commands and not outside_command_values and not track_violation and
              audio_check is not False)
    return {
        "exit_status": exit_status,
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
        "visual_tool_calls": visual_calls,
        "generate_runs": generate_runs,
        "track_violation": track_violation,
        "pass": passed,
    }
