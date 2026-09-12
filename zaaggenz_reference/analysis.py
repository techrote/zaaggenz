from __future__ import annotations
import json,math,re,subprocess
from pathlib import Path
import numpy as np
from scipy import signal

METHOD='zg-reference-descriptor-v1'
BANDS=((20,120),(120,500),(500,2000),(2000,6000),(6000,10000))

def descriptor_pcm(x,sr=24000):
    a=np.asarray(x,dtype=np.float64)
    if a.ndim==1:a=a[:,None]
    if a.ndim!=2 or a.shape[1] not in (1,2) or len(a)<sr:raise ValueError('at least one second mono/stereo PCM required')
    if not np.isfinite(a).all():raise ValueError('nonfinite PCM')
    rows=[]
    for start in range(0,len(a)-sr+1,sr):
        z=a[start:start+sr]
        freqs,_,Z=signal.stft(z.T,fs=sr,nperseg=2048,noverlap=1792,boundary=None,padded=False,axis=-1)
        power=np.mean(abs(Z)**2,axis=0);mask=(freqs>=20)&(freqs<=min(10000,sr/2-1e-9));p=power[mask]+1e-20;f=freqs[mask]
        centroid=(f[:,None]*p).sum(axis=0)/p.sum(axis=0);flat=np.exp(np.mean(np.log(p),axis=0))/np.mean(p,axis=0)
        mean=power.mean(axis=1);den=mean[mask].sum()+1e-20
        rms=float(np.sqrt(np.mean(z*z)));peak=float(np.max(np.abs(z)))
        row={'start_s':start/sr,'rms':rms,'crest_db':20*math.log10(max(peak,1e-30)/max(rms,1e-30)),
             'power_centroid_hz':float(np.median(centroid)),'power_flatness':float(np.median(flat))}
        for lo,hi in BANDS:row[f'energy_{lo}_{hi}']=float(mean[(freqs>=lo)&(freqs<hi)].sum()/den)
        rows.append(row)
    threshold=float(np.quantile([r['rms'] for r in rows],.75));hot=[r for r in rows if r['rms']>=threshold]
    keys=['power_centroid_hz','power_flatness','crest_db']+[f'energy_{a}_{b}' for a,b in BANDS]
    left=a[:,0];right=a[:,-1]
    return {'method':METHOD,'analysis_sr':sr,'complete_windows':len(rows),'energetic_window_count':len(hot),
      'sample_peak':float(np.max(np.abs(a))),'samples_abs_ge_1_fraction':float(np.mean(np.abs(a)>=1)),
      'stereo_correlation':float(np.corrcoef(left,right)[0,1]) if a.shape[1]==2 else 1.,
      'side_mid_energy_ratio':float(np.mean(((left-right)/2)**2)/max(np.mean(((left+right)/2)**2),1e-30)) if a.shape[1]==2 else 0.,
      'energetic_medians':{k:float(np.median([r[k] for r in hot])) for k in keys},'timeline':rows}

def _ffprobe(path):
    raw=subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)],text=True,timeout=60)
    d=json.loads(raw);s=next(v for v in d['streams'] if v['codec_type']=='audio');return d,s

def _loudness(path):
    cp=subprocess.run(['ffmpeg','-nostdin','-hide_banner','-i',str(path),'-af','ebur128=peak=true','-f','null','-'],capture_output=True,text=True,timeout=180)
    if cp.returncode:raise RuntimeError('ffmpeg loudness failed')
    text=cp.stderr[cp.stderr.rfind('Summary:'):]
    def one(p):
        m=re.search(p,text);return float(m.group(1)) if m else None
    return {'integrated_lufs':one(r'I:\s+(-?[\d.]+) LUFS'),'loudness_range_lu':one(r'LRA:\s+(-?[\d.]+) LU'),'true_peak_dbtp':one(r'Peak:\s+(-?[\d.]+) dBFS')}

def analyse_file(path,analysis_sr=24000):
    path=Path(path);meta,stream=_ffprobe(path);duration=float(meta['format']['duration'])
    if duration>1800:raise ValueError('reference exceeds 30-minute ingest bound')
    raw=subprocess.check_output(['ffmpeg','-nostdin','-v','error','-i',str(path),'-map','0:a:0','-ar',str(analysis_sr),'-ac','2','-c:a','pcm_f32le','-f','f32le','pipe:1'],timeout=180)
    pcm=np.frombuffer(raw,dtype='<f4')
    if len(pcm)%2:raise ValueError('decoded stereo byte count mismatch')
    pcm=pcm.reshape(-1,2);d=descriptor_pcm(pcm,analysis_sr);d.update(decoded_duration_s=len(pcm)/analysis_sr,native_sample_rate=int(stream['sample_rate']),native_channels=int(stream['channels']),codec=stream['codec_name'],loudness=_loudness(path))
    d['dependency_versions']={'numpy':np.__version__,'scipy':__import__('scipy').__version__,'ffmpeg':subprocess.check_output(['ffmpeg','-version'],text=True).splitlines()[0]}
    return d

def compare_planning(observed,expected):
    checks={}
    def ck(name,a,b,tol):checks[name]={'observed':a,'expected':b,'delta':a-b,'tolerance':tol,'pass':abs(a-b)<=tol}
    ck('duration_s',observed['decoded_duration_s'],expected['decoded_24k_duration_s'],.001)
    ck('sample_peak',observed['sample_peak'],expected['sample_peak_24k'],.005)
    ck('integrated_lufs',observed['loudness']['integrated_lufs'],expected['integrated_lufs'],.2)
    ck('true_peak_dbtp',observed['loudness']['true_peak_dbtp'],expected['true_peak_dbtp'],.2)
    for key,tol in [('power_centroid_hz',2.),('power_flatness',.005),('crest_db',.15)]:ck(key,observed['energetic_medians'][key],expected['energetic_medians'][key],tol)
    return {'checks':checks,'pass':all(v['pass'] for v in checks.values()),'warning':'descriptor tolerance covers dependency-version numerical differences; exact file identity remains the hard source gate'}
