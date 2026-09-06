const $ = (s, root=document) => root.querySelector(s);
const $$ = (s, root=document) => [...root.querySelectorAll(s)];
let state = { project: null, images: [], jobs: new Map(), polls: new Map() };
let voicePreviewState = { index: null, end: 0 };

function show(view){ ['welcome','createView','studioView'].forEach(id=>$('#'+id).classList.toggle('hidden',id!==view)); }
function toast(message,error=false){ const box=$('#toast'); box.textContent=message; box.className='toast'+(error?' error':''); setTimeout(()=>box.classList.add('hidden'),3500); }
async function api(url,options={}){ const response=await fetch(url,options); let data={}; try{data=await response.json()}catch{} if(!response.ok)throw new Error(data.error||`Lỗi HTTP ${response.status}`); return data; }
const esc=s=>String(s??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));

async function refreshProjects(){
  const projects=await api('/api/projects');
  $('#projectList').innerHTML=projects.length?projects.map(p=>`<div class="project-item ${state.project?.id===p.id?'active':''}" data-id="${p.id}"><i>✎</i><div><strong>${esc(p.name)}</strong><small>${p.scenes.length} cảnh · ${esc(p.settings.aspect)}</small></div></div>`).join(''):'<small>Chưa có dự án</small>';
  $$('.project-item').forEach(item=>item.onclick=()=>openProject(item.dataset.id));
}
function createScreen(){ state.project=null;history.replaceState(null,'',location.pathname);state.images=[];$('#imageCount').textContent='Chưa chọn ảnh';$('#createView').reset();show('createView');refreshProjects(); }

function addImages(files){
  const allowed=[...files].filter(f=>f.type.startsWith('image/')||/\.(png|jpe?g|webp|bmp|tiff?)$/i.test(f.name));
  state.images=allowed;
  $('#imageCount').textContent=allowed.length?`${allowed.length} ảnh đã chọn`:'Không có ảnh hợp lệ';
}

async function createProject(event){
  event.preventDefault();
  if(!state.images.length)return toast('Hãy chọn ít nhất một ảnh.',true);
  const form=new FormData();
  form.append('name',$('#projectName').value);
  form.append('script',$('#scriptInput').value);
  state.images.forEach(file=>form.append('images',file,file.webkitRelativePath||file.name));
  const sf=$('#scriptFile').files[0],vf=$('#voiceInput').files[0],mf=$('#musicInput').files[0];
  if(sf)form.append('script_file',sf); if(vf)form.append('voice',vf); if(mf)form.append('music',mf);
  progressOpen('Đang tạo dự án','Đang sao chép và phân tích tài nguyên…',20);
  try{const p=await api('/api/projects',{method:'POST',body:form});progressClose();await openProject(p.id);toast('Đã tạo và tự căn chỉnh dự án.');}
  catch(error){progressClose();toast(error.message,true);}
}

async function openProject(id){
  try{state.project=await api(`/api/projects/${id}`);history.replaceState(null,'',`?project=${encodeURIComponent(id)}`);renderStudio();show('studioView');refreshProjects();}
  catch(error){toast(error.message,true);}
}

function renderStudio(){
  const p=state.project,s=p.settings,a=p.analysis||{};
  $('#studioTitle').textContent=p.name;
  $('#studioMeta').textContent=`${p.scenes.length} cảnh · cập nhật ${p.updated_at.replace('T',' ')}`;
  $('#aspect').value=s.aspect;$('#resolution').value=s.resolution;$('#fps').value=s.fps;$('#inkColor').value=s.ink_color;
  $('#inkPath').value=s.ink_path;$('#colorFill').value=s.color_fill;$('#voiceVolume').value=s.voice_volume;$('#musicVolume').value=s.music_volume;
  $('#channelName').value=s.channel_name;$('#subtitles').checked=s.subtitles;$('#studioScript').value=p.script;
  $('#subtitlePosition').value=s.subtitle_position||'top';$('#subtitleColor').value=s.subtitle_color||'#FFFFFF';
  $('#subtitleFont').value=s.subtitle_font||'Microsoft JhengHei';$('#subtitleFontSize').value=s.subtitle_font_size||54;
  $('#timingMode').value=s.timing_mode||'voice';$('#manualDuration').value=s.manual_scene_duration||6;syncTimingMode();
  const voice=p.audio.voice||'Chưa chọn',music=p.audio.music||'Chưa chọn';
  $('#assetSummary').innerHTML=`<div class="asset-row"><span>▧ ${p.scenes.length} ảnh đã sắp xếp</span><b>✓ SẴN SÀNG</b></div><div class="asset-row"><span title="${esc(voice)}">♬ Voice: ${esc(voice)}</span><button type="button" class="asset-button" data-audio="voice">${p.audio.voice?'Thay file':'Chọn voice'}</button></div><div class="asset-row"><span title="${esc(music)}">♫ Nhạc: ${esc(music)}</span><button type="button" class="asset-button" data-audio="music">${p.audio.music?'Thay file':'Chọn nhạc'}</button></div><div class="asset-row"><span>ID: ${esc(p.id)}</span><b>LOCAL</b></div>`;
  $$('.asset-button').forEach(button=>button.onclick=()=>$('#studio'+(button.dataset.audio==='voice'?'Voice':'Music')+'Input').click());
  showVolume();
  $('#analysisInfo').textContent=a.mode==='voice'?`Đã căn theo voice ${Number(a.voice_duration).toFixed(2)} giây.`:`Thời lượng thủ công ${Number(a.total_duration||0).toFixed(2)} giây.`;
  const completed=p.scenes.filter(scene=>scene.rendered).length;
  $('#sceneSummary').textContent=`${p.scenes.length} cảnh · ${completed} đã dựng · ${p.scenes.length-completed} chờ dựng · tự sắp xếp theo số.`;
  $('#sceneGrid').innerHTML=p.scenes.map(scene=>sceneCard(scene,p)).join('');
  $$('.render-scene').forEach(button=>button.onclick=()=>startScene(Number(button.dataset.index)));
  $$('.preview-voice').forEach(button=>button.onclick=()=>previewSceneVoice(Number(button.dataset.index)).catch(error=>toast(error.message||'Không phát được voice.',true)));
  $$('.cut-voice-here').forEach(button=>button.onclick=()=>cutVoiceAtCurrentPosition(Number(button.dataset.index)));
  $$('.apply-voice-trim').forEach(button=>button.onclick=()=>applyVoiceTrim(Number(button.dataset.index)));
  $$('.voice-trim-start,.voice-trim-end').forEach(input=>input.oninput=()=>updateVoiceTrimSummary(Number(input.closest('.scene-card').dataset.index)));
  restoreActiveProgress();
  $('#outputPanel').classList.toggle('hidden',!p.final_video);
  $('#downloadFinal').href=`/api/projects/${p.id}/download`;
}

function sceneCard(scene,project){
  const id=project.id,hasVoice=project.audio.voice&&scene.voice_start!=null&&scene.voice_end!=null;
  const videoVersion=encodeURIComponent(project.updated_at||'');
  const sourceDuration=hasVoice?Math.max(.5,Number(scene.voice_end)-Number(scene.voice_start)):0;
  const trimStart=Number(scene.voice_trim_start||0),trimEnd=Number(scene.voice_trim_end||0);
  const voiceEditor=hasVoice?`<div class="voice-editor"><div class="voice-editor-head"><strong>♬ Voice phân cảnh</strong><span class="voice-remaining">Còn ${(sourceDuration-trimStart-trimEnd).toFixed(2)} giây</span></div><div class="voice-actions"><button type="button" class="ghost preview-voice" data-index="${scene.index}">▶ Nghe đoạn voice</button><button type="button" class="ghost cut-voice-here" data-index="${scene.index}">✂ Cắt cuối tại đây</button></div><div class="voice-trim-grid"><label>Cắt đầu (giây)<input class="voice-trim-start" type="number" min="0" max="${Math.max(0,sourceDuration-.5).toFixed(3)}" step=".05" value="${trimStart}"></label><label>Cắt cuối (giây)<input class="voice-trim-end" type="number" min="0" max="${Math.max(0,sourceDuration-.5).toFixed(3)}" step=".05" value="${trimEnd}"></label></div>${scene.index===project.scenes.length?'<small class="trim-hint">Nghe đến trước câu thông báo AI, rồi bấm “Cắt cuối tại đây”.</small>':''}<button type="button" class="secondary apply-voice-trim" data-index="${scene.index}">Áp dụng cắt voice</button></div>`:'';
  return `<article class="scene-card" data-index="${scene.index}">
    <div class="scene-media" id="media-${scene.index}">${scene.rendered?`<video controls preload="metadata" poster="/api/projects/${id}/images/${scene.index}" src="/api/projects/${id}/scenes/${scene.index}/video?v=${videoVersion}"></video>`:`<img loading="lazy" src="/api/projects/${id}/images/${scene.index}" alt="Cảnh ${scene.index}">`}<span class="scene-no">CẢNH ${String(scene.index).padStart(2,'0')}</span><span class="scene-status ${scene.rendered?'done':'waiting'}">${scene.rendered?'✓ ĐÃ DỰNG':'⌛ CHỜ DỰNG'}</span><div class="scene-progress hidden"><strong>Đang chờ dựng…</strong><div class="scene-progress-track"><i></i></div><span>0%</span></div></div>
    <div class="scene-body"><div class="scene-name"><strong>${esc(scene.image)}</strong><small title="${esc(scene.source_name)}">${esc(scene.source_name)}</small></div>
      <div class="scene-controls"><label>Thời lượng (giây)<input class="scene-duration" type="number" min=".8" max="600" step=".1" value="${scene.duration}"></label><label>Tốc độ vẽ<select class="scene-speed">${[.5,.75,1,1.25,1.5,2,3].map(x=>`<option value="${x}" ${x===scene.speed?'selected':''}>${x}×</option>`).join('')}</select></label></div>
      <textarea class="scene-text" rows="3" placeholder="Phụ đề cho cảnh">${esc(scene.text)}</textarea>${voiceEditor}
      <div class="scene-actions"><button class="secondary render-scene" data-index="${scene.index}">${scene.rendered?'↻ Dựng lại cảnh':'▶ Dựng cảnh'}</button></div>
    </div></article>`;
}

function showVolume(){ $('#voiceOut').textContent=`${Math.round($('#voiceVolume').value*100)}%`;$('#musicOut').textContent=`${Math.round($('#musicVolume').value*100)}%`; }
function syncTimingMode(){const manual=$('#timingMode').value==='manual';$('#manualDuration').disabled=!manual;$('#manualDuration').parentElement.classList.toggle('disabled',!manual)}
function voiceBounds(index){
  const scene=state.project.scenes.find(item=>item.index===index),card=$(`.scene-card[data-index="${index}"]`);if(!scene||!card||scene.voice_start==null)return null;
  const sourceStart=Number(scene.voice_start),sourceEnd=Number(scene.voice_end),base=Math.max(.5,sourceEnd-sourceStart);
  const trimStart=Math.max(0,Math.min(base-.5,Number($('.voice-trim-start',card)?.value||0)));
  const trimEnd=Math.max(0,Math.min(base-trimStart-.5,Number($('.voice-trim-end',card)?.value||0)));
  return {scene,card,start:sourceStart+trimStart,end:sourceEnd-trimEnd,trimStart,trimEnd,remaining:base-trimStart-trimEnd};
}
function updateVoiceTrimSummary(index){const bounds=voiceBounds(index);if(!bounds)return;$('.voice-remaining',bounds.card).textContent=`Còn ${bounds.remaining.toFixed(2)} giây`;$('.scene-duration',bounds.card).value=bounds.remaining.toFixed(3)}
function stopVoicePreview(){const player=$('#voicePreview');player.pause();$$('.preview-voice').forEach(button=>button.textContent='▶ Nghe đoạn voice');voicePreviewState={index:null,end:0}}
async function previewSceneVoice(index){
  const bounds=voiceBounds(index),player=$('#voicePreview');if(!bounds)return toast('Phân cảnh này chưa có đoạn voice.',true);
  if(voicePreviewState.index===index&&!player.paused){stopVoicePreview();return}
  if(player.dataset.project!==state.project.id){player.src=`/api/projects/${state.project.id}/voice`;player.dataset.project=state.project.id;player.load();if(player.readyState<1)await new Promise((resolve,reject)=>{player.addEventListener('loadedmetadata',resolve,{once:true});player.addEventListener('error',reject,{once:true})})}
  stopVoicePreview();voicePreviewState={index,end:bounds.end};player.currentTime=bounds.start;await player.play();const button=$(`.preview-voice[data-index="${index}"]`);if(button)button.textContent='■ Dừng nghe';
}
function cutVoiceAtCurrentPosition(index){
  const player=$('#voicePreview'),bounds=voiceBounds(index);if(!bounds||voicePreviewState.index!==index)return toast('Hãy bấm “Nghe đoạn voice” trước, rồi cắt tại vị trí mong muốn.',true);
  const trim=Math.max(0,Number(bounds.scene.voice_end)-player.currentTime),input=$('.voice-trim-end',bounds.card);input.value=trim.toFixed(3);updateVoiceTrimSummary(index);stopVoicePreview();toast('Đã đặt điểm cắt. Bấm “Áp dụng cắt voice” để lưu.')
}
async function applyVoiceTrim(index){try{stopVoicePreview();await save(false);renderStudio();toast(`Đã cắt voice cảnh ${index}. Hãy dựng lại cảnh này.`)}catch(e){toast(e.message,true)}}
$('#voicePreview').ontimeupdate=()=>{const player=$('#voicePreview');if(voicePreviewState.index!=null&&player.currentTime>=voicePreviewState.end)stopVoicePreview()};
function payload(){
  return {script:$('#studioScript').value,settings:{aspect:$('#aspect').value,resolution:$('#resolution').value,fps:Number($('#fps').value),ink_color:$('#inkColor').value,ink_path:$('#inkPath').value,color_fill:$('#colorFill').value,voice_volume:Number($('#voiceVolume').value),music_volume:Number($('#musicVolume').value),channel_name:$('#channelName').value,subtitles:$('#subtitles').checked,subtitle_position:$('#subtitlePosition').value,subtitle_color:$('#subtitleColor').value,subtitle_font:$('#subtitleFont').value,subtitle_font_size:Number($('#subtitleFontSize').value),timing_mode:$('#timingMode').value,manual_scene_duration:Number($('#manualDuration').value)},scenes:$$('.scene-card').map(card=>({index:Number(card.dataset.index),duration:Number($('.scene-duration',card).value),speed:Number($('.scene-speed',card).value),text:$('.scene-text',card).value,voice_trim_start:Number($('.voice-trim-start',card)?.value||0),voice_trim_end:Number($('.voice-trim-end',card)?.value||0)}))};
}
async function save(showToast=true){ if(!state.project)return;state.project=await api(`/api/projects/${state.project.id}`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload())});if(showToast)toast('Đã lưu thay đổi.');return state.project; }
async function reanalyze(){try{await save(false);state.project=await api(`/api/projects/${state.project.id}/analyze`,{method:'POST'});renderStudio();toast('Đã căn lại kịch bản theo voice.');}catch(e){toast(e.message,true)}}
async function uploadProjectAudio(kind,file){if(!file||!state.project)return;progressOpen(kind==='voice'?'Đang cập nhật voice':'Đang cập nhật nhạc','Đang lưu cấu hình và đọc file âm thanh…',25);try{await save(false);const autoAlign=state.project.settings.timing_mode==='voice';const form=new FormData();form.append('file',file);state.project=await api(`/api/projects/${state.project.id}/audio/${kind}`,{method:'POST',body:form});progressClose();renderStudio();toast(kind==='voice'?(autoAlign?'Đã cập nhật voice và căn lại thời lượng.':'Đã cập nhật voice; thời lượng thủ công được giữ nguyên.'):'Đã cập nhật nhạc nền. Chỉ cần ghép lại video.')}catch(e){progressClose();toast(e.message,true)}}

function progressOpen(title,message,value=0){$('#progressTitle').textContent=title;$('#progressMessage').textContent=message;$('#progressBar').style.width=value+'%';$('#progressValue').textContent=Math.round(value)+'%';$('#closeProgress').classList.add('hidden');$('#progressOverlay').classList.remove('hidden');}
function progressClose(){$('#progressOverlay').classList.add('hidden');}
function setSceneProgress(index,value,message='Đang dựng…'){
  const card=$(`.scene-card[data-index="${index}"]`);if(!card)return;
  const panel=$('.scene-progress',card),percent=Math.max(0,Math.min(100,Number(value)||0));
  panel.classList.remove('hidden');$('.scene-progress-track i',panel).style.width=percent+'%';$('span',panel).textContent=`${Math.round(percent)}%`;$('strong',panel).textContent=message;
  card.classList.add('rendering');$$('button,input,select,textarea',card).forEach(control=>control.disabled=true);const button=$('.render-scene',card);if(button)button.textContent='✎ Đang dựng…'
}
function restoreActiveProgress(){for(const context of state.jobs.values()){if(context.projectId!==state.project?.id)continue;for(const index of context.sceneIndexes||[])setSceneProgress(index,context.progress?.[index]||1,context.messages?.[index]||'Đang chờ dựng…')}}
async function refreshCurrentProject(){if(!state.project)return;const id=state.project.id,project=await api(`/api/projects/${id}`);if(state.project?.id===id){state.project=project;renderStudio()}}
async function watch(jobId,context={}){
  context={projectId:state.project.id,sceneIndexes:[],progress:{},messages:{},global:false,...context};state.jobs.set(jobId,context);
  const tick=async()=>{try{
    const job=await api(`/api/jobs/${jobId}`),details=job.details||{},sceneProgress=details.scene_progress||{};
    for(const [key,value] of Object.entries(sceneProgress)){const index=Number(key);context.progress[index]=value;context.messages[index]=`Đang dựng cảnh ${index}`;if(context.projectId===state.project?.id)setSceneProgress(index,value,context.messages[index])}
    if(context.global){$('#progressMessage').textContent=job.message;$('#progressBar').style.width=job.progress+'%';$('#progressValue').textContent=Math.round(job.progress)+'%'}
    if(job.state==='done'){
      state.jobs.delete(jobId);state.polls.delete(jobId);if(context.global)progressClose();await refreshCurrentProject();toast(context.sceneIndexes.length>1?'Đã dựng và ghép toàn bộ video.':'Tác vụ đã hoàn tất.');return;
    }
    if(job.state==='error'){
      state.jobs.delete(jobId);state.polls.delete(jobId);if(context.global)progressClose();await refreshCurrentProject();toast(job.error||'Dựng thất bại',true);return;
    }
    state.polls.set(jobId,setTimeout(tick,900));
  }catch(e){state.jobs.delete(jobId);state.polls.delete(jobId);if(context.global)progressClose();toast(e.message,true)}};
  await tick();
}
async function startScene(index){
  if([...state.jobs.values()].some(job=>job.projectId===state.project.id&&job.sceneIndexes?.includes(index)))return toast(`Cảnh ${index} đang được dựng.`);
  try{await save(false);setSceneProgress(index,1,'Đang đưa vào hàng đợi…');const r=await api(`/api/projects/${state.project.id}/render/scenes/${index}`,{method:'POST'});watch(r.job_id,{sceneIndexes:[index]})}catch(e){await refreshCurrentProject();toast(e.message,true)}
}
async function startAll(){
  if([...state.jobs.values()].some(job=>job.projectId===state.project.id&&job.sceneIndexes?.length))return toast('Đang có cảnh được dựng. Hãy chờ các cảnh đó hoàn tất.',true);
  try{await save(false);const indexes=state.project.scenes.filter(scene=>!scene.rendered).map(scene=>scene.index);if(!indexes.length)return mergeOnly();indexes.forEach(index=>setSceneProgress(index,1,'Đang chờ dựng song song…'));const r=await api(`/api/projects/${state.project.id}/render/all`,{method:'POST'});watch(r.job_id,{sceneIndexes:indexes})}catch(e){await refreshCurrentProject();toast(e.message,true)}
}
async function mergeOnly(){if([...state.jobs.values()].some(job=>job.projectId===state.project.id&&job.sceneIndexes?.length))return toast('Hãy chờ các cảnh đang dựng hoàn tất trước khi ghép.',true);try{await save(false);progressOpen('Đang ghép video','Bạn vẫn có thể tiếp tục chỉnh sửa trong lúc ghép…');const r=await api(`/api/projects/${state.project.id}/merge`,{method:'POST'});watch(r.job_id,{global:true})}catch(e){progressClose();toast(e.message,true)}}
$('#newProject').onclick=$('#heroStart').onclick=createScreen;$('#cancelCreate').onclick=()=>show('welcome');$('#createView').onsubmit=createProject;
$('#pickImages').onclick=()=>$('#imagesInput').click();$('#pickFolder').onclick=()=>$('#folderInput').click();
$('#imagesInput').onchange=e=>addImages(e.target.files);$('#folderInput').onchange=e=>addImages(e.target.files);
$$('[data-pick]').forEach(button=>button.onclick=()=>$('#'+button.dataset.pick).click());
$('#voiceInput').onchange=e=>$('#voiceName').textContent=e.target.files[0]?.name||'Không bắt buộc';$('#musicInput').onchange=e=>$('#musicName').textContent=e.target.files[0]?.name||'Không bắt buộc';
$('#studioVoiceInput').onchange=e=>{uploadProjectAudio('voice',e.target.files[0]);e.target.value=''};$('#studioMusicInput').onchange=e=>{uploadProjectAudio('music',e.target.files[0]);e.target.value=''};
$('#scriptFile').onchange=async e=>{const file=e.target.files[0];if(file)$('#scriptInput').value=await file.text()};
const zone=$('#imageZone');['dragenter','dragover'].forEach(name=>zone.addEventListener(name,e=>{e.preventDefault();zone.classList.add('drag')}));['dragleave','drop'].forEach(name=>zone.addEventListener(name,e=>{e.preventDefault();zone.classList.remove('drag')}));zone.addEventListener('drop',e=>addImages(e.dataTransfer.files));
$('#voiceVolume').oninput=$('#musicVolume').oninput=showVolume;$('#timingMode').onchange=syncTimingMode;$('#saveProject').onclick=()=>save();$('#reanalyze').onclick=reanalyze;$('#renderAll').onclick=startAll;$('#mergeOnly').onclick=mergeOnly;$('#closeProgress').onclick=progressClose;
function applyTheme(){const dark=document.body.classList.contains('dark');$('#themeToggle').textContent=dark?'☀ Giao diện sáng':'◐ Giao diện tối'}
const savedTheme=localStorage.getItem('whiteboard-theme');if(savedTheme==='light')document.body.classList.remove('dark');applyTheme();$('#themeToggle').onclick=()=>{document.body.classList.toggle('dark');localStorage.setItem('whiteboard-theme',document.body.classList.contains('dark')?'dark':'light');applyTheme()};
api('/api/health').then(()=>{$('#serverText').textContent='Server local đã kết nối'}).catch(()=>{$('#serverText').textContent='Mất kết nối server'});
refreshProjects().then(()=>{const id=new URLSearchParams(location.search).get('project');if(id)openProject(id)}).catch(e=>toast(e.message,true));
