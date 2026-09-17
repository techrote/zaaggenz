from __future__ import annotations
from dataclasses import dataclass
from copy import deepcopy
import hashlib,math
import numpy as np
from zaaggenz_melody.pitch import pitch_shift_static,cosine_taper
from .model import ZaagFamilyError,canonical_sha256
from .registry import family
from .render import render_family_source

BEATS_PER_BAR=4
MAX_BARS=64
MAX_EVENTS_PER_BAR=16
MAX_EVENT_POLYPHONY=8
GAIN_DB_MIN=-120.0
GAIN_DB_MAX=24.0
# ZG-022 renders one source beat. The frozen legacy synth import envelope permits
# no source BPM below 20, so even a future in-envelope family source is bounded
# by three seconds before duration-preserving pitch shifting.
MAX_SOURCE_TAIL_SECONDS=3.0
MAX_ARRANGEMENT_EVENTS=MAX_BARS*MAX_EVENTS_PER_BAR
MAX_ARRANGEMENT_VOICES=MAX_ARRANGEMENT_EVENTS*MAX_EVENT_POLYPHONY
MAX_OUTPUT_SAMPLES=round((MAX_BARS*BEATS_PER_BAR*60./60.+MAX_SOURCE_TAIL_SECONDS)*48000)
_EVENT_FIELDS=frozenset(('beat','duration_beats','family_id','degrees','gain_db'))


def _finite_number(value,label):
    if type(value) not in (int,float) or type(value)is bool or not math.isfinite(value):
        raise ZaagFamilyError(f'{label} must be a finite native number')
    return float(value)


def _degree_bounds(fid):
    expert=family(fid).expert
    # Compare integer degrees against logarithmic family bounds before any
    # exponentiation. This keeps arbitrarily large Python integers harmless.
    lower=math.ceil(12.*math.log2(expert.pitch_ratio_min))
    upper=math.floor(12.*math.log2(expert.pitch_ratio_max))
    return lower,upper


def _preflight_fields(bars,bpm,sample_rate_hz,events):
    if type(bars)is not int or not 1<=bars<=MAX_BARS:raise ZaagFamilyError(f'bars outside 1..{MAX_BARS}')
    bpm=_finite_number(bpm,'bpm')
    if not 60<=bpm<=260:raise ZaagFamilyError('bpm outside range')
    if type(sample_rate_hz)is not int or sample_rate_hz not in (12000,24000,48000):raise ZaagFamilyError('unsupported example sample rate')
    if type(events) not in (tuple,list):raise ZaagFamilyError('events must be a finite tuple/list')
    event_limit=bars*MAX_EVENTS_PER_BAR
    if len(events)>event_limit:raise ZaagFamilyError(f'arrangement has {len(events)} events; limit is {event_limit} ({MAX_EVENTS_PER_BAR} per bar)')
    total_beats=float(bars*BEATS_PER_BAR)
    normalized=[];voices=0;max_polyphony=0
    for index,row in enumerate(events):
        if type(row)is not dict or set(row)!=_EVENT_FIELDS:raise ZaagFamilyError(f'invalid arrangement event {index}: expected exactly {sorted(_EVENT_FIELDS)}')
        beat=_finite_number(row['beat'],f'event {index} beat')
        duration=_finite_number(row['duration_beats'],f'event {index} duration_beats')
        gain=_finite_number(row['gain_db'],f'event {index} gain_db')
        if beat<0 or beat>=total_beats:raise ZaagFamilyError(f'event {index} beat outside declared arrangement extent [0, {total_beats})')
        if duration<=0 or beat+duration>total_beats:raise ZaagFamilyError(f'event {index} duration extends outside declared arrangement extent')
        if not GAIN_DB_MIN<=gain<=GAIN_DB_MAX:raise ZaagFamilyError(f'event {index} gain_db outside [{GAIN_DB_MIN:g}, {GAIN_DB_MAX:g}] dB')
        fid=row['family_id']
        if type(fid)is not str:raise ZaagFamilyError(f'event {index} family_id must be a string')
        try:recipe=family(fid)
        except KeyError as exc:raise ZaagFamilyError(f'event {index} has unknown family_id {fid!r}') from exc
        if recipe.classification!='candidate':raise ZaagFamilyError('arranged examples use candidate families only')
        degrees=row['degrees']
        if type(degrees) not in (list,tuple) or not degrees:raise ZaagFamilyError(f'event {index} degrees must be a nonempty finite list/tuple')
        if len(degrees)>MAX_EVENT_POLYPHONY:raise ZaagFamilyError(f'event {index} has {len(degrees)} degrees; polyphony limit is {MAX_EVENT_POLYPHONY}')
        lower,upper=_degree_bounds(fid);checked=[]
        for degree in degrees:
            if type(degree)is not int:raise ZaagFamilyError(f'event {index} degrees must contain native integers')
            if not lower<=degree<=upper:
                raise ZaagFamilyError(f'{fid} event degree {degree} outside executable integer-degree range [{lower}, {upper}]')
            checked.append(degree)
        voices+=len(checked);max_polyphony=max(max_polyphony,len(checked))
        normalized.append({'beat':beat,'duration_beats':duration,'family_id':fid,'degrees':checked,'gain_db':gain})
    voice_limit=event_limit*MAX_EVENT_POLYPHONY
    if voices>voice_limit:raise ZaagFamilyError(f'arrangement has {voices} note voices; limit is {voice_limit}')
    spb=sample_rate_hz*60./bpm
    nominal_samples=round(total_beats*spb)
    tail_samples=math.ceil(MAX_SOURCE_TAIL_SECONDS*sample_rate_hz)
    maximum_output_samples=nominal_samples+tail_samples
    if maximum_output_samples>MAX_OUTPUT_SAMPLES:raise ZaagFamilyError('arrangement output extent exceeds global ZG-022 resource envelope')
    estimate={'event_count':len(normalized),'event_limit':event_limit,'note_voices':voices,'note_voice_limit':voice_limit,
              'max_polyphony':max_polyphony,'polyphony_limit':MAX_EVENT_POLYPHONY,'nominal_beats':total_beats,
              'nominal_samples':nominal_samples,'max_source_tail_samples':tail_samples,
              'maximum_output_samples':maximum_output_samples,'global_max_output_samples':MAX_OUTPUT_SAMPLES}
    return tuple(normalized),estimate,bpm


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
        events,_,bpm=_preflight_fields(self.bars,self.bpm,self.sample_rate_hz,self.events)
        object.__setattr__(self,'events',deepcopy(events));object.__setattr__(self,'bpm',bpm)
    def to_dict(self):return {'kind':'ZaagArrangementManifest','version':self.version,'id':self.id,'bars':self.bars,'bpm':self.bpm,'sample_rate_hz':self.sample_rate_hz,'description':self.description,'tuning':self.tuning,'source_policy':self.source_policy,'tail_policy':self.tail_policy,'normalization':self.normalization,'events':deepcopy(list(self.events))}
    @property
    def sha256(self):return canonical_sha256(self.to_dict())


def arrangement_work_estimate(manifest):
    """Return the exact admitted event/voice work and conservative output extent.

    This intentionally performs the same fail-closed validation as construction so
    a shared scheduler can use model-owned numbers rather than a caller estimate.
    """
    if not isinstance(manifest,ArrangementManifest):raise ZaagFamilyError('ArrangementManifest required')
    _,estimate,_=_preflight_fields(manifest.bars,manifest.bpm,manifest.sample_rate_hz,manifest.events)
    return deepcopy(estimate)


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
    events=[];roots=(0,-2,0,-3);families=('zaag.harmonic-turn','zaag.vowel-sway','zaag.complementary-pulse','zaag.grit-skip')
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
    validated_events,estimate,_=_preflight_fields(manifest.bars,manifest.bpm,manifest.sample_rate_hz,manifest.events)
    sr=manifest.sample_rate_hz;spb=sr*60./manifest.bpm;nominal=estimate['nominal_samples'];out=np.zeros(nominal,dtype=np.float64);sources={};pitch_cache={};source_counts={}
    for event in validated_events:
        fid=event['family_id']
        if fid not in sources:
            sources[fid]=render_family_source(family(fid),sr,beats=1).audio;source_counts[fid]=1
            if len(sources[fid])>estimate['max_source_tail_samples']:raise ZaagFamilyError(f'{fid} source render exceeds preflight tail envelope')
        base=sources[fid];start=round(event['beat']*spb);gate=max(1,round(event['duration_beats']*spb));gain=10**(event['gain_db']/20.)
        for degree in event['degrees']:
            # Degree admission already occurred via logarithmic bounds; exponentiation
            # is therefore limited to a small family-supported integer range.
            ratio=2**(degree/12.)
            key=(fid,degree)
            if key not in pitch_cache:pitch_cache[key]=pitch_shift_static(base,ratio,fft_size=2048)
            shifted=np.asarray(pitch_cache[key],dtype=np.float64);n=min(len(shifted),gate if family(fid).expert.tail_policy=='truncate' else len(shifted));note=shifted[:n].copy()
            if family(fid).expert.tail_policy=='truncate' and n>16:note=cosine_taper(note,min(n//4,round(.008*sr)))
            end=start+n
            if end>estimate['maximum_output_samples']:raise ZaagFamilyError('rendered note exceeds preflight output extent')
            if end>len(out):out=np.pad(out,(0,end-len(out)))
            out[start:end]+=gain*note
    audio=np.asarray(out,dtype=np.float32);diag={'method':'zg.zaag-arrangement.v1','manifest_sha256':manifest.sha256,'samples':len(audio),'events':len(manifest.events),'families':sorted(sources),'source_renders_per_family':source_counts,'pitch_cache_entries':len(pitch_cache),'source_policy':manifest.source_policy,'normalization':'none','peak':float(np.max(np.abs(audio),initial=0.)),'rms':float(np.sqrt(np.mean(audio.astype(np.float64)**2))) if len(audio) else 0.,'pcm_sha256':hashlib.sha256(audio.astype('<f4').tobytes()).hexdigest()}
    return ArrangementRender(audio,manifest,diag)
