import shutil
import subprocess

import pytest

from tools.build_bench_review import PLAYER


@pytest.mark.skipif(shutil.which('node') is None, reason='Node is required for browser clock simulation')
def test_early_animation_timestamp_and_end_of_video_keep_valid_frame_indices():
    script = "globalThis.window={};globalThis.document={querySelectorAll:()=>[]};\n" + PLAYER + """
let tick;
globalThis.performance={now:()=>1000};
globalThis.requestAnimationFrame=(callback)=>{tick=callback};
const player=Object.create(PixelPlayer.prototype);
Object.assign(player,{
  node:{querySelector:()=>({})},d:{frames:120,fps:24},frame:0,playing:false,
  draw(){if(this.frame<0 || this.frame>119)throw Error('invalid visible frame')},
  pause(){this.playing=false}
});
player.start();
tick(998);
if(player.frame!==0)throw Error('early RAF timestamp must retain frame 00');
tick(1200);
if(player.frame!==4)throw Error('playback must advance at 24 fps');
tick(6100);
if(player.frame!==119 || player.playing)throw Error('hold final frame and finish');
"""
    result=subprocess.run(['node','-e',script],text=True,capture_output=True)
    assert result.returncode==0,result.stderr
