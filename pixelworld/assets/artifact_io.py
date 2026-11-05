"""Output-only helpers. No drawing or generation policy is implemented here."""
from pathlib import Path
import base64
import json
import wave

import numpy as np
from PIL import Image, ImageDraw


def save(frames, case_dir, audio=None):
    case_dir = Path(case_dir)
    frames = np.asarray(frames)
    path = case_dir / "task_spec.json"
    spec = json.loads(path.read_text()) if path.is_file() else {}
    n, h, w, fps = (spec.get("frames", 20), spec.get("height", 144), spec.get("width", 256), spec.get("fps", 4))
    assert frames.shape == (n, h, w, 3) and frames.dtype == np.uint8, frames.shape
    audio_spec = spec.get("audio")
    audio_url = None
    if audio_spec:
        samples = round(n / fps * audio_spec["sample_rate"])
        pcm = np.asarray(audio)
        if pcm.ndim == 1:
            pcm = pcm[:, None]
        assert pcm.shape == (samples, audio_spec["channels"]) and pcm.dtype == np.int16, (pcm.shape, pcm.dtype)
        with wave.open(str(case_dir / "audio.wav"), "wb") as handle:
            handle.setnchannels(audio_spec["channels"])
            handle.setsampwidth(2)
            handle.setframerate(audio_spec["sample_rate"])
            handle.writeframes(pcm.astype("<i2").tobytes())
        audio_url = "data:audio/wav;base64," + base64.b64encode((case_dir / "audio.wav").read_bytes()).decode()
    values = frames.astype(np.uint32)
    packed = (values[:, :, :, 0] << 16) | (values[:, :, :, 1] << 8) | values[:, :, :, 2]
    tensor = packed.transpose(1, 2, 0)
    np.savez_compressed(case_dir / "pixels.npz", pixels=tensor)

    folder = case_dir / "frames"
    folder.mkdir(exist_ok=True)
    for index, frame in enumerate(frames):
        Image.fromarray(frame).save(folder / f"{index:02d}.png")

    sheet = Image.new("RGB", (w * 4, (h + 21) * 2), (25, 28, 35))
    draw = ImageDraw.Draw(sheet)
    for index, frame_index in enumerate(np.linspace(0, n - 1, 8).round().astype(int)):
        x, y = (index % 4) * w, (index // 4) * (h + 21)
        draw.text((x + 5, y + 3), f"frame {frame_index:02d} · {frame_index / fps:.2f}s", fill="white")
        sheet.paste(Image.fromarray(frames[frame_index]), (x, y + 21))
    sheet.save(case_dir / "inspection.png")

    transition = Image.new("RGB", (w * 4, h * 2 + 21), (25, 28, 35))
    draw = ImageDraw.Draw(transition)
    for index, frame_index in enumerate(min(i, n-1) for i in range(4)):
        x = index * w
        draw.text((x + 5, 4), f"frame {frame_index:02d} · {frame_index / fps:.2f}s", fill="white")
        transition.paste(Image.fromarray(frames[frame_index]), (x, 21))
        transition.paste(Image.fromarray(frames[frame_index]).resize((w, h), Image.Resampling.NEAREST), (x, h + 21))
    transition.save(case_dir / "transition_check.png")

    encode = lambda array: base64.b64encode(np.asarray(array, dtype="<u4").tobytes()).decode()
    deltas = []
    for index in range(1, n):
        current = packed[index].reshape(-1)
        previous = packed[index - 1].reshape(-1)
        positions = np.flatnonzero(current != previous)
        packet = []
        if len(positions):
            bounds = np.r_[0, np.flatnonzero(np.diff(positions) > 1) + 1, len(positions)]
            for start, end in zip(bounds[:-1], bounds[1:]):
                offset = int(positions[start])
                count = int(end - start)
                packet.extend([offset, count])
                packet.extend(current[offset:offset + count].tolist())
        deltas.append(encode(packet))
    data = {
        "id": case_dir.name,
        "width": w, "height": h, "frames": n, "fps": fps, "audio": audio_url,
        "first": encode(packed[0].reshape(-1)),
        "deltas": deltas,
        "caption": (case_dir / "prompt.txt").read_text().strip(),
    }
    template = (Path(__file__).parent / "player_template.html").read_text()
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False).replace("<", "\\u003c")
    (case_dir / "index.html").write_text(template.replace("__ID__", case_dir.name).replace("__DATA__", payload))
