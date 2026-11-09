import gzip
import json
import sys

import numpy as np
from PIL import Image

from tools.build_bench_review import export_pixels, build_case
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


def test_actual_full_trace_images_are_displayed_once_and_missing_blobs_are_skipped(tmp_path):
    run, output = tmp_path/'run', tmp_path/'public'
    workspace, logs = run/'workspace', run/'logs'
    workspace.mkdir(parents=True)
    (logs/'tool_images').mkdir(parents=True)
    spec = {'width':2, 'height':2, 'frames':2, 'fps':4}
    (run/'media_contract.json').write_text(json.dumps(spec))
    (run/'input_snapshot').mkdir()
    (run/'input_snapshot/prompt.txt').write_text('Move the ball.')
    np.savez_compressed(workspace/'pixels.npz', pixels=np.full((2,2,2), 0x102030, dtype=np.uint32))
    (workspace/'prompt.txt').write_text('Move the ball.')
    (run/'run_manifest.json').write_text(json.dumps({
        'model':'test-model', 'model_key':'test-model', 'case_id':'case1', 'track':'vision-agent',
        'status':'complete', 'media_contract':spec, 'started_utc':'2026-11-09T00:00:00Z',
        'token_usage':{'output_tokens':0},
    }))
    image = logs/'tool_images/view.png'
    Image.new('RGB',(3,2),(100,110,120)).save(image)
    events = [
        {'type':'item.completed','item':{'type':'full_trace_image_return','call_id':'view-1',
         'returned_images':[{'path':'tool_images/view.png','available':True}, {'path':None,'available':False}]}},
        {'type':'item.completed','item':{'type':'full_trace_image_return','call_id':'view-1',
         'returned_images':[{'path':'tool_images/view.png','available':True}]}},
        {'type':'item.completed','item':{'type':'full_trace_image_return','call_id':'missing',
         'returned_images':[{'path':'tool_images/missing.png','available':False}]}}
    ]
    (logs/'events.jsonl').write_text('\n'.join(json.dumps(event) for event in events)+'\n')
    result = build_case(run,output)
    assert result['visual_returns'] == 1
    assert result['output_tokens'] == 0
    assert (output/'tool_view_01.png').read_bytes() == image.read_bytes()
    page = (output/'index.html').read_text()
    assert '视觉工具实际返回图片 1' in page and 'tool_view_01.png' in page
    assert not (output/'tool_view_02.png').exists()
