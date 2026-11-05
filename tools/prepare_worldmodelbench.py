#!/usr/bin/env python3
"""Download only legal I2V inputs, outside the generation agent."""
import argparse
import hashlib
from io import BytesIO
import json
from pathlib import Path
from urllib.request import urlopen

from PIL import Image


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--revision',default='main',help='Pin an upstream commit for a full evaluation')
    parser.add_argument('--indices',type=int,nargs='+',default=[0])
    parser.add_argument('--width',type=int,default=256)
    parser.add_argument('--fps',type=float,default=4)
    parser.add_argument('--seconds',type=float,default=5)
    args=parser.parse_args()
    base=f'https://raw.githubusercontent.com/WorldModelBench-Team/WorldModelBench/{args.revision}/'
    metadata=urlopen(base+'worldmodelbench.json',timeout=60).read()
    rows=json.loads(metadata)
    args.output.mkdir(parents=True,exist_ok=True)
    provenance=[]
    for index in args.indices:
        row=rows[index];image=urlopen(base+row['first_frame'],timeout=60).read()
        im=Image.open(BytesIO(image)).convert('RGB');w,h=im.size
        height=round(h/w*args.width);case=f'{index:04d}';folder=args.output/case
        folder.mkdir(exist_ok=False)
        im.resize((args.width,height),Image.Resampling.LANCZOS).save(folder/'first_frame.png')
        (folder/'prompt.txt').write_text(row['text_instruction'])
        spec={'benchmark':'worldmodelbench','task_type':'i2v','width':args.width,'height':height,
              'frames':round(args.seconds*args.fps),'fps':args.fps,'audio':None}
        (folder/'task_spec.json').write_text(json.dumps(spec,indent=2))
        provenance.append({'id':case,'upstream_image':row['first_frame'],'source_image_sha256':hashlib.sha256(image).hexdigest(),
                           'source_metadata_sha256':hashlib.sha256(metadata).hexdigest(),'revision':args.revision,
                           'conditioning':'first_frame + text_instruction only','media':spec})
    (args.output.parent/'input_provenance.json').write_text(json.dumps(provenance,indent=2))
    print(json.dumps({'cases':[p['id'] for p in provenance],'output':str(args.output)}))


if __name__=='__main__':main()
