"""Prepare a separate photographic T2V experiment; do not launch an agent."""
import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pixelworld.config import load_config
from pixelworld.media import contract
from pixelworld.supervisor import case_ids
from pixelworld.util import atomic_json


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-config',type=Path,required=True)
    p.add_argument('--inputs-root',type=Path,required=True)
    p.add_argument('--runs-root',type=Path,required=True)
    p.add_argument('--output-config',type=Path,required=True)
    args = p.parse_args()
    old = load_config(args.source_config)
    inputs, runs = args.inputs_root.resolve(), args.runs_root.resolve()
    if inputs.exists() or runs.exists() or args.output_config.exists():
        raise FileExistsError('Use fresh inputs, outputs and config paths')
    identifiers = case_ids(old)
    for case in identifiers:
        spec = contract(old.inputs_root/case)
        if spec['task_type'] != 't2v':
            raise ValueError('Photographic T2V variant cannot change an I2V/editing task')
    inputs.mkdir(parents=True)
    for case in identifiers:
        source, target = old.inputs_root/case, inputs/case
        target.mkdir()
        shutil.copy2(source/'prompt.txt',target/'prompt.txt')
        spec = json.loads((source/'task_spec.json').read_text())
        spec['visual_target'] = 'photoreal'
        atomic_json(target/'task_spec.json',spec)
        contract(target)
    config = json.loads(args.source_config.read_text())
    config.update(protocol=config['protocol']+'-photoreal-v1',inputs_root=str(inputs),runs_root=str(runs),case_ids=identifiers)
    args.output_config.parent.mkdir(parents=True,exist_ok=True)
    atomic_json(args.output_config,config)
    runs.mkdir(parents=True)
    (runs/'STOP').touch()
    print(json.dumps({'prepared_cases':len(identifiers),'visual_target':'photoreal','source_prompts_unchanged':True,
                      'config':str(args.output_config),'agent_started':False,'outputs_initially_paused':True}))


if __name__ == '__main__':
    main()
