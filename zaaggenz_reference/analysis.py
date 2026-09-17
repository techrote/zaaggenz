from __future__ import annotations
import json,math,re,subprocess,tempfile
from pathlib import Path
import numpy as np
from scipy import signal

METHOD='zg-reference-descriptor-v1'
BANDS=((20,120),(120,500),(500,2000),(2000,6000),(6000,10000))
MAX_REFERENCE_DURATION_S=1800
DECODE_CHANNELS=2
DECODE_SAMPLE_BYTES=4


def _correlation_evidence(left,right):
    """Return Pearson correlation plus explicit availability provenance.

    Pearson correlation is undefined when either channel has zero variance.  Scale
    each channel before centering so otherwise-finite high-magnitude inputs do not
    overflow merely while deciding whether correlation is defined.
    """
    def centered(v):
        scale=float(np.max(np.abs(v)))
        if scale==0.0:
            return None,None
        y=v/scale
        y=y-np.mean(y)
        energy=float(np.dot(y,y))
        if energy==0.0 or not math.isfinite(energy):
            return None,None
        return y,energy

    l,le=centered(left);r,re_=centered(right)
    if l is None or r is None:
        if l is None and r is None:reason='both-channels-zero-variance'
        elif l is None:reason='left-channel-zero-variance'
        else:reason='right-channel-zero-variance'
        return None,{'status':'unknown','reason':reason}
    denominator=math.sqrt(le*re_)
    value=float(np.dot(l,r)/denominator)
    # Roundoff can exceed the mathematical range by a few ulps.
    value=max(-1.0,min(1.0,value))
    return value,{'status':'observed','reason':None}


def _require_finite_evidence(value,path='descriptor'):
    """Fail closed before descriptor evidence containing NaN/Infinity escapes."""
    if isinstance(value,dict):
        for key,item in value.items():_require_finite_evidence(item,f'{path}.{key}')
    elif isinstance(value,(list,tuple)):
        for index,item in enumerate(value):_require_finite_evidence(item,f'{path}[{index}]')
    elif isinstance(value,(float,np.floating)) and not math.isfinite(float(value)):
        raise ValueError(f'nonfinite descriptor evidence at {path}')


def _window_descriptor(z,sr,start):
    freqs,_,Z=signal.stft(z.T,fs=sr,nperseg=2048,noverlap=1792,boundary=None,padded=False,axis=-1)
    power=np.mean(abs(Z)**2,axis=0);mask=(freqs>=20)&(freqs<=min(10000,sr/2-1e-9));p=power[mask]+1e-20;f=freqs[mask]
    centroid=(f[:,None]*p).sum(axis=0)/p.sum(axis=0);flat=np.exp(np.mean(np.log(p),axis=0))/np.mean(p,axis=0)
    mean=power.mean(axis=1);den=mean[mask].sum()+1e-20
    rms=float(np.sqrt(np.mean(z*z)));peak=float(np.max(np.abs(z)))
    row={'start_s':start/sr,'rms':rms,'crest_db':20*math.log10(max(peak,1e-30)/max(rms,1e-30)),
         'power_centroid_hz':float(np.median(centroid)),'power_flatness':float(np.median(flat))}
    for lo,hi in BANDS:row[f'energy_{lo}_{hi}']=float(mean[(freqs>=lo)&(freqs<hi)].sum()/den)
    return row


def _row_summary(rows):
    threshold=float(np.quantile([r['rms'] for r in rows],.75));hot=[r for r in rows if r['rms']>=threshold]
    keys=['power_centroid_hz','power_flatness','crest_db']+[f'energy_{a}_{b}' for a,b in BANDS]
    return hot,{k:float(np.median([r[k] for r in hot])) for k in keys}


def descriptor_pcm(x,sr=24000):
    a=np.asarray(x,dtype=np.float64)
    if a.ndim==1:a=a[:,None]
    if a.ndim!=2 or a.shape[1] not in (1,2) or len(a)<sr:raise ValueError('at least one second mono/stereo PCM required')
    if not np.isfinite(a).all():raise ValueError('nonfinite PCM')
    rows=[_window_descriptor(a[start:start+sr],sr,start) for start in range(0,len(a)-sr+1,sr)]
    hot,medians=_row_summary(rows)
    left=a[:,0];right=a[:,-1]
    if a.shape[1]==2:
        correlation,correlation_evidence=_correlation_evidence(left,right)
    else:
        correlation=1.0
        correlation_evidence={'status':'legacy-mono-convention','reason':'mono-input'}
    result={'method':METHOD,'analysis_sr':sr,'complete_windows':len(rows),'energetic_window_count':len(hot),
      'sample_peak':float(np.max(np.abs(a))),'samples_abs_ge_1_fraction':float(np.mean(np.abs(a)>=1)),
      'stereo_correlation':correlation,'stereo_correlation_evidence':correlation_evidence,
      'side_mid_energy_ratio':float(np.mean(((left-right)/2)**2)/max(np.mean(((left+right)/2)**2),1e-30)) if a.shape[1]==2 else 0.,
      'energetic_medians':medians,'timeline':rows}
    _require_finite_evidence(result)
    return result


def reference_analysis_resource_bound(analysis_sr=24000):
    """Return the deterministic decoded-spool and PCM chunk bounds for ZG-006."""
    if not isinstance(analysis_sr,int) or isinstance(analysis_sr,bool) or analysis_sr<=0:
        raise ValueError('analysis_sr must be a positive integer')
    chunk_frames=analysis_sr
    frame_bytes=DECODE_CHANNELS*DECODE_SAMPLE_BYTES
    return {
        'max_duration_s':MAX_REFERENCE_DURATION_S,
        'max_decoded_frames':MAX_REFERENCE_DURATION_S*analysis_sr,
        'max_decoded_spool_bytes':MAX_REFERENCE_DURATION_S*analysis_sr*frame_bytes,
        'chunk_frames':chunk_frames,
        'max_chunk_f32_bytes':chunk_frames*frame_bytes,
        'max_chunk_f64_bytes':chunk_frames*DECODE_CHANNELS*8,
        'max_timeline_rows':MAX_REFERENCE_DURATION_S,
    }


def _iter_spooled_stereo_chunks(spool,analysis_sr,total_frames):
    """Yield at most one second of decoded f32 stereo PCM per read."""
    if total_frames<0:raise ValueError('decoded frame count must be non-negative')
    spool.seek(0);remaining=total_frames;frame_bytes=DECODE_CHANNELS*DECODE_SAMPLE_BYTES
    while remaining:
        frames=min(analysis_sr,remaining);needed=frames*frame_bytes;raw=spool.read(neeeded)
        if len(raw)!=needed:raise ValueError('decoded stereo stream truncated')
        pcm=np.frombuffer(raw,dtype='<f4')
        if pcm.size!=frames*DECODE_CHANNELS:raise ValueError('decoded stereo byte count mismatch')
        yield pcm.reshape(frames,DECODE_CHANNELS)
        remaining-=frames


def _spooled_correlation(spool,analysis_sr,total_frames,left_scale,right_scale):
    scales=(left_scale,right_scale);means=[None,None]
    sums=[0.0,0.0]
    for pcm32 in _iter_spooled_stereo_chunks(spool,analysis_sr,total_frames):
       z=np.asarray(pcm32,dtype=np.float64)
        for channel,scale in enumerate(scales):
            if scale!=0.0:sums[channel]+=float(np.sum(z[:,channel]/scale,dtype=np.float64))
    for channel,scale in enumerate(scales):
        if scale!=0.0:means[channel]=sums[channel]/total_frames
    energies=[None,None];cross=0.0
    accum=[0.0,0.0]
    for pcm32 in _iter_spooled_stereo_chunks(spool,analysis_sr,total_frames):
        z=np.asarray(pcm32,dtype=np.float64);centered=[None,None]
        for channel,scale in enumerate(scales):
            if means[channel] is not None:
                centered[channel]=z[:,channel]/scale-means[channel]
                accum[channel]+=float(np.dot(centered[channel],centered[channel]))
        if centered[0] is not None and centered[1] is not None:
            cross+=float(np.dot(centered[0],centered[1]))
    for channel in range(2):
        energy=accum[channel]
        if means[channel] is not None and energy!=0.0 and math.isfinite(energy):energies[channel]=energy
    if energies[0] is None or energies[1] is None:
        if energies[0] is None and energies[1] is None:reason='both-channels-zero-variance'
        elif energies[0] is None:reason='left-channel-zero-variance'
        else:reason='right-channel-zero-variance'
        return None,{'status':'unknown','reason':reason}
    denominator=math.sqrt(energies[0]*energies[1]);value=cross/denominator
    value=max(-1.0,min(1.0,float(value)))
    return value,{'status':'observed','reason':None}


def _descriptor_spooled_stereo(spool,analysis_sr,total_frames):
    if total_frames<analysis_sr:raise ValueError('at least one second mono/stereo PCM required')
    rows=[];frame_start=0;sample_peak=0.0;abs_ge_1=0;sample_count=0
    side_energy_sum=0.0;mid_energy_sum=0.0;left_scale=0.0;right_scale=0.0
    for pcm32 in _iter_spooled_stereo_chunks(spool,analysis_sr,total_frames):
        z=np.asarray(pcm32,dtype=np.float64)
        if not np.isfinite(z).all():raise ValueError('nonfinite PCM')
        sample_peak=max(sample_peak,float(np.max(np.abs(z))))
        abs_ge_1+=int(np.count_nonzero(np.abs(z)>=1));sample_count+=z.size
        left=z[:,0];right=z[:,1]
        left_scale=max(left_scale,float(np.max(np.abs(left))));right_scale=max(right_scale,float(np.max(np.abs(right))))
        side=(left-right)/2;mid=(left+right)/2
        side_energy_sum+=float(np.dot(side,side));mid_energy_sum+=float(np.dot(mid,mid))
        if len(z)==analysis_sr:rows.append(_window_descriptor(z,analysis_sr,frame_start))
        frame_start+=len(z)
    if frame_start!=total_frames:raise ValueError('decoded stereo stream truncated')
    correlation,correlation_evidence=_spooled_correlation(spool,analysis_sr,total_frames,left_scale,right_scale)
    hot,medians=_row_summary(rows)
    side_mean=side_energy_sum/total_frames;mid_mean=mid_energy_sum/total_frames
    result={'method':METHOD,'analysis_sr':analysis_sr,'complete_windows':len(rows),'energetic_window_count':len(hot),
      'sample_peak':sample_peak,'samples_abs_ge_1_fraction':abs_ge_1/sample_count,
      'stereo_correlation':correlation,'stereo_correlation_evidence':correlation_evidence,
      'side_mid_energy_ratio':float(side_mean/max(mid_mean,1e-30)),
      'energetic_medians':medians,'timeline':rows}
    _require_finite_evidence(result)
    return result


def _decoded_frame_count(byte_count,analysis_sr):
    frame_bytes=DECODE_CHANNELS*DECODE_SAMPLE_BYTES
    if byte_count<0 or byte_count%frame_bytes:raise ValueError('decoded stereo byte count mismatch')
    total_frames=byte_count//frame_bytes
    if total_frames>reference_analysis_resource_bound(analysis_sr)['max_decoded_frames']:
        raise ValueError('decoded reference exceeds 30-minute ingest bound')
    return total_frames


def _decode_spooled(path,analysis_sr):
    args=['ffmpeg','-nostdin','-v','error','-i',str(path),'-map','0:a:0','-ar',str(analysis_sr),'-ac','2','-c:a','pcm_f32le','-f','f32le','pipe:1']
    with tempfile.TemporaryFile(mode='w+b') as spool,tempfile.TemporaryFile(mode='w+b') as errors:
        cp=subprocess.run(args,stdout=spool,stderr=errors,timeout=180)
        if cp.returncode:
            errors.seek(0);detail=errors.read(65536).decode('utf-8','replace').strip()
            raise RuntimeError('ffmpeg decode failed'+(f': {detail}' if detail else ''))
        total_frames=_decoded_frame_count(spool.tell(),analysis_sr)
        descriptor=_descriptor_spooled_stereo(spool,analysis_sr,total_frames)
    return descriptor,total_frames


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
    if duration>MAX_REFERENCE_DURATION_S:raise ValueError('reference exceeds 30-minute ingest bound')
    d,total_frames=_decode_spooled(path,analysis_sr)
    d.update(decoded_duration_s=total_frames/analysis_sr,native_sample_rate=int(stream['sample_rate']),native_channels=int(stream['channels']),codec=stream['codec_name'],loudness=_loudness(path))
    d['dependency_versions']={'numpy':np.__version__,'scipy':__import__('scipy').__version__,'ffmpeg':subprocess.check_output(['ffmpeg','-version'],text=True).splitlines()[0]}
    _require_finite_evidence(d)
    return d


def compare_planning(observed,expected):
    checks={}
    def ck(name,a,b,tol):
        if a is None or b is None:
            checks[name]={'observed':a,'expected':b,'delta':None,'tolerance':tol,'pass':False,'status':'unavailable'}
            return
        checks[name]={'observed':a,'expected':b,'delta':a-b,'tolerance':tol,'pass':abs(a-b)<=tol,'status':'compared'}
    ck('duration_s',observed['decoded_duration_s'],expected['decoded_24k_duration_s'],.001)
    ck('sample_peak',observed['sample_peak'],expected['sample_peak_24k'],.005)
    ck('integrated_lufs',observed['loudness']['integrated_lufs'],expected['integrated_lufs'],.2)
    ck('true_peak_dbtp',observed['loudness']['true_peak_dbtp'],expected['true_peak_dbtp'],.2)
    for key,tol in [('power_centroid_hz',2.),('power_flatness',.005),('crest_db',.15)]:ck(key,observed['energetic_medians'][key],expected['energetic_medians'][key],tol)
    if 'stereo_correlation' in expected:
        ck('stereo_correlation',observed.get('stereo_correlation'),expected['stereo_correlation'],.005)
        if observed.get('stereo_correlation') is None:
            checks['stereo_correlation']['evidence']=observed.get('stereo_correlation_evidence')
    result={'checks':checks,'pass':all(v['pass'] for v in checks.values()),'warning':'descriptor tolerance covers dependency-version numerical differences; exact file identity remains the hard source gate'}
    _require_finite_evidence(result)
    return result
