"""Prepare official OpenVE editing inputs; does not launch models or score."""
import argparse
import json
from pathlib import Path
from pixelworld.openve import prepare, export_submission


def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='command',required=True)
    setup=sub.add_parser('prepare')
    setup.add_argument('--data-root',type=Path,required=True)
    setup.add_argument('--inputs-root',type=Path,required=True)
    setup.add_argument('--case-index',type=int,action='append',help='Zero-based official CSV row; omitted means all 431')
    setup.add_argument('--long-edge',type=int,default=256)
    setup.add_argument('--fps',type=float,default=4)
    export=sub.add_parser('export')
    export.add_argument('--config',type=Path,required=True)
    export.add_argument('--model',required=True)
    export.add_argument('--track',choices=['text','vision-agent'],required=True)
    export.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.command=='prepare':
        records=prepare(a.data_root,a.inputs_root,a.case_index,a.long_edge,a.fps)
        print(json.dumps({'prepared':len(records),'cases':[r['case_id'] for r in records]},indent=2))
    else:
        print(json.dumps(export_submission(a.config,a.model,a.track,a.output),indent=2))


if __name__=='__main__':main()
