from __future__ import annotations
from dataclasses import dataclass
import math
import numpy as np

class DynamicsError(ValueError):pass

def _finite(v,name):
    if type(v) not in (int,float) or type(v)is bool or not math.isfinite(float(v)):raise DynamicsError(f'{name} must be finite')
    return float(v)

def _audio(x):
    a=np.asarray(x,dtype=np.float64);mono=a.ndim==1
    if mono:a=a[:,None]
    if a.ndim!=2 or a.shape[1] not in (1,2) or not np.isfinite(a).all():raise DynamicsError('finite mono/stereo audio required')
    return a,mono

@dataclass(frozen=True)
class CompressionSpec:
    threshold_db:float=-12.
    ratio:float=4.
    attack_ms:float=8.
    release_ms:float=90.
    knee_db:float=0.
    makeup_db:float=0.
    wet:float=1.
    detector:str='linked-peak'
    def __post_init__(self):
        threshold=_finite(self.threshold_db,'threshold_db');ratio=_finite(self.ratio,'ratio');attack=_finite(self.attack_ms,'attack_ms');release=_finite(self.release_ms,'release_ms');knee=_finite(self.knee_db,'knee_db');makeup=_finite(self.makeup_db,'makeup_db');wet=_finite(self.wet,'wet')
        if not -120<=threshold<=24:raise DynamicsError('threshold_db out of range')
        if not 1<=ratio<=100:raise DynamicsError('ratio must be 1..100')
        if not .01<=attack<=5000 or not .01<=release<=10000:raise DynamicsError('attack/release out of range')
        if not 0<=knee<=48:raise DynamicsError('knee_db out of range')
        if not -36<=makeup<=36:raise DynamicsError('makeup_db out of range')
        if not 0<=wet<=1:raise DynamicsError('wet must be in [0,1]')
        if self.detector!='linked-peak':raise DynamicsError('only linked-peak detector is registered in v1')
        for n,v in [('threshold_db',threshold),('ratio',ratio),('attack_ms',attack),('release_ms',release),('knee_db',knee),('makeup_db',makeup),('wet',wet)]:object.__setattr__(self,n,v)
    def to_dict(self):return {'threshold_db':self.threshold_db,'ratio':self.ratio,'attack_ms':self.attack_ms,'release_ms':self.release_ms,'knee_db':self.knee_db,'makeup_db':self.makeup_db,'wet':self.wet,'detector':self.detector,'semantics':'feed-forward linked peak; attack/release smooth gain reduction, never the audio path'}

@dataclass(frozen=True)
class CompressionResult:
    audio:np.ndarray
    detector_db:np.ndarray
    static_gain_reduction_db:np.ndarray
    smoothed_gain_reduction_db:np.ndarray
    spec:CompressionSpec
    def __post_init__(self):
        shape=np.asarray(self.audio).shape;n=shape[0]
        for name in ('detector_db','static_gain_reduction_db','smoothed_gain_reduction_db'):
            a=np.asarray(getattr(self,name))
            if a.shape!=(n,) or not np.isfinite(a).all():raise DynamicsError(name+' invalid')
    @property
    def diagnostics(self):
        gr=np.asarray(self.smoothed_gain_reduction_db)
        return {'detector':self.spec.detector,'max_gain_reduction_db':float(np.max(gr)) if len(gr) else 0.,'mean_gain_reduction_db':float(np.mean(gr)) if len(gr) else 0.,'control_signal_separate_from_audio':True,'declared_latency_samples':0}

def _static_reduction(level_db,spec):
    x=np.asarray(level_db,dtype=np.float64);over=x-spec.threshold_db;k=spec.knee_db
    if spec.ratio==1:return np.zeros_like(x)
    slope=1.-1./spec.ratio
    if k<=0:return np.maximum(over,0.)*slope
    lo=-k/2.;hi=k/2.;out=np.zeros_like(x);above=over>=hi;middle=(over>lo)&(over<hi)
    out[above]=over[above]*slope
    z=over[middle]-lo;out[middle]=slope*z*z/(2.*k)
    return out

def compress(x,sample_rate_hz,spec):
    if not isinstance(spec,CompressionSpec):raise DynamicsError('CompressionSpec required')
    if type(sample_rate_hz)is not int or not 8000<=sample_rate_hz<=192000:raise DynamicsError('sample rate out of range')
    a,mono=_audio(x);n=len(a)
    if spec.wet==0 or (spec.ratio==1 and spec.makeup_db==0):
        zeros=np.zeros(n,dtype=np.float64);detector=20.*np.log10(np.maximum(np.max(np.abs(a),axis=1),1e-15))
        out=np.asarray(x).copy();return CompressionResult(out,detector,zeros.copy(),zeros.copy(),spec)
    detector_amp=np.max(np.abs(a),axis=1);detector_db=20.*np.log10(np.maximum(detector_amp,1e-15));static=_static_reduction(detector_db,spec)
    attack=math.exp(-1./(sample_rate_hz*spec.attack_ms*.001));release=math.exp(-1./(sample_rate_hz*spec.release_ms*.001));smooth=np.zeros(n,dtype=np.float64);state=0.
    for i,target in enumerate(static):
        coeff=attack if target>state else release;state=coeff*state+(1.-coeff)*target;smooth[i]=state
    gain=10.**((spec.makeup_db-smooth)/20.);wet_audio=a*gain[:,None];out=(1.-spec.wet)*a+spec.wet*wet_audio
    out=out[:,0] if mono else out
    return CompressionResult(np.asarray(out,dtype=np.float64),detector_db,static,smooth,spec)
