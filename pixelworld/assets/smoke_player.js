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
    try{await this.ensure();if(this.frame===this.d.frames-1)this.draw(0);this.started=performance.now()-this.frame/this.d.fps*1000;
      if(this.audio){this.audio.currentTime=this.frame/this.d.fps;await this.audio.play()}
      this.playing=true;this.button.textContent='❚❚ 暂停';this.raf=requestAnimationFrame(t=>this.tick(t));
    }catch(e){this.error(e)}
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
