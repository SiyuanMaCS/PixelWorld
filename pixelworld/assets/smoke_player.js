'use strict';
class PixelPlayer {
  constructor(root, data) {
    this.root=root; this.d=data; this.frame=0; this.playing=false; this.frames=null;
    this.canvas=root.querySelector('canvas'); this.canvas.width=data.width; this.canvas.height=data.height;
    this.ctx=this.canvas.getContext('2d'); this.image=this.ctx.createImageData(data.width,data.height);
    this.button=root.querySelector('.play'); this.seek=root.querySelector('.seek'); this.clock=root.querySelector('.clock');
    this.seek.max=data.frames-1; this.audio=data.audio?new Audio(data.audio):null;
    this.button.onclick=()=>this.playing?this.pause():this.start();
    root.querySelector('.replay').onclick=async()=>{this.pause();await this.ensure();this.draw(0);this.start()};
    this.seek.oninput=async()=>{this.pause();try{await this.ensure();this.draw(+this.seek.value)}catch(e){this.error(e)}};
    this.updateClock(); window.__smokePlayers.push(this);
  }
  updateClock(){this.clock.textContent=`${this.frame+1}/${this.d.frames} · ${(this.frame/this.d.fps).toFixed(2)} / ${(this.d.frames/this.d.fps).toFixed(2)}s`}
  error(e){this.pause();this.clock.textContent='Load failed: '+e.message;this.root.dataset.error=e.message}
  async ensure(){
    if(this.frames)return;
    if(this.loading)return this.loading;
    this.loading=(async()=>{
      const response=await fetch(this.d.asset);if(!response.ok)throw Error('HTTP '+response.status);
      const blob=await response.blob(),url=URL.createObjectURL(blob);
      const im=await new Promise((ok,no)=>{const x=new Image();x.onload=()=>ok(x);x.onerror=()=>no(Error('Invalid pixel sprite'));x.src=url});
      const w=this.d.width,h=this.d.height,n=this.d.frames,c=document.createElement('canvas');c.width=w;c.height=h*n;
      const ctx=c.getContext('2d',{willReadFrequently:true});ctx.drawImage(im,0,0);URL.revokeObjectURL(url);
      if(im.width!==w||im.height!==h*n)throw Error('Pixel sprite dimensions');
      const raw=ctx.getImageData(0,0,w,h*n).data,size=w*h*4;this.frames=[];
      for(let i=0;i<n;i++){const a=new Uint8ClampedArray(size),off=i*size,prev=i?this.frames[i-1]:null;
        for(let j=0;j<size;j+=4){a[j]=raw[off+j]^(prev?prev[j]:0);a[j+1]=raw[off+j+1]^(prev?prev[j+1]:0);a[j+2]=raw[off+j+2]^(prev?prev[j+2]:0);a[j+3]=255}this.frames.push(a)}
      this.draw(this.frame);
    })();try{await this.loading}catch(e){this.loading=null;throw e}
  }
  draw(n){this.frame=Math.max(0,Math.min(this.d.frames-1,n));this.seek.value=this.frame;this.updateClock();if(this.frames){this.image.data.set(this.frames[this.frame]);this.ctx.putImageData(this.image,0,0);this.root.querySelector('.poster').hidden=true}}
  pause(){this.playing=false;cancelAnimationFrame(this.raf);if(this.audio)this.audio.pause();this.button.textContent='▶ 播放'}
  async start(){
    this.button.textContent='载入中…';
    for(const control of this.root.querySelectorAll('button,input'))control.disabled=true;
    try{await this.ensure();if(this.frame===this.d.frames-1)this.draw(0);this.started=performance.now()-this.frame/this.d.fps*1000;
      if(this.audio){this.audio.currentTime=this.frame/this.d.fps;await this.audio.play()}
      this.playing=true;this.button.textContent='❚❚ 暂停';this.raf=requestAnimationFrame(t=>this.tick(t));
    }catch(e){this.error(e)}finally{for(const control of this.root.querySelectorAll('button,input'))control.disabled=false}
  }
  tick(t){
    if(!this.playing)return;let elapsed=this.audio?this.audio.currentTime:(t-this.started)/1000;
    if(elapsed>=this.d.frames/this.d.fps||(this.audio&&this.audio.ended)){
      if(this.root.querySelector('.loop').checked){this.started=t;elapsed=0;if(this.audio){this.audio.currentTime=0;this.audio.play().catch(e=>this.error(e))}}
      else{this.draw(this.d.frames-1);this.pause();return}
    }
    this.draw(Math.floor(elapsed*this.d.fps));this.raf=requestAnimationFrame(x=>this.tick(x));
  }
}
window.__smokePlayers=[];
for(const root of document.querySelectorAll('.player'))new PixelPlayer(root,JSON.parse(root.dataset.player));
window.__smokeReady=true;

// Use one animation clock for selected revisions; independent playback stays available.
window.__candidateComparisons=[];
for(const root of document.querySelectorAll('[data-candidate-compare]')){
  const players=window.__smokePlayers.filter(p=>root.contains(p.root)),seek=root.querySelector('.compare-seek'),clock=root.querySelector('.compare-clock'),button=root.querySelector('.compare-play');
  if(!players.length)continue;
  seek.max=players[0].d.frames-1;
  const group={root,players,playing:false,frame:0,raf:null,
    selected(){return players.filter(p=>p.root.closest('.candidate-entry').querySelector('.compare-pick').checked)},
    pause(){this.playing=false;cancelAnimationFrame(this.raf);players.forEach(p=>p.pause());button.textContent='▶ 同步播放勾选版本'},
    draw(frame){this.frame=frame;seek.value=frame;clock.textContent=`${(frame/players[0].d.fps).toFixed(2)} / ${(players[0].d.frames/players[0].d.fps).toFixed(2)}s`;this.selected().forEach(p=>p.draw(frame))},
    async ensure(){const selected=this.selected();if(!selected.length)throw Error('请勾选要对比的版本');await Promise.all(selected.map(p=>p.ensure()))},
    async start(){if(this.playing){this.pause();return}button.disabled=true;button.textContent='载入中…';try{await this.ensure();players.forEach(p=>p.pause());if(this.frame===players[0].d.frames-1)this.draw(0);this.started=performance.now()-this.frame/players[0].d.fps*1000;this.playing=true;this.selected().forEach(p=>{p.playing=true;p.button.textContent='❚❚ 暂停'});button.textContent='❚❚ 暂停同步播放';this.raf=requestAnimationFrame(t=>this.tick(t))}catch(e){this.pause();clock.textContent='Load failed: '+e.message}finally{button.disabled=false}},
    tick(t){if(!this.playing)return;let elapsed=(t-this.started)/1000;const d=players[0].d;if(elapsed>=d.frames/d.fps){if(root.querySelector('.compare-loop').checked){this.started=t;elapsed=0}else{this.draw(d.frames-1);this.pause();return}}this.draw(Math.min(d.frames-1,Math.floor(elapsed*d.fps)));this.raf=requestAnimationFrame(x=>this.tick(x))}
  };
  button.onclick=()=>group.start();root.querySelector('.compare-pause').onclick=()=>group.pause();
  root.querySelector('.compare-replay').onclick=()=>{group.pause();group.frame=0;group.start()};
  seek.oninput=async()=>{group.pause();try{await group.ensure();group.draw(+seek.value)}catch(e){clock.textContent=e.message}};
  root.querySelectorAll('.compare-pick').forEach(c=>c.onchange=()=>group.pause());
  players.forEach(p=>{const play=p.button.onclick,slide=p.seek.oninput,replay=p.root.querySelector('.replay').onclick;p.button.onclick=()=>{if(group.playing){group.pause();return}play()};p.seek.oninput=()=>{group.pause();slide()};p.root.querySelector('.replay').onclick=()=>{group.pause();replay()}});
  root.__comparison=group;window.__candidateComparisons.push(group);
}
window.__candidateCompareReady=true;
