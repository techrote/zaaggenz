from __future__ import annotations
from dataclasses import dataclass
import math
import numpy as np

class BitcrushError(ValueError):pass

def _audio(x):
    a=np.asarray(x,dtype=np.float64);mono=a.ndim==1
    if mono:a=a[:,None]
    if a.ndim!=2 or a.shape[1] not in (1,2) or not np.isfinite(a).all():raise BitcrushError('finite mono/stereo audio required')
    return a,mono

@dataclass(frozen=True)
class BitcrushSpec:
    bit_depth:int=8
    hold_samples:int=1
    full_scale:float=1.
    wet:float=1.
    dither:str='none'
    def __post_init__(self):
        if type(self.bit_depth)is not int or type(self.bit_depth)is bool or not 2<=self.bit_depth<=24:raise BitcrushError('bit_depth must be integer 2..24')
        if type(self.hold_samples)is not int or type(self.hold_samples)is bool or not 1<=self.hold_samples<=1024:raise BitcrushError('hold_samples must be integer 1..1024')
        fs=float(self.full_scale);wet=float(self.wet)
        if not math.isfinite(fs) or fs<=0 or fs>32:raise BitcrushError('full_scale must be positive and <=32')
        if not math.isfinite(wet) or not 0<=wet<=1:raise BitcrushError('wet must be in [0,1]')
        if self.dither!='none':raise BitcrushError('v1 is deterministic and supports dither=none only')
        object.__setattr__(self,'full_scale',fs);object.__setattr__(self,'wet',wet)
    def to_dict(self):return {'bit_depth':self.bit_depth,'hold_samples':self.hold_samples,'full_scale':self.full_scale,'wet':self.wet,'dither':self.dither,'quantizer':'signed uniform round-to-nearest; no hidden normalization','hold_phase':'sample 0 anchored','alias_policy':'intentional unfiltered quantization/sample-hold images; caller must opt into crossover-delta confinement when spill is undesired'}

@dataclass(frozen=True)
class BitcrushResult:
    audio:np.ndarray
    quantization_step:float
    held_sample_fraction:float
    spec:BitcrushSpec
    @property
    def diagnostics(self):return {'quantization_step':self.quantization_step,'hold_samples':self.spec.hold_samples,'held_sample_fraction':self.held_sample_fraction,'dither':self.spec.dither,'alias_policy':self.spec.to_dict()['alias_policy'],'declared_latency_samples':0}

def bitcrush(x,spec):
    if not isinstance(spec,BitcrushSpec):raise BitcrushError('BitcrushSpec required')
    a,mono=_audio(x);n=len(a)
    if spec.wet==0:return BitcrushResult(np.asarray(x).copy(),2.*spec.full_scale/(2**spec.bit_depth-1),0.,spec)
    held=a.copy()
    if spec.hold_samples>1:
        for start in range(0,n,spec.hold_samples):held[start:start+spec.hold_samples]=a[start]
    levels=2**spec.bit_depth-1;step=2.*spec.full_scale/levels
    clipped=np.clip(held,-spec.full_scale,spec.full_scale);wet_audio=np.round((clipped+spec.full_scale)/step)*step-spec.full_scale
    out=(1.-spec.wet)*a+spec.wet*wet_audio;out=out[:,0] if mono else out
    changed=float(np.mean(np.any(np.abs(held-a)>0,axis=1))) if n else 0.
    return BitcrushResult(np.asarray(out,dtype=np.float64),step,changed,spec)
