"""Local-only observational audit. NEVER emits source audio or aligned stems.
Pinned 24-kHz, 20..10000-Hz spectral descriptors match the planning method.
One-second features/energetic selections are not matched musical passages.
"""
from __future__ import annotations
import json, math, pathlib, re, subprocess
import numpy as np
from scipy import signal
from scipy.spatial.distance import cdist
from common import METHOD, dump, table, sha, rms, db

FILES={
 'activation':'Aversion - Activation [FREE PROMO].mp3',
 'zaagtivation':"AVERSION - ACTIVATION (EQUAL2'S ZAAGTIVATION EDIT) [FREE DL].mp3",
 'one_kick':'CareLexX - 1 Kick A Second.f251.webm',
 'push_up':'Creeds - Push Up (MYTH Edit) (Uptempo).f251.webm',
 'con_calma':'Daddy Yankee - Con Calma (MARBUL X EXCIDIUM X CARELEXX EDIT)(1).webm',
 'go_insane':'GO INSANE(1).webm',
}
BANDS=[(20,120),(120,500),(500,2000),(2000,6000),(6000,10000)]


def loudness(path):
    cmd=['ffmpeg','-nostdin','-hide_banner','-i',str(path),'-af','ebur128=peak=true','-f','null','-']
    text=subprocess.run(cmd,capture_output=True,text=True,check=True,timeout=120).stderr
    text=text[text.rfind('Summary:'):]
    def extract(pattern):
        m=re.search(pattern,text)
        return float(m.group(1)) if m else None
    return {'integrated_lufs':extract(r'I:\s+(-?[\d.]+) LUFS'),
            'loudness_range_lu':extract(r'LRA:\s+(-?[\d.]+) LU'),
            'ffmpeg_true_peak_dbtp':extract(r'Peak:\s+(-?[\d.]+) dBFS'),
            'note':'FFmpeg ebur128 native-file measurement; printed precision 0.1 units. Not a playback SPL estimate.'}


def analyse(path,ident):
    sr=24000
    meta=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)]))
    stream=next(s for s in meta['streams'] if s['codec_type']=='audio')
    if float(meta['format']['duration'])>1800: raise ValueError('30-minute audit limit exceeded')
    raw=subprocess.check_output(['ffmpeg','-nostdin','-v','error','-i',str(path),'-map','0:a:0',
          '-ar',str(sr),'-ac','2','-c:a','pcm_f32le','-f','f32le','pipe:1'],timeout=120)
    x=np.frombuffer(raw,dtype='<f4').reshape(-1,2)
    if not np.isfinite(x).all(): raise ValueError('nonfinite decoded audio')
    rows=[]
    for start in range(0,len(x)-sr+1,sr):
        z=x[start:start+sr]
        freqs,_,Z=signal.stft(z.T,fs=sr,nperseg=2048,noverlap=1792,boundary=None,padded=False,axis=-1)
        power=np.mean(abs(Z)**2,axis=0)
        mask=(freqs>=20)&(freqs<=10000);p=power[mask].astype(float)+1e-20;f=freqs[mask]
        centroid=(f[:,None]*p).sum(axis=0)/p.sum(axis=0)
        flat=np.exp(np.mean(np.log(p),axis=0))/np.mean(p,axis=0)
        mean=power.mean(axis=1); den=mean[mask].sum()+1e-20
        row={'id':ident,'start_s':start/sr,'end_s':(start+sr)/sr,'rms':rms(z),'crest_db':db(float(abs(z).max())/rms(z)),
             'power_centroid_hz':float(np.median(centroid)),'power_flatness':float(np.median(flat))}
        for a,b in BANDS:row[f'energy_{a}_{b}']=float(mean[(freqs>=a)&(freqs<b)].sum()/den)
        rows.append(row)
    hop=240; envelopes=[]
    for lo,hi in [(25,180),(180,1200),(1200,7000)]:
        z=signal.sosfilt(signal.butter(3,[lo,hi],fs=sr,btype='bandpass',output='sos'),x,axis=0)
        n=len(z)//hop;e=np.sqrt(np.mean(z[:n*hop].reshape(n,hop,2)**2,axis=(1,2))+1e-20)
        d=np.maximum(np.diff(np.log(e+1e-5),prepend=np.log(e[0]+1e-5)),0)
        envelopes.append(d/(np.percentile(d,95)+1e-9))
    onset=sum(envelopes);onset=np.maximum(onset-np.median(onset),0)
    tempo=[]
    for t0 in range(0,int(len(x)/sr)-15,16):
        v=onset[t0*100:(t0+16)*100];v=v-v.mean()
        a=signal.correlate(v,v,mode='full',method='fft')[len(v)-1:];a/=a[0]+1e-20
        # Integer lags: return actual represented period, not falsely exact BPM.
        lags=np.arange(17,301);peaks,_=signal.find_peaks(a[lags],distance=2)
        ix=sorted(peaks,key=lambda i:a[lags[i]],reverse=True)[:6]
        tempo.append({'start_s':t0,'support_s':16,'candidates':[{'bpm':6000/int(lags[i]),'lag_10ms':int(lags[i]),'acf':float(a[lags[i]])} for i in ix]})
    threshold=np.quantile([r['rms'] for r in rows],.75)
    hot=[r for r in rows if r['rms']>=threshold]
    keys=['power_centroid_hz','power_flatness','crest_db']+[f'energy_{a}_{b}' for a,b in BANDS]
    left=x[:,0].astype(float); right=x[:,1].astype(float)
    summary={'id':ident,'filename':path.name,'sha256':sha(path),'bytes':path.stat().st_size,
      'native_sample_rate':int(stream['sample_rate']),'native_channels':int(stream['channels']),
      'codec':stream['codec_name'],'decoded_24k_duration_s':len(x)/sr,'analysis_sr':sr,
      'sample_peak_24k':float(abs(x).max()),'decoded_samples_abs_ge_1_fraction':float(np.mean(abs(x)>=1)),
      'stereo_correlation':float(np.corrcoef(left,right)[0,1]),
      'side_mid_energy_ratio':rms((left-right)/2)**2/(rms((left+right)/2)**2+1e-20),
      'energetic_window_count':len(hot),'energetic_medians':{k:float(np.median([r[k] for r in hot])) for k in keys},
      'loudness':loudness(path),'tempo_ambiguity_windows':tempo}
    return summary,rows


def pair_candidates(rows):
    """Proposals based on band-envelope shape; not alignment truth/confidence."""
    keys=[f'energy_{a}_{b}' for a,b in BANDS]+['rms','power_centroid_hz','power_flatness']
    windows={}
    for name in ('activation','zaagtivation'):
        r=[v for v in rows if v['id']==name]; feature=np.array([[v[k] for k in keys] for v in r])
        feature=np.log(np.maximum(feature,1e-8))
        feature=(feature-feature.mean(axis=0))/(feature.std(axis=0)+1e-8)
        w=[]; starts=[]
        for j in range(8,len(feature)-8,4):
            w.append(feature[j:j+8].ravel());starts.append(j)
        windows[name]=(np.array(starts),np.asarray(w))
    ta,a=windows['activation'];tb,b=windows['zaagtivation'];dist=cdist(a,b)/np.sqrt(a.shape[1])
    ij=[]
    for i in range(len(a)):
        j=int(np.argmin(dist[i]));order=np.sort(dist[i]); margin=float(order[1]-order[0])
        if int(np.argmin(dist[:,j]))==i:ij.append((float(dist[i,j]),i,j,margin))
    chosen=[]
    for distance,i,j,margin in sorted(ij):
        if all(abs(int(ta[i])-r['activation_start_s'])>=8 and abs(int(tb[j])-r['zaagtivation_start_s'])>=8 for r in chosen):
            chosen.append({'activation_start_s':int(ta[i]),'zaagtivation_start_s':int(tb[j]),'duration_s':8,
               'zfeature_rms_distance':distance,'runner_up_distance_margin':margin,'status':'unreviewed similarity candidate; NOT verified corresponding motif'})
        if len(chosen)==10:break
    return chosen


def main(source,out,planning=None):
    missing=[]; summaries=[];allrows=[]
    for name,filename in FILES.items():
        path=source/filename
        if not path.is_file(): missing.append(name);continue
        summary,rows=analyse(path,name);summaries.append(summary);allrows.extend(rows)
        print(name,summary['decoded_24k_duration_s'],summary['loudness'],flush=True)
    if not allrows:
        raise ValueError('No recognised local reference files; no fabricated measurements produced')
    table(out/'reference_timeline.csv',allrows)
    cand=pair_candidates(allrows) if {'activation','zaagtivation'}<=set(s['id'] for s in summaries) else []
    checks=[]
    if planning and planning.is_file():
        old=json.loads(planning.read_text())['tracks']
        for s in summaries:
            if s['id'] not in old:continue
            o=old[s['id']]
            checks.append({'id':s['id'],'sha256_matches':s['sha256']==o['sha256'],
                'decoded_duration_delta_s':s['decoded_24k_duration_s']-o['decoded_duration_s'],
                'energetic_median_deltas':{k:s['energetic_medians'][k]-o['energetic_medians'][k] for k in s['energetic_medians']}})
    result={'method':METHOD,'frame_method':'planning paired-descriptor-v1 (24 kHz stereo power, 2048/256 Hann; 20..10000 Hz)',
       'tracks':summaries,'missing_inputs':missing,'planning_reproduction_checks':checks,
       'pair_candidates':cand,'warnings':['No source audio is included in these outputs.',
       'Title metadata does not certify provenance or redistribution rights.',
       'Within-track top RMS quartiles are not level/section/motif matched excerpts.',
       'Tempo autocorrelations contain half/double/quarter ambiguities; 10 ms lag grid is coarse.',
       'Similarity candidates require manual role/motif review and matched level before inference.',
       'No key, chord, source separation or original producer-chain inference performed.']}
    dump(out/'reference_audit.json',result)
    return result
