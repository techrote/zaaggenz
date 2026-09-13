import {Editor,copy,rational,value,snap,add} from './editor.mjs';
import {RenderTransport} from './jobs_transport.mjs';
const $=id=>document.getElementById(id),transport=new RenderTransport();
let editor,token,selected=null,validation=null,epoch=0,validationSequence=0,job=null,slots=[],activeSlot=null;
const status=(message,error=false)=>{ $('status').textContent=message;$('status').classList.toggle('error',error); };
async function api(path,payload){
  const response=await fetch('/api/timeline/'+path,payload===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-Zaaggenz-Token':token},body:JSON.stringify(payload)});
  const data=await response.json();if(!response.ok)throw Error(data.error??`HTTP ${response.status}`);return data;
}
function quietCancel(id){if(id)api('cancel',{job_id:id}).catch(()=>{});}
function clearPlayback(){
  transport.stop('timeline');activeSlot=null;$('audio').pause();$('audio').removeAttribute('src');$('audio').dataset.revision='';$('audio').load();
  $('play').disabled=true;$('playback-revision').textContent='—';$('waveform').dataset.revision='';
  $('waveform').getContext('2d').clearRect(0,0,1200,140);
  $('download').removeAttribute('href');$('download').classList.add('disabled');$('download').setAttribute('aria-disabled','true');
}
function invalidate(){epoch++;quietCancel(job);job=null;validation=null;clearPlayback();$('render').disabled=true;$('render-region').disabled=true;}
function afterEdit(){invalidate();paint();if(selected)select(selected);validateLatest();}
function safe(action){try{action();}catch(e){status(e.message,true);}}
function mutate(action){safe(()=>{action();afterEdit();});}
async function validateLatest(){
  const seq=++validationSequence,serialized=JSON.stringify(editor.document);
  $('revision').textContent='Validating…';
  try{
    const result=await api('validate',{document:JSON.parse(serialized)});
    if(seq!==validationSequence||JSON.stringify(editor.document)!==serialized)return;
    validation=result;$('revision').textContent=result.revision_id;
    $('pitch-context').textContent=`Source ${result.source_hz.toFixed(2)} Hz · ${result.tuning.id} · source-preserving melody`;
    $('render').disabled=false;$('render-region').disabled=false;
    updateTarget();status(`Ready · ${editor.document.notes.length} events · estimated render admission ${(result.estimated_memory_bytes/1048576).toFixed(1)} MiB`);
  }catch(e){if(seq===validationSequence){validation=null;$('revision').textContent='Invalid editing revision';status(e.message,true);}}
}
function rowFromForm(){return {beat:rational($('beat').value),duration_beats:rational($('duration').value),
  degree:$('rest').checked?null:Number($('degree').value),detune_cents:Number($('detune').value),gain_db:Number($('gain').value),
  muted:$('muted').checked,roll_density:Number($('density').value)};}
function select(id){
  selected=id;const row=editor.document.notes.find(r=>r.id===id);
  if(row){$('beat').value=row.beat;$('duration').value=row.duration_beats;$('degree').value=row.degree??0;
    $('detune').value=row.detune_cents;$('gain').value=row.gain_db;$('rest').checked=row.degree===null;
    $('muted').checked=row.muted;$('density').value=String(row.roll_density);}
  paint();updateTarget();
}
function updateTarget(){const hz=validation?.targets?.[selected];$('target-pitch').textContent=hz===null?'Rest · no target pitch':Number.isFinite(hz)?`Selected target ${hz.toFixed(3)} Hz · source ${validation.source_hz.toFixed(2)} Hz`:'Target pitch appears after the event is applied.';}
function svgElement(name,attrs,text){const node=document.createElementNS('http://www.w3.org/2000/svg',name);for(const [key,v]of Object.entries(attrs))node.setAttribute(key,String(v));if(text!==undefined)node.textContent=text;return node;}
function paint(){
  const data=editor.document;$('project-name').value=data.name;$('length').value=data.end_beat;$('master').value=data.master_gain_db;
  $('undo').disabled=!editor.past.length;$('redo').disabled=!editor.future.length;
  const exists=data.notes.some(r=>r.id===selected);if(!exists)selected=null;
  for(const id of ['apply','duplicate','delete','mute'])$(id).disabled=!exists;
  const svg=$('roll');svg.replaceChildren();const end=value(data.end_beat),width=1140,left=48;
  for(let beat=0;beat<=end;beat++){
    const x=left+beat/end*width;svg.append(svgElement('line',{x1:x,x2:x,y1:24,y2:300,class:beat%4?'gridline':'barline'}));
    if(beat%4===0)svg.append(svgElement('text',{x:x+3,y:17},`Bar ${beat/4+1}`));
  }
  const pitched=data.notes.filter(r=>r.degree!==null).map(r=>r.degree),low=Math.min(-1,...pitched),high=Math.max(12,...pitched),span=high-low+1;
  for(let i=0;i<=span&&i<=40;i++){
    const deg=low+i,y=280-(deg-low)/span*235;
    svg.append(svgElement('line',{x1:left,x2:1188,y1:y,y2:y,class:'gridline'}));
    svg.append(svgElement('text',{x:5,y:y+3},String(deg)));
  }
  for(const row of data.notes){
    const x=left+value(row.beat)/end*width,y=row.degree===null?290:274-(row.degree-low)/span*235;
    const rect=svgElement('rect',{x,y,width:Math.max(5,value(row.duration_beats)/end*width-1),height:Math.max(9,Math.min(18,220/span)),rx:3,
      class:`note${row.id===selected?' selected':''}${row.muted?' muted':''}${row.degree===null?' rest':''}`,'data-id':row.id,tabindex:0,
      'aria-label':`${row.degree===null?'Rest':`Degree ${row.degree}`} at beat ${row.beat}${row.roll_density?' with rolls':''}`});
    rect.append(svgElement('title',{},`${row.id}: ${row.beat} + ${row.duration_beats} beats${row.roll_density?`; density ${row.roll_density}`:''}`));
    rect.addEventListener('click',()=>select(row.id));
    rect.addEventListener('keydown',e=>{if(e.key==='Enter')select(row.id);});
    rect.addEventListener('pointerdown',e=>{
      if(e.button!==0)return;const start=e.clientX,original=copy(row),resize=e.shiftKey,id=row.id;
      const screenWidth=svg.getBoundingClientRect().width*width/1200;
      const finish=event=>{window.removeEventListener('pointerup',finish);const delta=(event.clientX-start)/screenWidth*end;
        if(Math.abs(event.clientX-start)<4){select(id);return;}
        safe(()=>{const updated={...original};const field=resize?'duration_beats':'beat';
          const target=Math.max(resize?value($('snap').value):0,value(original[field])+delta);
          updated[field]=snap(target.toFixed(6),$('snap').value);editor.edit(id,updated,$('snap').value);selected=id;afterEdit();select(id);});
      };window.addEventListener('pointerup',finish,{once:true});
    });svg.append(rect);
  }
  $('event-list').replaceChildren();for(const row of data.notes){const button=document.createElement('button');button.textContent=`${row.id}: ${row.degree===null?'rest':row.degree} @ ${value(row.beat).toFixed(2)}`;
    button.setAttribute('aria-pressed',String(row.id===selected));button.addEventListener('click',()=>select(row.id));$('event-list').append(button);}
  const clipSelection=$('clips').value;$('clips').replaceChildren(new Option('Custom region',''));
  for(const c of data.clips)$('clips').add(new Option(`${c.name} (${c.start_beat}–${c.end_beat})`,c.id));$('clips').value=clipSelection;
  $('layer-context').textContent=JSON.stringify({ownership:data.layer_ownership,retained_project_head:data.project.head},null,2);
}
function redrawOutputs(){const current=$('outputs').value;$('outputs').replaceChildren(new Option('Choose a rendered output',''));
  for(const slot of slots)$('outputs').add(new Option(`${slot.name} · ${slot.revision.slice(0,10)} · ${slot.region.start_beat}–${slot.region.end_beat}`,slot.id));$('outputs').value=current;}
function publish(slot){
  if(editor.document&&JSON.stringify(editor.document)!==JSON.stringify(slot.document))throw Error('Select the output revision before playback.');
  const generation=transport.begin('timeline',slot.revision);
  if(!transport.accept('timeline',{accepted:true,state:'completed',generation,revision_id:slot.revision,artifact:slot.artifact,audio:slot.url}))throw Error('Stale audio rejected.');
  const snapshot=transport.current('timeline');activeSlot=slot;
  $('audio').src=snapshot.audio;$('audio').dataset.revision=snapshot.revisionId;$('play').disabled=false;
  $('playback-revision').textContent=snapshot.revisionId;$('waveform').dataset.revision=snapshot.revisionId;
  $('revision').textContent=snapshot.revisionId;$('outputs').value=slot.id;
  const ctx=$('waveform').getContext('2d');ctx.clearRect(0,0,1200,140);ctx.fillStyle='#95b097';
  const points=snapshot.scopes.waveform;for(let i=0;i<points.length;i++){const h=Math.min(66,points[i]*66);ctx.fillRect(i*1200/points.length,70-h,Math.max(1,1200/points.length),Math.max(1,2*h));}
  $('download').href=slot.url;$('download').download=`${slot.name.replace(/[^a-zA-Z0-9_-]/g,'_')}.wav`;
  $('download').classList.remove('disabled');$('download').setAttribute('aria-disabled','false');
}
async function render(region){
  if(!validation)return;const data=editor.document,revision=validation.revision_id,requestEpoch=++epoch;
  quietCancel(job);job=null;clearPlayback();const name=$('output-name').value;
  try{
    const submitted=await api('render',{document:data,region,name});
    if(requestEpoch!==epoch){quietCancel(submitted.job_id);return;}
    if(submitted.revision_id!==revision)throw Error('Server returned a different render revision.');
    job=submitted.job_id;
    for(;;){
      const result=await api(`jobs/${submitted.job_id}`);
      if(requestEpoch!==epoch)return;
      status(`${name}: ${result.state} · ${Math.round(result.progress*100)}%`);
      if(result.state==='failed'||result.state==='cancelled')throw Error(result.error??result.state);
      if(result.state==='completed'){
        if(result.revision_id!==revision||result.artifact.revision_id!==revision||result.artifact.recipe_sha256!==submitted.recipe_sha256)throw Error('Mismatched artifact rejected.');
        const response=await fetch(`/api/timeline/jobs/${submitted.job_id}/audio`);
        if(!response.ok||response.headers.get('X-Timeline-Revision')!==revision)throw Error('Mismatched audio response rejected.');
        const blob=await response.blob();if(requestEpoch!==epoch)return;
        const slot={id:submitted.job_id,name,document:copy(data),revision,region:submitted.region,artifact:result.artifact,url:URL.createObjectURL(blob)};
        slots.push(slot);if(slots.length>8)URL.revokeObjectURL(slots.shift().url);redrawOutputs();publish(slot);job=null;
        status(`${name} ready · ${slot.artifact.asset.frame_count} samples · ${slot.artifact.scopes.diagnostics.clipped_fraction>0?'WARNING: output clipping occurred':'no output clipping reported'}`);break;
      }
      await new Promise(resolve=>setTimeout(resolve,120));
    }
  }catch(e){if(requestEpoch===epoch){job=null;status(e.message,true);}}
}
function bind(){
  $('density').replaceChildren(new Option('Off','0'));for(let n=1;n<=16;n++)$('density').add(new Option(String(n),String(n)));

  $('note-form').addEventListener('submit',e=>{e.preventDefault();mutate(()=>{selected=editor.add(rowFromForm(),$('snap').value);});});
  $('apply').onclick=()=>mutate(()=>editor.edit(selected,rowFromForm(),$('snap').value));
  $('duplicate').onclick=()=>mutate(()=>{selected=editor.duplicate(selected,$('snap').value);});
  $('delete').onclick=()=>mutate(()=>editor.remove(selected));$('mute').onclick=()=>mutate(()=>editor.mute(selected));
  $('undo').onclick=()=>mutate(()=>editor.undo());$('redo').onclick=()=>mutate(()=>editor.redo());
  $('example4').onclick=()=>mutate(()=>editor.example(4));$('example16').onclick=()=>mutate(()=>editor.example(16));
  $('project-name').onchange=()=>mutate(()=>editor.commit(s=>s.name=$('project-name').value));
  $('set-length').onclick=()=>mutate(()=>editor.commit(s=>s.end_beat=rational($('length').value)));
  $('master').onchange=()=>mutate(()=>editor.commit(s=>s.master_gain_db=Number($('master').value)));
  $('add-clip').onclick=()=>mutate(()=>editor.clip($('clip-name').value,$('region-start').value,$('region-end').value));
  $('duplicate-clip').onclick=()=>mutate(()=>editor.duplicateClip($('clips').value));
  $('clips').onchange=()=>{const clip=editor.document.clips.find(c=>c.id===$('clips').value);if(clip){$('region-start').value=clip.start_beat;$('region-end').value=clip.end_beat;}};
  $('render').onclick=()=>render(null);
  $('render-region').onclick=()=>safe(()=>render({start_beat:rational($('region-start').value),end_beat:rational($('region-end').value)}));
  $('cancel').onclick=()=>{epoch++;quietCancel(job);job=null;status('Render cancelled; editing state is unchanged.');};
  $('stop').onclick=()=>{epoch++;quietCancel(job);job=null;clearPlayback();status('Playback stopped. Select a named output to reload it.');};
  $('play').onclick=async()=>{try{if(!activeSlot||editor.document&&JSON.stringify(editor.document)!==JSON.stringify(activeSlot.document))throw Error('Playback revision no longer matches editing state.');await $('audio').play();}catch(e){status(e.message,true);}};
  $('outputs').onchange=()=>{const slot=slots.find(s=>s.id===$('outputs').value);if(!slot)return;
    safe(()=>{editor.replace(slot.document);invalidate();paint();publish(slot);validateLatest();});};
  $('save').onclick=()=>safe(()=>{if(!validation)throw Error('Correct invalid editing state before saving.');
    const url=URL.createObjectURL(new Blob([JSON.stringify(editor.document,null,2)],{type:'application/json'}));
    const link=document.createElement('a');link.href=url;link.download='zaaggenz-timeline.zgtimeline.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
  $('open').onchange=async()=>{const file=$('open').files[0];if(!file)return;
    try{if(file.size>2000000)throw Error('Project exceeds the 2 MB authoring limit.');const input=JSON.parse(await file.text());
      await api('validate',{document:input});editor.replace(input);selected=null;afterEdit();
    }catch(e){status(e.message,true);}finally{$('open').value='';}};
  $('roll').ondblclick=e=>{if(e.target.closest('[data-id]'))return;const bounds=$('roll').getBoundingClientRect(),x=(e.clientX-bounds.left)*1200/bounds.width;
    $('beat').value=snap(Math.max(0,(x-48)/1140*value(editor.document.end_beat)).toFixed(6),$('snap').value);
    mutate(()=>{selected=editor.add(rowFromForm(),$('snap').value);});};
  document.addEventListener('keydown',e=>{if(/INPUT|TEXTAREA|SELECT/.test(e.target.tagName))return;
    if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='z'){e.preventDefault();mutate(()=>e.shiftKey?editor.redo():editor.undo());}
    else if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='y'){e.preventDefault();mutate(()=>editor.redo());}
    else if(e.key==='Delete'&&selected){e.preventDefault();mutate(()=>editor.remove(selected));}});
}
try{const boot=await api('bootstrap');token=boot.token;editor=new Editor(boot.document);bind();paint();await validateLatest();}
catch(e){status(e.message,true);}
