from __future__ import annotations
from dataclasses import dataclass
import math
import numpy as np

VERSION='zg-qc-fixtures-v1'
NAMES=('silence','impulse','sine','harmonic_comb','stretched_comb','am','fm','chirp','crossing_chirps','bandlimited_noise','transient_tone','stereo_inphase','stereo_antiphase','stereo_quadrature','over_full_scale')

@dataclass(frozen=True)
class Fixture:
    name:str
    sample_rate_hz:int
    channels:int
    frames:int
    generation:str
    automated:bool
    data:np.ndarray


def fixture_names():return NAMES

def _phase_from_frequency(freq,sr,phase0=0.):
    f=np.asarray(freq,dtype=np.float64)
    if f.ndim!=1 or not len(f):raise ValueError('frequency vector required')
    phase=np.empty_like(f);phase[0]=phase0
    if len(f)>1:phase[1:]=phase0+2*np.pi*np.cumsum((f[1:]+f[:-1])*.5)/sr
    return phase

def _tone(freq,t):return np.sin(2*np.pi*freq*t)

def fixture(name,sr=48000,duration_s=1.0,seed=20260912):
    if name not in NAMES:raise ValueError('unknown QC fixture')
    if type(sr)is not int or not 8000<=sr<=192000:raise ValueError('sample rate out of range')
    n=max(1,round(float(duration_s)*sr));t=np.arange(n,dtype=np.float64)/sr
    if name=='silence':x=np.zeros(n);g='all-zero mono'
    elif name=='impulse':x=np.zeros(n);x[min(n//3,n-1)]=1.;g='unit impulse at floor(N/3)'
    elif name=='sine':x=.5*_tone(997.,t);g='0.5*sin(2pi*997t)'
    elif name=='harmonic_comb':
        x=sum((k**-.8)*_tone(48.*k,t+.013*k) for k in range(1,17));x*=.45/max(np.max(np.abs(x)),1e-12);g='16 harmonics of 48 Hz, k^-0.8'
    elif name=='stretched_comb':
        x=sum((k**-.8)*_tone(48.*k**1.07,t+.009*k) for k in range(1,17));x*=.45/max(np.max(np.abs(x)),1e-12);g='16 stretched partials 48*k^1.07'
    elif name=='am':x=.45*(.55+.45*np.sin(2*np.pi*5*t))*_tone(220.,t);g='220 Hz carrier, 5 Hz AM'
    elif name=='fm':
        f=220+35*np.sin(2*np.pi*3*t);x=.45*np.sin(_phase_from_frequency(f,sr,.2));g='220 Hz +/-35 Hz sinusoidal FM at 3 Hz, integrated phase'
    elif name=='chirp':
        f=np.geomspace(40.,min(8000.,sr*.42),n);x=.45*np.sin(_phase_from_frequency(f,sr));g='40 Hz to min(8 kHz,.42fs) geometric chirp'
    elif name=='crossing_chirps':
        hi=min(5000.,sr*.38);f1=np.linspace(120.,hi,n);f2=np.linspace(hi,120.,n);x=.25*np.sin(_phase_from_frequency(f1,sr))+.25*np.sin(_phase_from_frequency(f2,sr,.4));g='two linear chirps crossing in frequency'
    elif name=='bandlimited_noise':
        rng=np.random.default_rng(seed);z=rng.standard_normal(n);Z=np.fft.rfft(z);f=np.fft.rfftfreq(n,1/sr);Z[(f<700)|(f>min(6000,sr*.45))]=0;x=np.fft.irfft(Z,n);x*=.35/max(np.max(np.abs(x)),1e-12);g=f'seeded FFT bandlimited noise seed={seed}'
    elif name=='transient_tone':
        x=.25*_tone(330.,t);m=min(n,max(1,round(.004*sr)));x[:m]+=np.hanning(2*m)[m:]*.8;g='330 Hz tone plus 4 ms onset transient'
    elif name in ('stereo_inphase','stereo_antiphase','stereo_quadrature'):
        l=.45*_tone(440.,t)
        r=l.copy() if name=='stereo_inphase' else -l if name=='stereo_antiphase' else .45*np.cos(2*np.pi*440*t)
        x=np.column_stack((l,r));g={'stereo_inphase':'440 Hz identical L/R','stereo_antiphase':'440 Hz L/-R','stereo_quadrature':'440 Hz sine/cosine'}[name]
    elif name=='over_full_scale':x=1.5*_tone(997.,t);g='1.5 peak sine; proves analysis remains unclamped'
    x=np.asarray(x,dtype=np.float64);channels=1 if x.ndim==1 else x.shape[1]
    x.setflags(write=False)
    return Fixture(name,sr,channels,n,g,True,x)
