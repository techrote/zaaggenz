from __future__ import annotations
from dataclasses import dataclass
import numpy as np
from .multiband import BandError,split_bands

BAND_NAMES=('sub','lowmid','highmid','air')
FILTER_POLICY='zg.butter4_sosfiltfilt_effect_delta.v1'

@dataclass(frozen=True)
class BandDeltaReport:
    band:str
    selected:bool
    confine_delta:bool
    input_rms:float
    raw_delta_rms:float
    routed_delta_rms:float
    leakage_rms_by_band:tuple[float,float,float,float]
    def to_dict(self):return {'band':self.band,'selected':self.selected,'confine_delta':self.confine_delta,'input_rms':self.input_rms,'raw_delta_rms':self.raw_delta_rms,'routed_delta_rms':self.routed_delta_rms,'leakage_rms_by_band':dict(zip(BAND_NAMES,self.leakage_rms_by_band))}

def filter_metadata(crossovers,sample_rate_hz):
    c=tuple(float(x) for x in crossovers)
    if len(c)!=3 or not 20<=c[0]<c[1]<c[2]<.49*sample_rate_hz:raise BandError('invalid crossovers')
    return {'id':FILTER_POLICY,'crossovers_hz':list(c),'prototype':'Butterworth','order':4,'implementation':'scipy.signal.sosfiltfilt','phase':'offline zero-phase','declared_latency_samples':0,'reconstruction':'dry + sum(projected effect deltas); dry path never split/recombined'}

def _rms(x):
    a=np.asarray(x,dtype=np.float64);return float(np.sqrt(np.mean(a*a))) if a.size else 0.

def route_band_processors(x,sample_rate_hz,crossovers,processors,confine_flags=(True,True,True,True)):
    if len(processors)!=4 or len(confine_flags)!=4:raise BandError('four processors and four confine flags required')
    source=np.asarray(x,dtype=np.float64)
    if source.ndim not in (1,2) or not np.isfinite(source).all():raise BandError('finite mono/stereo audio required')
    if all(p is None for p in processors):return np.asarray(x).copy(),tuple(BandDeltaReport(name,False,bool(confine_flags[i]),0.,0.,0.,(0.,0.,0.,0.)) for i,name in enumerate(BAND_NAMES))
    bands=split_bands(source,sample_rate_hz,crossovers);out=source.copy();reports=[]
    for i,(name,band,processor,confine) in enumerate(zip(BAND_NAMES,bands,processors,confine_flags)):
        if processor is None:
            reports.append(BandDeltaReport(name,False,bool(confine),_rms(band),0.,0.,(0.,0.,0.,0.)));continue
        changed=np.asarray(processor(np.asarray(band).copy()),dtype=np.float64)
        if changed.shape!=np.asarray(band).shape or not np.isfinite(changed).all():raise BandError('band processor changed shape or produced nonfinite samples')
        raw=changed-np.asarray(band,dtype=np.float64)
        routed=split_bands(raw,sample_rate_hz,crossovers)[i] if confine else raw
        out=out+routed
        leakage=tuple(_rms(v) for v in split_bands(routed,sample_rate_hz,crossovers))
        reports.append(BandDeltaReport(name,True,bool(confine),_rms(band),_rms(raw),_rms(routed),leakage))
    return out,tuple(reports)
