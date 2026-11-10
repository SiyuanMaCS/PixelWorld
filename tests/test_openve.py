import json
from pathlib import Path
import numpy as np
from PIL import Image
import pytest

from pixelworld.config import load_config
from pixelworld.runner import run_case
from pixelworld.openve import sample_video


@pytest.mark.parametrize('track', ['text','vision-agent'])
def test_editing_inputs_are_frozen_and_track_visual_boundary_preserved(tmp_path,track):
    source=tmp_path/'inputs/openve_0058';source.mkdir(parents=True)
    spec={'task_type':'video_edit','width':32,'height':24,'frames':9,'fps':9/2.26,'audio':None}
    (source/'task_spec.json').write_text(json.dumps(spec))
    (source/'prompt.txt').write_text('Change the car while preserving its motion.')
    Image.new('RGB',(32,24),'black').save(source/'first_frame.png')
    Image.new('RGB',(64,24),'black').save(source/'source_inspection.png')
    (source/'source_info.json').write_text(json.dumps({'duration_seconds':2.26}))
    (source/'source_video.mp4').write_bytes(b'fixture input bytes')
    np.savez_compressed(source/'source_pixels.npz',rgb=np.zeros((9,24,32,3),dtype=np.uint8))
    path=tmp_path/'config.json'
    path.write_text(json.dumps({'protocol':'pixelworld-openve-edit-v1-20261110','inputs_root':'inputs',
        'runs_root':'runs','models':[{'key':'m','model':'m','tracks':[track]}]}))
    result=run_case(load_config(path),'m',track,'openve_0058',dry_run=True,codex_binary='/bin/echo')
    ws=Path(result['workspace']);snapshot=ws.parent/'input_snapshot'
    assert (ws/'source_video.mp4').read_bytes()==(snapshot/'source_video.mp4').read_bytes()
    assert result['initial_input_hashes']['source_pixels.npz']
    assert 'complete source video' in (ws.parent/'task_prompt.txt').read_text()
    assert 'future continuation' not in (ws/'GENERATION_RULES.md').read_text()
    command=result['command']
    if track=='text':
        assert '--image' not in command
        assert command[command.index('view_image')-1]=='--disable'
    else:
        assert command.count('--image')==2
        assert str(ws/'source_inspection.png') in command


def test_sampling_preserves_whole_short_clip_duration_and_aspect(tmp_path):
    cv2=pytest.importorskip('cv2')
    source=tmp_path/'source.avi'
    writer=cv2.VideoWriter(str(source),cv2.VideoWriter_fourcc(*'MJPG'),50,(64,36))
    if not writer.isOpened():pytest.skip('MJPG encoder unavailable')
    for i in range(113):writer.write(np.full((36,64,3),i,dtype=np.uint8))
    writer.release()
    rgb,info=sample_video(source,256,4)
    assert rgb.shape==(9,144,256,3)
    assert info['duration_seconds']==pytest.approx(2.26)
    assert len(rgb)/info['effective_fps']==pytest.approx(2.26)
    assert info['original_frame_indices'][-1] > 95
    assert rgb[-1].mean() > rgb[0].mean()+80
