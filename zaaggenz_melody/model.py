from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from copy import deepcopy
import math
import numpy as np
from zaaggenz_contracts import digest

class MelodyError(ValueError):pass

class NoteMode(str,Enum):
    SOURCE_DERIVED='source-derived'
    TARGET_NOTE='target-note'
    @property
    def phase_policy(self):return 'source-derived' if self is NoteMode.SOURCE_DERIVED else 'reset-event'

@dataclass(frozen=True)
class MelodicRenderSpec:
    version:str='1.0.0'
    mode:NoteMode=NoteMode.SOURCE_DERIVED
    standard_fft:int=2048
    high_fft:int=4096
    pitch_ratio_min:float=.25
    pitch_ratio_max:float=4.
    target_hz_min:float=15.
    target_hz_max:float=240.
    release_ms:float=8.
    glide_tail_crossfade_ms:float=18.
    roll_slice_fraction:float=.88
    roll_fade_fraction:float=.42
    roll_slice_max_ms:float=120.
    max_roll_density:int=16
    max_roll_retriggers:int=64
    roll_energy_compensation:float=.5
    def __post_init__(self):
        if self.version!='1.0.0':raise MelodyError('unsupported melodic render spec version')
        try:object.__setattr__(self,'mode',NoteMode(self.mode))
        except ValueError as exc:raise MelodyError('unknown note render mode') from exc
        if self.standard_fft not in (512,1024,2048,4096) or self.high_fft not in (1024,2048,4096,8192):raise MelodyError('unsupported phase-vocoder FFT size')
        vals=(self.pitch_ratio_min,self.pitch_ratio_max,self.target_hz_min,self.target_hz_max,self.release_ms,
              self.glide_tail_crossfade_ms,self.roll_slice_fraction,self.roll_fade_fraction,self.roll_slice_max_ms,
              self.roll_energy_compensation)
        if any(type(v) not in (int,float) or type(v)is bool or not math.isfinite(float(v)) for v in vals):raise MelodyError('finite render settings required')
        if not 0<self.pitch_ratio_min<1<self.pitch_ratio_max<=8:raise MelodyError('invalid pitch ratio range')
        if not 0<self.target_hz_min<self.target_hz_max:raise MelodyError('invalid target frequency range')
        if not 0<=self.release_ms<=100 or not 0<=self.glide_tail_crossfade_ms<=100:raise MelodyError('invalid fade duration')
        if not .1<=self.roll_slice_fraction<=1.5 or not .05<=self.roll_fade_fraction<=.95:raise MelodyError('invalid roll slice/fade fraction')
        if not 5<=self.roll_slice_max_ms<=500:raise MelodyError('invalid maximum roll slice duration')
        if type(self.max_roll_density)is not int or not 1<=self.max_roll_density<=64:raise MelodyError('invalid roll density bound')
        if type(self.max_roll_retriggers)is not int or not 0<=self.max_roll_retriggers<=512:raise MelodyError('invalid roll retrigger bound')
        if not 0<=self.roll_energy_compensation<=1:raise MelodyError('invalid roll energy compensation')
    def to_dict(self):
        return dict(version=self.version,mode=self.mode.value,standard_fft=self.standard_fft,high_fft=self.high_fft,
                    pitch_ratio_min=self.pitch_ratio_min,pitch_ratio_max=self.pitch_ratio_max,target_hz_min=self.target_hz_min,
                    target_hz_max=self.target_hz_max,release_ms=self.release_ms,glide_tail_crossfade_ms=self.glide_tail_crossfade_ms,
                    roll_slice_fraction=self.roll_slice_fraction,roll_fade_fraction=self.roll_fade_fraction,
                    roll_slice_max_ms=self.roll_slice_max_ms,max_roll_density=self.max_roll_density,
                    max_roll_retriggers=self.max_roll_retriggers,roll_energy_compensation=self.roll_energy_compensation)
    @property
    def sha256(self):return digest(self.to_dict())

@dataclass(frozen=True)
class MelodicRenderResult:
    mix:np.ndarray
    stems:dict
    events:tuple
    diagnostics:dict
    def __post_init__(self):
        mix=np.asarray(self.mix,dtype=np.float32);mix.setflags(write=False);object.__setattr__(self,'mix',mix)
        stems={}
        for k,v in self.stems.items():
            a=np.asarray(v,dtype=np.float32);a.setflags(write=False);stems[k]=a
        object.__setattr__(self,'stems',stems);object.__setattr__(self,'events',tuple(deepcopy(self.events)));object.__setattr__(self,'diagnostics',deepcopy(self.diagnostics))
