"""OpenVE input preparation and submission export, outside agent workspaces."""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import urllib.request

import numpy as np
from PIL import Image, ImageDraw

from .config import load_config
from .util import atomic_json, sha256

DATASET_ID = 'Lewandofski/OpenVE-Bench'
DATASET_REVISION = '255b2ff91a8c7d45696f37f5aed14bd427b35e34'
SOURCE_URL = 'https://github.com/OpenVE-Team/OpenVE-3M'
SOURCE_REVISION = 'f36055a7f43186f7e7d77f9f4b243cb51731da97'
OFFICIAL_COUNT = 431


def rows(path: Path) -> list[dict]:
    with path.open(encoding='utf-8-sig', newline='') as f:
        result = list(csv.DictReader(f))
    if len(result) != OFFICIAL_COUNT or not all(
            {'edited_type', 'prompt', 'original_video'} <= r.keys() for r in result):
        raise ValueError('Expected the pinned official 431-row OpenVE CSV')
    return result


def download(relative: str, target: Path) -> None:
    if target.is_file():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    url = f'https://huggingface.co/datasets/{DATASET_ID}/resolve/{DATASET_REVISION}/{relative}'
    with urllib.request.urlopen(url, timeout=90) as response:
        data = response.read()
    temp = target.with_suffix(target.suffix + '.part')
    temp.write_bytes(data)
    temp.replace(target)


def sample_video(path: Path, long_edge: int, target_fps: float):
    import cv2
    if long_edge < 2 or not math.isfinite(target_fps) or target_fps <= 0:
        raise ValueError('Positive sampling FPS and long edge >=2 required')
    video = cv2.VideoCapture(str(path))
    try:
        count = int(video.get(cv2.CAP_PROP_FRAME_COUNT))
        native_fps = video.get(cv2.CAP_PROP_FPS)
        width, height = int(video.get(3)), int(video.get(4))
        if not video.isOpened() or min(count, native_fps, width, height) <= 0:
            raise ValueError('Source video cannot be decoded')
        duration = count / native_fps
        n = max(1, round(duration * target_fps))
        # Preserve the full source duration; do not truncate every edit to 5s.
        fps = n / duration
        scale = long_edge / max(width, height)
        w = max(2, 2 * round(width * scale / 2))
        h = max(2, 2 * round(height * scale / 2))
        timestamps = [i / fps for i in range(n)]
        indices = [min(count - 1, round(t * native_fps)) for t in timestamps]
        result = []
        for index in indices:
            video.set(cv2.CAP_PROP_POS_FRAMES, index)
            ok, frame = video.read()
            if not ok:
                raise ValueError(f'Cannot decode original frame {index}')
            img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            result.append(np.asarray(img.resize((w, h), Image.Resampling.LANCZOS)))
        info = {'original_frames': count, 'original_fps': native_fps,
                'original_width': width, 'original_height': height,
                'duration_seconds': duration, 'requested_fps': target_fps,
                'effective_fps': fps, 'sample_timestamps_seconds': timestamps,
                'original_frame_indices': indices, 'width': w, 'height': h}
        return np.stack(result), info
    finally:
        video.release()


def prepare(data_root: Path, inputs_root: Path, indices: list[int] | None = None,
            long_edge: int = 256, target_fps: float = 4) -> list[dict]:
    csv_path = data_root / 'benchmark_videos.csv'
    download('benchmark_videos.csv', csv_path)
    official = rows(csv_path)
    indices = list(range(len(official))) if indices is None else indices
    if len(set(indices)) != len(indices) or any(i < 0 or i >= len(official) for i in indices):
        raise ValueError('Case indices must be unique official zero-based row indices')
    records = []
    for index in indices:
        row = official[index]
        path = PurePosixPath(row['original_video'])
        if path.is_absolute() or '..' in path.parts or path.parts[:2] != ('OpenVE-Bench', 'videos'):
            raise ValueError('Unexpected official source-video path')
        source = data_root / 'videos' / path.name
        download('videos/' + path.name, source)
        case = f'openve_{index:04d}'
        destination = inputs_root / case
        if destination.exists():
            raise FileExistsError(f'Prepared inputs are immutable: {destination}')
        frames, info = sample_video(source, long_edge, target_fps)
        destination.mkdir(parents=True)
        shutil.copy2(source, destination / 'source_video.mp4')
        np.savez_compressed(destination / 'source_pixels.npz', rgb=frames)
        Image.fromarray(frames[0]).save(destination / 'first_frame.png')
        n, h, w, _ = frames.shape
        columns = min(5, n)
        inspection = Image.new('RGB', (columns * w, math.ceil(n/columns) * (h+20)), '#141b24')
        draw = ImageDraw.Draw(inspection)
        for i, frame in enumerate(frames):
            x, y = i % columns * w, i // columns * (h + 20)
            inspection.paste(Image.fromarray(frame), (x, y))
            draw.text((x+4, y+h+3), f'{i}: {info["sample_timestamps_seconds"][i]:.2f}s', fill='white')
        inspection.save(destination / 'source_inspection.png')
        atomic_json(destination / 'source_info.json', info)
        (destination / 'prompt.txt').write_text(row['prompt'] + '\n')
        spec = {'task_type': 'video_edit', 'benchmark': 'openve-bench-v1',
                'width': w, 'height': h, 'frames': n, 'fps': info['effective_fps'], 'audio': None}
        atomic_json(destination / 'task_spec.json', spec)
        provenance = {'case_id': case, 'row_index': index, 'official_row': row,
                      'dataset_id': DATASET_ID, 'dataset_revision': DATASET_REVISION,
                      'csv_sha256': sha256(csv_path), 'source_sha256': sha256(source),
                      'sampling': info, 'media_contract': spec}
        # Not copied into agent workspace; includes benchmark metadata only.
        atomic_json(destination / 'preparation_record.json', provenance)
        records.append(provenance)
    return records


def encode_pixels(workspace: Path, spec: dict, target: Path) -> None:
    with np.load(workspace / 'pixels.npz', allow_pickle=False) as data:
        packed = data['pixels']
        if packed.dtype != np.uint32 or packed.shape != (spec['height'], spec['width'], spec['frames']):
            raise ValueError('Invalid submitted packed RGB shape')
        packed = packed.transpose(2, 0, 1)
        rgb = np.stack([(packed >> s) & 255 for s in (16, 8, 0)], axis=-1).astype(np.uint8)
    binary = shutil.which('ffmpeg')
    if not binary:
        import imageio_ffmpeg
        binary = imageio_ffmpeg.get_ffmpeg_exe()
    target.parent.mkdir(parents=True, exist_ok=True)
    cmd = [binary, '-y', '-v', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
           '-s', f'{spec["width"]}x{spec["height"]}', '-r', str(spec['fps']),
           '-i', '-', '-an', '-c:v', 'libx264', '-crf', '18', '-pix_fmt', 'yuv420p', str(target)]
    subprocess.run(cmd, input=rgb.tobytes(), check=True, capture_output=True)


def export_submission(config_path: Path, model: str, track: str, target: Path) -> dict:
    config = load_config(config_path)
    config.model(model)
    target.mkdir(parents=True, exist_ok=True)
    selected = {}
    for path in (config.runs_root / model / track).glob('case_*_attempt_*/run_manifest.json'):
        manifest = json.loads(path.read_text())
        if manifest['status'] != 'complete' or not manifest.get('validation', {}).get('pass'):
            continue
        case = manifest['case_id']
        if case not in selected or manifest['attempt'] < selected[case][1]['attempt']:
            selected[case] = (path.parent, manifest)
    exported = []
    for case, (run, manifest) in sorted(selected.items()):
        record = json.loads((config.inputs_root / case / 'preparation_record.json').read_text())
        video = target / 'videos' / (case + '.mp4')
        encode_pixels(run / 'workspace', manifest['media_contract'], video)
        exported.append(record['official_row'] | {'edited_result_path': str(video.resolve())})
    with (target / 'new_result.csv').open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['edited_type','prompt','original_video','edited_result_path'])
        writer.writeheader()
        writer.writerows(exported)
    summary = {'exported': len(exported), 'official_total': OFFICIAL_COUNT,
               'full_official_scope': len(exported) == OFFICIAL_COUNT,
               'model': model, 'track': track, 'selected_attempts': {c:m['attempt'] for c,(_,m) in selected.items()},
               'dataset_revision': DATASET_REVISION, 'evaluator_revision': SOURCE_REVISION,
               'scores_computed': False}
    atomic_json(target / 'submission_manifest.json', summary)
    return summary
