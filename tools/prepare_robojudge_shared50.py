"""Prepare only canonical shared-50 initial frames and instructions; never videos."""
import argparse,concurrent.futures,hashlib,io,json,time
from pathlib import Path
import requests
from PIL import Image

parser=argparse.ArgumentParser()
parser.add_argument('--manifest',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
parser.add_argument('--indices',default='all')
parser.add_argument('--width',type=int,default=256)
parser.add_argument('--revision',default='7ba7a753d5c4644bbcc0a926cc1e7a46678aa54b')
args=parser.parse_args()
items=json.loads(args.manifest.read_text())
assert len(items)==50 and len({x['key'] for x in items})==50
indices=range(50) if args.indices=='all' else [int(x) for x in args.indices.split(',')]
repo='HuggingFriends/mllm-as-embodied-world-judge'
revision=args.revision
args.output.mkdir(parents=True,exist_ok=True)
robot_prefix='In a fixed robotic workspace, a rigid and physically consistent embodied robotic arm with high stability and no deformation proceeds to '
human_prefix='In a first-person egocentric video, a real human hand starts to '
human_datasets={'egodex_human','egoscaler_human','epickitchens_human'}
def prepare(i):
    row=items[i];folder=args.output/('common50_%04d'%i);folder.mkdir(exist_ok=True)
    image_url=row['init_frame_url'].replace('/resolve/main/','/resolve/'+revision+'/')
    prompt_url=row['instruction_url'].replace('/resolve/main/','/resolve/'+revision+'/')
    a=requests.get(image_url,timeout=60);a.raise_for_status()
    b=requests.get(prompt_url,timeout=60);b.raise_for_status()
    original=Image.open(io.BytesIO(a.content)).convert('RGB');h=round(original.height*args.width/original.width)
    original.resize((args.width,h),Image.Resampling.BOX).save(folder/'first_frame.png')
    instruction=b.text.strip();prefix=human_prefix if row['dataset'] in human_datasets else robot_prefix
    (folder/'prompt.txt').write_text(prefix+instruction+'\n')
    spec={'task_type':'i2v','width':args.width,'height':h,'frames':20,'fps':4,'audio':None,'benchmark':'robojudge'}
    (folder/'task_spec.json').write_text(json.dumps(spec,indent=2))
    result={'id':folder.name,'source_key':row['key'],'dataset_revision':revision,'initial_frame_url':image_url,'instruction_url':prompt_url,
            'input_only':True,'source_image_sha256':hashlib.sha256(a.content).hexdigest(),
            'prompt_sha256':hashlib.sha256((prefix+instruction).encode()).hexdigest(),'media_contract':spec,'prefix':'paper-prefix-1'}
    (folder/'input_provenance.json').write_text(json.dumps(result,indent=2));print(folder.name,'prepared',flush=True);return result
with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:rows=list(ex.map(prepare,indices))
(args.output.parent/'manifest.json').write_text(json.dumps({'benchmark':'robojudge-shared50','prepared_at':time.time(),'cases':rows,'dataset_revision':revision},indent=2))
