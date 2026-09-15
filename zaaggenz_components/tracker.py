from __future__ import annotations
import hashlib,math
from copy import deepcopy
import numpy as np
from scipy import signal,optimize
from zaaggenz_contracts import Contract
from zaaggenz_analysis.stft import STFTSpec,stft
from zaaggenz_analysis.features import analyse_multiresolution
from .model import ComponentTrackerSpec,ComponentAnalysis,ComponentError,exact_bypass
from .reconstruct import reconstruct_components

METHOD='zg-component-tracker-v1'

def _audio(x):
    a=np.asarray(x)
    mono=a.ndim==1
    if mono:a=a[:,None]
    if a.ndim!=2 or a.shape[1] not in (1,2):raise ComponentError('mono/stereo audio required')
    if not np.issubdtype(a.dtype,np.number) or not np.isfinite(a).all():raise ComponentError('finite numeric audio required')
    return np.asarray(a,dtype=np.float64),mono

def _pow2(value):return int(2**round(math.log2(max(32,value))))
def _pcm(a):return np.asarray(a,dtype='<f4',order='C').tobytes()
def _asset(a,sr,level='source'):
    x=np.asarray(a);ch=1 if x.ndim==1 else x.shape[1];frames=x.shape[0];payload=_pcm(x)
    return dict(kind='AudioAssetRef',version='1.0.0',content_sha256=hashlib.sha256(payload).hexdigest(),identity_domain='pcm-f32le-interleaved-v1',sample_rate_hz=sr,channels=ch,channel_layout='mono' if ch==1 else 'stereo-lr',frame_count=frames,level_domain=level,sample_policy='unclamped_float')

def _parabolic_frequency(mag,k,sr,nfft):
    if k<=0 or k>=len(mag)-1:return k*sr/nfft
    y=np.log(np.maximum(mag[k-1:k+2],1e-300));den=y[0]-2*y[1]+y[2]
    delta=0. if abs(den)<1e-20 else .5*(y[0]-y[2])/den
    return (k+float(np.clip(delta,-.5,.5)))*sr/nfft

def _fit_candidates(a,sr,result,i,frequencies,base_confidences,ambiguity_flags):
    if not frequencies:return []
    s0,s1=map(int,result.supports[i]);anchor=int(result.anchors[i]);start=max(0,s0);end=min(len(a),s1)
    if start>=end:return []
    win_n=s1-s0;w=signal.windows.hann(win_n,sym=False);local=np.arange(start,end)-s0;weight=np.sqrt(np.maximum(w[local],0));tau=(np.arange(start,end,dtype=np.float64)-anchor)/sr
    cols=[]
    for f in frequencies:
        ang=2*math.pi*f*tau;cols.extend((np.cos(ang),np.sin(ang)))
    X=np.column_stack(cols);Xw=X*weight[:,None];Y=a[start:end]*weight[:,None]
    try:coef,_,_,_=np.linalg.lstsq(Xw,Y,rcond=1e-8);cond=float(np.linalg.cond(Xw))
    except np.linalg.LinAlgError:return []
    penalty=1.0 if cond<1e4 else max(.05,1e4/max(cond,1e4));rows=[]
    for j,f in enumerate(frequencies):
        c=coef[2*j];s=coef[2*j+1];amps=np.hypot(c,s);ph=np.arctan2(-s,c);conf=float(np.clip(base_confidences[j]*penalty,0,1))
        rows.append(dict(frame=i,anchor=anchor,start=s0,end=s1,frequency_hz=float(f),amplitudes=tuple(float(max(0,x)) for x in amps),phases=tuple(float((x+math.pi)%(2*math.pi)-math.pi) for x in ph),confidence=conf,ambiguous=bool(ambiguity_flags[j]),condition=cond))
    return rows

def _candidate_frames(a,sr,spec):
    n=_pow2(sr*spec.window_seconds);hop=max(1,n//spec.hop_fraction);nfft=n*spec.fft_factor
    r=stft(a,sr,STFTSpec(n,hop,nfft,role='observation'));freqs=r.frequencies_hz();rows=[];abstained=0
    hi=min(spec.max_hz,sr*.499);band=np.where((freqs>=spec.min_hz)&(freqs<=hi))[0]
    if len(band)<3:return r,[[] for _ in range(len(r.anchors))],len(r.anchors)
    # Periodic Hann's first zeros are two native DFT bins either side of a sinusoid.
    # Zero padding interpolates that lobe; it does not create extra resolution.
    min_peak_bins=max(1,int(2*nfft/n))
    for i in range(len(r.anchors)):
        if r.valid_fraction[i]<spec.min_support_fraction:rows.append([]);abstained+=1;continue
        mag=np.sqrt(np.sum(np.abs(r.spectra[i])**2,axis=0));bmag=mag[band];power=bmag*bmag;mean=float(np.mean(power))
        if mean<=1e-24:rows.append([]);abstained+=1;continue
        flat=float(np.exp(np.mean(np.log(power+1e-30)))/(mean+1e-30))
        if flat>spec.max_flatness:rows.append([]);abstained+=1;continue
        floor=max(float(np.median(bmag)),1e-15);peak=float(np.max(bmag));prom=max(floor*2.5,peak*.03)
        local,_=signal.find_peaks(bmag,prominence=prom,height=max(floor*1.8,peak*.01),distance=min_peak_bins)
        ks=[int(band[k]) for k in local]
        if not ks:
            k=int(band[int(np.argmax(bmag))]);ks=[k] if mag[k]>=floor*1.8 else []
        ks=sorted(ks,key=lambda k:mag[k],reverse=True)[:spec.max_tracks]
        fs=[];confs=[]
        for k in ks:
            f=_parabolic_frequency(mag,k,sr,nfft)
            if not spec.min_hz<=f<=hi:continue
            snr=20*math.log10(max(mag[k],1e-30)/floor);conf=np.clip((snr-spec.min_snr_db)/30.,0,1)*np.clip(1-flat/max(spec.max_flatness,1e-9),0,1)
            if conf>=spec.min_confidence:fs.append(float(f));confs.append(float(conf))
        order=np.argsort(fs) if fs else [];fs=[fs[j] for j in order];confs=[confs[j] for j in order];amb=[False]*len(fs)
        for j in range(len(fs)-1):
            if 1200*abs(math.log2(fs[j+1]/fs[j]))<spec.ambiguity_cents:amb[j]=amb[j+1]=True
        fitted=_fit_candidates(a,sr,r,i,fs,confs,amb);rows.append(fitted)
        if not fitted:abstained+=1
    return r,rows,abstained

def _prediction(track,frame):
    last=track['rows'][-1];pred=last['frequency_hz']
    if len(track['rows'])>=2:
        prev=track['rows'][-2];steps=max(1,last['frame']-prev['frame']);ahead=max(1,frame-last['frame']);ratio=max(.5,min(2.,last['frequency_hz']/prev['frequency_hz']));pred*=ratio**(ahead/steps)
    return pred

def _track(frame_rows,spec):
    active=[];done=[];serial=0
    for frame,cands in enumerate(frame_rows):
        preds=[_prediction(t,frame) for t in active]
        # A real merge/crossing requires competition between established trajectories
        # that were both observed on the immediately preceding frame. A stale fragment
        # must not poison an otherwise continuous glide.
        for c in cands:
            close=[i for i,p in enumerate(preds) if active[i]['last_frame']==frame-1 and active[i]['missed']==0 and len(active[i]['rows'])>=2 and 1200*abs(math.log2(c['frequency_hz']/p))<spec.ambiguity_cents]
            if len(close)>1:
                c['ambiguous']=True
                for i in close:active[i]['ambiguous']=True
        matched_t=set();matched_c=set()
        if active and cands:
            cost=np.full((len(active),len(cands)),1e9,dtype=np.float64)
            for i,p in enumerate(preds):
                for j,c in enumerate(cands):cost[i,j]=1200*abs(math.log2(c['frequency_hz']/p))
            rr,cc=optimize.linear_sum_assignment(cost)
            for i,j in zip(rr,cc):
                if cost[i,j]>spec.max_jump_cents:continue
                row=deepcopy(cands[j]);active[i]['rows'].append(row);active[i]['missed']=0;active[i]['ambiguous']|=row['ambiguous'];active[i]['had_gap']|=(frame-active[i]['last_frame']>1);active[i]['last_frame']=frame;matched_t.add(i);matched_c.add(j)
        survivors=[]
        for i,t in enumerate(active):
            if i not in matched_t:t['missed']+=1
            if t['missed']>spec.max_gap_frames:done.append(t)
            else:survivors.append(t)
        active=survivors
        for j,c in enumerate(cands):
            if j in matched_c or len(active)>=spec.max_tracks:continue
            serial+=1;active.append(dict(serial=serial,rows=[deepcopy(c)],missed=0,ambiguous=bool(c['ambiguous']),had_gap=False,last_frame=frame))
    done.extend(active);return [t for t in done if len(t['rows'])>=spec.min_track_frames]

def _transient_mask(a,sr,spec):
    n=len(a);mask=np.zeros(n,dtype=np.float32)
    if n==0:return mask,0
    mono=np.mean(a,axis=1)
    try:
        timeline=analyse_multiresolution(a,sr)['short'];eligible=[f for f in timeline.frames if f.spectral_flux is not None and f.support_fraction>=.999];vals=np.array([f.spectral_flux for f in eligible],dtype=float)
    except Exception:eligible=[];vals=np.empty(0)
    anchors=[]
    if len(vals):
        med=float(np.median(vals));mad=float(np.median(np.abs(vals-med)));thr=max(1e-6,med+spec.transient_sigma*(1.4826*mad+1e-12));anchors.extend(f.anchor_sample for f in eligible if f.spectral_flux>thr)
    if n>2:
        d=np.abs(np.diff(mono,prepend=mono[0]));med=float(np.median(d));mad=float(np.median(np.abs(d-med)));peak=max(float(np.max(np.abs(mono))),1e-12);idx=np.flatnonzero((d>med+20*(1.4826*mad+1e-12))&(d>.15*peak));anchors.extend(int(x) for x in idx)
    guard=max(1,round(spec.transient_guard_ms*sr/1000))
    for x in anchors:mask[max(0,x-guard):min(n,x+guard+1)]=1
    return mask,len(set(anchors))

def _track_bundle(source,sr,tracks,spec,r,transient_mask,residual,transient):
    source1=source[:,0] if source.shape[1]==1 else source;residual1=residual[:,0] if residual.shape[1]==1 else residual;transient1=transient[:,0] if transient.shape[1]==1 else transient
    asset=_asset(source1,sr);resasset=_asset(residual1,sr);transasset=_asset(transient1,sr);exported=[];transform_frames=0;ambiguous_tracks=0
    for idx,t in enumerate(tracks,1):
        continuity='unknown' if t['ambiguous'] else ('reanchored' if t['had_gap'] else 'continuous')
        if continuity=='unknown':ambiguous_tracks+=1
        frames=[]
        for row in t['rows']:
            action='transform' if continuity=='continuous' and row['confidence']>=spec.transform_confidence and transient_mask[row['anchor']]<.5 else 'preserve'
            if action=='transform':transform_frames+=1
            frames.append(dict(support=dict(start_sample=row['start'],end_sample=row['end'],anchor_sample=row['anchor'],padding='zero'),frequency_hz=row['frequency_hz'],amplitudes=list(row['amplitudes']),phases_radians=list(row['phases']),confidence=row['confidence'],action=action))
        exported.append(dict(id=f'p{idx:04d}',segment_id=f's{idx:04d}',continuity=continuity,frames=frames))
    conf=dict(spec.metadata());conf.update(window_samples=r.spec.window_samples,hop_samples=r.spec.hop_samples,fft_samples=r.spec.fft_samples)
    return Contract(dict(kind='PartialTrackBundle',version='1.0.0',asset=asset,method=dict(id=METHOD,version='1.0.0',configuration=conf),phase_convention='cosine-at-anchor-radians-v1',channel_policy='shared-frequency-independent-channel-coefficients',data_origin='estimated',tracks=exported,residual_asset=resasset,transient_asset=transasset,remainder_policy='additive-owned-remainders-v1')),transform_frames,ambiguous_tracks

def analyse_components(x,sample_rate_hz,spec=ComponentTrackerSpec()):
    if not isinstance(spec,ComponentTrackerSpec):raise ComponentError('ComponentTrackerSpec required')
    if type(sample_rate_hz)is not int or not 8000<=sample_rate_hz<=192000:raise ComponentError('sample rate out of range')
    a,mono=_audio(x);source32=np.asarray(a,dtype=np.float32);n=len(a)
    if n==0:
        dummy=type('R',(),{'spec':type('S',(),{'window_samples':_pow2(sample_rate_hz*spec.window_seconds),'hop_samples':1,'fft_samples':_pow2(sample_rate_hz*spec.window_seconds)*spec.fft_factor})()})();z=np.zeros_like(source32);mask=np.zeros(0,dtype=np.float32);bundle,_,_=_track_bundle(source32,sample_rate_hz,[],spec,dummy,mask,z,z);src=source32[:,0] if mono else source32
        return ComponentAnalysis(bundle,src,src.copy(),src.copy(),src.copy(),mask,dict(method=METHOD,sample_rate_hz=sample_rate_hz,tracks=0,tracked_frames=0,transform_frames=0,abstained_frames=0,ambiguous_tracks=0,transient_fraction=0.,reconstruction_rms_error=0.),sample_rate_hz)
    r,frames,abstained=_candidate_frames(a,sample_rate_hz,spec);tracks=_track(frames,spec);mask,onsets=_transient_mask(a,sample_rate_hz,spec);zero=np.zeros_like(source32);temp,_,_=_track_bundle(source32,sample_rate_hz,tracks,spec,r,mask,zero,zero)
    raw=reconstruct_components(temp);raw2=raw[:,None] if raw.ndim==1 else raw;sinusoidal=np.asarray(raw2*(1-mask[:,None]),dtype=np.float32);transient=np.asarray(source32*mask[:,None],dtype=np.float32);residual=np.asarray(source32-sinusoidal-transient,dtype=np.float32);bundle,transform_frames,ambiguous_tracks=_track_bundle(source32,sample_rate_hz,tracks,spec,r,mask,residual,transient)
    reconstruction=np.asarray(sinusoidal,dtype=np.float64)+np.asarray(transient,dtype=np.float64)+np.asarray(residual,dtype=np.float64);err=float(np.sqrt(np.mean((reconstruction-np.asarray(source32,dtype=np.float64))**2))) if source32.size else 0.;tracked=sum(len(t['rows']) for t in tracks);source_rms=float(np.sqrt(np.mean(source32.astype(np.float64)**2))) if source32.size else 0.
    diag=dict(method=METHOD,sample_rate_hz=sample_rate_hz,tracks=len(tracks),tracked_frames=tracked,transform_frames=transform_frames,abstained_frames=abstained,ambiguous_tracks=ambiguous_tracks,detected_transient_onsets=onsets,transient_fraction=float(np.mean(mask)) if n else 0.,source_rms=source_rms,sinusoidal_rms=float(np.sqrt(np.mean(sinusoidal.astype(np.float64)**2))) if sinusoidal.size else 0.,residual_rms=float(np.sqrt(np.mean(residual.astype(np.float64)**2))) if residual.size else 0.,reconstruction_rms_error=err,window_samples=r.spec.window_samples,hop_samples=r.spec.hop_samples,fft_samples=r.spec.fft_samples)
    src=source32[:,0] if mono else source32;sin=sinusoidal[:,0] if mono else sinusoidal;tra=transient[:,0] if mono else transient;res=residual[:,0] if mono else residual
    return ComponentAnalysis(bundle,src,sin,tra,res,mask,diag,sample_rate_hz)
