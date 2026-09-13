from __future__ import annotations
import hashlib,math
import numpy as np
from scipy import signal
from .model import DescriptorError,observation

def audio_array(x):
    a=np.asarray(x)
    mono=a.ndim==1
    if mono:a=a[:,None]
    if a.ndim!=2 or a.shape[1] not in (1,2):raise DescriptorError('mono/stereo audio required')
    if not np.issubdtype(a.dtype,np.number) or not np.isfinite(a).all():raise DescriptorError('finite numeric audio required')
    return np.asarray(a,dtype=np.float64),mono

def pcm_asset(x,sample_rate_hz,level_domain='source'):
    a,mono=audio_array(x)
    if type(sample_rate_hz)is not int or not 8000<=sample_rate_hz<=192000:raise DescriptorError('sample rate out of range')
    payload=np.asarray(a[:,0] if mono else a,dtype='<f4',order='C').tobytes();channels=1 if mono else a.shape[1]
    return dict(kind='AudioAssetRef',version='1.0.0',content_sha256=hashlib.sha256(payload).hexdigest(),identity_domain='pcm-f32le-interleaved-v1',
        sample_rate_hz=sample_rate_hz,channels=channels,channel_layout='mono' if channels==1 else 'stereo-lr',frame_count=len(a),level_domain=level_domain,sample_policy='unclamped_float')

def whole_support(n):
    n=int(n)
    if n<0:raise DescriptorError('negative frame count')
    if n==0:return dict(start_sample=0,end_sample=1,anchor_sample=0,padding='zero')
    return dict(start_sample=0,end_sample=n,anchor_sample=(n-1)//2,padding='none')

def _analysis_channel(a):
    if not len(a):return np.zeros(0,dtype=np.float64),0
    energy=np.mean(a*a,axis=0);index=int(np.argmax(energy));return a[:,index],index

def _parabolic(y,k):
    if k<=0 or k>=len(y)-1:return float(k),float(y[k])
    a,b,c=float(y[k-1]),float(y[k]),float(y[k+1]);den=a-2*b+c
    delta=0. if abs(den)<1e-18 else .5*(a-c)/den;delta=float(np.clip(delta,-.5,.5));return k+delta,b-.25*(a-c)*delta

def periodicity_observations(x,sample_rate_hz,*,min_f0_hz=30.,max_f0_hz=1200.,support=None):
    a,_=audio_array(x);support=whole_support(len(a)) if support is None else support
    if len(a)<32:
        d={'reason':'too-short'}
        return [observation('periodicity_peak',None,support,validity='abstained',confidence=0.,role='estimate',details=d),
                observation('f0_candidate_hz',None,support,validity='abstained',confidence=0.,role='estimate',details=d)]
    y,ch=_analysis_channel(a);y=y-np.mean(y);energy=float(np.dot(y,y))
    if energy<=1e-20:
        details={'reason':'silent-or-constant-after-dc-removal','analysis_channel':ch}
        return [observation('periodicity_peak',None,support,validity='abstained',confidence=0.,role='estimate',details=details),
                observation('f0_candidate_hz',None,support,validity='abstained',confidence=0.,role='estimate',details=details)]
    n=len(y);fft_n=1<<(2*n-1).bit_length();Y=np.fft.rfft(y,n=fft_n);ac=np.fft.irfft(Y*np.conj(Y),n=fft_n)[:n]
    overlap=np.arange(n,0,-1,dtype=np.float64);ac=ac/overlap;ac/=max(float(ac[0]),1e-30)
    lo=max(1,int(math.floor(sample_rate_hz/max_f0_hz)));hi=min(n-2,int(math.ceil(sample_rate_hz/min_f0_hz)))
    if lo>=hi:raise DescriptorError('f0 search range is unsupported by this excerpt/sample rate')
    segment=ac[lo:hi+1];peaks,_=signal.find_peaks(segment,prominence=.01);ks=[lo+int(k) for k in peaks]
    if not ks:ks=[lo+int(np.argmax(segment))]
    candidates=[]
    for k in ks:
        pos,score=_parabolic(ac,k)
        if pos>0:candidates.append((float(score),float(sample_rate_hz/pos),float(pos)))
    candidates.sort(reverse=True)
    if not candidates:
        d={'reason':'no-periodic-candidate','analysis_channel':ch}
        return [observation('periodicity_peak',None,support,validity='abstained',confidence=0.,role='estimate',details=d),observation('f0_candidate_hz',None,support,validity='abstained',confidence=0.,role='estimate',details=d)]
    near=[c for c in candidates if c[0]>=candidates[0][0]-.02];best=min(near,key=lambda c:c[2]);best_score=max(0.,min(1.,best[0]));alts=[{'hz':c[1],'periodicity':max(0.,min(1.,c[0]))} for c in candidates[:6]]
    octave=False
    for c in candidates:
        if c==best:continue
        ratio=max(c[1],best[1])/min(c[1],best[1])
        if abs(1200*math.log2(ratio)-1200)<45 and c[0]>=best[0]-.06:octave=True;break
    valid=best_score>=.18;details={'analysis_channel':ch,'alternatives':alts,'octave_ambiguous':octave,'search_hz':[float(min_f0_hz),float(max_f0_hz)],'estimator':'unbiased autocorrelation, shortest-lag tie preference'}
    validity='valid' if valid else 'unknown';value=best_score if valid else None;hz=best[1] if valid else None
    return [observation('periodicity_peak',value,support,validity=validity,confidence=best_score,role='estimate',details=details),
            observation('f0_candidate_hz',hz,support,validity=validity,confidence=best_score,role='estimate',details=details)]

def envelope_observations(x,sample_rate_hz,*,support=None):
    a,_=audio_array(x);support=whole_support(len(a)) if support is None else support;y,ch=_analysis_channel(a)
    if len(y)<64:
        d={'reason':'too-short'}
        return [observation('envelope_modulation_depth',None,support,validity='abstained',confidence=0.,role='estimate',details=d),observation('envelope_modulation_hz',None,support,validity='abstained',confidence=0.,role='estimate',details=d)]
    frame=max(16,round(.020*sample_rate_hz));hop=max(1,round(.005*sample_rate_hz))
    if len(y)<frame:y=np.pad(y,(0,frame-len(y)))
    starts=np.arange(0,max(1,len(y)-frame+1),hop,dtype=int);env=np.array([math.sqrt(float(np.mean(y[s:s+frame]**2))) for s in starts],dtype=np.float64);mean=float(np.mean(env))
    if mean<=1e-12:
        d={'reason':'silent','analysis_channel':ch,'frame_samples':frame,'hop_samples':hop}
        return [observation('envelope_modulation_depth',None,support,validity='abstained',confidence=0.,role='estimate',details=d),observation('envelope_modulation_hz',None,support,validity='abstained',confidence=0.,role='estimate',details=d)]
    depth=min(4.,float(np.std(env)/mean));details={'analysis_channel':ch,'frame_samples':frame,'hop_samples':hop,'level_policy':'std(RMS envelope)/mean(RMS envelope)'}
    depth_obs=observation('envelope_modulation_depth',depth,support,confidence=min(1.,depth/.1+0.1),role='estimate',details=details)
    z=env-np.mean(env);n=len(z)
    if n<8 or depth<.004:return [depth_obs,observation('envelope_modulation_hz',None,support,validity='abstained',confidence=0.,role='estimate',details={**details,'reason':'nearly-constant-envelope'})]
    win=np.hanning(n);spec=np.abs(np.fft.rfft(z*win))**2;freq=np.fft.rfftfreq(n,d=hop/sample_rate_hz);mask=(freq>=.5)&(freq<=30.)
    if not np.any(mask) or float(np.sum(spec[mask]))<=1e-24:return [depth_obs,observation('envelope_modulation_hz',None,support,validity='unknown',confidence=0.,role='estimate',details={**details,'reason':'no-resolved-modulation-peak'})]
    ids=np.flatnonzero(mask);k=int(ids[np.argmax(spec[mask])]);hz=float(freq[k]);conf=float(spec[k]/max(np.sum(spec[mask]),1e-30));valid=conf>=.15
    return [depth_obs,observation('envelope_modulation_hz',hz if valid else None,support,validity='valid' if valid else 'unknown',confidence=min(1.,conf),role='estimate',details={**details,'modulation_band_hz':[.5,30.]})]

def occupancy_observation(x,sample_rate_hz,*,support=None):
    a,_=audio_array(x);support=whole_support(len(a)) if support is None else support
    if len(a)<32:return observation('spectral_occupancy',None,support,validity='abstained',confidence=0.,role='estimate',details={'reason':'too-short'})
    nper=min(4096,len(a));powers=[]
    for c in range(a.shape[1]):
        f,p=signal.welch(a[:,c],fs=sample_rate_hz,window='hann',nperseg=nper,noverlap=nper//2,scaling='spectrum');powers.append(p)
    p=np.mean(powers,axis=0);mask=(f>=20)&(f<=min(20000,sample_rate_hz*.499));q=np.asarray(p[mask],dtype=np.float64);total=float(q.sum())
    if total<=1e-24:return observation('spectral_occupancy',None,support,validity='abstained',confidence=0.,role='estimate',details={'reason':'silent'})
    q=q/total;entropy=-float(np.sum(q*np.log(np.maximum(q,1e-300))));effective=math.exp(entropy);value=float(np.clip(effective/len(q),0,1))
    return observation('spectral_occupancy',value,support,confidence=min(1.,math.sqrt(total)/(math.sqrt(total)+1e-6)),role='estimate',details={'definition':'exp(Shannon entropy)/band-bin-count','band_hz':[20,min(20000,sample_rate_hz*.499)],'nperseg':nper,'channel_policy':'mean power; no stereo cancellation'})

def rms_observation(x,*,support=None):
    a,_=audio_array(x);support=whole_support(len(a)) if support is None else support;value=float(np.sqrt(np.mean(a*a))) if a.size else 0.
    return observation('rms',value,support,role='measurement',confidence=None,details={'channels':'all-samples-equal-weight'})
