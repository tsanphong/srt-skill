const $ = (s, root=document) => root.querySelector(s);
const $$ = (s, root=document) => [...root.querySelectorAll(s)];
let state = { project: null, images: [], poll: null };

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
  $('#timingMode').value=s.timing_mode||'voice';$('#manualDuration').value=s.manual_scene_duration||6;syncTimingMode();
  const voice=p.audio.voice||'Chưa chọn',music=p.audio.music||'Chưa chọn';
  $('#assetSummary').innerHTML=`<div class="asset-row"><span>▧ ${p.scenes.length} ảnh đã sắp xếp</span><b>✓ SẴN SÀNG</b></div><div class="asset-row"><span title="${esc(voice)}">♬ Voice: ${esc(voice)}</span><button type="button" class="asset-button" data-audio="voice">${p.audio.voice?'Thay file':'Chọn voice'}</button></div><div class="asset-row"><span title="${esc(music)}">♫ Nhạc: ${esc(music)}</span><button type="button" class="asset-button" data-audio="music">${p.audio.music?'Thay file':'Chọn nhạc'}</button></div><div class="asset-row"><span>ID: ${esc(p.id)}</span><b>LOCAL</b></div>`;
  $$('.asset-button').forEach(button=>button.onclick=()=>$('#studio'+(button.dataset.audio==='voice'?'Voice':'Music')+'Input').click());
  showVolume();
  $('#analysisInfo').textContent=a.mode==='voice'?`Đã căn theo voice ${Number(a.voice_duration).toFixed(2)} giây.`:`Thời lượng thủ công ${Number(a.total_duration||0).toFixed(2)} giây.`;
  const completed=p.scenes.filter(scene=>scene.rendered).length;
  $('#sceneSummary').textContent=`${p.scenes.length} cảnh · ${completed} đã dựng · ${p.scenes.length-completed} chờ dựng · tự sắp xếp theo số.`;
  $('#sceneGrid').innerHTML=p.scenes.map(scene=>sceneCard(scene,p.id)).join('');
  $$('.render-scene').forEach(button=>button.onclick=()=>startScene(Number(button.dataset.index)));
  $('#outputPanel').classList.toggle('hidden',!p.final_video);
  $('#downloadFinal').href=`/api/projects/${p.id}/download`;
}

function sceneCard(scene,id){
  return `<article class="scene-card" data-index="${scene.index}">
    <div class="scene-media" id="media-${scene.index}">${scene.rendered?`<video controls preload="metadata" poster="/api/projects/${id}/images/${scene.index}" src="/api/projects/${id}/scenes/${scene.index}/video"></video>`:`<img loading="lazy" src="/api/projects/${id}/images/${scene.index}" alt="Cảnh ${scene.index}">`}<span class="scene-no">CẢNH ${String(scene.index).padStart(2,'0')}</span><span class="scene-status ${scene.rendered?'done':'waiting'}">${scene.rendered?'✓ ĐÃ DỰNG':'⌛ CHỜ DỰNG'}</span></div>
    <div class="scene-body"><div class="scene-name"><strong>${esc(scene.image)}</strong><small title="${esc(scene.source_name)}">${esc(scene.source_name)}</small></div>
      <div class="scene-controls"><label>Thời lượng (giây)<input class="scene-duration" type="number" min=".8" max="600" step=".1" value="${scene.duration}"></label><label>Tốc độ vẽ<select class="scene-speed">${[.5,.75,1,1.25,1.5,2,3].map(x=>`<option value="${x}" ${x===scene.speed?'selected':''}>${x}×</option>`).join('')}</select></label></div>
      <textarea class="scene-text" rows="3" placeholder="Phụ đề cho cảnh">${esc(scene.text)}</textarea>
      <div class="scene-actions"><button class="secondary render-scene" data-index="${scene.index}">${scene.rendered?'↻ Dựng lại cảnh':'▶ Dựng cảnh'}</button></div>
    </div></article>`;
}

function showVolume(){ $('#voiceOut').textContent=`${Math.round($('#voiceVolume').value*100)}%`;$('#musicOut').textContent=`${Math.round($('#musicVolume').value*100)}%`; }
function syncTimingMode(){const manual=$('#timingMode').value==='manual';$('#manualDuration').disabled=!manual;$('#manualDuration').parentElement.classList.toggle('disabled',!manual)}
function payload(){
  return {script:$('#studioScript').value,settings:{aspect:$('#aspect').value,resolution:$('#resolution').value,fps:Number($('#fps').value),ink_color:$('#inkColor').value,ink_path:$('#inkPath').value,color_fill:$('#colorFill').value,voice_volume:Number($('#voiceVolume').value),music_volume:Number($('#musicVolume').value),channel_name:$('#channelName').value,subtitles:$('#subtitles').checked,timing_mode:$('#timingMode').value,manual_scene_duration:Number($('#manualDuration').value)},scenes:$$('.scene-card').map(card=>({index:Number(card.dataset.index),duration:Number($('.scene-duration',card).value),speed:Number($('.scene-speed',card).value),text:$('.scene-text',card).value}))};
}
async function save(showToast=true){ if(!state.project)return;state.project=await api(`/api/projects/${state.project.id}`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload())});if(showToast)toast('Đã lưu thay đổi.');return state.project; }
async function reanalyze(){try{await save(false);state.project=await api(`/api/projects/${state.project.id}/analyze`,{method:'POST'});renderStudio();toast('Đã căn lại kịch bản theo voice.');}catch(e){toast(e.message,true)}}
async function uploadProjectAudio(kind,file){if(!file||!state.project)return;const autoAlign=state.project.settings.timing_mode==='voice';const form=new FormData();form.append('file',file);progressOpen(kind==='voice'?'Đang cập nhật voice':'Đang cập nhật nhạc','Đang đọc file âm thanh…',35);try{state.project=await api(`/api/projects/${state.project.id}/audio/${kind}`,{method:'POST',body:form});progressClose();renderStudio();toast(kind==='voice'?(autoAlign?'Đã cập nhật voice và căn lại thời lượng.':'Đã cập nhật voice; thời lượng thủ công được giữ nguyên.'):'Đã cập nhật nhạc nền. Chỉ cần ghép lại video.')}catch(e){progressClose();toast(e.message,true)}}

function progressOpen(title,message,value=0){$('#progressTitle').textContent=title;$('#progressMessage').textContent=message;$('#progressBar').style.width=value+'%';$('#progressValue').textContent=Math.round(value)+'%';$('#closeProgress').classList.add('hidden');$('#progressOverlay').classList.remove('hidden');}
function progressClose(){clearInterval(state.poll);$('#progressOverlay').classList.add('hidden');}
async function watch(jobId){
  clearInterval(state.poll);
  const tick=async()=>{try{const job=await api(`/api/jobs/${jobId}`);$('#progressMessage').textContent=job.message;$('#progressBar').style.width=job.progress+'%';$('#progressValue').textContent=Math.round(job.progress)+'%';if(job.state==='done'){clearInterval(state.poll);state.project=await api(`/api/projects/${state.project.id}`);renderStudio();$('#progressTitle').textContent='Hoàn tất';$('#closeProgress').classList.remove('hidden');toast('Tác vụ đã hoàn tất.')}else if(job.state==='error'){clearInterval(state.poll);$('#progressTitle').textContent='Dựng thất bại';$('#progressMessage').textContent=job.error;$('#closeProgress').classList.remove('hidden');toast(job.error,true)}}catch(e){clearInterval(state.poll);toast(e.message,true)}};
  await tick();state.poll=setInterval(tick,1100);
}
async function startScene(index){try{await save(false);progressOpen(`Đang dựng cảnh ${index}`,'Chuẩn bị nét vẽ…');const r=await api(`/api/projects/${state.project.id}/render/scenes/${index}`,{method:'POST'});watch(r.job_id)}catch(e){progressClose();toast(e.message,true)}}
async function startAll(){try{await save(false);progressOpen('Đang dựng toàn bộ','Các cảnh được xử lý lần lượt…');const r=await api(`/api/projects/${state.project.id}/render/all`,{method:'POST'});watch(r.job_id)}catch(e){progressClose();toast(e.message,true)}}
async function mergeOnly(){try{await save(false);progressOpen('Đang ghép video','Chuẩn hóa khung hình và âm thanh…');const r=await api(`/api/projects/${state.project.id}/merge`,{method:'POST'});watch(r.job_id)}catch(e){progressClose();toast(e.message,true)}}
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
