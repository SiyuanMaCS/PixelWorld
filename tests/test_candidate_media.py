import json
import numpy as np
from PIL import Image

from pixelworld.candidate_media import read_candidate,revision_versions


SPEC={'height':6,'width':8,'frames':3,'fps':1,'audio':None,'task_type':'i2v'}


def save(directory,offset):
    directory.mkdir(parents=True)
    yy,xx=np.indices((6,8))
    rgb=np.stack([np.stack([(xx+offset+i)%256,(yy+i)%256,(xx+yy)%256],axis=-1) for i in range(3)]).astype(np.uint8)
    values=rgb.astype(np.uint32);packed=(values[...,0]<<16)|(values[...,1]<<8)|values[...,2]
    np.savez_compressed(directory/'pixels.npz',pixels=packed.transpose(1,2,0))
    (directory/'frames').mkdir()
    for i,frame in enumerate(rgb):Image.fromarray(frame).save(directory/'frames'/f'{i:02d}.png')
    return rgb


def test_reverting_to_an_old_video_remains_a_playable_revision(tmp_path):
    run=tmp_path/'run';rows=[]
    for i,offset in enumerate([0,1,1,0]):
        save(run/'trace'/f'round_{i:03d}',offset);rows.append({'round':i,'utc':str(i)})
    (run/'trace/rounds.jsonl').write_text('\n'.join(json.dumps(r) for r in rows))
    save(run/'workspace',0)
    (run/'run_manifest.json').write_text(json.dumps({'media_contract':SPEC}))
    versions,mapping,warnings=revision_versions(run,tmp_path/'assets')
    assert len(versions)==3 and mapping=={0:0,1:1,2:1,3:2}
    assert versions[2]['same_pixels_as']==0 and versions[2]['is_final']
    assert versions[0]['asset']==versions[2]['asset']
    assert len(list((tmp_path/'assets').glob('*.png')))==2
    assert not warnings


def test_corrupt_tensor_can_play_the_complete_saved_pngs(tmp_path):
    rgb=save(tmp_path/'candidate',4)
    (tmp_path/'candidate/pixels.npz').write_bytes(b'')
    actual,source,warning=read_candidate(tmp_path/'candidate',SPEC)
    assert np.array_equal(actual,rgb) and source=='saved_pngs' and warning
