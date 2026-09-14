from __future__ import annotations
from dataclasses import dataclass
import math,re
from .dissonance_model import DissonanceError,DissonanceModelSpec,TimbreSpectrum

ADAPTIVE_METHOD_ID='zg.bounded_adaptive_tuning.v1'
ADAPTIVE_VERSION='1.0.0'
ID=re.compile(r'^[a-z][a-z0-9_.-]{0,63}$')
ROLES={'voice','root','pedal'}

def _finite(v,name):
    if type(v) not in (int,float) or type(v)is bool or not math.isfinite(float(v)):raise DissonanceError(f'{name} must be finite')
    return float(v)

def _bound(v,name,lo,hi):
    v=_finite(v,name)
    if not lo<=v<=hi:raise DissonanceError(f'{name} must be in [{lo},{hi}]')
    return v

@dataclass(frozen=True)
class AdaptiveVoice:
    id:str
    nominal_cents:float
    spectrum:TimbreSpectrum
    role:str='voice'
    locked:bool=False
    def __post_init__(self):
        if type(self.id)is not str or not ID.fullmatch(self.id):raise DissonanceError('invalid adaptive voice id')
        if not isinstance(self.spectrum,TimbreSpectrum):raise DissonanceError('voice requires TimbreSpectrum')
        if self.role not in ROLES:raise DissonanceError('invalid adaptive voice role')
        if type(self.locked)is not bool:raise DissonanceError('locked must be bool')
        object.__setattr__(self,'nominal_cents',_finite(self.nominal_cents,'nominal_cents'))
    def to_dict(self):return {'id':self.id,'nominal_cents':self.nominal_cents,'spectrum':self.spectrum.to_dict(),'role':self.role,'locked':self.locked}

@dataclass(frozen=True)
class AdaptiveWeights:
    tension:float=1.
    voice_leading:float=.18
    drift:float=.12
    candidate_proximity:float=.08
    def __post_init__(self):
        for name in ('tension','voice_leading','drift','candidate_proximity'):
            object.__setattr__(self,name,_bound(getattr(self,name),name,0.,100.))
    def to_dict(self):return {name:getattr(self,name) for name in ('tension','voice_leading','drift','candidate_proximity')}

@dataclass(frozen=True)
class AdaptiveTuningRequest:
    voices:tuple[AdaptiveVoice,...]
    candidate_intervals_cents:tuple[float,...]
    root_voice_id:str
    desired_tension:float=0.
    root_lock:bool=True
    max_total_drift_cents:float=60.
    max_step_cents:float=12.
    search_step_cents:float=2.
    min_separation_cents:float=20.
    min_source_confidence:float=.5
    max_passes:int=3
    weights:AdaptiveWeights=AdaptiveWeights()
    model:DissonanceModelSpec=DissonanceModelSpec()
    def __post_init__(self):
        voices=tuple(self.voices)
        if not 2<=len(voices)<=12 or any(not isinstance(v,AdaptiveVoice) for v in voices):raise DissonanceError('adaptive tuning requires 2..12 voices')
        ids=[v.id for v in voices]
        if len(ids)!=len(set(ids)) or self.root_voice_id not in ids:raise DissonanceError('voice ids must be unique and root_voice_id must exist')
        roots=[v for v in voices if v.role=='root']
        if roots and any(v.id!=self.root_voice_id for v in roots):raise DissonanceError('root role conflicts with root_voice_id')
        try:candidates=tuple(sorted(set(float(x) for x in self.candidate_intervals_cents)))
        except Exception as exc:raise DissonanceError('candidate intervals must be numeric') from exc
        if not candidates or len(candidates)>128 or any(not math.isfinite(x) or not 0<=x<=1200 for x in candidates):raise DissonanceError('candidate intervals must contain 1..128 finite values in [0,1200]')
        if type(self.root_lock)is not bool:raise DissonanceError('root_lock must be bool')
        total=_bound(self.max_total_drift_cents,'max_total_drift_cents',0.,600.);step=_bound(self.max_step_cents,'max_step_cents',0.,120.);search=_bound(self.search_step_cents,'search_step_cents',.1,60.)
        if step>total and total>0:raise DissonanceError('max_step_cents cannot exceed total drift bound')
        if search>max(step,.1):raise DissonanceError('search_step_cents cannot exceed max step')
        sep=_bound(self.min_separation_cents,'min_separation_cents',0.,600.)
        if type(self.max_passes)is not int or not 1<=self.max_passes<=8:raise DissonanceError('max_passes must be 1..8')
        if not isinstance(self.weights,AdaptiveWeights):raise DissonanceError('AdaptiveWeights required')
        if not isinstance(self.model,DissonanceModelSpec):raise DissonanceError('DissonanceModelSpec required')
        object.__setattr__(self,'voices',voices);object.__setattr__(self,'candidate_intervals_cents',candidates)
        object.__setattr__(self,'desired_tension',_bound(self.desired_tension,'desired_tension',0.,1.));object.__setattr__(self,'max_total_drift_cents',total)
        object.__setattr__(self,'max_step_cents',step);object.__setattr__(self,'search_step_cents',search);object.__setattr__(self,'min_separation_cents',sep)
        object.__setattr__(self,'min_source_confidence',_bound(self.min_source_confidence,'min_source_confidence',0.,1.))
    def to_dict(self):return {'kind':'AdaptiveTuningRequest','version':ADAPTIVE_VERSION,'method_id':ADAPTIVE_METHOD_ID,'voices':[v.to_dict() for v in self.voices],
        'candidate_intervals_cents':list(self.candidate_intervals_cents),'root_voice_id':self.root_voice_id,'desired_tension':self.desired_tension,
        'root_lock':self.root_lock,'max_total_drift_cents':self.max_total_drift_cents,'max_step_cents':self.max_step_cents,'search_step_cents':self.search_step_cents,
        'min_separation_cents':self.min_separation_cents,'min_source_confidence':self.min_source_confidence,'max_passes':self.max_passes,
        'weights':self.weights.to_dict(),'dissonance_model':self.model.to_dict(),'amplitude_policy':'immutable; adaptive tuning changes pitch only'}

@dataclass(frozen=True)
class AdaptiveState:
    offsets_cents:tuple[tuple[str,float],...]=()
    step_index:int=0
    def __post_init__(self):
        rows=tuple((str(k),_finite(v,'state offset')) for k,v in self.offsets_cents)
        if len({k for k,_ in rows})!=len(rows):raise DissonanceError('duplicate state voice id')
        if type(self.step_index)is not int or self.step_index<0:raise DissonanceError('step_index must be nonnegative integer')
        object.__setattr__(self,'offsets_cents',tuple(sorted(rows)))
    def mapping(self):return dict(self.offsets_cents)
    def to_dict(self):return {'offsets_cents':dict(self.offsets_cents),'step_index':self.step_index}
