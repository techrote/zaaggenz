from __future__ import annotations
from dataclasses import dataclass
import math
import numpy as np
from .bitcrush import BitcrushSpec,bitcrush
from .dynamics import CompressionSpec,compress

class BandEffectError(ValueError):pass
DSP_STAGES=('gain','compression','bitcrush')

@dataclass(frozen=True)
class BandEffectSpec:
    gain_db:float=0.
    compression:CompressionSpec|None=None
    bitcrush:BitcrushSpec|None=None
    stage_order:tuple[str,...]=DSP_STAGES
    def __post_init__(self):
        gain=float(self.gain_db)
        if not math.isfinite(gain) or not -36<=gain<=24:raise BandEffectError('gain_db must be in [-36,24]')
        order=tuple(self.stage_order)
        if len(order)!=len(set(order)) or any(x not in DSP_STAGES for x in order):raise BandEffectError('stage_order must contain unique registered DSP stages')
        if set(order)!=set(DSP_STAGES):raise BandEffectError('stage_order must include gain, compression and bitcrush exactly once')
        if self.compression is not None and not isinstance(self.compression,CompressionSpec):raise BandEffectError('CompressionSpec required')
        if self.bitcrush is not None and not isinstance(self.bitcrush,BitcrushSpec):raise BandEffectError('BitcrushSpec required')
        object.__setattr__(self,'gain_db',gain);object.__setattr__(self,'stage_order',order)
    @property
    def identity(self):
        compression_identity=self.compression is None or self.compression.wet==0 or (self.compression.ratio==1 and self.compression.makeup_db==0)
        crush_identity=self.bitcrush is None or self.bitcrush.wet==0
        return self.gain_db==0 and compression_identity and crush_identity
    def to_dict(self):return {'gain_db':self.gain_db,'compression':None if self.compression is None else self.compression.to_dict(),'bitcrush':None if self.bitcrush is None else self.bitcrush.to_dict(),'stage_order':list(self.stage_order),'identity':self.identity,'normalization':'none','declared_latency_samples':0}

@dataclass(frozen=True)
class BandEffectResult:
    audio:np.ndarray
    spec:BandEffectSpec
    stages:tuple[dict,...]
    def __post_init__(self):
        a=np.asarray(self.audio)
        if a.ndim not in (1,2) or not np.isfinite(a).all():raise BandEffectError('invalid effect output')
    @property
    def diagnostics(self):return {'identity_path':self.spec.identity,'stage_order':list(self.spec.stage_order),'stages':list(self.stages),'normalization':'none','declared_latency_samples':0}

def process_band_effects(x,sample_rate_hz,spec):
    if not isinstance(spec,BandEffectSpec):raise BandEffectError('BandEffectSpec required')
    source=np.asarray(x)
    if source.ndim not in (1,2) or not np.issubdtype(source.dtype,np.number) or not np.isfinite(source).all():raise BandEffectError('finite mono/stereo audio required')
    if spec.identity:return BandEffectResult(source.copy(),spec,())
    current=np.asarray(source,dtype=np.float64);rows=[]
    for stage in spec.stage_order:
        if stage=='gain':
            if spec.gain_db!=0:
                current=current*(10.**(spec.gain_db/20.));rows.append({'stage':'gain','gain_db':spec.gain_db,'declared_latency_samples':0})
        elif stage=='compression':
            if spec.compression is not None:
                result=compress(current,sample_rate_hz,spec.compression);current=np.asarray(result.audio,dtype=np.float64);rows.append({'stage':'compression','spec':spec.compression.to_dict(),'diagnostics':result.diagnostics})
        elif stage=='bitcrush':
            if spec.bitcrush is not None:
                result=bitcrush(current,spec.bitcrush);current=np.asarray(result.audio,dtype=np.float64);rows.append({'stage':'bitcrush','spec':spec.bitcrush.to_dict(),'diagnostics':result.diagnostics,'alias_policy':'intentional unfiltered quantization/sample-hold images; use band confinement to bound spill'})
        else:raise BandEffectError('unknown stage')
    return BandEffectResult(current,spec,tuple(rows))
