"""Immutable per-task media contracts; no generation or judge policy."""
from __future__ import annotations

import json
from pathlib import Path

DEFAULT_MEDIA = {"task_type": "i2v", "width": 256, "height": 144,
                 "frames": 20, "fps": 4.0, "audio": None}


def contract(source: Path) -> dict:
    path = source / "task_spec.json" if source.is_dir() else source
    raw = json.loads(path.read_text()) if path.is_file() else {}
    result = DEFAULT_MEDIA | raw
    allowed = set(DEFAULT_MEDIA) | {"benchmark", "turn", "action"}
    if set(raw) - allowed:
        raise ValueError(f"Unsupported task fields: {set(raw) - allowed}")
    if result["task_type"] not in ("i2v", "v2v", "t2v"):
        raise ValueError("task_type must be i2v, v2v or t2v")
    for key in ("width", "height", "frames"):
        value = result[key]
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError(f"{key} must be a positive integer")
    if not 0 < float(result["fps"]) <= 240:
        raise ValueError("fps must be positive and <=240")
    audio = result["audio"]
    if audio is not None:
        if set(audio) != {"sample_rate", "channels"} or audio["channels"] not in (1, 2):
            raise ValueError("audio needs sample_rate and 1 or 2 channels")
        if not isinstance(audio["sample_rate"], int) or not 8000 <= audio["sample_rate"] <= 192000:
            raise ValueError("Invalid audio sample rate")
    return result


def task_rules(spec: dict) -> str:
    w, h, n, fps = (spec[k] for k in ("width", "height", "frames", "fps"))
    inputs = "`first_frame.png`, `prompt.txt` and `task_spec.json`" if spec["task_type"] == "i2v" else "`prompt.txt` and `task_spec.json`"
    first = " Frame 00 must be pixel-identical to `first_frame.png`." if spec["task_type"] == "i2v" else " Generate all frames from the text."
    if spec['task_type']=='v2v':
        inputs='`conditioning.mp4`, `conditioning_frames/`, `conditioning_info.json`, `conditioning_inspection.png`, `first_frame.png`, `prompt.txt` and `task_spec.json`'
        first=' Generate only the future continuation after the conditioning clip, without including the historical segment. `first_frame.png` is the last historical frame for reference; output frame 00 is a future prediction, not a required copy.'
    audio = ""
    if spec["audio"]:
        rate, channels = spec["audio"]["sample_rate"], spec["audio"]["channels"]
        samples = round(n / fps * rate)
        audio = f"\n- Also generate {samples} PCM samples at {rate} Hz, {channels} channel(s), synchronized to the RGB video; pass `audio=` (int16 shape `({samples},{channels})`) to `artifact_io.save`."
    return f"""# PixelWorld generation contract v2

- Use only {inputs}. Work inside this workspace. No network, other cases, reference continuations, masks, scores, memory, external AI models, learned weights, external simulation/rendering engines, or subagents.
- Generate {n} RGB frames at {w}×{h}, {fps:g} fps, for {n/fps:g} seconds.{first}
- You must create `generate.py`, run it, and call `artifact_io.save(frames, case_dir)` at least once before finishing. Finish only after the required output artifacts exist. Keep `generate.py` runnable so it regenerates the submitted RGB video.{audio}
- Local Python/numpy/PIL, mathematical geometry, motion, lighting, copying and warping pixels are allowed.
- If you revise the video, save each revised candidate before continuing. Avoid repeated revision without a clear expected improvement; aim for high-quality output while considering efficiency.
"""
