"""Output-only helpers. No drawing or generation policy is implemented here."""
from pathlib import Path
import base64
import json

import numpy as np
from PIL import Image, ImageDraw


def save(frames, case_dir):
    case_dir = Path(case_dir)
    frames = np.asarray(frames)
    assert frames.shape == (20, 144, 256, 3) and frames.dtype == np.uint8, frames.shape
    values = frames.astype(np.uint32)
    packed = (values[:, :, :, 0] << 16) | (values[:, :, :, 1] << 8) | values[:, :, :, 2]
    tensor = packed.transpose(1, 2, 0)
    np.savez_compressed(case_dir / "pixels.npz", pixels=tensor)

    folder = case_dir / "frames"
    folder.mkdir(exist_ok=True)
    for index, frame in enumerate(frames):
        Image.fromarray(frame).save(folder / f"{index:02d}.png")

    sheet = Image.new("RGB", (1024, 330), (25, 28, 35))
    draw = ImageDraw.Draw(sheet)
    for index, frame_index in enumerate((0, 2, 5, 8, 11, 14, 17, 19)):
        x, y = (index % 4) * 256, (index // 4) * 165
        draw.text((x + 5, y + 3), f"frame {frame_index:02d} · {frame_index / 4:.2f}s", fill="white")
        sheet.paste(Image.fromarray(frames[frame_index]), (x, y + 21))
    sheet.save(case_dir / "inspection.png")

    transition = Image.new("RGB", (1024, 309), (25, 28, 35))
    draw = ImageDraw.Draw(transition)
    for index, frame_index in enumerate((0, 1, 2, 3)):
        x = index * 256
        draw.text((x + 5, 4), f"frame {frame_index:02d} · {frame_index / 4:.2f}s", fill="white")
        transition.paste(Image.fromarray(frames[frame_index]), (x, 21))
        transition.paste(Image.fromarray(frames[frame_index]).resize((256, 144), Image.Resampling.NEAREST), (x, 165))
    transition.save(case_dir / "transition_check.png")

    encode = lambda array: base64.b64encode(np.asarray(array, dtype="<u4").tobytes()).decode()
    deltas = []
    for index in range(1, 20):
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
        "first": encode(packed[0].reshape(-1)),
        "deltas": deltas,
        "caption": (case_dir / "prompt.txt").read_text().strip(),
    }
    template = (Path(__file__).parent / "player_template.html").read_text()
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False).replace("<", "\\u003c")
    (case_dir / "index.html").write_text(template.replace("__ID__", case_dir.name).replace("__DATA__", payload))
