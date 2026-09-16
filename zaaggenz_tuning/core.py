from __future__ import annotations
from dataclasses import dataclass
import math
from copy import deepcopy
from zaaggenz_contracts import validate
from zaaggenz_contracts.legacy import envelope
from zaaggenz_contracts.tuning_rules import formal_period_degrees_description, valid_formal_period_degrees

class TuningError(ValueError): pass

def _finite_positive(x,name):
    if type(x) not in (int,float) or type(x) is bool or not math.isfinite(float(x)) or float(x)<=0:
        raise TuningError(f'{name} must be finite and positive')
    return float(x)

def cents_to_ratio(cents):
    if type(cents) not in (int,float) or type(cents) is bool or not math.isfinite(float(cents)):
        raise TuningError('cents must be finite')
    return 2.0**(float(cents)/1200.0)

def ratio_to_cents(ratio):
    return 1200.0*math.log2(_finite_positive(ratio,'ratio'))

@dataclass(frozen=True)
class KeyboardMap:
    first_key:int
    last_key:int
    middle_key:int
    reference_key:int
    formal_period_degrees:int
    entries:tuple[int|None,...]
    def __post_init__(self):
        if not (0<=self.first_key<=self.last_key<=127 and 0<=self.middle_key<=127 and 0<=self.reference_key<=127):
            raise TuningError('keyboard key range must be MIDI 0..127')
        if not 1<=len(self.entries)<=128: raise TuningError('keyboard map requires 1..128 entries')
        if not valid_formal_period_degrees(self.formal_period_degrees):
            raise TuningError('formal period degrees must be '+formal_period_degrees_description())
        for x in self.entries:
            if x is not None and (type(x)is not int or not -4096<=x<=4096):raise TuningError('invalid keyboard degree')
    def degree(self,key):
        if type(key)is not int or not 0<=key<=127:raise TuningError('keyboard key must be MIDI integer 0..127')
        if not self.first_key<=key<=self.last_key:return None
        q,r=divmod(key-self.middle_key,len(self.entries));entry=self.entries[r]
        return None if entry is None else q*self.formal_period_degrees+entry

@dataclass(frozen=True)
class Tuning:
    id:str
    reference_hz:float
    reference_degree:int
    period_ratio:float
    degree_ratios:tuple[float,...]
    keyboard:KeyboardMap|None=None
    description:str=''
    provenance:str='explicit'
    def __post_init__(self):
        if not isinstance(self.id,str) or not self.id:raise TuningError('tuning id required')
        _finite_positive(self.reference_hz,'reference_hz');p=_finite_positive(self.period_ratio,'period_ratio')
        if p<=1:raise TuningError('period ratio must be > 1')
        if type(self.reference_degree)is not int:raise TuningError('reference degree must be integer')
        if not self.degree_ratios or len(self.degree_ratios)>256:raise TuningError('1..256 explicit degrees required')
        ratios=tuple(_finite_positive(x,'degree ratio') for x in self.degree_ratios)
        if abs(ratios[0]-1.0)>1e-14:raise TuningError('degree zero must be unison')
        if any(a>=b for a,b in zip(ratios,ratios[1:])):raise TuningError('degree ratios must increase')
        if ratios[-1]>=p:raise TuningError('explicit degrees must exclude the period')
        if self.keyboard is not None:
            rd=self.keyboard.degree(self.keyboard.reference_key)
            if rd is None or rd!=self.reference_degree:raise TuningError('keyboard reference disagrees with tuning reference degree')
    @property
    def degrees_per_period(self):return len(self.degree_ratios)
    def degree_ratio(self,degree):
        if type(degree)is not int:raise TuningError('degree must be integer')
        q,r=divmod(degree,self.degrees_per_period)
        try:return self.period_ratio**q*self.degree_ratios[r]
        except OverflowError as exc:raise TuningError('degree frequency ratio overflow') from exc
    def relative_ratio(self,degree,reference_degree=None):
        ref=self.reference_degree if reference_degree is None else reference_degree
        if type(ref)is not int:raise TuningError('reference degree must be integer')
        return self.degree_ratio(degree)/self.degree_ratio(ref)
    def frequency(self,degree,detune_cents=0.0,root_hz=None,root_degree=None):
        anchor=_finite_positive(self.reference_hz if root_hz is None else root_hz,'root_hz')
        ref=self.reference_degree if root_degree is None else root_degree
        ratio=self.relative_ratio(degree,ref)*cents_to_ratio(detune_cents)
        out=anchor*ratio
        if not math.isfinite(out) or out<=0:raise TuningError('frequency overflow')
        return out
    def keyboard_degree(self,key):return None if self.keyboard is None else self.keyboard.degree(key)
    def keyboard_frequency(self,key,detune_cents=0.0):
        degree=self.keyboard_degree(key)
        return None if degree is None else self.frequency(degree,detune_cents)

def tuning_from_spec(spec,description='',provenance='contract'):
    validate(spec,'TuningSpec');k=spec['keyboard']
    keyboard=None if k is None else KeyboardMap(k['first_key'],k['last_key'],k['middle_key'],k['reference_key'],k['formal_period_degrees'],tuple(k['entries']))
    return Tuning(spec['id'],spec['reference_hz'],spec['reference_degree'],spec['period_ratio'],tuple(spec['degree_ratios']),keyboard,description,provenance)

def tuning_to_spec(tuning):
    if not isinstance(tuning,Tuning):raise TuningError('Tuning required')
    k=tuning.keyboard
    keyboard=None if k is None else dict(first_key=k.first_key,last_key=k.last_key,middle_key=k.middle_key,reference_key=k.reference_key,formal_period_degrees=k.formal_period_degrees,entries=list(k.entries))
    spec=envelope('TuningSpec',id=tuning.id,reference_hz=tuning.reference_hz,reference_degree=tuning.reference_degree,period_ratio=tuning.period_ratio,degree_ratios=list(tuning.degree_ratios),keyboard=keyboard)
    validate(spec,'TuningSpec');return spec

def frequency_for_degree(tuning_or_spec,degree,detune_cents=0.0,*,root_hz=None,root_degree=None):
    t=tuning_or_spec if isinstance(tuning_or_spec,Tuning) else tuning_from_spec(tuning_or_spec)
    return t.frequency(degree,detune_cents,root_hz,root_degree)

def transpose_frequency(tuning_or_spec,frequency_hz,degree_steps,detune_cents=0.0):
    t=tuning_or_spec if isinstance(tuning_or_spec,Tuning) else tuning_from_spec(tuning_or_spec)
    f=_finite_positive(frequency_hz,'frequency_hz')
    if type(degree_steps)is not int:raise TuningError('degree_steps must be integer')
    return f*t.relative_ratio(t.reference_degree+degree_steps,t.reference_degree)*cents_to_ratio(detune_cents)

def analyse_frequency(tuning_or_spec,frequency_hz):
    """Nearest tuning coordinate relative to the immutable tuning reference; never mutates/retunes it."""
    t=tuning_or_spec if isinstance(tuning_or_spec,Tuning) else tuning_from_spec(tuning_or_spec)
    f=_finite_positive(frequency_hz,'frequency_hz');target=f/t.reference_hz
    approx=t.reference_degree+round(math.log(target,t.period_ratio)*t.degrees_per_period)
    candidates=range(approx-t.degrees_per_period-2,approx+t.degrees_per_period+3)
    degree=min(candidates,key=lambda d:abs(ratio_to_cents(target/t.relative_ratio(d))))
    expected=t.frequency(degree);detune=ratio_to_cents(f/expected)
    return {'degree':degree,'detune_cents':detune,'expected_hz':expected,'observed_hz':f,'tuning_id':t.id}
