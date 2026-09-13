from __future__ import annotations
from dataclasses import dataclass
from copy import deepcopy
import math,re
from zaaggenz_contracts import digest

class HarmonyError(ValueError):pass
ID=re.compile(r'^[a-z][a-z0-9_.-]{0,63}$')

def _id(v,name='id'):
    if type(v)is not str or not ID.fullmatch(v):raise HarmonyError(f'invalid {name}')
    return v

def _finite(v,name):
    if type(v) not in (int,float) or type(v)is bool or not math.isfinite(float(v)):raise HarmonyError(f'{name} must be finite')
    return float(v)

@dataclass(frozen=True)
class SonorityTone:
    id:str
    degree_offset:int|None=None
    ratio:float|None=None
    detune_cents:float=0.
    required:bool=True
    def __post_init__(self):
        _id(self.id,'tone id')
        if (self.degree_offset is None)==(self.ratio is None):raise HarmonyError('tone requires exactly one of degree_offset or ratio')
        if self.degree_offset is not None and (type(self.degree_offset)is not int or type(self.degree_offset)is bool or not -4096<=self.degree_offset<=4096):raise HarmonyError('degree_offset out of range')
        if self.ratio is not None:
            r=_finite(self.ratio,'ratio')
            if not 1/64<=r<=64:raise HarmonyError('ratio out of range')
        d=_finite(self.detune_cents,'detune_cents')
        if not -4800<=d<=4800:raise HarmonyError('detune_cents out of range')
        if type(self.required)is not bool:raise HarmonyError('required must be boolean')
    def to_dict(self):return dict(id=self.id,degree_offset=self.degree_offset,ratio=None if self.ratio is None else float(self.ratio),detune_cents=float(self.detune_cents),required=self.required)

@dataclass(frozen=True)
class SonoritySpec:
    id:str
    root_degree:int
    tones:tuple[SonorityTone,...]
    bass_tone_id:str|None=None
    context_id:str|None=None
    def __post_init__(self):
        _id(self.id,'sonority id')
        if type(self.root_degree)is not int or type(self.root_degree)is bool or not -4096<=self.root_degree<=4096:raise HarmonyError('root_degree out of range')
        tones=tuple(self.tones)
        if not 1<=len(tones)<=12 or any(not isinstance(t,SonorityTone) for t in tones):raise HarmonyError('sonority requires 1..12 tones')
        if len({t.id for t in tones})!=len(tones):raise HarmonyError('duplicate tone id')
        if self.bass_tone_id is not None and self.bass_tone_id not in {t.id for t in tones}:raise HarmonyError('bass_tone_id not in sonority')
        if self.context_id is not None:_id(self.context_id,'context id')
        object.__setattr__(self,'tones',tones)
    def to_dict(self):return dict(id=self.id,root_degree=self.root_degree,tones=[t.to_dict() for t in self.tones],bass_tone_id=self.bass_tone_id,context_id=self.context_id)

@dataclass(frozen=True)
class VoiceSpec:
    id:str
    role:str
    min_hz:float
    max_hz:float
    preferred_hz:float
    max_leap_cents:float=2400.
    anchor_policy:str='moving'
    fixed_hz:float|None=None
    def __post_init__(self):
        _id(self.id,'voice id')
        if self.role not in ('sub','body','aux','synthline'):raise HarmonyError('invalid voice role')
        lo=_finite(self.min_hz,'min_hz');hi=_finite(self.max_hz,'max_hz');pref=_finite(self.preferred_hz,'preferred_hz');leap=_finite(self.max_leap_cents,'max_leap_cents')
        if not 1<=lo<pref<hi<=96000:raise HarmonyError('invalid voice frequency range/preference')
        if not 1<=leap<=9600:raise HarmonyError('invalid max leap')
        if self.anchor_policy not in ('moving','hold-first','fixed-hz'):raise HarmonyError('invalid anchor policy')
        if self.anchor_policy=='fixed-hz':
            f=_finite(self.fixed_hz,'fixed_hz') if self.fixed_hz is not None else None
            if f is None or not lo<=f<=hi:raise HarmonyError('fixed-hz voice requires in-range fixed_hz')
        elif self.fixed_hz is not None:raise HarmonyError('fixed_hz is only valid for fixed-hz anchor policy')
    def to_dict(self):return dict(id=self.id,role=self.role,min_hz=float(self.min_hz),max_hz=float(self.max_hz),preferred_hz=float(self.preferred_hz),max_leap_cents=float(self.max_leap_cents),anchor_policy=self.anchor_policy,fixed_hz=None if self.fixed_hz is None else float(self.fixed_hz))

@dataclass(frozen=True)
class VoicingConstraints:
    voices:tuple[VoiceSpec,...]
    min_spacing_cents:float=0.
    movement_weight:float=1.
    register_weight:float=.06
    max_register_shifts:int=32
    candidate_cap_per_voice:int=128
    target_harmonics:int=12
    target_max_hz:float=12000.
    target_max_teeth:int=128
    def __post_init__(self):
        voices=tuple(self.voices)
        if not 1<=len(voices)<=8 or any(not isinstance(v,VoiceSpec) for v in voices):raise HarmonyError('1..8 voices required')
        if len({v.id for v in voices})!=len(voices):raise HarmonyError('duplicate voice id')
        if any(a.preferred_hz>=b.preferred_hz for a,b in zip(voices,voices[1:])):raise HarmonyError('voices must be ordered low-to-high by preferred_hz')
        spacing=_finite(self.min_spacing_cents,'min_spacing_cents');mw=_finite(self.movement_weight,'movement_weight');rw=_finite(self.register_weight,'register_weight');maxhz=_finite(self.target_max_hz,'target_max_hz')
        if not 0<=spacing<=2400 or not 0<=mw<=100 or not 0<=rw<=100:raise HarmonyError('invalid voicing weights/spacing')
        if type(self.max_register_shifts)is not int or not 1<=self.max_register_shifts<=128:raise HarmonyError('invalid register-shift bound')
        if type(self.candidate_cap_per_voice)is not int or not 1<=self.candidate_cap_per_voice<=512:raise HarmonyError('invalid per-voice candidate cap')
        if type(self.target_harmonics)is not int or not 1<=self.target_harmonics<=64:raise HarmonyError('invalid target harmonic count')
        if not 20<=maxhz<=96000:raise HarmonyError('invalid target maximum Hz')
        if type(self.target_max_teeth)is not int or not 1<=self.target_max_teeth<=512:raise HarmonyError('invalid target tooth bound')
        object.__setattr__(self,'voices',voices)
    def to_dict(self):return dict(voices=[v.to_dict() for v in self.voices],min_spacing_cents=float(self.min_spacing_cents),movement_weight=float(self.movement_weight),register_weight=float(self.register_weight),max_register_shifts=self.max_register_shifts,candidate_cap_per_voice=self.candidate_cap_per_voice,target_harmonics=self.target_harmonics,target_max_hz=float(self.target_max_hz),target_max_teeth=self.target_max_teeth)
    @property
    def sha256(self):return digest(self.to_dict())

@dataclass(frozen=True)
class VoicePitch:
    voice_id:str
    role:str
    tone_id:str
    frequency_hz:float
    degree:int
    detune_cents:float
    source_coordinate:dict
    def __post_init__(self):
        _id(self.voice_id,'voice id');_id(self.tone_id if not self.tone_id.startswith('__') else 'anchor','tone id');_finite(self.frequency_hz,'frequency_hz');_finite(self.detune_cents,'detune_cents')
    def to_dict(self):return dict(voice_id=self.voice_id,role=self.role,tone_id=self.tone_id,frequency_hz=float(self.frequency_hz),degree=self.degree,detune_cents=float(self.detune_cents),source_coordinate=deepcopy(self.source_coordinate))

@dataclass(frozen=True)
class CostBreakdown:
    movement_cents:float
    register_cents:float
    voice_leading_cost:float
    acoustic_fit_cost:float|None=None
    grammar_cost:float|None=None
    def __post_init__(self):
        for name in ('movement_cents','register_cents','voice_leading_cost'):_finite(getattr(self,name),name)
        if self.acoustic_fit_cost is not None:_finite(self.acoustic_fit_cost,'acoustic_fit_cost')
        if self.grammar_cost is not None:_finite(self.grammar_cost,'grammar_cost')
    def to_dict(self):return dict(movement_cents=float(self.movement_cents),register_cents=float(self.register_cents),voice_leading_cost=float(self.voice_leading_cost),acoustic_fit_cost=self.acoustic_fit_cost,grammar_cost=self.grammar_cost)

@dataclass(frozen=True)
class VoicingFrame:
    sonority_id:str
    root_degree:int
    voices:tuple[VoicePitch,...]
    costs:CostBreakdown
    fundamental_targets_hz:tuple[float,...]
    target_comb_hz:tuple[float,...]
    def __post_init__(self):
        _id(self.sonority_id,'sonority id');voices=tuple(self.voices)
        if not voices or any(not isinstance(v,VoicePitch) for v in voices):raise HarmonyError('voicing frame requires voices')
        if any(a.frequency_hz>=b.frequency_hz for a,b in zip(voices,voices[1:])):raise HarmonyError('voicing frame contains crossing/equal voices')
        object.__setattr__(self,'voices',voices);object.__setattr__(self,'fundamental_targets_hz',tuple(self.fundamental_targets_hz));object.__setattr__(self,'target_comb_hz',tuple(self.target_comb_hz))
    def to_dict(self):return dict(sonority_id=self.sonority_id,root_degree=self.root_degree,voices=[v.to_dict() for v in self.voices],costs=self.costs.to_dict(),fundamental_targets_hz=list(self.fundamental_targets_hz),target_comb_hz=list(self.target_comb_hz))

@dataclass(frozen=True)
class ProgressionResult:
    tuning_id:str
    constraint_sha256:str
    frames:tuple[VoicingFrame,...]
    total_voice_leading_cost:float
    def __post_init__(self):
        _id(self.tuning_id,'tuning id');frames=tuple(self.frames)
        if not frames:raise HarmonyError('progression requires at least one frame')
        object.__setattr__(self,'frames',frames)
    def to_dict(self):return dict(format='zaaggenz-harmony-progression',version='1.0.0',tuning_id=self.tuning_id,constraint_sha256=self.constraint_sha256,frames=[f.to_dict() for f in self.frames],total_voice_leading_cost=float(self.total_voice_leading_cost),cost_domains={'voice_leading':'optimised here','acoustic_fit':'separate/not combined','grammar':'separate/not combined'})
    @property
    def sha256(self):return digest(self.to_dict())
