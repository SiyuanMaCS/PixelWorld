"""Prepare native official 4K I2V inputs without reading reference futures."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from PIL import Image
from pixelworld.physics_iq import official_cases
from pixelworld.constants import PHYSICS_IQ_COMMIT,PHYSICS_IQ_DATASET_REVISION
from pixelworld.util import atomic_json,sha256,utc_now


def prepare(source_frames: Path,base_inputs: Path,inputs: Path,width=3840,height=2160):
    if (width,height) not in ((1280,720),(3840,2160)):raise ValueError('Use an authorized 720p or native 4K condition')
    spec={'task_type':'i2v','width':width,'height':height,'fps':24,'frames':120,'audio':None,
          'benchmark':'physics_iq_native_source_24fps'}
    def one(case):
        source=source_frames/Path(case['source_file']).name
        if sha256(source)!=case['source_sha256']:raise ValueError('Official source frame hash mismatch: '+case['id'])
        destination=inputs/case['id'];destination.mkdir(parents=True,exist_ok=True)
        with Image.open(source) as image:
            image=image.convert('RGB')
            if image.size!=(3840,2160):raise ValueError('Native source dimensions differ')
            if hashlib.sha256(image.resize((256,144),Image.Resampling.BOX).tobytes()).hexdigest()!=case['resized_rgb_sha256']:
                raise ValueError('Canonical source RGB identity differs')
            if (width,height)!=(3840,2160):image=image.resize((width,height),Image.Resampling.LANCZOS)
            rgb_hash=hashlib.sha256(image.tobytes()).hexdigest()
            png=destination/'first_frame.png'
            if png.exists():
                with Image.open(png) as prior:
                    if hashlib.sha256(prior.convert('RGB').tobytes()).hexdigest()!=rgb_hash:raise ValueError('Prepared input changed')
            else:image.save(png)
        prompt=(base_inputs/case['id']/'prompt.txt').read_text().strip()
        if hashlib.sha256(prompt.encode()).hexdigest()!=case['prompt_sha256']:raise ValueError('BPP prompt identity differs')
        (destination/'prompt.txt').write_text(prompt+'\n');atomic_json(destination/'task_spec.json',spec)
        return {'id':case['id'],'source_file':str(source.resolve()),'source_sha256':case['source_sha256'],
                'first_frame_png_sha256':sha256(png),'native_rgb_sha256':rgb_hash,'prompt_sha256':case['prompt_sha256']}
    inputs.mkdir(parents=True,exist_ok=True)
    with ThreadPoolExecutor(max_workers=4) as pool:rows=list(pool.map(one,official_cases()))
    inventory={'schema':'pixelworld-native-source-physics-iq-inputs-v1','prepared_utc':utc_now(),'spec':spec,'cases':rows,
               'upstream_commit':PHYSICS_IQ_COMMIT,'dataset_revision':PHYSICS_IQ_DATASET_REVISION,
               'input_transform':'official_source_rgb_identity' if width==3840 else 'official_source_lanczos720',
               'reference_futures_or_masks_used':False}
    atomic_json(inputs.parent/(inputs.name+'_manifest.json'),inventory)
    return inventory


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-frames',type=Path,required=True);parser.add_argument('--base-inputs',type=Path,required=True)
    parser.add_argument('--inputs',type=Path,required=True)
    parser.add_argument('--width',type=int,default=3840);parser.add_argument('--height',type=int,default=2160)
    args=parser.parse_args()
    record=prepare(args.source_frames,args.base_inputs,args.inputs,args.width,args.height)
    print(json.dumps({'prepared':len(record['cases']),'spec':record['spec']}))
