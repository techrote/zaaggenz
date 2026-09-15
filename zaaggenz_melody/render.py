from __future__ import annotations
from dataclasses import replace
from fractions import Fraction
import hashlib,math
import numpy as np
from zaaggenz_contracts import Contract,digest,validate
from zaaggenz_contracts.legacy import legacy_object
from zaaggenz_contracts.model import fraction
from zaaggenz_contracts.music import beat_to_sample
from zaaggenz_tuning import tuning_from_spec,cents_to_ratio
from zaaggenz_jobs import RenderArtifact
from .model import MelodyError,NoteMode,MelodicRenderSpec,MelodicRenderResult
from .pitch import pitch_shift_static,pitch_warp_variable,cosine_taper

SUPPORTED_GESTURE_AXES={'pitch_cents','gain_db','density_per_beat'}

def _contract(recipe):
    try:return recipe if isinstance(recipe,Contract) else Contract(recipe)
    except Exception as exc:raise MelodyError('valid RenderRecipe required') from exc

def _rat(q):return f'{q.numerator}/{q.denominator}'
def _finite_db(v):
    if type(v) not in (int,float) or type(v)is bool or not math.isfinite(float(v)):raise MelodyError('finite dB value required')
    return float(v)

def _checkpoint(ctx,progress=None):
    if ctx is None:return
    ctx.check_cancelled()
    if progress is not None:ctx.progress(float(progress))

def _gesture_map(phrase):return {g['id']:g for g in phrase['gestures']}

def _curve(gesture,axis):
    if gesture is None:return None
    unsupported={c['axis'] for c in gesture['curves']}-SUPPORTED_GESTURE_AXES
    if unsupported:raise MelodyError('gesture axes require another consumer: '+','.join(sorted(unsupported)))
    return next((c for c in gesture['curves'] if c['axis']==axis),None)

def _curve_samples(curve,event_beat,time_map,n,default=0.):
    if n<=0:return np.zeros(0,dtype=np.float64)
    if curve is None:return np.full(n,float(default),dtype=np.float64)
    origin=beat_to_sample(time_map,_rat(event_beat));xs=[];ys=[]
    for p in curve['points']:
        at=event_beat+fraction(p['beat']);xs.append(beat_to_sample(time_map,_rat(at))-origin);ys.append(float(p['value']))
    x=np.arange(n,dtype=np.float64)
    if curve['interpolation']=='linear':return np.interp(x,np.asarray(xs,float),np.asarray(ys,float),left=float(default),right=float(ys[-1]))
    out=np.full(n,float(default),dtype=np.float64)
    for pos,value in zip(xs,ys):out[x>=pos]=value
    return out

def _curve_value(curve,event_beat,time_map,offset_beat,default=0.):
    if curve is None:return float(default)
    target=beat_to_sample(time_map,_rat(event_beat+offset_beat))-beat_to_sample(time_map,_rat(event_beat))
    xs=[];ys=[]
    for p in curve['points']:
        xs.append(beat_to_sample(time_map,_rat(event_beat+fraction(p['beat'])))-beat_to_sample(time_map,_rat(event_beat)));ys.append(float(p['value']))
    if curve['interpolation']=='step':
        value=float(default)
        for x,y in zip(xs,ys):
            if target<x:break
            value=y
        return value
    return float(np.interp(target,np.asarray(xs,float),np.asarray(ys,float),left=float(default),right=float(ys[-1])))

def _validate_consumer(recipe,spec):
    d=recipe.to_dict();validate(d,'RenderRecipe')
    if d['render_mode']!='synth' or d['arrangement'] is not None or d['reversebass'] is not None:raise MelodyError('ZG-008 consumes synth-mode melodic recipes only')
    if d['sculpt'] is not None and d['nodes']:raise MelodyError('legacy SCULPT plus explicit DSP graph has no declared melodic ordering')
    if not d['nodes'] and d['output_node']!=d['source']['id']:raise MelodyError('melodic recipe output node is not backed by a DSP graph')
    if d['source']['method']!='legacy.synth.1.2.1':raise MelodyError('unsupported source method')
    if d['phrase'] is None:raise MelodyError('melodic recipe requires PhrasePlan')
    if d['phase_policy']!=spec.mode.phase_policy:raise MelodyError('recipe phase policy disagrees with named note mode')
    if d['tail']['mode'] not in ('preserve','truncate'):raise MelodyError('melodic renderer requires explicit preserve/truncate tail policy')
    if d['quality'] not in ('standard','high'):raise MelodyError('melodic renderer requires standard/high quality')
    for ev in d['phrase']['events']:
        if ev['layer_role']!='synthline':raise MelodyError('ZG-008 owns synthline note events only')
    return d

def _fft_for(recipe,spec):return spec.high_fft if recipe['quality']=='high' else spec.standard_fft

def _target_source(base_params,target_hz,cache,ctx=None):
    key=float(target_hz).hex()
    if key not in cache:
        _checkpoint(ctx)
        from uptempo_harmony.synth import synthesize_one
        p=replace(base_params,f0_hz=float(target_hz),beats=1);cache[key]=synthesize_one(p)[0]
        _checkpoint(ctx)
    return cache[key]

def _pitch_event_source(base_source,base_params,target_hz,pitch_cents,gate_n,recipe,spec,target_cache,ctx=None):
    if not spec.target_hz_min<=target_hz<=spec.target_hz_max:raise MelodyError(f'target frequency {target_hz:.6g} Hz outside declared melodic source range')
    if spec.mode is NoteMode.SOURCE_DERIVED:
        source=base_source;base_ratio=target_hz/float(base_params.f0_hz)
    else:
        source=_target_source(base_params,target_hz,target_cache,ctx);base_ratio=1.
    absolute_hz=target_hz*np.power(2.,pitch_cents/1200.)
    if np.any(absolute_hz<spec.target_hz_min) or np.any(absolute_hz>spec.target_hz_max):raise MelodyError('glide leaves declared target-frequency range')
    ratios=base_ratio*np.power(2.,pitch_cents/1200.) if spec.mode is NoteMode.SOURCE_DERIVED else np.power(2.,pitch_cents/1200.)
    if np.any(ratios<spec.pitch_ratio_min) or np.any(ratios>spec.pitch_ratio_max):raise MelodyError('source-derived pitch ratio outside declared bound')
    fft=_fft_for(recipe,spec);_checkpoint(ctx)
    if np.max(ratios)-np.min(ratios)<1e-10:return pitch_shift_static(source,float(ratios[0]),fft_size=fft),ratios
    warped=pitch_warp_variable(source,ratios,output_samples=len(source));at=min(max(1,gate_n),len(source));final_ratio=float(ratios[at-1]);tail=pitch_shift_static(source,final_ratio,fft_size=fft)
    fade=min(at,max(1,round(spec.glide_tail_crossfade_ms*base_params.sr/1000)))
    start=at-fade;alpha=np.linspace(0,1,fade,dtype=np.float32)
    if warped.ndim==1:warped[start:at]=(1-alpha)*warped[start:at]+alpha*tail[start:at]
    else:warped[start:at]=(1-alpha[:,None])*warped[start:at]+alpha[:,None]*tail[start:at]
    if at<len(warped):warped[at:]=tail[at:]
    return warped,ratios

def _apply_gain(wave,gain_db):
    gain=np.power(10.,np.asarray(gain_db,dtype=np.float64)/20.)
    if np.asarray(wave).ndim==1:return (np.asarray(wave,dtype=np.float64)*gain).astype(np.float32)
    return (np.asarray(wave,dtype=np.float64)*gain[:,None]).astype(np.float32)

def _event_tail(wave,gate_n,recipe,spec):
    if recipe['tail']['mode']=='truncate':
        n=max(1,min(len(wave),gate_n));return cosine_taper(wave[:n],round(spec.release_ms*recipe['time_map']['sample_rate_hz']/1000))
    n=len(wave);cap=recipe['tail']['maximum_samples']
    if cap>0:n=min(n,gate_n+cap)
    return np.asarray(wave[:n],dtype=np.float32).copy()

def _ensure(a,n):
    if len(a)>=n:return a
    return np.pad(a,(0,n-len(a)))
def _add(a,x,start,scale=1.):
    if start<0:raise MelodyError('event begins before phrase render origin')
    end=start+len(x);a=_ensure(a,end);a[start:end]+=float(scale)*np.asarray(x,dtype=np.float64);return a

def _roll_density(curve,spec):
    if curve is None:return 1
    values=[float(p['value']) for p in curve['points']]
    if max(values)-min(values)>1e-9:raise MelodyError('time-varying density_per_beat is not silently collapsed; split the phrase into explicit roll events')
    value=values[0]
    if value<=1:return 1
    rounded=round(value)
    if abs(value-rounded)>1e-9:raise MelodyError('density_per_beat must be an integer for ZG-008 roll-grid rendering')
    if rounded>spec.max_roll_density:raise MelodyError('roll density exceeds declared render bound')
    return int(rounded)

def _apply_preserved_topology(pre,d):
    """Apply topology that the base-preserving compiler has kept on SYNTHLINE."""
    if d['sculpt'] is not None:
        if d['nodes']:raise MelodyError('legacy SCULPT plus explicit DSP graph has no declared melodic ordering')
        try:
            from uptempo_harmony.multiband import SpectralSculptParams,process_spectral_sculpt
            return np.asarray(process_spectral_sculpt(np.asarray(pre,dtype=np.float32),d['time_map']['sample_rate_hz'],SpectralSculptParams(**d['sculpt'])),dtype=np.float64)
        except (ImportError,TypeError,ValueError) as exc:raise MelodyError('preserved legacy SCULPT could not execute on melodic output') from exc
    if d['nodes']:
        try:
            from zaaggenz_dsp.graph import execute_graph,GraphError
            return np.asarray(execute_graph(pre,d['time_map']['sample_rate_hz'],d['nodes'],d['output_node'],d['source']['id'],False).output,dtype=np.float64)
        except GraphError as exc:raise MelodyError('preserved DSP graph could not execute on melodic output: '+str(exc)) from exc
    return np.asarray(pre,dtype=np.float64)

def render_phrase(recipe,spec=MelodicRenderSpec(),*,job_context=None):
    if not isinstance(spec,MelodicRenderSpec):raise MelodyError('MelodicRenderSpec required')
    c=_contract(recipe);d=_validate_consumer(c,spec);phrase=d['phrase'];tm=d['time_map'];tuning=tuning_from_spec(d['tuning']);base_params=legacy_object('synth',d['source']['params']);gestures=_gesture_map(phrase)
    _checkpoint(job_context,.03)
    pitched=any(ev['pitch'] is not None for ev in phrase['events'])
    base_source=np.zeros(0,dtype=np.float32)
    if pitched and spec.mode is NoteMode.SOURCE_DERIVED:
        from uptempo_harmony.synth import synthesize_one
        base_source=synthesize_one(base_params)[0]
    _checkpoint(job_context,.08)
    target_cache={};phrase_start=beat_to_sample(tm,phrase['start_beat']);phrase_end=beat_to_sample(tm,phrase['end_beat']);nominal=max(0,phrase_end-phrase_start)
    synthline=np.zeros(nominal,dtype=np.float64);exciter=np.zeros(nominal,dtype=np.float64);records=[];roll_total=0;events=phrase['events'];count=max(1,len(events))
    for event_index,ev in enumerate(events):
        _checkpoint(job_context,.08+.76*event_index/count)
        beat=fraction(ev['beat']);duration=fraction(ev['duration_beats']);onset=beat_to_sample(tm,ev['beat'])-phrase_start;gate_end=beat_to_sample(tm,_rat(beat+duration))-phrase_start;gate_n=gate_end-onset
        if gate_n<1:raise MelodyError('note gate rounds to fewer than one sample')
        gesture=gestures.get(ev['gesture_id']) if ev['gesture_id'] is not None else None
        pitch_curve=_curve(gesture,'pitch_cents');gain_curve=_curve(gesture,'gain_db');density_curve=_curve(gesture,'density_per_beat')
        if ev['pitch'] is None:
            records.append(dict(id=ev['id'],rest=True,onset_sample=onset,gate_samples=gate_n,roll_retriggers=0));continue
        target=tuning.frequency(ev['pitch']['degree'],ev['pitch']['detune_cents'])
        natural=len(base_source) if spec.mode is NoteMode.SOURCE_DERIVED else len(_target_source(base_params,target,target_cache,job_context))
        cents=_curve_samples(pitch_curve,beat,tm,natural,0.);wave,ratios=_pitch_event_source(base_source,base_params,target,cents,gate_n,d,spec,target_cache,job_context)
        gain_offsets=_curve_samples(gain_curve,beat,tm,len(wave),0.);wave=_apply_gain(wave,float(ev['gain_db'])+gain_offsets);main=_event_tail(wave,gate_n,d,spec);synthline=_add(synthline,main,onset)
        density=_roll_density(density_curve,spec);rolls=0;roll_slice_max=0;roll_interval_min=None
        if density>1:
            j=1
            while Fraction(j,density)<duration and rolls<spec.max_roll_retriggers:
                _checkpoint(job_context)
                off=Fraction(j,density);roll_start=beat_to_sample(tm,_rat(beat+off))-phrase_start
                next_off=min(duration,Fraction(j+1,density));interval=max(1,beat_to_sample(tm,_rat(beat+next_off))-beat_to_sample(tm,_rat(beat+off)))
                local_cents=_curve_value(pitch_curve,beat,tm,off,0.);local_gain=float(ev['gain_db'])+_curve_value(gain_curve,beat,tm,off,0.)
                if spec.mode is NoteMode.SOURCE_DERIVED:roll_source=base_source;local_ratio=(target/base_params.f0_hz)*cents_to_ratio(local_cents)
                else:roll_source=_target_source(base_params,target,target_cache,job_context);local_ratio=cents_to_ratio(local_cents)
                if not spec.pitch_ratio_min<=local_ratio<=spec.pitch_ratio_max:raise MelodyError('roll pitch ratio outside declared bound')
                shifted=pitch_shift_static(roll_source,local_ratio,fft_size=_fft_for(d,spec));max_slice=max(16,round(spec.roll_slice_max_ms*base_params.sr/1000));slice_n=max(16,min(len(shifted),round(interval*spec.roll_slice_fraction),max_slice));sl=shifted[:slice_n]
                fade=max(1,min(slice_n-1,round(slice_n*spec.roll_fade_fraction)));sl=cosine_taper(sl,fade)
                group=density**(-.5*spec.roll_energy_compensation);sl=(sl*(10**(local_gain/20))*group).astype(np.float32);exciter=_add(exciter,sl,roll_start);rolls+=1;j+=1
                roll_slice_max=max(roll_slice_max,slice_n);roll_interval_min=interval if roll_interval_min is None else min(roll_interval_min,interval)
        roll_total+=rolls
        records.append(dict(id=ev['id'],rest=False,onset_sample=onset,gate_samples=gate_n,target_hz=float(target),mode=spec.mode.value,
                            source_samples=len(wave),output_samples=len(main),pitch_ratio_start=float(ratios[0]),pitch_ratio_end=float(ratios[min(len(ratios)-1,max(0,min(gate_n-1,len(ratios)-1)))]),
                            gain_db=float(ev['gain_db']),roll_density=density,roll_retriggers=rolls,roll_slice_samples_max=roll_slice_max,roll_interval_samples_min=roll_interval_min))
    _checkpoint(job_context,.86)
    n=max(len(synthline),len(exciter));synthline=_ensure(synthline,n);exciter=_ensure(exciter,n);raw_pre=synthline+exciter;pre=_apply_preserved_topology(raw_pre,d)
    try:
        from zaaggenz_dsp.graph import apply_output_policy,GraphError
        mix,master_diag=apply_output_policy(pre,d['output'])
    except GraphError as exc:raise MelodyError('melodic final output policy failed: '+str(exc)) from exc
    diag=dict(contract_version=d['version'],render_spec_sha256=spec.sha256,recipe_sha256=c.sha256,mode=spec.mode.value,sample_rate_hz=base_params.sr,
              phrase_start_sample=phrase_start,nominal_phrase_samples=nominal,rendered_samples=n,source_samples=len(base_source),notes=sum(not r['rest'] for r in records),rests=sum(r['rest'] for r in records),
              roll_retriggers=roll_total,pre_master_peak=float(np.max(np.abs(pre),initial=0)),master_peak=float(master_diag['output_peak']),clipped_fraction=float(master_diag['clip_fraction']))
    _checkpoint(job_context,.92)
    return MelodicRenderResult(np.asarray(mix,dtype=np.float32),{'synthline':np.asarray(synthline,dtype=np.float32),'exciter':np.asarray(exciter,dtype=np.float32),'pre_master':np.asarray(pre,dtype=np.float32)},tuple(records),diag)

def melodic_cache_key(recipe,spec=MelodicRenderSpec()):
    c=_contract(recipe);return digest({'domain':'zaaggenz.melodic-render-v1','recipe_sha256':c.sha256,'render_spec':spec.to_dict()})

def _waveform_scope(audio,bins=360):
    x=np.asarray(audio,dtype=np.float32);bins=max(1,min(int(bins),max(1,len(x))));edges=np.linspace(0,len(x),bins+1,dtype=int);return [float(np.max(np.abs(x[edges[i]:edges[i+1]]),initial=0)) for i in range(bins)]

def make_render_executor(recipe,spec,revision_id,cache_key=None):
    c=_contract(recipe);key=melodic_cache_key(c,spec) if cache_key is None else cache_key
    def execute(ctx):
        ctx.check_cancelled();result=render_phrase(c,spec,job_context=ctx);ctx.check_cancelled();ctx.progress(.96)
        pcm=np.asarray(result.mix,dtype='<f4').tobytes();sr=c.to_dict()['time_map']['sample_rate_hz'];asset=dict(kind='AudioAssetRef',version='1.0.0',content_sha256=hashlib.sha256(pcm).hexdigest(),identity_domain='pcm-f32le-interleaved-v1',sample_rate_hz=sr,channels=1,channel_layout='mono',frame_count=len(result.mix),level_domain='post_master',sample_policy='unclamped_float')
        scopes=dict(waveform=_waveform_scope(result.mix),events=list(result.events),diagnostics=result.diagnostics)
        ctx.check_cancelled();ctx.progress(.99)
        return RenderArtifact(revision_id,c.sha256,'synth',key,pcm,asset,scopes)
    return execute
