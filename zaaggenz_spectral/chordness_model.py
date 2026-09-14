from __future__ import annotations
from dataclasses import dataclass
from copy import deepcopy
import json,math,re

class ChordnessError(ValueError):pass
ID=re.compile(r'^[a-z][a-z0-9_.-]{0,63}$')
MODES={'off','reweight','retune','hybrid'}
SELECTION_MODES={'manual','descriptor'}

def _finite(v,name):
    if type(v) not in (int,float) or type(v)is bool or not math.isfinite(float(v)):
        raise ChordnessError(f'{name} must be finite')
    return float(v)

def _bound(v,name,lo,hi):
    v=_finite(v,name)
    if not lo<=v<=hi:raise ChordnessError(f'{name} must be in [{lo},{hi}]')
    return v

def _json_source(v):
    if v is None:return {}
    if type(v)is not dict:raise ChordnessError('source must be a mapping')
    try:text=json.dumps(v,allow_nan=False,sort_keys=True,separators=(',',':'))
    except (TypeError,ValueError) as exc:raise ChordnessError('source metadata must be JSON serialisable') from exc
    if len(text.encode('utf-8'))>8192:raise ChordnessError('source metadata too large')
    return deepcopy(v)

@dataclass(frozen=True)
class CombTemplate:
    id:str
    teeth_hz:tuple[float,...]
    tooth_capacity:int=1
    label:str=''
    source:dict|None=None
    def __post_init__(self):
        if type(self.id)is not str or not ID.fullmatch(self.id):raise ChordnessError('invalid comb id')
        try:teeth=tuple(float(x) for x in self.teeth_hz)
        except Exception as exc:raise ChordnessError('teeth_hz must be numeric') from exc
        if not 1<=len(teeth)<=128 or any(not math.isfinite(x) or x<=0 for x in teeth):raise ChordnessError('comb requires 1..128 positive finite teeth')
        if any(a>=b for a,b in zip(teeth,teeth[1:])):raise ChordnessError('comb teeth must be strictly increasing')
        if type(self.tooth_capacity)is not int or type(self.tooth_capacity)is bool or not 1<=self.tooth_capacity<=16:raise ChordnessError('tooth_capacity must be integer 1..16')
        if type(self.label)is not str or len(self.label)>128:raise ChordnessError('invalid comb label')
        object.__setattr__(self,'teeth_hz',teeth);object.__setattr__(self,'source',_json_source(self.source))
    def to_dict(self):return {'id':self.id,'teeth_hz':list(self.teeth_hz),'tooth_capacity':self.tooth_capacity,'label':self.label,'source':deepcopy(self.source)}

@dataclass(frozen=True)
class ChordnessCoefficients:
    target_fit:float=1.
    roughness:float=.25
    density_penalty:float=.02
    reassignment_cents:float=.10
    gain_motion_db:float=.05
    def __post_init__(self):
        for name in ('target_fit','roughness','density_penalty','reassignment_cents','gain_motion_db'):
            object.__setattr__(self,name,_bound(getattr(self,name),name,0.,100.))
    def to_dict(self):return {k:float(getattr(self,k)) for k in ('target_fit','roughness','density_penalty','reassignment_cents','gain_motion_db')}
