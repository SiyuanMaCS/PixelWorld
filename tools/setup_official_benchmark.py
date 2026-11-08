"""Recreate pinned evaluator sources/environments using the user's own tools.

This never installs Codex, runs generation, downloads baseline videos, or scores
anything. Neural evaluator resources are kept outside agent workspaces.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    'robojudge': ('https://github.com/Sphere-AI-Lab/RoboJudge.git', 'db6c2b7bd8e447ad1e21a63a48c5e26e816811e2', 'robojudge-eval-night'),
    'vbench-i2v': ('https://github.com/Vchitect/VBench.git', 'fd18b3d055cb0fc6f066ca90fe2c3c8cbb698490', 'vbench-i2v-night'),
    'worldarena': ('https://github.com/tsinghua-fib-lab/WorldArena.git', '2da2ae253b8637ba9de3afc7bea4e087f778ee4d', 'worldarena-eval-night'),
    'wbench': ('https://github.com/meituan-longcat/WBench.git', 'edc4e80e642baac4f2b5764dec9f1a491200af8f', 'wbench-eval-night'),
    'worldscore': ('https://github.com/haoyi-duan/WorldScore.git', '096c75fc4ada9c7d92e03140c3c1f0c8f383b61f', 'worldscore-eval-night'),
}


def checkout(url: str, revision: str, source: Path) -> None:
    if source.exists():
        actual = subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()
        dirty = subprocess.check_output(['git','-C',str(source),'diff','HEAD','--name-only'],text=True).strip()
        if actual != revision or dirty:
            raise ValueError('Existing checkout differs from pin; choose a new root, do not overwrite it')
        return
    source.parent.mkdir(parents=True,exist_ok=True)
    env={**os.environ,'GIT_LFS_SKIP_SMUDGE':'1'}
    subprocess.run(['git','clone','--filter=blob:none','--no-checkout',url,str(source)],env=env,check=True)
    subprocess.run(['git','-C',str(source),'checkout','--detach',revision],env=env,check=True)


def main() -> None:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('benchmark',choices=SOURCES)
    p.add_argument('--root',type=Path)
    p.add_argument('--venv',type=Path,help='Optional isolated evaluator environment; never installs Codex')
    p.add_argument('--python',default='3.11')
    p.add_argument('--download-checkpoint',action='store_true',help='Only the pinned public RoboJudge9B checkpoint')
    args=p.parse_args()
    url,revision,name=SOURCES[args.benchmark]
    base=(args.root or ROOT/'vendor'/name).resolve()
    source=base/'source'
    checkout(url,revision,source)
    if args.benchmark=='robojudge':
        shutil.copy2(ROOT/'configs/evaluation/robojudge_shared50_inputs.json',base/'shared50_inputs.json')
    if args.venv:
        requirements=ROOT/'configs/evaluation'/f'{args.benchmark}.requirements.txt'
        if not requirements.exists():
            raise ValueError('Use the pinned source installation instructions for its CUDA extensions; no substitute environment is installed')
        uv=shutil.which('uv')
        if not uv:raise RuntimeError('uv is required for optional environment setup')
        subprocess.run([uv,'venv','--python',args.python,str(args.venv.resolve())],check=True)
        cuda_index='cu118' if args.benchmark=='robojudge' else 'cu121'
        subprocess.run([uv,'pip','install','--python',str(args.venv.resolve()/'bin/python'),
                        '--index-url','https://pypi.org/simple','--extra-index-url',f'https://download.pytorch.org/whl/{cuda_index}',
                        '--index-strategy','unsafe-best-match','-r',str(requirements)],check=True)
    if args.download_checkpoint:
        if args.benchmark!='robojudge':
            raise ValueError('This flag only downloads the identified original RoboJudge checkpoint')
        from huggingface_hub import snapshot_download
        checkpoint_revision='54b5fd7b93e0288bc91a8827af03b72eec7ffad1'
        checkpoint=base/'checkpoint'
        snapshot_download('HuggingFriends/RoboJudge-9B',revision=checkpoint_revision,local_dir=checkpoint,max_workers=2)
        files={}
        for path in checkpoint.iterdir():
            if not path.is_file():continue
            digest=hashlib.sha256()
            with path.open('rb') as f:
                for block in iter(lambda:f.read(8*1024*1024),b''):digest.update(block)
            files[path.name]={'bytes':path.stat().st_size,'sha256':digest.hexdigest()}
        (base/'checkpoint_manifest.json').write_text(json.dumps({'repo_id':'HuggingFriends/RoboJudge-9B',
            'revision':checkpoint_revision,'files':files},indent=2))
    record={'benchmark':args.benchmark,'source_url':url,'source_revision':revision,
            'codex_installed':False,'generation_run':False,'baseline_videos_downloaded':False,'scores_computed':False}
    (base/'setup_provenance.json').write_text(json.dumps(record,indent=2))
    print(json.dumps(record))


if __name__=='__main__':
    main()
