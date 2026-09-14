from __future__ import annotations
import hashlib,math
import numpy as np

class PlacementMetricError(ValueError):pass

def pcm_sha256(x):return hashlib.sha256(np.asarray(x,dtype='<f4',order='C').tobytes()).hexdigest()

def _mono(x):
    a=np.asarray(x,dtype=np.float64)
    if a.ndim==2:a=np.mean(a,axis=1)
    if a.ndim!=1 or not np.isfinite(a).all():raise PlacementMetricError('finite mono/stereo audio required')
    return a

def db(value):return 20.*math.log10(max(float(value),1e-15))

def spectral_metrics(x,sample_rate_hz,target_root_hz=440.,bandwidth_hz=10.):
    a=_mono(x);w=np.hanning(len(a));spec=np.abs(np.fft.rfft(a*w))**2;freq=np.fft.rfftfreq(len(a),1./sample_rate_hz)
    total=float(np.sum(spec));harmonic=np.zeros(len(spec),dtype=bool);n=1
    while n*target_root_hz<sample_rate_hz/2:
        harmonic|=np.abs(freq-n*target_root_hz)<=bandwidth_hz;n+=1
    harmonic_power=float(np.sum(spec[harmonic]));centroid=float(np.sum(freq*spec)/max(total,1e-30))
    return {'target_root_hz':float(target_root_hz),'harmonic_bandwidth_hz':float(bandwidth_hz),
            'target_harmonic_power_fraction':harmonic_power/max(total,1e-30),
            'non_target_power_fraction':(total-harmonic_power)/max(total,1e-30),'spectral_centroid_hz':centroid}

def level_metrics(x):
    a=_mono(x);rms=float(np.sqrt(np.mean(a*a)));peak=float(np.max(np.abs(a))) if len(a) else 0.
    return {'rms_dbfs':db(rms),'peak_dbfs':db(peak),'crest_db':db(peak/max(rms,1e-15)),
            'note':'RMS/peak engineering level metrics; not perceptual loudness'}

def transient_metrics(x,anchor_sample,radius=96):
    a=_mono(x);anchor=int(anchor_sample);lo=max(0,anchor-radius);hi=min(len(a),anchor+radius+1);window=a[lo:hi]
    if not len(window):raise PlacementMetricError('transient window outside audio')
    derivative=np.diff(window,prepend=window[0]);return {'anchor_sample':anchor,'radius_samples':int(radius),
        'window_peak':float(np.max(np.abs(window))),'window_rms':float(np.sqrt(np.mean(window*window))),
        'derivative_rms':float(np.sqrt(np.mean(derivative*derivative)))}

def summarize_audio(x,sample_rate_hz,*,target_root_hz=440.,transient_sample=None):
    out={'sha256_f32le':pcm_sha256(x),**level_metrics(x),**spectral_metrics(x,sample_rate_hz,target_root_hz)}
    if transient_sample is not None:out['transient']=transient_metrics(x,transient_sample)
    return out

def difference_metrics(a,b):
    x=_mono(a);y=_mono(b)
    if x.shape!=y.shape:raise PlacementMetricError('comparison shape mismatch')
    delta=x-y;return {'rms_difference':float(np.sqrt(np.mean(delta*delta))),
                      'peak_difference':float(np.max(np.abs(delta))) if len(delta) else 0.,
                      'exact':bool(np.array_equal(x,y))}
