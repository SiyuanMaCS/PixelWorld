"""Lossless playback of saved RGB revisions; never execute a generator."""
from pathlib import Path
import base64
import hashlib
import io
import json
import os
import zipfile

import numpy as np
from PIL import Image

from .media import DEFAULT_MEDIA


def read_candidate(directory: Path, spec: dict) -> tuple[np.ndarray, str, str | None]:
    h,w,n=(spec[k] for k in ('height','width','frames'))
    warning=None
    try:
        with np.load(directory/'pixels.npz',allow_pickle=False) as archive:
            packed=archive['pixels']
        if packed.shape==(n,h,w):
            packed=packed.transpose(1,2,0)
        if packed.shape!=(h,w,n) or packed.dtype!=np.uint32 or np.any(packed>0xffffff):
            raise ValueError('Invalid RGB tensor')
        rgb=np.stack([(packed>>16)&255,(packed>>8)&255,packed&255],axis=-1).astype(np.uint8).transpose(2,0,1,3).copy()
        return rgb,'tensor',None
    except (OSError,ValueError,EOFError,KeyError,zipfile.BadZipFile) as error:
        warning=f'Tensor unreadable ({type(error).__name__}); playing the complete saved PNG sequence.'
    rgb=np.stack([np.array(Image.open(directory/'frames'/f'{i:02d}.png').convert('RGB')) for i in range(n)])
    if rgb.shape!=(n,h,w,3):
        raise ValueError('Incomplete saved PNG sequence')
    return rgb,'saved_pngs',warning


def encode_candidate(rgb: np.ndarray, target: Path, spec: dict) -> dict:
    digest=hashlib.sha256(np.ascontiguousarray(rgb).tobytes()).hexdigest()
    name=f'video-{digest[:20]}.png'
    target.mkdir(parents=True,exist_ok=True)
    output=target/name
    if not output.exists():
        delta=rgb.copy();delta[1:]=np.bitwise_xor(rgb[1:],rgb[:-1])
        data=io.BytesIO();Image.fromarray(delta.reshape(spec['frames']*spec['height'],spec['width'],3)).save(data,format='PNG')
        temporary=output.with_name(output.name+f'.tmp.{os.getpid()}')
        temporary.write_bytes(data.getvalue());temporary.replace(output)
    poster=io.BytesIO();Image.fromarray(rgb[0]).save(poster,format='WEBP',quality=90,method=4)
    return {'asset':name,'poster':'data:image/webp;base64,'+base64.b64encode(poster.getvalue()).decode(),
            'width':spec['width'],'height':spec['height'],'frames':spec['frames'],'fps':spec['fps'],
            'audio':None,'rgb_sha256':digest}


def revision_versions(run: Path, target: Path, spec: dict | None = None) -> tuple[list[dict],dict,list[dict]]:
    """Merge only consecutive identical RGB; keep A->B->A as three versions."""
    manifest=json.loads((run/'run_manifest.json').read_text())
    spec=spec or manifest.get('media_contract',DEFAULT_MEDIA)
    rows_path=run/'trace/rounds.jsonl'
    rows=[json.loads(line) for line in rows_path.read_text().splitlines()] if rows_path.is_file() else []
    rows.sort(key=lambda row:row['round'])
    versions=[];mapping={};warnings=[]
    for row in rows:
        index=row['round']
        try:
            rgb,source,warning=read_candidate(run/'trace'/f'round_{index:03d}',spec)
        except (OSError,ValueError,EOFError) as error:
            warnings.append({'snapshot':index,'unavailable':str(error)})
            continue
        digest=hashlib.sha256(rgb.tobytes()).hexdigest()
        if not versions or digest!=versions[-1]['rgb_sha256']:
            record=encode_candidate(rgb,target,spec)
            record.update(version=len(versions),snapshot=index,utc=row.get('utc'),source=source,
                          warning=warning,snapshots=[index],is_final=False)
            earlier=next((v['version'] for v in versions if v['rgb_sha256']==digest),None)
            record['same_pixels_as']=earlier
            versions.append(record)
        else:
            versions[-1]['snapshots'].append(index)
        mapping[index]=versions[-1]['version']
        if warning:warnings.append({'snapshot':index,'warning':warning})
    rgb,source,warning=read_candidate(run/'workspace',spec)
    digest=hashlib.sha256(rgb.tobytes()).hexdigest()
    if not versions or digest!=versions[-1]['rgb_sha256']:
        record=encode_candidate(rgb,target,spec)
        record.update(version=len(versions),snapshot=None,utc=manifest.get('completed_utc'),source=source,
                      warning=warning,snapshots=[],is_final=False,
                      same_pixels_as=next((v['version'] for v in versions if v['rgb_sha256']==digest),None))
        versions.append(record)
    versions[-1]['is_final']=True
    return versions,mapping,warnings
