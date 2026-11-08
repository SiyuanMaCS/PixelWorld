from __future__ import annotations

from pathlib import Path
import argparse
import ast
import hashlib
import json
import shutil
import time
import zipfile

import numpy as np
from PIL import Image

from .util import atomic_json, sha256, utc_now
from .media import DEFAULT_MEDIA, contract

AUXILIARY_CANDIDATE_FILES = ('transition_check.png', 'index.html', 'OBSERVATION.md', 'METHOD.md')


def _optional_digest(path: Path):
    return sha256(path) if path.is_file() and path.stat().st_size else None


def candidate_key(workspace: Path, media: dict | None = None):
    spec = media or DEFAULT_MEDIA
    code, pixels, inspection = (workspace / n for n in ('generate.py','pixels.npz','inspection.png'))
    frames = workspace / 'frames'
    if not (code.is_file() and pixels.is_file() and frames.is_dir()):
        return None
    if min(code.stat().st_size, pixels.stat().st_size) == 0:
        return None
    pngs = [frames / f'{i:02d}.png' for i in range(spec["frames"])]
    if not all(p.is_file() and p.stat().st_size for p in pngs) or pixels.stat().st_mtime_ns < code.stat().st_mtime_ns:
        return None
    inspection_sha = None
    if inspection.is_file() and inspection.stat().st_size:
        try:
            with Image.open(inspection) as image:
                image.verify()
            inspection_sha = sha256(inspection)
        except (OSError, ValueError):
            pass
    audio = workspace / 'audio.wav'
    audio_sha = sha256(audio) if spec.get('audio') and audio.is_file() else None
    first = (sha256(code), sha256(pixels), inspection_sha, audio_sha,
             *(_optional_digest(workspace/name) for name in AUXILIARY_CANDIDATE_FILES))
    time.sleep(.15)
    second = (sha256(code), sha256(pixels), _optional_digest(inspection),
              sha256(audio) if spec.get('audio') and audio.is_file() else None,
              *(_optional_digest(workspace/name) for name in AUXILIARY_CANDIDATE_FILES))
    return first if first == second else None


def freeze(workspace: Path, trace: Path, index: int, key, media: dict | None = None) -> dict | None:
    """Commit only an internally consistent copied candidate; never alter source."""
    spec = media or DEFAULT_MEDIA
    h, w, n = (spec[k] for k in ("height", "width", "frames"))
    target = trace / f'round_{index:03d}'
    temporary = trace / f'.round_{index:03d}.tmp'
    trace.mkdir(parents=True, exist_ok=True)
    if temporary.exists():
        shutil.rmtree(temporary)
    temporary.mkdir()
    copied, omitted = [], []
    try:
        for name in ('generate.py','pixels.npz','inspection.png','transition_check.png','OBSERVATION.md','METHOD.md','index.html','audio.wav','task_spec.json'):
            source = workspace / name
            if source.is_file() and source.stat().st_size:
                shutil.copy2(source, temporary / name)
                copied.append(name)
        shutil.copytree(workspace / 'frames', temporary / 'frames')
        copied.append('frames/')
        if (sha256(temporary / 'generate.py'), sha256(temporary / 'pixels.npz')) != key[:2]:
            raise ValueError('Source changed while freezing')
        if spec.get('audio') and (not (temporary/'audio.wav').is_file() or sha256(temporary/'audio.wav') != key[3]):
            raise ValueError('Audio changed while freezing')
        for name, expected in zip(AUXILIARY_CANDIDATE_FILES, key[4:]):
            if _optional_digest(temporary/name) != expected:
                raise ValueError('Auxiliary candidate output changed while freezing')
        with np.load(temporary / 'pixels.npz', allow_pickle=False) as archive:
            pixels = archive['pixels']
        if pixels.dtype != np.uint32 or pixels.shape not in ((h,w,n),(n,h,w)) or np.any(pixels > 0xFFFFFF):
            raise ValueError('Invalid RGB tensor')
        frames = pixels.transpose(2,0,1) if pixels.shape == (h,w,n) else pixels
        for i in range(spec["frames"]):
            rgb = np.asarray(Image.open(temporary / 'frames' / f'{i:02d}.png').convert('RGB'), dtype=np.uint32)
            if rgb.shape != (h,w,3):
                raise ValueError('Invalid candidate PNG dimensions')
            packed = (rgb[...,0]<<16)|(rgb[...,1]<<8)|rgb[...,2]
            if not np.array_equal(packed, frames[i]):
                raise ValueError('PNG and tensor were written at different times')
        if spec['task_type'] == 'i2v':
            original = workspace.parent / 'input_snapshot/first_frame.png'
            if not original.is_file():
                original = workspace / 'first_frame.png'
            first = np.asarray(Image.open(original).convert('RGB'), dtype=np.uint32)
            if not np.array_equal((first[...,0]<<16)|(first[...,1]<<8)|first[...,2], frames[0]):
                raise ValueError('Candidate first frame mismatch')
        if (sha256(workspace / 'generate.py'),sha256(workspace / 'pixels.npz')) != key[:2]:
            raise ValueError('Source changed during consistency check')
        for name in ('inspection.png','transition_check.png'):
            path = temporary / name
            if path.is_file():
                try:
                    with Image.open(path) as image:
                        image.verify()
                except (OSError, ValueError):
                    path.unlink();copied.remove(name);omitted.append(name)
        rgb_frames = np.stack([(frames >> 16) & 255, (frames >> 8) & 255, frames & 255],axis=-1).astype(np.uint8)
        record = {'round':index,'utc':utc_now(),'generate_sha256':key[0],'pixels_sha256':key[1],
                  'inspection_sha256':sha256(temporary/'inspection.png') if (temporary/'inspection.png').is_file() else None,
                  'canonical_rgb_sha256':hashlib.sha256(np.ascontiguousarray(rgb_frames).tobytes()).hexdigest(),
                  'files':copied,'omitted_invalid_optional_images':omitted,
                  'audio_sha256':key[3] if len(key)>3 else None,
                  'required_output_files_complete': all((temporary/name).is_file() for name in
                      ('generate.py','pixels.npz','inspection.png','transition_check.png','index.html')),
                  'media_contract':spec,'artifact_checks':{'frame0_exact':True if spec['task_type']=='i2v' else None,'all_png_tensor_exact':True,'copied_code_and_tensor_match_source':True}}
        atomic_json(temporary / 'snapshot.json',record)
        temporary.replace(target)
        with (trace / 'rounds.jsonl').open('a') as handle:
            handle.write(json.dumps(record)+'\n')
        return record
    except (OSError, ValueError, KeyError, EOFError, zipfile.BadZipFile):
        shutil.rmtree(temporary, ignore_errors=True)
        return None


def record_code(workspace: Path, trace: Path, prior: str | None) -> str | None:
    """Observe code revisions even before the first RGB output exists."""
    source = workspace / 'generate.py'
    try:
        data = source.read_bytes()
        if not data:
            return prior
        digest = hashlib.sha256(data).hexdigest()
        if digest == prior:
            return prior
        folder = trace / 'code_versions'
        folder.mkdir(parents=True,exist_ok=True)
        path = folder / f'{digest}.py'
        if not path.exists():
            path.write_bytes(data)
        try:
            ast.parse(data);valid = True
        except (SyntaxError, ValueError):
            valid = False
        with (trace / 'code_history.jsonl').open('a') as handle:
            handle.write(json.dumps({'utc':utc_now(),'sha256':digest,'file':f'code_versions/{digest}.py',
                                     'syntax_valid':valid,'source':'external file observation'})+'\n')
        return digest
    except OSError:
        return prior


def watch(workspace: Path, trace: Path, stop_file: Path, interval: float = .5, media: dict | None = None) -> None:
    trace.mkdir(parents=True,exist_ok=True)
    seen = set();index = 0;last_code = None
    while True:
        last_code = record_code(workspace,trace,last_code)
        try:
            key = candidate_key(workspace, media)
            if key and key not in seen:
                record = freeze(workspace,trace,index,key,media)
                if record:
                    print(json.dumps(record),flush=True);seen.add(key);index += 1
        except (OSError, ValueError):
            pass  # Retry a source file still being written, without feedback.
        if stop_file.exists():
            break
        time.sleep(interval)
    atomic_json(trace/'watcher_complete.json',{'completed_utc':utc_now(),'rounds':index})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--workspace',type=Path,required=True)
    parser.add_argument('--trace',type=Path,required=True)
    parser.add_argument('--stop-file',type=Path,required=True)
    parser.add_argument('--interval',type=float,default=.5)
    parser.add_argument('--spec-file',type=Path)
    args = parser.parse_args()
    watch(args.workspace.resolve(),args.trace.resolve(),args.stop_file.resolve(),args.interval,contract(args.spec_file) if args.spec_file else None)


if __name__=='__main__':main()
