from __future__ import annotations

from pathlib import Path
import json
import re
import shutil

import numpy as np
from PIL import Image

from .constants import FRAMES, HEIGHT, TENSOR_SHAPE, WIDTH
from .util import atomic_json, sha256


SUBAGENT_PATTERN = re.compile(
    r"(?:^|&&|\|\||;)\s*(?:env\s+\S+\s+)*(?:\S*/)?(?:codex\s+exec|traecli\s+exec|agent-new)\b",
    re.I | re.M,
)
NETWORK_PATTERN = re.compile(
    r"(?:^|&&|\|\||;)\s*(?:env\s+\S+\s+)*(?:\S*/)?(?:curl|wget|nc|ncat)\b|"
    r"\b(?:requests\.(?:get|post|request)|socket\.connect|urllib\.request\.urlopen)\s*\(",
    re.I | re.M,
)
ABSOLUTE_PATH_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])(/[A-Za-z0-9_@%+=:.,-]+/[A-Za-z0-9_@%+=:,./-]*)")
SYSTEM_READ_PREFIXES = ("/bin/", "/usr/", "/lib/", "/lib64/", "/dev/", "/proc/")


def invokes_subagent(command: str) -> bool:
    return bool(SUBAGENT_PATTERN.search(command))


def invokes_network(command: str) -> bool:
    return bool(NETWORK_PATTERN.search(command))


def canonicalize_tensor(workspace: Path, logs: Path) -> dict | None:
    """Losslessly repair only the unambiguous uint32 T,H,W layout."""
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
    for match in ABSOLUTE_PATH_PATTERN.findall(command):
        value = match.rstrip(".,:)")
        if value == str(workspace.resolve()) or value.startswith(workspace_value):
            continue
        if value.startswith(SYSTEM_READ_PREFIXES):
            continue
        values.append(value)
    if re.search(r"(?:^|[\s'\"])(?:\.\./)+", command):
        values.append("relative-parent-traversal")
    return values


def validate(workspace: Path, events_path: Path, exit_status: int, track: str) -> dict:
    required = ("generate.py", "pixels.npz", "inspection.png", "transition_check.png",
                "index.html", "OBSERVATION.md", "METHOD.md")
    missing = [name for name in required if not (workspace / name).is_file()]
    frame_paths = sorted((workspace / "frames").glob("*.png")) if (workspace / "frames").is_dir() else []
    frame0_exact = False
    tensor_exact = False
    tensor_shape = None
    if not missing and len(frame_paths) == FRAMES:
        try:
            pixels = np.load(workspace / "pixels.npz")["pixels"]
            tensor_shape = list(pixels.shape)
            frame0_exact = np.array_equal(
                np.asarray(Image.open(workspace / "first_frame.png").convert("RGB")),
                np.asarray(Image.open(workspace / "frames" / "00.png").convert("RGB")),
            )
            tensor_exact = pixels.shape == TENSOR_SHAPE and pixels.dtype == np.uint32
            if tensor_exact:
                for index, path in enumerate(frame_paths):
                    rgb = np.asarray(Image.open(path).convert("RGB"), dtype=np.uint32)
                    packed = (rgb[:, :, 0] << 16) | (rgb[:, :, 1] << 8) | rgb[:, :, 2]
                    if not np.array_equal(packed, pixels[:, :, index]):
                        tensor_exact = False
                        break
        except Exception:
            tensor_exact = False

    terminal, commands, reads, failed_reads, file_changes, visual_calls = [], [], [], [], [], []
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
            file_changes.extend(change.get("path", "") for change in item.get("changes") or [])
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

    outside_reads = [value for value in reads if not _inside(workspace, value)]
    failed_outside_reads = [value for value in failed_reads if not _inside(workspace, value)]
    outside_changes = [value for value in file_changes if not _inside(workspace, value)]
    network_commands = [command for command in commands if invokes_network(command)]
    subagent_commands = [command for command in commands if invokes_subagent(command)]
    outside_command_values = sorted({value for command in commands
                                     for value in outside_command_paths(command, workspace)})
    generate_runs = sum(bool(re.search(r"\bpython(?:3)?\s+(?:\./)?generate\.py\b", command))
                        for command in commands)
    track_violation = None
    if track in ("text", "vision-input") and visual_calls:
        track_violation = "view_image was invoked in a Track that disables output visual tools"
    passed = (exit_status == 0 and "turn.completed" in terminal and not missing and
              len(frame_paths) == FRAMES and frame0_exact and tensor_exact and
              not outside_reads and not outside_changes and not network_commands and
              not subagent_commands and not outside_command_values and not track_violation)
    return {
        "exit_status": exit_status,
        "terminal_events": terminal,
        "missing_required": missing,
        "frames": len(frame_paths),
        "tensor_shape": tensor_shape,
        "frame0_exact": frame0_exact,
        "png_tensor_exact": tensor_exact,
        "read_calls": len(reads),
        "outside_workspace_reads": outside_reads,
        "failed_outside_workspace_read_attempts": failed_outside_reads,
        "outside_workspace_file_changes": outside_changes,
        "network_commands": network_commands,
        "subagent_commands": subagent_commands,
        "outside_workspace_command_paths": outside_command_values,
        "visual_tool_calls": visual_calls,
        "generate_runs": generate_runs,
        "track_violation": track_violation,
        "pass": passed,
    }
