import argparse
import json
from pathlib import Path
from pixelworld.pcve import prepare,export


def main():
    p=argparse.ArgumentParser(description='Prepare only official PCVE source inputs; targets stay outside generation')
    sub=p.add_subparsers(dest='command',required=True)
    a=sub.add_parser('prepare');a.add_argument('--data-root',type=Path,required=True);a.add_argument('--inputs-root',type=Path,required=True);a.add_argument('--case-index',type=int,action='append')
    a=sub.add_parser('export');a.add_argument('--config',type=Path,required=True);a.add_argument('--model',required=True);a.add_argument('--track',choices=['text','vision-agent'],required=True);a.add_argument('--benchmark-root',type=Path,required=True);a.add_argument('--baseline',required=True)
    args=p.parse_args()
    if args.command=='prepare':
        result=prepare(args.data_root,args.inputs_root,args.case_index);print(json.dumps({'prepared':len(result),'cases':[r['case_id'] for r in result]}))
    else:print(json.dumps(export(args.config,args.model,args.track,args.benchmark_root,args.baseline),indent=2))


if __name__=='__main__':main()
