"""Bounded vocal contour extraction with explicit abstention and shared spectral-feature provenance."""
from __future__ import annotations
import hashlib, math
import numpy as np
from scipy import signal
from zaaggenz_analysis import analyse_multiresolution, select_interval
from .model import VocalAnalysis,VocalCaptureError,VERSION,make_source_identity

METHOD={'id':'zg-vocal-contour-v1','version':'1.0.0','frame_ms':40.0,'hop_ms':10.0,'pitch_min_hz':65.0,'pitch_max_hz':500.0,'voicing_threshold':0.58}

def _audio(x):
    a=np.asarray(x)
    if a.ndim==1:a=a[:,None]
    if a.ndim!=2 or a.shape[1] not in (1,2) or not np.issubdtype(a.dtype,np.number) or not np.isfinite(a).all():raise VocalCaptureError('finite mono/stereo audio required')
    if len(a)==0:raise VocalCaptureError('capture audio is empty')
    return np.asarray(a,dtype=np.float64)
def _db(x):return 20*math.log10(max(float(x),1e-9))
def _identity(a,sr,origin):
    pcm=np.asarray(a,dtype='<f4',order='C');raw=pcm.tobytes(order='C');sha=hashlib.sha256(raw).hexdigest()
    return make_source_identity(sha,sr,a.shape[1],len(a),origin)

def _frame_pitch(frame,sr):
    x=np.asarray(frame,dtype=np.float64);x=x-np.mean(x)
    rms=float(np.sqrt(np.mean(x*x)))
    if rms<1e-5:return None,0.,1.
    w=signal.windows.hann(len(x),sym=False);y=x*w
    power=np.abs(np.fft.rfft(y))**2+1e-30;flat=float(np.exp(np.mean(np.log(power)))/np.mean(power));
    n=1
    while n<2*len(y):n*=2
    spec=np.fft.rfft(y,n);ac=np.fft.irfft(spec*np.conj(spec),n)[:len(y)];ac0=float(ac[0])
    if ac0<=1e-18:return None,0.,flat
    lo=max(1,int(sr/METHOD['pitch_max_hz']));hi=min(len(ac)-2,int(math.ceil(sr/METHOD['pitch_min_hz'])))
    if hi<=lo:return None,0.,flat
    region=ac[lo:hi+1]/ac0;k=lo+int(np.argmax(region));periodicity=float(ac[k]/ac0)
    if not (ac[k]>=ac[k-1] and ac[k]>=ac[k+1]):return None,0.,flat
    denom=ac[k-1]-2*ac[k]+ac[k+1];delta=0. if abs(denom)<1e-18 else .5*(ac[k-1]-ac[k+1])/denom;lag=k+float(np.clip(delta,-.5,.5))
    confidence=float(np.clip((periodicity-.35)/.55,0,1)*np.clip((.55-flat)/.5,0,1))
    if periodicity<METHOD['voicing_threshold'] or flat>.35 or confidence<.35:return None,confidence,flat
    return float(sr/lag),confidence,flat

def analyse_vocal(x,sample_rate_hz,*,origin='local-import'):
    if type(sample_rate_hz)is not int or not 8000<=sample_rate_hz<=192000:raise VocalCaptureError('sample rate out of range')
    if origin not in ('local-recording','local-import','generated-fixture'):raise VocalCaptureError('invalid local source origin')
    a=_audio(x)
    if len(a)>sample_rate_hz*30:raise VocalCaptureError('capture is limited to 30 seconds')
    mono=np.mean(a,axis=1);win=max(64,round(sample_rate_hz*METHOD['frame_ms']/1000));hop=max(1,round(sample_rate_hz*METHOD['hop_ms']/1000));half=win//2
    centers=list(range(0,len(mono),hop));rms=[]
    for c in centers:
        s=max(0,c-half);e=min(len(mono),c+win-half);frame=np.zeros(win);frame[:e-s]=mono[s:e];rms.append(float(np.sqrt(np.mean(frame*frame))))
    db=np.array([_db(v) for v in rms]);noise=float(np.percentile(db,20));peak=float(np.max(db));threshold=max(-60.,min(noise+10.,peak-18.));active=db>=threshold
    active=active.copy()
    for i in range(1,len(active)-1):
        if active[i] and not active[i-1] and not active[i+1]:active[i]=False
    for i in range(1,len(active)-2):
        if active[i-1] and not active[i] and active[i+1]:active[i]=True
        if active[i-1] and not active[i] and not active[i+1] and i+2<len(active) and active[i+2]:active[i:i+2]=True
    ranges=[];i=0
    while i<len(active):
        if not active[i]:i+=1;continue
        j=i+1
        while j<len(active) and active[j]:j+=1
        start=max(0,centers[i]-half);end=min(len(mono),centers[j-1]+win-half)
        if end-start>=round(sample_rate_hz*.045):ranges.append((start,end,i,j))
        i=j
    shared=analyse_multiresolution(a if a.shape[1]>1 else a[:,0],sample_rate_hz)['short']
    raw=[]
    for idx,(start,end,fi,fj) in enumerate(ranges):
        pitches=[];confs=[];flats=[]
        for c in centers[fi:fj]:
            s=c-half;e=s+win;frame=np.zeros(win);lo=max(0,s);hi=min(len(mono),e);frame[lo-s:hi-s]=mono[lo:hi]
            pitch,conf,flat=_frame_pitch(frame,sample_rate_hz);flats.append(flat)
            if pitch is not None:pitches.append(pitch);confs.append(conf)
        voiced_fraction=len(pitches)/max(1,fj-fi);pconf=float(np.median(confs)) if confs else 0.;medflat=float(np.median(flats)) if flats else 1.
        voiced=voiced_fraction>=.4 and pconf>=.45
        lowconf=(not voiced) and pconf>=.25
        pitch=float(np.median(pitches)) if voiced else None
        rows=select_interval(shared,start,end,'overlap');centroids=[r.spectral_centroid_hz for r in rows if r.valid and r.spectral_centroid_hz is not None];supports=[r.support_fraction for r in rows if r.valid]
        brightness=float(np.median(centroids)) if centroids else None;bconf=float(np.clip((np.median(supports) if supports else 0.)*(1-medflat),0,1))
        seg_rms=float(np.sqrt(np.mean(mono[start:end]**2)));rms_db=_db(seg_rms);before=db[max(0,fi-2):fi];jump=rms_db-(float(np.median(before)) if len(before) else threshold);onset=float(np.clip((jump+3)/18,0,1))
        raw.append({'id':f'vocal-{idx:03d}','start_sample':start,'end_sample':end,'onset_confidence':onset,'accent_db':0.,'rms_dbfs':rms_db,
                    'voicing':'voiced' if voiced else ('low-confidence' if lowconf else 'unvoiced'),'pitch_hz':pitch,'pitch_confidence':pconf if voiced else min(pconf,.499999),
                    'brightness_hz':brightness,'brightness_confidence':bconf,'spectral_flatness':float(np.clip(medflat,0,1))})
    if raw:
        median=float(np.median([r['rms_dbfs'] for r in raw]))
        for r in raw:r['accent_db']=float(np.clip(r['rms_dbfs']-median,-24,24))
    diag={'active_threshold_dbfs':threshold,'noise_floor_dbfs':noise,'peak_dbfs':peak,'frame_count':len(centers),
          'voiced_segments':sum(r['voicing']=='voiced' for r in raw),'unvoiced_segments':sum(r['voicing']=='unvoiced' for r in raw),
          'low_confidence_segments':sum(r['voicing']=='low-confidence' for r in raw),'shared_feature_method':'zg-multiresolution-features-v1'}
    return VocalAnalysis({'format':'zaaggenz-vocal-analysis','version':VERSION,'source':_identity(a,sample_rate_hz,origin),'method':dict(METHOD),'segments':raw,'diagnostics':diag})
