from __future__ import annotations
import math
import numpy as np

SUPPORTED_OVERSAMPLE=(1,2,4)
REFERENCE_OVERSAMPLE=8
FILTER_HALFSPAN_BASE=16
FILTER_BETA=8.6
FILTER_POLICY_ID='zg.kaiser_polyphase_zero_phase.v1'

class AntialiasError(ValueError):pass

def _factor(value,allow_reference=False):
    allowed=SUPPORTED_OVERSAMPLE+((REFERENCE_OVERSAMPLE,) if allow_reference else ())
    if type(value)is not int or type(value)is bool or value not in allowed:
        raise AntialiasError('oversample factor must be '+('/'.join(map(str,allowed))))
    return value

def filter_metadata(factor):
    factor=_factor(factor,allow_reference=True)
    if factor==1:
        return {'id':'legacy-direct-1x','factor':1,'fir_taps':0,'kaiser_beta':None,
                'declared_latency_samples':0,'alignment':'sample-synchronous direct path'}
    taps=2*FILTER_HALFSPAN_BASE*factor+1
    return {'id':FILTER_POLICY_ID,'factor':factor,'fir_taps':taps,'kaiser_beta':FILTER_BETA,
            'cutoff_fraction_of_oversampled_nyquist':1./factor,'declared_latency_samples':0,
            'alignment':'offline zero-phase compensated polyphase; symmetric pre/post ringing is retained'}

def _fir(factor):
    try:from scipy.signal import firwin
    except ImportError as exc:raise AntialiasError('scipy is required for antialiased nonlinear nodes') from exc
    meta=filter_metadata(factor)
    return firwin(meta['fir_taps'],1./factor,window=('kaiser',FILTER_BETA))

def _resample(x,up,down,window):
    try:from scipy.signal import resample_poly
    except ImportError as exc:raise AntialiasError('scipy is required for antialiased nonlinear nodes') from exc
    return resample_poly(x,up,down,axis=0,window=window,padtype='constant')

def _shape_high(x,kind,drive_db=0.,threshold=1.):
    if kind=='tanh':return np.tanh(x*(10.**(float(drive_db)/20.)))
    if kind=='hard_clip':return np.clip(x,-float(threshold),float(threshold))
    raise AntialiasError('unsupported shaper kind')

def oversampled_shaper(x,*,kind,factor,drive_db=0.,threshold=1.,mix=1.,allow_reference=False):
    factor=_factor(factor,allow_reference=allow_reference);a=np.asarray(x,dtype=np.float64)
    if a.ndim not in (1,2) or not np.isfinite(a).all():raise AntialiasError('finite mono/stereo array required')
    mix=float(mix)
    if not math.isfinite(mix) or not 0<=mix<=1:raise AntialiasError('mix must be in [0,1]')
    if mix==0:return a.copy()
    if kind=='hard_clip' and (not math.isfinite(float(threshold)) or float(threshold)<=0):raise AntialiasError('threshold must be positive')
    if not math.isfinite(float(drive_db)):raise AntialiasError('drive_db must be finite')
    if factor==1:wet=_shape_high(a,kind,drive_db,threshold)
    else:
        h=_fir(factor);hi=_resample(a,factor,1,h);wet_hi=_shape_high(hi,kind,drive_db,threshold)
        wet=_resample(wet_hi,1,factor,h)[:len(a)]
        if wet.shape!=a.shape:raise AntialiasError('polyphase reconstruction changed signal shape')
    return (1.-mix)*a+mix*wet

def reference_shaper(x,*,kind,drive_db=0.,threshold=1.,mix=1.):
    return oversampled_shaper(x,kind=kind,factor=REFERENCE_OVERSAMPLE,drive_db=drive_db,
                               threshold=threshold,mix=mix,allow_reference=True)

def reference_error(x,*,kind,drive_db=0.,threshold=1.,mix=1.):
    ref=reference_shaper(x,kind=kind,drive_db=drive_db,threshold=threshold,mix=mix)
    errors={}
    scale=max(float(np.sqrt(np.mean(ref*ref))),1e-15)
    for factor in SUPPORTED_OVERSAMPLE:
        out=oversampled_shaper(x,kind=kind,factor=factor,drive_db=drive_db,threshold=threshold,mix=mix)
        err=float(np.sqrt(np.mean((out-ref)**2)))
        errors[factor]={'rms_error':err,'relative_rms_error':err/scale,'filter':filter_metadata(factor)}
    return errors
