// MBR-003 Compose rack surface; rendered exclusively from validated server
// contract metadata. Never silently change a source, render, or output slot.
const make=(name,label)=>{const node=document.createElement(name);if(label!==undefined)node.textContent=label;return node;};
function group(parent,klass='rack-controls'){const node=make('div');node.className=klass;parent.append(node);return node;}
function button(parent,label,action,apply,disabled=false){
  const node=make('button',label);node.type='button';node.disabled=disabled;
  node.addEventListener('click',()=>apply(action));parent.append(node);return node;
}
function number(parent,label,current,meta,action,apply){
  const wrapper=make('label',label+(meta.unit?' · '+meta.unit:''));const node=make('input');
  node.type='number';node.value=String(current);
  node.step=meta.type==='integer'?'1':'any';
  if(meta.minimum!==undefined)node.min=String(meta.minimum);
  if(meta.maximum!==undefined)node.max=String(meta.maximum);
  node.addEventListener('change',()=>{
    if(!node.reportValidity()||node.value==='')return;
    const value=Number(node.value);if(!Number.isFinite(value))return;
    apply({...action,value});
  });
  wrapper.append(node);parent.append(wrapper);
}
function choice(parent,label,current,values,action,apply){
  const wrapper=make('label',label);const node=make('select');
  for(const value of values)node.append(new Option(value,value));
  node.value=current;
  node.addEventListener('change',()=>apply({...action,value:node.value}));
  wrapper.append(node);parent.append(wrapper);
}
function flag(parent,label,current,action,apply){
  const wrapper=make('label');wrapper.className='check';
  const node=make('input');node.type='checkbox';node.checked=Boolean(current);
  node.addEventListener('change',()=>apply({...action,value:node.checked}));
  wrapper.append(node,document.createTextNode(label));parent.append(wrapper);
}
function set(scope,id,field){return {kind:'set',scope,id,field};}
const mix={type:'number',minimum:0,maximum:1,unit:'0–1'};
export function renderRack(host,state,apply,tools={}){
  host.replaceChildren();
  if(!state){host.append(make('p','Rack metadata is unavailable; refresh the validated revision.'));return;}
  const top=group(host);
  if(!state.present){
    top.append(make('p','No rack is installed in this project. Legacy audio and source presets remain unchanged.'));
    button(top,'Enable four-band rack',{kind:'enable'},apply);
    renderPresetTools(host,state,apply,tools);
    return;
  }
  const rack=state.value;
  const about=make('p','Bus: '+rack.placement.bus+' · '+rack.placement.after+
    ' · no extra final master · '+rack.sample_rate_hz+' Hz · '+rack.channels+' channel(s).');
  about.className='hint';host.append(about);
  flag(top,'Bypass rack',rack.bypass,set('rack','rack','bypass'),apply);
  number(top,'Rack wet',rack.wet,mix,set('rack','rack','wet'),apply);
  button(top,'Remove rack (dry)',{kind:'reset'},apply);
  const crossings=group(host);
  rack.crossovers.frequencies_hz.forEach((frequency,index)=>{
    number(crossings,'Crossover '+(index+1),frequency,
      {type:'number',minimum:20,maximum:rack.sample_rate_hz/2,unit:'Hz'},
      set('crossover',index,'frequency_hz'),apply);
  });
  for(const band of rack.bands){
    const panel=group(host,'rack-band');panel.append(make('h3',band.band.toUpperCase()));
    const controls=group(panel);
    flag(controls,'Bypass band',band.bypass,set('band',band.id,'bypass'),apply);
    flag(controls,'Confine delta',band.confine_delta,set('band',band.id,'confine_delta'),apply);
    number(controls,'Band wet',band.wet,mix,set('band',band.id,'wet'),apply);
    const additions=group(panel);
    for(const typeId of Object.keys(state.parameters)){
      if(band.inserts.some(i=>i.type_id===typeId))continue;
      button(additions,'Add '+typeId.slice(3),{kind:'add',band:band.id,type_id:typeId},apply);
    }
    if(!band.inserts.length)panel.append(make('p','No active stages. This band is unchanged.'));
    band.inserts.forEach((stage,index)=>{
      const block=group(panel,'rack-stage');
      block.append(make('h4',stage.type_id.replace('zg.','')));
      const identity=make('div',stage.id);identity.className='rack-stage-id';block.append(identity);
      const buttons=group(block);
      button(buttons,'Move up',{kind:'move',band:band.id,id:stage.id,step:-1},apply,index===0);
      button(buttons,'Move down',{kind:'move',band:band.id,id:stage.id,step:1},apply,index===band.inserts.length-1);
      if(state.parameters[stage.type_id]){
        if(stage.type_id!=='zg.spectral')
          button(buttons,'Reset parameters',{kind:'reset_insert_params',band:band.id,id:stage.id},apply);
        button(buttons,'Remove insert',{kind:'remove',band:band.id,id:stage.id},apply);
      }
      flag(buttons,'Bypass insert',stage.bypass,set('insert',band.id+'/'+stage.id,'bypass'),apply);
      number(buttons,'Insert wet',stage.wet,mix,set('insert',band.id+'/'+stage.id,'wet'),apply);
      const params=state.parameters[stage.type_id];
      if(!params||stage.params===null){
        block.append(make('p',params
          ? 'No active parameter request; use Reset parameters to initialize the supported built-in defaults.'
          : 'Stored processor state preserved; specialized spectral or external controls are not yet implemented here.'));
        return;
      }
      if(stage.type_id==='zg.spectral'){
        const request=stage.params;
        const retune=request.kind==='SpectralRetuneRequest';
        const chordness=request.kind==='ChordnessRequest';
        if(!retune&&!chordness){
          block.append(make('p','Unknown spectral request; saved state retained without editable controls.'));
          return;
        }
        const details=make('details');details.className='rack-spectral';block.append(details);
        details.append(make('summary',retune
          ?'Internal spectral retune · target & confidence'
          :'Internal Chordness · selection, gains & confidence'));
        const fields=group(details);
        const definition=state.parameters['zg.spectral'][retune?'retune':'chordness'];
        for(const [key,meta] of Object.entries(definition)){
          const label=key.replaceAll('_',' ');
          const action=set('spectral',band.id+'/'+stage.id,key);
          if('enum' in meta)choice(fields,label,request[key],meta.enum,action,apply);
          else if(meta.type==='boolean')flag(fields,label,request[key],action,apply);
          else if('const' in meta)fields.append(make('span',label+': '+String(request[key])+' (fixed policy)'));
          else number(fields,label,request[key],
            key==='max_hz'?{...meta,maximum:Math.min(meta.maximum,rack.sample_rate_hz/2)}:meta,
            action,apply);
        }
        if(retune){
          const target=group(details);
          target.append(make('p','Target tuning is inherited from the saved source; the first voice degree is editable. All other target voices, partial ratios and time segments remain preserved.'));
          const first=request.voices?.[0];
          if(first)number(target,'Primary target degree',first.degree,
            {type:'integer',minimum:-4096,maximum:4096,unit:'tuning steps'},
            set('spectral_voice',band.id+'/'+stage.id,'degree'),apply);
          target.append(make('p','Voices: '+request.voices.length+' · target segments: '+request.segments.length+' · no implicit tuning conversion.'));
        }else{
          const selector=group(details);
          selector.append(make('p','Manual template selection is bounded by the saved max selected templates. Changing selection never rewrites comb teeth.'));
          for(const template of request.templates){
            flag(selector,'Select template '+template.label+' ('+template.id+')',
              request.selected_template_ids.includes(template.id),
              {kind:'select_spectral_template',band:band.id,id:stage.id,template_id:template.id},apply);
          }
          const coeff=group(details);
          coeff.append(make('h5','Chordness objective weights'));
          for(const [key,meta] of Object.entries(state.spectral_coefficients||{})){
            number(coeff,key.replaceAll('_',' '),request.coefficients[key],meta,
              set('chordness_coefficient',band.id+'/'+stage.id,key),apply);
          }
        }
        return;
      }
      const fields=group(block);
      for(const [key,meta] of Object.entries(params)){
        if('const' in meta||'enum' in meta||meta.type==='boolean'){
          const fixed=make('span',key+': '+String(stage.params[key])+' (fixed policy)');
          fixed.className='rack-fixed';fields.append(fixed);continue;
        }
        number(fields,key.replaceAll('_',' '),stage.params[key],meta,
          set('parameter',band.id+'/'+stage.id,key),apply);
      }
    });
  }
  renderPresetTools(host,state,apply,tools);
}

function renderPresetTools(host,state,apply,tools){
  const presets=group(host,'rack-controls rack-presets');
  presets.append(make('h3','User rack presets (stored in the saved project)'));
  const named=make('label','Preset name');const name=make('input');
  name.value='My rack';name.maxLength=128;named.append(name);presets.append(named);
  const keyed=make('label','Preset ID (a–z, digits, dots, dashes)');const id=make('input');
  id.value='user.myrack';id.maxLength=64;keyed.append(id);presets.append(keyed);
  const save=make('button','Save new preset');save.type='button';
  save.addEventListener('click',()=>apply({kind:'save_preset',id:id.value,name:name.value}));
  presets.append(save);
  const saved=make('label','Load saved preset');const select=make('select');
  select.append(new Option('Select saved preset',''));
  for(const item of state.presets)select.append(new Option(item.name+' ('+item.id+')',item.id));
  saved.append(select);presets.append(saved);
  const load=make('button','Load');load.type='button';load.disabled=!state.presets.length;
  load.addEventListener('click',()=>{if(select.value)apply({kind:'load_preset',id:select.value});});
  presets.append(load);
  const replace=make('button','Replace selected preset');replace.type='button';replace.disabled=true;
  replace.title='Explicitly replace only this user preset with the current rack.';
  replace.addEventListener('click',()=>{if(select.value)apply({kind:'replace_preset',id:select.value,name:name.value});});
  presets.append(replace);
  const rename=make('button','Rename selected preset');rename.type='button';rename.disabled=true;
  rename.title='Rename user preset without changing its saved processing or source.';
  rename.addEventListener('click',()=>{if(select.value)apply({kind:'rename_preset',id:select.value,name:name.value});});
  presets.append(rename);
  const exported=make('button','Export selected preset');exported.type='button';exported.disabled=true;
  exported.title='Download exact source-bound preset; does not change the project.';
  exported.addEventListener('click',()=>{if(select.value)tools.exportPreset?.(select.value);});
  presets.append(exported);
  const remove=make('button','Delete selected preset');remove.type='button';remove.disabled=true;
  remove.title='Delete only this saved user preset; do not change the active rack or factory source.';
  remove.addEventListener('click',()=>{
    const selected=state.presets.find(item=>item.id===select.value);
    if(selected&&window.confirm('Delete user rack preset "'+selected.name+'" ('+selected.id+
      ')? Current rack and source will remain unchanged.')){
      apply({kind:'delete_preset',id:selected.id});
    }
  });
  presets.append(remove);
  const imported=make('label','Import rack preset file');
  const file=make('input');file.type='file';file.accept='.zgrack.json,.json,application/json';
  file.addEventListener('change',async()=>{
    const chosen=file.files?.[0];file.value='';
    if(chosen)await tools.importPreset?.(chosen);
  });
  imported.append(file);presets.append(imported);
  presets.append(make('p','Portable imports require the matching source; modified hashes and duplicate IDs are rejected.'));
  select.addEventListener('change',()=>{
    const selected=state.presets.find(item=>item.id===select.value);
    replace.disabled=rename.disabled=exported.disabled=remove.disabled=!selected;
    if(selected)name.value=selected.name;
  });
}

function levelText(value){
  if(typeof value!=='number'||!Number.isFinite(value)||value<0)return 'not measured';
  return value===0?'−∞ dBFS':(20*Math.log10(value)).toFixed(1)+' dBFS';
}
function measuredLevels(row){
  if(!row||typeof row!=='object')return 'not measured';
  return 'peak '+levelText(row.peak)+' · RMS '+levelText(row.rms);
}
function validCount(value){return Number.isSafeInteger(value)&&value>=0?String(value):'not measured';}

/** Display only measurements attached to an accepted, completed RenderArtifact.
 * The caller clears this surface on every edit or publication invalidation.
 * Never infer meters from current controls, browser playback, or stale jobs.
 */
export function renderRackMeters(host,artifact){
  host.replaceChildren();
  if(!artifact){
    host.append(make('p','No current completed render. Render the validated revision for measurements.'));
    return;
  }
  const diagnostics=artifact.scopes?.diagnostics?.rack;
  if(!diagnostics){
    host.append(make('p','This completed render used the dry source path; no rack measurements exist.'));
    return;
  }
  if(!Array.isArray(diagnostics.bands)||diagnostics.bands.length!==4){
    host.append(make('p','Rack measurements unavailable or incomplete for this render.'));
    return;
  }
  const note=make('p','Measured completed render · revision '+artifact.revision_id+
    ' · '+(diagnostics.meter_context==='complete-input-context'
      ?'full phrase context (including for region previews)':'context unspecified')+
    ' · no automatic level compensation.');
  note.className='hint';host.append(note);
  const overall=make('p','Rack input '+measuredLevels(diagnostics.input)+
    ' · rack output '+measuredLevels(diagnostics.output));
  host.append(overall);
  for(const band of diagnostics.bands){
    const section=group(host,'rack-meter-band');
    section.append(make('h4',String(band.band??band.id).toUpperCase()+
      (band.active?' · processed':' · identity / bypass')));
    section.append(make('p','Band input '+measuredLevels(band.input)+
      ' · post-band wet '+measuredLevels(band.output)+
      ' · routed output '+measuredLevels(band.routed_output)));
    if(band.meter_unavailable_reason){
      section.append(make('p','Meter unavailable: '+band.meter_unavailable_reason));
    }
    for(const stage of (Array.isArray(band.stages)?band.stages:[])){
      const item=make('p',String(stage.type_id??'processor')+' ['+
        String(stage.id??'unidentified')+'] · ');
      if(stage.executed!==true){
        item.textContent+='not executed'+(stage.reason?' ('+stage.reason+')':'');
      }else if(stage.type_id==='zg.compression'){
        const reduction=stage.processor?.diagnostics?.max_gain_reduction_db;
        item.textContent+='max gain reduction '+
          (typeof reduction==='number'&&Number.isFinite(reduction)&&reduction>=0
            ?reduction.toFixed(2)+' dB':'not measured')+
          ' (processor-internal, before insert wet)';
      }else if(stage.type_id==='zg.spectral'){
        const changed=stage.processor?.diagnostics?.changed_frames;
        const reasons=stage.processor?.decision_counts_by_reason;
        item.textContent+='changed frames '+validCount(changed);
        if(reasons&&typeof reasons==='object'&&!Array.isArray(reasons)){
          item.textContent+=' · decision reasons: '+Object.entries(reasons).map(([key,count])=>
            key+' '+validCount(count)).join(', ');
        }
      }else{
        item.textContent+='executed · stage output '+measuredLevels(stage.output);
      }
      section.append(item);
    }
  }
}
