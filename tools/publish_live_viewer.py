"""Publish only the live viewer and its cache versions on the Pages branch."""
import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def publish(checkout: Path):
    checkout = checkout.resolve()
    with checkout.with_name(checkout.name + '.publish.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        identity = json.loads((checkout/'.git/pixelworld-delivery.json').read_text())
        branch = subprocess.check_output(['git','symbolic-ref','--short','HEAD'], cwd=checkout, text=True).strip()
        if identity != {'repository':'SiyuanMaCS/SiyuanMaCS.github.io','branch':'pixelworld-pages'} or branch != identity['branch']:
            raise ValueError('Use the dedicated PixelWorld Pages delivery checkout')
        if subprocess.check_output(['git','status','--porcelain'], cwd=checkout, text=True).strip():
            raise ValueError('Finish the current Pages changes before a viewer-only publication')
        script = (ROOT/'tools/live_refresh.js').read_bytes()
        version = hashlib.sha256(script).hexdigest()[:12]
        (checkout/'pixelworld/live_refresh.js').write_bytes(script)
        changed = ['pixelworld/live_refresh.js']
        from tools.build_bench_review import document
        gallery = 'pixelworld/phygen_pixelspace_smoke/index.html'
        (checkout/gallery).write_text(document('PhyGenBench T2V / I2V Smoke',
            '<section class="hero"><p class="eyebrow">PIXELWORLD · PAIRED SMOKE</p>'
            '<h1>PhyGenBench · T2V / I2V</h1>'
            '<p>相同物理 prompt，分别测试 T2V、I2V 与 Text、Vision。'
            'I2V 首帧来自 Qwen-Image-2.1；后续帧均由 coding agent 生成。</p></section>'
            '<p><a href="/pixelworld/index.html">← PixelWorld 总览</a> · '
            '<a href="/pixelworld/phygen_qwen_init/index.html">Qwen 初始帧 →</a> · '
            '<a href="/pixelworld/phygen_pixelspace.html">协议与进度 →</a></p>'
            '<p id="live-poll-time" class="note">正在读取当前模型与四个条件的进度…</p>'))
        changed.append(gallery)
        paths = subprocess.check_output(['git','ls-files','--','pixelworld'], cwd=checkout, text=True).splitlines()
        for relative in paths:
            if not relative.endswith('.html'):
                continue
            path = checkout/relative
            text = path.read_text()
            updated = re.sub(r'/pixelworld/live_refresh\.js(?:\?[^\s\"\x27<>]*)?',
                             '/pixelworld/live_refresh.js?v='+version, text)
            if updated != text:
                path.write_text(updated)
                changed.append(relative)
        for start in range(0,len(changed),1000):
            subprocess.run(['git','add','--',*changed[start:start+1000]], cwd=checkout, check=True)
        if subprocess.run(['git','diff','--cached','--quiet'], cwd=checkout).returncode:
            subprocess.run(['git','commit','-m','Refresh live viewer '+version], cwd=checkout, check=True)
        subprocess.run(['git','push','origin',branch], cwd=checkout, check=True)
        return {'script_sha256':hashlib.sha256(script).hexdigest(), 'updated_files':len(changed),
                'commit':subprocess.check_output(['git','rev-parse','HEAD'], cwd=checkout, text=True).strip()}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkout',type=Path,required=True)
    print(json.dumps(publish(parser.parse_args().checkout)))
