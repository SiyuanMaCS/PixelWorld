"""Render a rich case page outside the publication critical path."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_bench_review import build_case


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--job',type=Path,required=True)
    args=parser.parse_args()
    # The publisher and recovery renderer may discover the same case together.
    # Claim the output before touching its status or files.
    args.output.mkdir(parents=True, exist_ok=True)
    render_lock=(args.output/'.render.lock').open('a')
    try:
        fcntl.flock(render_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return
    status={'phase':'rendering','pid':os.getpid(),'run':str(args.run),'output':str(args.output),'updated_at':time.time()}
    args.job.write_text(json.dumps(status))
    try:
        row=build_case(args.run,args.output)
        page=args.output/'index.html'
        page.write_text(page.read_text().replace('href="../../../../index.html"','href="../index.html"').replace('本轮 smoke 总览','此模型总览'))
        status.update(phase='ready',row=row,updated_at=time.time())
    except Exception as exc:
        status.update(phase='failed',error=f'{type(exc).__name__}: {exc}',updated_at=time.time())
    temporary=args.job.with_suffix('.tmp')
    temporary.write_text(json.dumps(status,ensure_ascii=False))
    temporary.replace(args.job)


if __name__=='__main__':main()
