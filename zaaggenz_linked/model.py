"""Versioned linked fake-out / reinterpretation / return authoring model."""
from __future__ import annotations
from dataclasses import dataclass
import json, math, re
from fractions import Fraction
from zaaggenz_contracts import digest
from zaaggenz_contracts.model import check_json, fraction, loads
from zaaggenz_harmony import SonoritySpec, SonorityTone
from zaaggenz_meter import MeterPlan

VERSION='1.0.0'
PHASES=('preparation','violation','bridge','return')
ROLES={'preparation':'establish','violation':'fakeout','bridge':'transition','return':'return'}
LAYERS=('synthline','exciter','body','aux','sub')
TRANSFORMS={
 'withheld-low-band-arrival':('violation','sub','deferred-explicit'),
 'motif-completion':('bridge','synthline','applied-source-derived'),
 'spectral-emergence':('bridge','aux','deferred-explicit'),
 'envelope-morph':('bridge','synthline','deferred-explicit'),
 'restore-phase-alignment':('bridge','body','deferred-explicit'),
}
VARIANTS={
 'baseline':(False,False,'neutral'),
 'violation-only':(True,False,'neutral'),
 'recovery-only':(False,True,'linked'),
 'both-linked':(True,True,'linked'),
 'both-unrelated':(True,True,'unrelated'),
}
_ID=re.compile(r'[a-z][a-z0-9_.-]{0,63}\Z')

class LinkedEventError(ValueError): pass

def exact(v,keys,name):
    if type(v) is not dict or set(v)!=set(keys): raise LinkedEventError(f'{name}: expected exact fields')
def ident(v,name):
    if type(v) is not str or not _ID.fullmatch(v): raise LinkedEventError(f'{name}: lowercase identifier required')
    return v
def integer(v,lo,hi,name):
    if type(v) is not int or not lo<=v<=hi: raise LinkedEventError(f'{name}: integer out of bounds')
    return v
def number(v,lo,hi,name):
    if type(v) not in (int,float) or type(v) is bool or not math.isfinite(float(v)) or not lo<=float(v)<=hi: raise LinkedEventError(f'{name}: finite value out of bounds')
    return float(v)
def rat(v,name,positive=False,nonnegative=False):
    try:q=fraction(v)
    except Exception as exc: raise LinkedEventError(f'{name}: reduced rational required') from exc
    if positive and q<=0: raise LinkedEventError(f'{name}: positive rational required')
    if nonnegative and q<0: raise LinkedEventError(f'{name}: nonnegative rational required')
    return q

def sonority_from_dict(data):
    exact(data,{'id','root_degree','tones','bass_tone_id','context_id'},'sonority')
    try:
        tones=[]
        if type(data['tones']) is not list: raise LinkedEventError('sonority tones list required')
        for t in data['tones']:
            exact(t,{'id','degree_offset','ratio','detune_cents','required'},'sonority tone')
            tones.append(SonorityTone(**t))
        return SonoritySpec(data['id'],data['root_degree'],tuple(tones),data['bass_tone_id'],data['context_id'])
    except LinkedEventError: raise
    except Exception as exc: raise LinkedEventError(f'invalid harmony destination: {exc}') from exc

def validate_plan(data):
    try:check_json(data)
    except Exception as exc:raise LinkedEventError(str(exc)) from exc
    exact(data,{'format','version','id','description','end_beat','source_family','phases','preparation','local_expectation','bridge','return_destination','return_sonority','meter_plan','stable_clock_id','transforms','engine_model'},'linked plan')
    if data['format']!='zaaggenz-linked-return' or data['version']!=VERSION:raise LinkedEventError('unsupported linked-return format/version')
    ident(data['id'],'plan.id');ident(data['source_family'],'source_family')
    if type(data['description']) is not str or not data['description'].strip() or len(data['description'])>2048:raise LinkedEventError('bounded description required')
    end=rat(data['end_beat'],'end_beat',positive=True)
    if end>256:raise LinkedEventError('end_beat exceeds bound')
    phases=data['phases']
    if type(phases) is not list or [p.get('name') if type(p) is dict else None for p in phases]!=list(PHASES):raise LinkedEventError('phase order invalid')
    previous=Fraction(0)
    for p in phases:
        exact(p,{'name','start_beat','end_beat','role','layers'},'phase')
        start,stop=rat(p['start_beat'],'phase.start',nonnegative=True),rat(p['end_beat'],'phase.end',positive=True)
        if start!=previous or not start<stop<=end:raise LinkedEventError('phases must be contiguous and bounded')
        previous=stop
        if p['role']!=ROLES[p['name']]:raise LinkedEventError('phase role mismatch')
        if type(p['layers']) is not list or not p['layers'] or len(set(p['layers']))!=len(p['layers']) or any(x not in LAYERS for x in p['layers']):raise LinkedEventError('phase layers invalid')
    if previous!=end:raise LinkedEventError('phase sequence must end at end_beat')
    by={p['name']:p for p in phases}
    prep=data['preparation'];exact(prep,{'step_beats','degrees','duration_beats','gain_db'},'preparation')
    step=rat(prep['step_beats'],'preparation.step',positive=True);gate=rat(prep['duration_beats'],'preparation.duration',positive=True)
    if type(prep['degrees']) is not list or not prep['degrees']:raise LinkedEventError('preparation degrees required')
    for d in prep['degrees']:integer(d,-4096,4096,'preparation degree')
    number(prep['gain_db'],-120,24,'preparation gain')
    prep_len=rat(by['preparation']['end_beat'],'prep end')-rat(by['preparation']['start_beat'],'prep start')
    if len(prep['degrees'])*step>prep_len or gate>step:raise LinkedEventError('preparation motif does not fit phase')
    local=data['local_expectation'];exact(local,{'beat','duration_beats','expected_degree','substitute_degree','detune_cents','gain_db'},'local expectation')
    beat=rat(local['beat'],'local.beat',nonnegative=True);lgate=rat(local['duration_beats'],'local.duration',positive=True)
    if not rat(by['violation']['start_beat'],'vstart')<=beat<beat+lgate<=rat(by['violation']['end_beat'],'vend'):raise LinkedEventError('local expectation must lie in violation phase')
    integer(local['expected_degree'],-4096,4096,'expected degree');integer(local['substitute_degree'],-4096,4096,'substitute degree')
    if local['expected_degree']==local['substitute_degree']:raise LinkedEventError('substitute must differ from expected degree')
    number(local['detune_cents'],-4800,4800,'local detune');number(local['gain_db'],-120,24,'local gain')
    bridge=data['bridge'];exact(bridge,{'step_beats','duration_beats','gain_db','neutral_degree_offsets','unrelated_degree_offsets'},'bridge')
    bstep=rat(bridge['step_beats'],'bridge.step',positive=True);bgate=rat(bridge['duration_beats'],'bridge.duration',positive=True);number(bridge['gain_db'],-120,24,'bridge gain')
    bstart,bstop=rat(by['bridge']['start_beat'],'bstart'),rat(by['bridge']['end_beat'],'bstop');count=(bstop-bstart)/bstep
    if count.denominator!=1 or not 1<=count<=64 or bgate>bstep:raise LinkedEventError('bridge grid invalid')
    for key in ('neutral_degree_offsets','unrelated_degree_offsets'):
        arr=bridge[key]
        if type(arr) is not list or len(arr)!=int(count):raise LinkedEventError('bridge offsets must match event count')
        for d in arr:integer(d,-128,128,key)
    ret=data['return_destination'];exact(ret,{'beat','duration_beats','degree','detune_cents','gain_db'},'return destination')
    rbeat=rat(ret['beat'],'return.beat',nonnegative=True);rgate=rat(ret['duration_beats'],'return.duration',positive=True)
    if not rat(by['return']['start_beat'],'rstart')<=rbeat<rbeat+rgate<=rat(by['return']['end_beat'],'rend') or rbeat+rgate!=end:raise LinkedEventError('return destination must occupy final interval')
    integer(ret['degree'],-4096,4096,'return degree');number(ret['detune_cents'],-4800,4800,'return detune');number(ret['gain_db'],-120,24,'return gain')
    son=sonority_from_dict(data['return_sonority']);allowed={son.root_degree}
    for t in son.tones:
        if t.degree_offset is not None:allowed.add(son.root_degree+t.degree_offset)
    if ret['degree'] not in allowed:raise LinkedEventError('return degree not represented by harmony target')
    try:meter=MeterPlan(data['meter_plan'])
    except Exception as exc:raise LinkedEventError(f'invalid meter plan: {exc}') from exc
    if meter.to_dict()['end_beat']!=data['end_beat']:raise LinkedEventError('meter plan length mismatch')
    if data['stable_clock_id']!=meter.to_dict()['stable_clock_id']:raise LinkedEventError('stable clock mismatch')
    transforms=data['transforms']
    if type(transforms) is not list or set(x.get('kind') for x in transforms if type(x) is dict)!=set(TRANSFORMS):raise LinkedEventError('all transform families required')
    for x in transforms:
        exact(x,{'kind','phase','layer','apply_policy'},'transform');expected=TRANSFORMS[x['kind']]
        if (x['phase'],x['layer'],x['apply_policy'])!=expected:raise LinkedEventError('transform policy mismatch')
    state=data['engine_model'];exact(state,{'local_prediction_probability','destination_probability','uncertainty','semantics'},'engine model')
    for k in ('local_prediction_probability','destination_probability','uncertainty'):number(state[k],0,1,k)
    if state['semantics']!='generator-state-not-listener-outcome':raise LinkedEventError('engine model must be labelled as generator state')

@dataclass(frozen=True,init=False)
class LinkedEventPlan:
    _json:str
    def __init__(self,data):validate_plan(data);object.__setattr__(self,'_json',json.dumps(data,sort_keys=True,separators=(',',':'),allow_nan=False))
    def to_dict(self):return loads(self._json)
    @property
    def sha256(self):return digest(self.to_dict())
    @classmethod
    def from_json(cls,text):return cls(loads(text))

@dataclass(frozen=True)
class ControlledVariant:
    name:str
    def __post_init__(self):
        if self.name not in VARIANTS:raise LinkedEventError('unknown controlled variant')
    @property
    def violation(self):return VARIANTS[self.name][0]
    @property
    def recovery(self):return VARIANTS[self.name][1]
    @property
    def linkage(self):return VARIANTS[self.name][2]
    def to_dict(self):return {'name':self.name,'violation':self.violation,'recovery':self.recovery,'linkage':self.linkage}
