import gzip
import json
import sys

import numpy as np
from PIL import Image

from tools.build_bench_review import export_pixels, build_case, case_page_is_current
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


def test_chunked_native_pixels_round_trip_all_frames_without_downsampling(tmp_path):
    source=tmp_path/'source';source.mkdir();target=tmp_path/'public'
    rng=np.random.default_rng(7);rgb=rng.integers(0,256,(7,3,4,3),dtype=np.uint8)
    values=rgb.astype(np.uint32);packed=(values[...,0]<<16)|(values[...,1]<<8)|values[...,2]
    np.savez_compressed(source/'pixels.npz',pixels=packed.transpose(1,2,0))
    spec={'width':4,'height':3,'frames':7,'fps':24}
    video=export_pixels(source,target,spec,chunk_bytes=72)
    assert [c['frames']for c in video['chunks']]==[2,2,2,1]
    blocks=[]
    for c in video['chunks']:
        block=np.frombuffer(gzip.decompress((target/c['pixels_file']).read_bytes()),dtype=np.uint8).reshape(3,4,c['frames'],3)
        blocks.append(block.transpose(2,0,1,3))
    np.testing.assert_array_equal(np.concatenate(blocks),rgb)
    assert export_pixels(source,target,spec,chunk_bytes=72)==video


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


def test_running_placeholder_is_replaced_when_video_finishes(tmp_path):
    run, output = tmp_path/'run', tmp_path/'public'
    (run/'workspace').mkdir(parents=True)
    (run/'input_snapshot').mkdir()
    (run/'input_snapshot/prompt.txt').write_text('Move the object.')
    (run/'media_contract.json').write_text(json.dumps({'width':2,'height':2,'frames':2,'fps':4}))
    manifest = {'model':'m','model_key':'m','case_id':'case1','track':'text','attempt':1,
                'status':'running','started_utc':'2026-11-09T00:00:00Z','token_usage':{}}
    (run/'run_manifest.json').write_text(json.dumps(manifest))
    build_case(run,output)
    assert case_page_is_current(run,output)
    assert '尚未保存可播放视频' in (output/'index.html').read_text()
    np.savez_compressed(run/'workspace/pixels.npz',pixels=np.full((2,2,2),0x102030,dtype=np.uint32))
    manifest.update(status='complete',validation={'pass':True},token_usage={'output_tokens':123})
    (run/'run_manifest.json').write_text(json.dumps(manifest))
    assert not case_page_is_current(run,output)
    result=build_case(run,output)
    assert result['playable'] and case_page_is_current(run,output)
    assert 'class=player' in (output/'index.html').read_text()
    assert '尚未保存可播放视频' not in (output/'index.html').read_text()


def test_incremental_indexes_do_not_link_to_an_unprepared_detail(tmp_path, monkeypatch):
    from tools import sync_incremental_previews as sync
    from types import SimpleNamespace
    monkeypatch.setattr(sync.subprocess,'Popen',lambda *args,**kwargs:SimpleNamespace(pid=99999999))
    root, web, public = tmp_path/'root',tmp_path/'staging',tmp_path/'public'
    for index in (1,2):
        run=root/'generations/robojudge/m/text'/f'case_{index}_attempt_01'
        (run/'workspace').mkdir(parents=True)
        (run/'input_snapshot').mkdir()
        (run/'input_snapshot/prompt.txt').write_text('Fixture only.')
        (run/'media_contract.json').write_text(json.dumps({'width':2,'height':2,'frames':2,'fps':4}))
        (run/'run_manifest.json').write_text(json.dumps({'model':'m','model_key':'m','case_id':str(index),
            'track':'text','attempt':1,'status':'complete','validation':{'pass':True},
            'started_utc':f'2026-11-09T00:00:0{index}Z','token_usage':{}}))
        np.savez_compressed(run/'workspace/pixels.npz',pixels=np.full((2,2,2),0x102030,dtype=np.uint32))
    result=sync.sync_previews(root,web,public,limit=1)
    assert result['updated']==[] and result['remaining']==2
    assert len(result['quick_updated'])==2
    page=(public/'bench_smoke_codex_20261109/robojudge/m/text/index.html').read_text()
    assert 'case_1_attempt_01/index.html' not in page
    assert 'case_2_attempt_01/index.html' not in page
    for index in (1,2):
        assert f'case_{index}_attempt_01/quick.html' in page
        assert (public/f'bench_smoke_codex_20261109/robojudge/m/text/case_{index}_attempt_01/quick.html').is_file()
