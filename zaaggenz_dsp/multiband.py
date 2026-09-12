from __future__ import annotations
import numpy as np
from scipy import signal

class BandError(ValueError):pass

def _audio(x):
    a=np.asarray(x,dtype=np.float64)
    mono=a.ndim==1
    if mono:a=a[:,None]
    if a.ndim!=2 or a.shape[1] not in (1,2) or not np.isfinite(a).all():raise BandError('finite mono/stereo audio required')
    return a,mono

def _cross(crossovers,sr):
    if len(crossovers)!=3:raise BandError('exactly three crossovers required')
    c=tuple(float(v) for v in crossovers)
    if not all(np.isfinite(c)) or not 20<=c[0]<c[1]<c[2]<.49*sr:raise BandError('crossovers must increase from >=20 Hz to below Nyquist')
    return c

def _lp(x,sr,f):
    if len(x)<8:raise BandError('nonzero multiband processing requires at least 8 samples')
    sos=signal.butter(4,f,fs=sr,output='sos');pad=min(len(x)-1,3*(2*len(sos)+1))
    return signal.sosfiltfilt(sos,x,axis=0,padlen=pad)

def split_bands(x,sr,crossovers):
    a,mono=_audio(x);c=_cross(crossovers,sr)
    l0=_lp(a,sr,c[0]);l1=_lp(a,sr,c[1]);l2=_lp(a,sr,c[2])
    bands=(l0,l1-l0,l2-l1,a-l2)
    return tuple(v[:,0] if mono else v for v in bands)

def _project(delta,sr,crossovers,index):return split_bands(delta,sr,crossovers)[index]

def route_effect_deltas(x,sr,crossovers,processors,confine_delta=True):
    """y = x + Σ P_i(F_i(B_i x)-B_i x). Zero effects never touch the dry path."""
    a,mono=_audio(x)
    if len(processors)!=4:raise BandError('four band processors required')
    if all(p is None for p in processors):return np.asarray(x).copy()
    bands=split_bands(a[:,0] if mono else a,sr,crossovers);out=a.copy()
    for i,(band,processor) in enumerate(zip(bands,processors)):
        if processor is None:continue
        original,_=_audio(band);changed,_=_audio(processor(np.asarray(band).copy()))
        if changed.shape!=original.shape or not np.isfinite(changed).all():raise BandError('band processor changed shape or produced nonfinite samples')
        delta=changed-original
        if confine_delta:delta,_=_audio(_project(delta[:,0] if mono else delta,sr,crossovers,i))
        out+=delta
    return out[:,0] if mono else out

def multiband_gain(x,sr,crossovers,gains_db,confine_delta=True):
    if len(gains_db)!=4:raise BandError('four gains required')
    gains=tuple(float(v) for v in gains_db)
    if not all(np.isfinite(g) and -36<=g<=24 for g in gains):raise BandError('band gain outside -36..24 dB')
    processors=[]
    for g in gains:
        if g==0:processors.append(None)
        else:
            linear=10**(g/20);processors.append(lambda b,linear=linear:b*linear)
    return route_effect_deltas(x,sr,crossovers,processors,confine_delta)
