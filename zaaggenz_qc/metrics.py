from __future__ import annotations
import math
import numpy as np

METHOD='zg-qc-diagnostics-v1'

def _matrix(x):
    a=np.asarray(x,dtype=np.float64)
    if a.ndim==1:a=a[:,None]
    if a.ndim!=2 or not a.shape[0] or a.shape[1] not in (1,2):raise ValueError('nonempty mono/stereo audio required')
    return a

def diagnose(x,sr,mode='automated'):
    a=_matrix(x);finite=np.isfinite(a)
    clean=np.where(finite,a,0.)
    rms=np.sqrt(np.mean(clean*clean,axis=0));peak=np.max(np.abs(clean),axis=0)
    crest=np.array([20*math.log10(p/r) if r>0 and p>0 else 0. for p,r in zip(peak,rms)])
    return {'method':METHOD,'sample_rate_hz':int(sr),'frames':int(a.shape[0]),'channels':int(a.shape[1]),
      'evaluation_mode':mode,'finite_fraction':float(np.mean(finite)),'peak':float(np.max(peak)),
      'rms':float(np.sqrt(np.mean(clean*clean))),'crest_db':float(np.max(crest)),
      'channel_peak':[float(v) for v in peak],'channel_rms':[float(v) for v in rms],
      'dc':[float(v) for v in np.mean(clean,axis=0)],'abs_ge_1_fraction':float(np.mean(np.abs(clean)>=1.))}

def alignment(reference,candidate,max_shift=4096):
    r=_matrix(reference);c=_matrix(candidate)
    if r.shape[1]!=c.shape[1]:raise ValueError('channel mismatch')
    # Mono summary of channel energy while preserving antiphase inputs.
    rm=np.sqrt(np.mean(r*r,axis=1));cm=np.sqrt(np.mean(c*c,axis=1))
    rm-=rm.mean();cm-=cm.mean();best=None
    lim=min(max_shift,len(rm)-1,len(cm)-1)
    for shift in range(-lim,lim+1):
        if shift>=0:a=rm[shift:];b=cm[:len(a)]
        else:b=cm[-shift:];a=rm[:len(b)]
        den=float(np.linalg.norm(a)*np.linalg.norm(b));score=float(np.dot(a,b)/den) if den else (1. if not np.any(a) and not np.any(b) else 0.)
        key=(score,-abs(shift),-shift)
        if best is None or key>best[0]:best=(key,shift,score)
    return {'lag_samples':best[1],'correlation':best[2]}

def source_preservation(reference,candidate):
    r=_matrix(reference);c=_matrix(candidate)
    if r.shape!=c.shape:raise ValueError('shape mismatch')
    rv=r.ravel();cv=c.ravel();den=float(np.dot(cv,cv));gain=float(np.dot(rv,cv)/den) if den else 0.
    fitted=cv*gain;rr=float(np.sqrt(np.mean(rv*rv)));err=float(np.sqrt(np.mean((rv-fitted)**2)))
    corr=float(np.corrcoef(rv,cv)[0,1]) if np.std(rv)>0 and np.std(cv)>0 else (1. if np.array_equal(rv,cv) else 0.)
    d0=diagnose(r,1);d1=diagnose(c,1)
    return {'gain_fit':gain,'correlation':corr,'gain_aligned_relative_rms':err/max(rr,1e-30),
            'gain_aligned_error_db':20*math.log10(max(err/max(rr,1e-30),1e-15)),
            'crest_delta_db':d1['crest_db']-d0['crest_db']}
