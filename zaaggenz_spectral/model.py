from __future__ import annotations
from copy import deepcopy
from dataclasses import dataclass
import math
from zaaggenz_tuning import tuning_from_spec

METHOD_ID='zg-partial-spectral-retune-v1'
METHOD_VERSION='1.0.0'

class SpectralRetuneError(ValueError):pass

def _finite(v,name):
    if type(v) not in (int,float) or type(v) is bool or not math.isfinite(float(v)):
        raise SpectralRetuneError(f'{name} must be finite')
    return float(v)

def _positive(v,name):
    v=_finite(v,name)
    if v<=0:raise SpectralRetuneError(f'{name} must be positive')
    return v

@dataclass(frozen=True)
class LatticeVoice:
    degree:int
    partial_ratios:tuple[float,...]=(1.,2.,3.,4.,5.,6.,7.,8.)
    label:str=''
    def __post_init__(self):
        if type(self.degree)is not int:raise SpectralRetuneError('voice degree must be integer')
        ratios=tuple(_positive(v,'partial ratio') for v in self.partial_ratios)
        if not 1<=len(ratios)<=128:raise SpectralRetuneError('voice requires 1..128 partial ratios')
        if any(a>=b for a,b in zip(ratios,ratios[1:])):raise SpectralRetuneError('partial ratios must increase')
        if type(self.label)is not str or len(self.label)>64:raise SpectralRetuneError('invalid voice label')
        object.__setattr__(self,'partial_ratios',ratios)

@dataclass(frozen=True)
class SpectralRetuneRequest:
    tuning_spec:dict
    voices:tuple[LatticeVoice,...]
    amount:float=1.
    min_confidence:float=.55
    min_hz:float=30.
    max_hz:float=6000.
    max_displacement_cents:float=350.
    max_correction_slew_cents_per_second:float=1800.
    assignment_hysteresis_cents:float=35.
    preserve_ambiguous:bool=True
    def __post_init__(self):
        if not isinstance(self.tuning_spec,dict):raise SpectralRetuneError('TuningSpec mapping required')
        try:tuning_from_spec(self.tuning_spec)
        except Exception as exc:raise SpectralRetuneError('valid TuningSpec required') from exc
        voices=tuple(self.voices)
        if not 1<=len(voices)<=32 or any(not isinstance(v,LatticeVoice) for v in voices):raise SpectralRetuneError('1..32 LatticeVoice values required')
        amount=_finite(self.amount,'amount');confidence=_finite(self.min_confidence,'min_confidence')
        lo=_positive(self.min_hz,'min_hz');hi=_positive(self.max_hz,'max_hz')
        disp=_positive(self.max_displacement_cents,'max_displacement_cents')
        slew=_positive(self.max_correction_slew_cents_per_second,'max_correction_slew_cents_per_second')
        hysteresis=_finite(self.assignment_hysteresis_cents,'assignment_hysteresis_cents')
        if not 0<=amount<=1:raise SpectralRetuneError('amount must be in [0,1]')
        if not 0<=confidence<=1:raise SpectralRetuneError('min_confidence must be in [0,1]')
        if lo>=hi:raise SpectralRetuneError('min_hz must be below max_hz')
        if not 0<=hysteresis<=disp:raise SpectralRetuneError('invalid assignment hysteresis')
        if type(self.preserve_ambiguous)is not bool:raise SpectralRetuneError('preserve_ambiguous must be bool')
        object.__setattr__(self,'tuning_spec',deepcopy(self.tuning_spec));object.__setattr__(self,'voices',voices)
        object.__setattr__(self,'amount',amount);object.__setattr__(self,'min_confidence',confidence)
        object.__setattr__(self,'min_hz',lo);object.__setattr__(self,'max_hz',hi)
        object.__setattr__(self,'max_displacement_cents',disp);object.__setattr__(self,'max_correction_slew_cents_per_second',slew)
        object.__setattr__(self,'assignment_hysteresis_cents',hysteresis)

@dataclass(frozen=True)
class TargetTooth:
    id:str;voice_index:int;degree:int;partial_index:int;ratio:float;frequency_hz:float;label:str=''

@dataclass(frozen=True)
class FrameDecision:
    track_id:str;frame_index:int;anchor_sample:int;source_hz:float;requested_hz:float|None
    realised_hz:float;correction_cents:float;confidence:float;source_action:str;decision:str
    reason:str;tooth_id:str|None;phase_correction_radians:float
    def to_dict(self):return dict(track_id=self.track_id,frame_index=self.frame_index,anchor_sample=self.anchor_sample,source_hz=self.source_hz,requested_hz=self.requested_hz,realised_hz=self.realised_hz,correction_cents=self.correction_cents,confidence=self.confidence,source_action=self.source_action,decision=self.decision,reason=self.reason,tooth_id=self.tooth_id,phase_correction_radians=self.phase_correction_radians)
