from __future__ import annotations
from dataclasses import dataclass
from .core import Tuning,TuningError,tuning_from_spec

@dataclass(frozen=True)
class PitchTarget:
    tuning_id:str
    degree:int
    detune_cents:float
    frequency_hz:float
    source:str

def resolve_pitch_target(tuning_or_spec,*,degree=None,key=None,detune_cents=0.0,root_hz=None,root_degree=None):
    """One pitch-target API for CLI/keyboard/SYNTH/AUX consumers. Unmapped key => explicit rest (`None`)."""
    t=tuning_or_spec if isinstance(tuning_or_spec,Tuning) else tuning_from_spec(tuning_or_spec)
    if (degree is None)==(key is None):raise TuningError('provide exactly one of degree or key')
    if key is not None:
        d=t.keyboard_degree(key)
        if d is None:return None
        degree=d;source='keyboard'
    else:
        if type(degree)is not int:raise TuningError('degree must be integer')
        source='degree'
    hz=t.frequency(degree,detune_cents,root_hz,root_degree)
    return PitchTarget(t.id,degree,float(detune_cents),hz,source)
