import gzip
import json
import sys

import numpy as np

from tools.build_bench_review import export_pixels
from tools.build_bench_review import main


def test_changed_candidate_retains_old_url_and_exports_new_rgb(tmp_path):
    source, target = tmp_path/'candidate', tmp_path/'public'
    source.mkdir()
    spec = {'width':2, 'height':2, 'frames':2, 'fps':4}
    pixels = np.full((2,2,2), 0x102030, dtype=np.uint32)
    np.savez_compressed(source/'pixels.npz', pixels=pixels)
    initial = export_pixels(source,target,spec)
    first = target/initial['pixels_file']
    before = first.read_bytes()
    assert export_pixels(source,target,spec) == initial
    pixels[...,1] = 0x405060
    np.savez_compressed(source/'pixels.npz', pixels=pixels)
    changed = export_pixels(source,target,spec)
    assert changed['pixels_file'] != initial['pixels_file']
    assert first.read_bytes() == before
    decoded = np.frombuffer(gzip.decompress((target/changed['pixels_file']).read_bytes()), dtype=np.uint8).reshape(2,2,2,3)
    np.testing.assert_array_equal(decoded[:,:,0], np.broadcast_to([16,32,48],(2,2,3)))
    np.testing.assert_array_equal(decoded[:,:,1], np.broadcast_to([64,80,96],(2,2,3)))


def test_robojudge_text_and_vision_scores_keep_track_and_partial_scope(tmp_path, monkeypatch):
    root, output = tmp_path/'run', tmp_path/'web'
    for suffix, pa, ia in [('text_gpu_smoke', 2, 2), ('gpu_smoke', 3, 5)]:
        directory = root/'evaluation'/f'robojudge_gpt61-sol_{suffix}'
        directory.mkdir(parents=True)
        (directory/'summary.json').write_text(json.dumps({
            'valid_paired_count': 1,
            'complete_shared50': False,
            'partial_paired_means': {'PA': pa, 'IA': ia},
            'items': [{'case_id': 'common50_0001', 'PA': pa, 'IA': ia}],
        }))
    monkeypatch.setattr(sys, 'argv', ['build_bench_review', '--root', str(root), '--output', str(output)])
    main()
    page = (output/'index.html').read_text()
    assert 'GPT-6.1-Sol / text' in page
    assert 'GPT-6.1-Sol / vision-agent' in page
    assert 'PA 2.00 / IA 2.00' in page
    assert 'PA 3.00 / IA 5.00' in page
    assert page.count('不是 shared50 均分') == 2
    assert page.count('Cases：common50_0001') == 2
