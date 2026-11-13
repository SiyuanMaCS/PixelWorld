/* Saved RGB candidates and observed tools; independent of Pages deployment. */
(() => {
  const root = 'https://raw.githubusercontent.com/SiyuanMaCS/SiyuanMaCS.github.io/pixelworld-live/pixelworld/';
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const label = key => ({'gpt61-sol':'GPT-6.1-Sol','gpt56-sol':'GPT-5.6-Sol','gpt6-astra':'GPT-6-Astra','deepseek-v41':'DeepSeek-V4.1-Flash','seed21-pro':'Seed-2.1-Pro-0915'}[key] || key);
  const prefixes = {
    physics_iq_512w24fps_gpt_native: 'physics_iq_512w24fps_gpt_native',
    'bench_smoke_codex_20261109/physics_iq': 'physics_iq',
    'bench_smoke_codex_20261109/physics_iq_gpt_native_v2': 'physics_iq_gpt_native_v2',
    'bench_smoke_codex_20261109/physics_iq_seed21_native_v2': 'physics_iq_seed21_native_v2',
    'bench_smoke_codex_20261109/robojudge': 'robojudge',
    pcve_smoke: 'pcve_smoke'
  };
  const query = new URLSearchParams(location.search);
  let context = null;
  if (location.pathname.endsWith('/live.html')) {
    context = {suite:query.get('suite'),model:query.get('model'),track:query.get('track'),case:query.get('case'),attempt:query.get('attempt')};
  } else {
    const relative = location.pathname.split('/pixelworld/')[1] || '';
    for (const [prefix,suite] of Object.entries(prefixes)) {
      if (!relative.startsWith(prefix + '/')) continue;
      const parts = relative.slice(prefix.length + 1).split('/');
      context = {suite,model:parts[0],track:parts[1]};
      if (parts[2]?.startsWith('case_')) {
        const match = parts[2].match(/^case_(.+)_attempt_(\d+)$/);
        if (match) Object.assign(context,{case:match[1],attempt:String(+match[2])});
      }
      break;
    }
  }
  const phygenGallery = location.pathname.endsWith('/phygen_pixelspace_smoke/index.html');
  const relevant = context || phygenGallery || /\/(index|pixelworld-index|physics_iq_512w24fps|phygen_pixelspace)\.html$/.test(location.pathname);
  if (!relevant) return;
  window.__pixelworldLiveRefreshActive = true;
  async function get(path) {
    const response = await fetch(root + path + '?t=' + Math.floor(Date.now()/10000), {cache:'no-store'});
    if (!response.ok) throw Error('HTTP ' + response.status);
    return response.json();
  }
  function href(suite,model,track,caseId,attempt) {
    return '/pixelworld/live.html?' + new URLSearchParams({suite,model,track,case:caseId,attempt});
  }
  function asset(path) { return path ? root + path : ''; }
  function video(v) {
    const data = {...v,pixels:asset(v.pixels),poster:asset(v.poster)};
    return `<div class="player" data-video='${esc(JSON.stringify(data))}'><div class="player-frame"><canvas></canvas><button class="play-overlay">▶</button></div><div class="controls"><button class="play">▶ 播放</button><button class="replay">↻ 重播</button><input class="seek" type="range" min="0" step="1" value="0"></div><p class="status">点击播放 · 保存的 RGB 候选</p></div>`;
  }
  function initializePlayers() {
    window.__benchPlayers = [];
    document.querySelectorAll('.player').forEach(node => {
      const p = new PixelPlayer(node,JSON.parse(node.dataset.video));
      node.dataset.state = 'idle';
      const start = p.start.bind(p), pause = p.pause.bind(p);
      p.start = () => {node.dataset.state='playing'; start();};
      p.pause = () => {node.dataset.state='paused'; pause();};
      node.querySelector('canvas').onclick=()=>p.toggle();
      const overlay=node.querySelector('.play-overlay'); if(overlay) overlay.onclick=()=>p.toggle();
      window.__benchPlayers.push(p);
    });
    document.querySelectorAll('video').forEach(node=>{node.onplay=()=>node.dataset.state='playing';node.onpause=()=>node.dataset.state='paused';});
  }
  let fingerprint = '';
  function renderCase(d) {
    const mark = JSON.stringify(d);
    const banner = `<span class="badge">实时记录</span> ${esc(d.delivery_status==='stale'?'接口/系统中断 · stale':d.status)} · ${Number(d.output_tokens || 0).toLocaleString()} 输出 token · ${d.candidates.length} 保存候选`;
    const existing=document.querySelector('#live-status');
    if (existing) existing.innerHTML=banner;
    if (mark===fingerprint || document.querySelector('[data-state=playing]')) return;
    fingerprint=mark;
    (window.__benchPlayers || []).forEach(p=>p.pause());
    const latest=d.candidates.at(-1), spec=d.spec;
    let body=`<a class="back" href="/pixelworld/index.html">← PixelWorld 总览</a><section class="hero"><p class="eyebrow">CODING AGENTS AS PIXEL WORLD MODELS</p><h1>${esc(label(d.model_key))} · ${esc(d.case_id)}</h1></section><div id="live-status" class="card">${banner}<p class="note">${esc(d.track==='text'?'Text':'Vision')} · Attempt ${d.attempt} · ${spec.width}×${spec.height} · ${spec.fps} FPS · ${spec.frames} 帧。保存候选与最终有效提交分别记录。</p></div>`;
    body+=`<div class="case-layout" id="video"><div>${latest?video(latest):'<div class="box">尚未保存候选视频；下方展示当前工具记录。</div>'}</div><aside class="card"><h3>任务输入</h3><p>${esc(d.prompt)}</p>${d.first_frame?`<img class="inspection" src="${asset(d.first_frame)}" alt="实际输入首帧">`:''}</aside></div>`;
    if(d.source_video)body+=`<section class="card"><h3>任务输入视频</h3><video controls preload="metadata" src="${asset(d.source_video)}" style="width:100%;max-height:480px"></video></section>`;
    if(d.status==='failed') body+=`<div class="card"><h3>终止记录</h3><p>${d.budget_exhausted?'输出 token 预算耗尽':'查看下方实际终止事件与工具输出'}</p><pre>${esc(JSON.stringify(d.validation,null,2))}</pre></div>`;
    body+='<section id="candidates"><h2>每轮保存的候选</h2>';
    for (const [i,v] of d.candidates.entries()) body+=`<details class="candidate" ${i===0?'open':''}><summary>${esc(v.label)} · ${esc(v.utc || '')}</summary><div class="candidate-content">${video(v)}${v.inspection?`<img class="inspection" src="${asset(v.inspection)}" alt="本轮时间采样检查图">`:''}${v.transition_check?`<img class="inspection" src="${asset(v.transition_check)}" alt="首帧到后续帧的过渡">`:''}<details><summary>本轮生成代码</summary><pre>${esc(v.code || '')}</pre></details></div></details>`;
    body+='</section><section id="trace"><h2>实际工具与返回记录</h2>';
    for(const [i,e] of d.events.entries()) body+=`<details ${i===d.events.length-1?'open':''}><summary>${i+1}. ${esc(e.kind)} · ${esc(e.utc || '')}${e.exit_code!=null?' · exit '+e.exit_code:''}</summary>${e.command?`<h4>执行命令</h4><pre>${esc(e.command)}</pre>`:''}${(e.images || []).map(path=>`<img loading="lazy" class="inspection" src="${asset(path)}" alt="视觉工具实际返回的图片">`).join('')}<pre>${esc(e.aggregated_output || e.text || '')}</pre></details>`;
    body+='</section><p class="note" id="live-poll-time"></p>';
    document.querySelector('main').innerHTML=body;
    initializePlayers();
  }
  function renderGroup(d) {
    const heading=document.querySelector('main .hero h1');if(heading)heading.textContent=label(d.model_key)+' · '+(d.track==='text'?'Text':'Vision');
    let box=document.querySelector('#live-group-status');
    if(!box){box=document.createElement('div');box.id='live-group-status';box.className='card';document.querySelector('main .hero')?.after(box);}
    const c=d.counts;
    box.innerHTML=`<span class="badge">实时进度</span> ${c.complete || 0}/${d.cases_total || 0} 有效交付 · ${c.running || 0} 运行中 · ${c.pending || 0} 待生成 · ${c.exhausted || 0} 未交付<p class="note">状态：${esc(d.updated_utc)}。保存候选可以直接播放，无需等待 agent 结束。</p>`;
    box.innerHTML+=`<p class="note">平均耗时 ${d.mean_duration_seconds!=null?(d.mean_duration_seconds/60).toFixed(1)+' 分钟':'—'} · 已加载 ${d.token_mean_cases || 0} 条成功记录，平均输出 ${d.mean_output_tokens_cached!=null?Math.round(d.mean_output_tokens_cached).toLocaleString()+' token':'—'}</p>`;
    const old=document.querySelector('main > p');
    if(old?.textContent.includes('详情已同步')) old.textContent=`${c.complete || 0} 个有效交付 · 当前候选和工具记录自动更新。`;
    let grid=document.querySelector('.video-grid');
    if(!grid){grid=document.createElement('div');grid.className='video-grid';box.after(grid);}
    for(const [caseId,history] of Object.entries(d.cases)) {
      const valid=history.filter(a=>a.status==='complete');
      const selected=valid.length?valid.sort((a,b)=>a.attempt-b.attempt)[0]:history.toSorted((a,b)=>b.attempt-a.attempt)[0];
      const url=href(d.suite,d.model_key,d.track,caseId,selected.attempt);
      const markup=`<h3>${esc(caseId)}</h3><span class="pill">${esc(selected.status)}</span>${selected.poster?`<a href="${url}"><img loading="lazy" class="inspection" src="${asset(selected.poster)}"></a>`:''}<p>${Number(selected.output_tokens || 0).toLocaleString()} 输出 token · ${selected.candidate_count} 保存候选</p><a href="${url}">视频、逐轮候选与实际工具记录 →</a><details><summary>全部 ${history.length} 次运行记录</summary>${history.toSorted((a,b)=>a.attempt-b.attempt).map(a=>`<p><a href="${href(d.suite,d.model_key,d.track,caseId,a.attempt)}">Attempt ${a.attempt}: ${esc(a.status)} · ${a.candidate_count} 候选</a></p>`).join('')}</details>`;
      let card=[...grid.querySelectorAll('article')].find(a=>a.querySelector('h3')?.textContent.trim()===caseId);
      if(!card){card=document.createElement('article');card.className='card';grid.prepend(card);}
      if(card.dataset.liveMark!==JSON.stringify(selected)){card.innerHTML=markup;card.dataset.liveMark=JSON.stringify(selected);}
    }
  }
  async function renderPhygenGallery(catalogue) {
    const groups=catalogue.groups.filter(g=>g.suite.startsWith('phygen_'));
    const data=await Promise.all(groups.map(g=>get(g.path)));
    let box=document.querySelector('#phygen-live-cases');
    if(!box){box=document.createElement('section');box.id='phygen-live-cases';const main=document.querySelector('main');main.querySelector('footer')?.before(box);if(!box.isConnected)main.append(box);}
    const condition=g=>(g.suite.includes('i2v')?'i2v':'t2v')+'-'+(g.track==='text'?'text':'vision');
    const choices=[['t2v-text','T2V · Text'],['t2v-vision','T2V · Vision'],['i2v-text','I2V · Text'],['i2v-vision','I2V · Vision']];
    let body='<h2>模型 × 四个条件</h2><div class="scroll"><table><tr><th>模型</th>'+choices.map(c=>'<th>'+c[1]+'</th>').join('')+'</tr>';
    for(const model of [...new Set(data.map(g=>g.model_key))]){body+='<tr><td>'+esc(label(model))+'</td>';for(const [id] of choices){const g=data.find(g=>g.model_key===model&&condition(g)===id);body+=g?`<td><strong>${g.counts.complete || 0}/${g.cases_total}</strong> 有效交付<br>${g.counts.running || 0} 运行中<br><a href="/pixelworld/live.html?suite=${g.suite}&model=${g.model_key}&track=${g.track}">查看这一条件 →</a></td>`:'<td>—</td>';}body+='</tr>';}
    body+='</table></div><h2>样本与生成过程</h2><p class="note">有效提交、运行中状态及已保存候选分别显示；点击样本可播放每轮视频并查看实际工具记录。</p><p>'+[['all','全部'],...choices].map(([id,name])=>`<button class="button" data-phygen-filter="${id}">${name}</button>`).join(' ')+'</p><div class="video-grid">';
    for(const g of data) for(const [caseId,history] of Object.entries(g.cases)) {
      if(window.__phygenLiveFilter&&window.__phygenLiveFilter!=='all'&&condition(g)!==window.__phygenLiveFilter)continue;
      const valid=history.filter(a=>a.status==='complete');
      const s=valid.length?valid.sort((a,b)=>a.attempt-b.attempt)[0]:[...history].sort((a,b)=>b.attempt-a.attempt)[0];
      const url=href(g.suite,g.model_key,g.track,caseId,s.attempt);
      body+=`<article class="card"><span class="badge">${g.suite.includes('i2v')?'I2V · Qwen 首帧':'T2V'} · ${g.track==='text'?'Text':'Vision'}</span><h3>${esc(label(g.model_key))} · ${esc(caseId)}</h3><span class="pill">${esc(s.status)}</span>${s.poster?`<a href="${url}"><img loading="lazy" class="inspection" src="${asset(s.poster)}" alt="当前保存的候选首帧"></a>`:''}<p>${Number(s.output_tokens || 0).toLocaleString()} 输出 token · ${s.candidate_count} 保存候选</p><a href="${url}">播放视频与逐轮生成过程 →</a></article>`;
    }
    body+='</div>';
    if(box.innerHTML!==body)box.innerHTML=body;
    box.querySelectorAll('[data-phygen-filter]').forEach(button=>button.onclick=()=>{window.__phygenLiveFilter=button.dataset.phygenFilter;renderPhygenGallery(catalogue);});
  }
  function summary(catalogue) {
    const groups=catalogue.groups;
    if(location.pathname.endsWith('/physics_iq_512w24fps.html')) {
      const selected=groups.filter(g=>g.suite==='physics_iq_512w24fps_gpt_native');
      const table=document.querySelector('table.matrix');
      if(table){let body='<tr><th>Model</th><th>Text</th><th>Vision</th></tr>';for(const model of [...new Set(selected.map(g=>g.model_key))]){body+=`<tr><td>${esc(label(model))}</td>`;for(const track of ['text','vision-agent']){const g=selected.find(x=>x.model_key===model&&x.track===track);const c=g?.counts || {};body+=`<td class="run-cell"><span class="badge">${c.running?'ACTIVE':'待调度/完成'}</span> <strong>${c.complete || 0}/${g?.cases_total || 198}</strong><p>${c.running || 0} 运行中 · ${c.pending || 0} 待生成</p><a href="/pixelworld/physics_iq_512w24fps_gpt_native/${model}/${track}/index.html">实时视频与候选 →</a></td>`;}body+='</tr>';}table.innerHTML=body;}
    }
    if(location.pathname.endsWith('/phygen_pixelspace.html')) {
      const table=document.querySelector('table');
      const selected=groups.filter(g=>g.suite.startsWith('phygen_'));
      if(table && selected.length) table.innerHTML='<tr><th>条件</th><th>模型</th><th>Track</th><th>有效视频</th><th>运行中</th><th>待生成</th><th>查看</th></tr>'+selected.map(g=>`<tr><td>${g.suite.includes('i2v')?'I2V · Qwen 首帧':'T2V'}</td><td>${esc(label(g.model_key))}</td><td>${g.track==='text'?'Text':'Vision'}</td><td>${g.counts.complete || 0}/${g.cases_total}</td><td>${g.counts.running || 0}</td><td>${g.counts.pending || 0}</td><td><a href="/pixelworld/live.html?suite=${g.suite}&model=${g.model_key}&track=${g.track}">实时视频与候选 →</a></td></tr>`).join('');
    }
    const routes={'Physics-IQ 512w24fps':['physics_iq_512w24fps_gpt_native'],'Physics-IQ Verified':['physics_iq','physics_iq_gpt_native_v2','physics_iq_seed21_native_v2'],'RoboJudge shared-50':['robojudge','robojudge_seed21_native_v2'],'PCVE-RigidBench · 必跑':['pcve_smoke'],'PhyGenBench · T2V + I2V':groups.filter(g=>g.suite.startsWith('phygen_')).map(g=>g.suite)};
    document.querySelectorAll('article.card.feature').forEach(card=>{const scopes=routes[card.querySelector('h3')?.textContent];if(!scopes)return;const selected=groups.filter(g=>scopes.includes(g.suite));if(!selected.length)return;const total=selected.reduce((a,g)=>a+(g.cases_total || 0),0),count=name=>selected.reduce((a,g)=>a+(g.counts[name] || 0),0);const badge=card.querySelector('.badge');if(badge)badge.textContent=count('running')?'running · '+count('running')+' active':'进度已更新';let facts=card.querySelector('.facts');if(!facts){facts=document.createElement('div');facts.className='facts';card.querySelector('a')?.before(facts);}facts.innerHTML=`<div><strong>${count('complete')} / ${total}</strong>有效视频</div><div><strong>${count('running')}</strong>运行中</div><div><strong>${count('pending')}</strong>待生成</div>`;});
  }
  async function poll() {
    try {
      if(context){const group=await get(`${context.suite}/${context.model}/${context.track}/index.json`);if(context.case){const attempt=(group.cases[context.case] || []).find(a=>String(a.attempt)===String(context.attempt));if(attempt){const detail=await get(attempt.detail);if(attempt.status==='stale')detail.delivery_status='stale';renderCase(detail);}}else renderGroup(group);}
      else {const catalogue=await get('catalogue.json');summary(catalogue);if(phygenGallery)await renderPhygenGallery(catalogue);}
      let stamp=document.querySelector('#live-poll-time');if(!stamp){stamp=document.createElement('p');stamp.id='live-poll-time';stamp.className='note';document.querySelector('main').append(stamp);}stamp.textContent='最近读取实时记录：'+new Date().toLocaleString()+' · 每 10 秒自动检查';
    } catch(e) {const node=document.querySelector('#live-poll-time');if(node)node.textContent='实时记录暂未读到：'+e.message+'；保留已显示内容并自动重试。';}
    setTimeout(poll,10000);
  }
  poll();
})();
