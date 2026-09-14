from __future__ import annotations
from dataclasses import dataclass
from copy import deepcopy
import hashlib,json,math
import numpy as np
from zaaggenz_melody.pitch import pitch_shift_static,cosine_taper
from .model import ZaagFamilyError,canonical_sha256
from .registry import family
from .render import render_family_source

@dataclass(frozen=True)
class ArrangementManifest:
    id:str
    bars:int
    bpm:float
    sample_rate_hz:int
    events:tuple[dict,...]
    description:str
    tuning:str='12edo-local-48hz'
    source_policy:str='render-each-family-once-then-source-derived-pitch'
    tail_policy:str='preserve'
    normalization:str='none'
    version:str='1.0.0'
    def __post_init__(self):
        if type(self.bars)is not int or not 1<=self.bars<=64:raise ZaagFamilyError('bars outside 1..64')
        if not math.isfinite(float(self.bpm)) or not 60<=float(self.bpm)<=260:raise ZaagFamilyError('bpm outside range')
        if self.sample_rate_hz not in (12000,24000,48000):raise ZaagFamilyError('unsupported example sample rate')
        events=tuple(deepcopy(self.events))
        for row in events:
            if type(row)is not dict or 'beat' not in row or 'duration_beats' not in row or 'family_id' not in row or 'degrees' not in row:raise ZaagFamilyError('invalid arrangement event')
            if family(row['family_id']).classification!='candidate':raise ZaagFamilyError('arranged examples use candidate families only')
            if not row['degrees'] or any(type(x)is not int for x in row['degrees']):raise ZaagFamilyError('degrees must be nonempty integer list')
            if float(row['beat'])<0 or float(row['duration_beats'])<=0:raise ZaagFamilyError('invalid event timing')
        object.__setattr__(self,'events',events);object.__setattr__(self,'bpm',float(self.bpm))
    def to_dict(self):return {'kind':'ZaagArrangementManifest','version':self.version,'id':self.id,'bars':self.bars,'bpm':self.bpm,'sample_rate_hz':self.sample_rate_hz,'description':self.description,'tuning':self.tuning,'source_policy':self.source_policy,'tail_policy':self.tail_policy,'normalization':self.normalization,'events':deepcopy(list(self.events))}
    @property
    def sha256(self):return canonical_sha256(self.to_dict())

@dataclass(frozen=True)
class ArrangementRender:
    audio:np.ndarray
    manifest:ArrangementManifest
    diagnostics:dict
    def __post_init__(self):
        a=np.asarray(self.audio,dtype=np.float32)
        if a.ndim!=1 or not np.isfinite(a).all():raise ZaagFamilyError('invalid arranged audio')
        a.setflags(write=False);object.__setattr__(self,'audio',a);object.__setattr__(self,'diagnostics',deepcopy(self.diagnostics))

def _event(beat,duration,family_id,degrees,gain_db=0.):return {'beat':float(beat),'duration_beats':float(duration),'family_id':family_id,'degrees':list(degrees),'gain_db':float(gain_db)}

def one_shot_manifest(sr=48000):return ArrangementManifest('zg022-one-shot',1,190.,sr,(_event(0,.75,'zaag.relaxed-punch',(0,),-3.),),'Single source-preserving Relaxed Punch note.')

def four_bar_manifest(sr=48000):
    events=[];pattern=(0,3,5,7,5,3,10,7)
    for i in range(32):events.append(_event(i*.5,.45,'zaag.upper-bounce',(pattern[i%len(pattern)],),-7. if i%4 else -4.5))
    return ArrangementManifest('zg022-four-bar-bounce',4,190.,sr,tuple(events),'Four-bar half-beat source-derived upper-bounce phrase with a stable melodic return.')

def sixteen_bar_manifest(sr=48000):
    events=[];roots=(0,5,3,7);families=('zaag.harmonic-turn','zaag.vowel-sway','zaag.complementary-pulse','zaag.grit-skip')
    for bar in range(16):
        root=roots[(bar//4)%len(roots)];fid=families[(bar//4)%len(families)]
        chord=(root,root+3,root+7) if bar%4 in (1,3) else (root,)
        events.append(_event(bar*4,.9,fid,chord,-10. if len(chord)>1 else -6.))
        events.append(_event(bar*4+1.,.65,fid,(root+7,),-8.))
        events.append(_event(bar*4+2.,.45,fid,(root+10,),-9.))
        events.append(_event(bar*4+3.,.75,fid,(root+5,),-8.))
    return ArrangementManifest('zg022-sixteen-bar-turn',16,190.,sr,tuple(events),'Sixteen-bar harmonic/source-family turn: explicit roots/intervals, no hidden chord inference.')

def example_manifests(sr=48000):return (one_shot_manifest(sr),four_bar_manifest(sr),sixteen_bar_manifest(sr))

def render_arrangement(manifest):
    if not isinstance(manifest,ArrangementManifest):raise ZaagFamilyError('ArrangementManifest required')
    sr=manifest.sample_rate_hz;spb=sr*60./manifest.bpm;nominal=round(manifest.bars*4*spb);out=np.zeros(nominal,dtype=np.float64);sources={};pitch_cache={};source_counts={}
    for event in manifest.events:
        fid=event['family_id']
        if fid not in sources:
            sources[fid]=render_family_source(family(fid),sr,beats=1).audio;source_counts[fid]=1
        base=sources[fid];start=round(event['beat']*spb);gate=max(1,round(event['duration_beats']*spb));gain=10**(event['gain_db']/20.)
        for degree in event['degrees']:
            ratio=2**(degree/12.)
            expert=family(fid).expert
            if not expert.pitch_ratio_min<=ratio<=expert.pitch_ratio_max:raise ZaagFamilyError(f'{fid} event ratio outside documented family pitch range')
            key=(fid,degree)
            if key not in pitch_cache:pitch_cache[key]=pitch_shift_static(base,ratio,fft_size=2048)
            shifted=np.asarray(pitch_cache[key],dtype=np.float64);n=min(len(shifted),gate if family(fid).expert.tail_policy=='truncate' else len(shifted));note=shifted[:n].copy()
            if family(fid).expert.tail_policy=='truncate' and n>16:note=cosine_taper(note,min(n//4,round(.008*sr)))
            end=start+n
            if end>len(out):out=np.pad(out,(0,end-len(out)))
            out[start:end]+=gain*note
    audio=np.asarray(out,dtype=np.float32);diag={'method':'zg.zaag-arrangement.v1','manifest_sha256':manifest.sha256,'samples':len(audio),'events':len(manifest.events),'families':sorted(sources),'source_renders_per_family':source_counts,'pitch_cache_entries':len(pitch_cache),'source_policy':manifest.source_policy,'normalization':'none','peak':float(np.max(np.abs(audio),initial=0.)),'rms':float(np.sqrt(np.mean(audio.astype(np.float64)**2))) if len(audio) else 0.,'pcm_sha256':hashlib.sha256(audio.astype('<f4').tobytes()).hexdigest()}
    return ArrangementRender(audio,manifest,diag)
