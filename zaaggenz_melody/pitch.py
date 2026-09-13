from __future__ import annotations
import math
import numpy as np
from scipy import signal
from .model import MelodyError

def _audio(x):
    a=np.asarray(x)
    mono=a.ndim==1
    if mono:a=a[:,None]
    if a.ndim!=2 or a.shape[1] not in (1,2):raise MelodyError('mono/stereo source required')
    if not np.issubdtype(a.dtype,np.number) or not np.isfinite(a).all():raise MelodyError('finite numeric source required')
    return np.asarray(a,dtype=np.float64),mono

def _fft_size(n,requested):
    if n<64:raise MelodyError('source is too short for non-neutral phase-vocoder transposition')
    return min(requested,2**int(math.floor(math.log2(n))))

def _stretch_channel(x,rate,n_fft):
    if not math.isfinite(rate) or rate<=0:raise MelodyError('time-stretch rate must be finite and positive')
    if abs(rate-1.)<1e-12:return x.copy()
    n_fft=_fft_size(len(x),n_fft);hop=max(1,n_fft//4)
    _,_,d=signal.stft(x,fs=1.,window='hann',nperseg=n_fft,noverlap=n_fft-hop,nfft=n_fft,boundary='zeros',padded=True)
    if d.shape[1]<2:return signal.resample(x,max(1,round(len(x)/rate)))
    steps=np.arange(0,d.shape[1]-1,rate,dtype=np.float64);omega=2*np.pi*hop*np.arange(d.shape[0],dtype=np.float64)/n_fft
    phase=np.angle(d[:,0]).copy();out=np.empty((d.shape[0],len(steps)),dtype=np.complex128)
    for oi,step in enumerate(steps):
        i=int(math.floor(step));alpha=step-i;mag=(1-alpha)*np.abs(d[:,i])+alpha*np.abs(d[:,i+1])
        delta=np.angle(d[:,i+1])-np.angle(d[:,i])-omega;delta=(delta+np.pi)%(2*np.pi)-np.pi
        phase+=omega+delta;out[:,oi]=mag*np.exp(1j*phase)
    _,y=signal.istft(out,fs=1.,window='hann',nperseg=n_fft,noverlap=n_fft-hop,nfft=n_fft,input_onesided=True,boundary=True)
    target=max(1,round(len(x)/rate))
    if len(y)<target:y=np.pad(y,(0,target-len(y)))
    return np.asarray(y[:target],dtype=np.float64)

def pitch_shift_static(x,ratio,*,fft_size=2048):
    """Duration-preserving source-derived transposition.

    Neutral ratio 1 is a direct copy. Other ratios time-stretch with a phase
    vocoder and resample back to the original duration; there is no hidden peak/RMS normalisation.
    """
    if type(ratio) not in (int,float) or type(ratio)is bool or not math.isfinite(float(ratio)) or ratio<=0:raise MelodyError('pitch ratio must be finite and positive')
    a,mono=_audio(x)
    if abs(float(ratio)-1.)<1e-12:return np.asarray(x,dtype=np.float32).copy()
    channels=[]
    for c in range(a.shape[1]):
        stretched=_stretch_channel(a[:,c],1./float(ratio),fft_size)
        channels.append(signal.resample(stretched,len(a)))
    out=np.column_stack(channels).astype(np.float32)
    return out[:,0] if mono else out

def pitch_warp_variable(x,ratios,*,output_samples=None):
    """Integrate a time-varying playback ratio for the glide portion of an event.

    This is intentionally separate from the static duration-preserving path.
    The melodic renderer crossfades a glide back to the final static-pitch tail,
    preserving the declared natural tail duration.
    """
    a,mono=_audio(x);n=len(a) if output_samples is None else int(output_samples)
    if n<0:raise MelodyError('output_samples must be non-negative')
    r=np.asarray(ratios,dtype=np.float64)
    if r.ndim==0:r=np.full(n,float(r))
    if r.shape!=(n,) or not np.isfinite(r).all() or np.any(r<=0):raise MelodyError('ratio trajectory must be finite, positive and match output length')
    if n==0:return np.zeros((0,),dtype=np.float32) if mono else np.zeros((0,a.shape[1]),dtype=np.float32)
    if np.all(np.abs(r-1.)<1e-12):
        out=np.zeros((n,a.shape[1]),dtype=np.float64);m=min(n,len(a));out[:m]=a[:m]
    else:
        idx=np.zeros(n,dtype=np.float64)
        if n>1:idx[1:]=np.cumsum(.5*(r[:-1]+r[1:]))
        base=np.arange(len(a),dtype=np.float64);out=np.zeros((n,a.shape[1]),dtype=np.float64)
        for c in range(a.shape[1]):out[:,c]=np.interp(idx,base,a[:,c],left=0.,right=0.)
    out=out.astype(np.float32);return out[:,0] if mono else out

def cosine_taper(x,fade_samples):
    a=np.asarray(x,dtype=np.float32).copy();n=len(a);fade=max(0,min(int(fade_samples),n))
    if fade:
        w=.5*(1+np.cos(np.linspace(0,np.pi,fade,dtype=np.float64))).astype(np.float32)
        if a.ndim==1:a[-fade:]*=w
        else:a[-fade:]*=w[:,None]
    return a
