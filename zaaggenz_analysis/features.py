from __future__ import annotations
from dataclasses import dataclass
import math
import numpy as np
from scipy import signal
from .stft import STFTResult, STFTSpec, AnalysisError, stft, resolution_specs, _audio

METHOD='zg-multiresolution-features-v1'

@dataclass(frozen=True)
class FeatureFrame:
    anchor_sample:int
    support_start_sample:int
    support_end_sample:int
    support_fraction:float
    valid:bool
    spectral_centroid_hz:float|None
    spectral_flatness:float|None
    dominant_hz:float|None
    spectral_flux:float|None
    peaks_hz:tuple[float,...]

@dataclass(frozen=True)
class FeatureTimeline:
    name:str
    sample_rate_hz:int
    source_frames:int
    channels:int
    method:str
    stft_spec:STFTSpec
    frames:tuple[FeatureFrame,...]
    role:str
    def metadata(self):
        return {'name':self.name,'sample_rate_hz':self.sample_rate_hz,'source_frames':self.source_frames,
                'channels':self.channels,'method':self.method,'stft':self.stft_spec.metadata(),'role':self.role}

def _frame_features(result):
    f=result.frequencies_hz();powers=np.mean(np.abs(result.spectra)**2,axis=1)
    rows=[];previous=None
    for i,p0 in enumerate(powers):
        p=np.asarray(p0,dtype=np.float64);total=float(p.sum());valid=bool(total>1e-24)
        if valid:
            q=p+1e-30;centroid=float(np.dot(f,q)/q.sum());flat=float(np.exp(np.mean(np.log(q)))/np.mean(q));dominant=float(f[int(np.argmax(p))])
            # Prominence relative to this frame; endpoints are handled separately because low f0 can occupy bin 1.
            peaks,_=signal.find_peaks(p,prominence=max(float(p.max())*.02,1e-30))
            if len(p)>1 and p[1]>p[2 if len(p)>2 else 1]:peaks=np.r_[1,peaks]
            ranked=sorted((int(k) for k in set(peaks) if k>0),key=lambda k:p[k],reverse=True)[:8]
            peaks_hz=tuple(sorted(float(f[k]) for k in ranked))
            norm=p/max(total,1e-30);flux=None if previous is None else float(np.sqrt(np.mean((norm-previous)**2)))
            previous=norm
        else:
            centroid=flat=dominant=flux=None;peaks_hz=();previous=None
        s=result.supports[i]
        rows.append(FeatureFrame(int(result.anchors[i]),int(s[0]),int(s[1]),float(result.valid_fraction[i]),valid,centroid,flat,dominant,flux,peaks_hz))
    return tuple(rows)

def analyse_multiresolution(x,sample_rate_hz,specs=None):
    a=_audio(x);specs=resolution_specs(sample_rate_hz) if specs is None else specs
    if type(specs)is not dict or set(specs)!={'short','medium','long'}:raise AnalysisError('exact short/medium/long spec set required')
    out={}
    for name in ('short','medium','long'):
        spec=specs[name];r=stft(a,sample_rate_hz,spec)
        out[name]=FeatureTimeline(name,sample_rate_hz,len(a),a.shape[1],METHOD,spec,_frame_features(r),spec.role)
    return out

def select_interval(timeline,start_sample,end_sample,mode='overlap'):
    if not isinstance(timeline,FeatureTimeline) or type(start_sample)is not int or type(end_sample)is not int or start_sample>=end_sample:raise AnalysisError('valid timeline/sample interval required')
    if mode=='overlap':return tuple(f for f in timeline.frames if f.support_start_sample<end_sample and f.support_end_sample>start_sample)
    if mode=='anchor':return tuple(f for f in timeline.frames if start_sample<=f.anchor_sample<end_sample)
    raise AnalysisError('interval mode must be overlap or anchor')

def overlay_landmarks(timeline,annotation,asset_id,source_sample_rate,source_frame_count=None):
    """Project validated source-domain landmarks onto an analysis timeline.

    ``source_frame_count`` should be supplied from the exact reference timing
    catalogue when available.  The legacy four-argument form remains valid for
    already-validated annotations and derives a defensive extent from the
    analysis timeline rather than accepting unbounded source coordinates.
    """
    if not isinstance(timeline,FeatureTimeline) or type(source_sample_rate)is not int or source_sample_rate<=0:raise AnalysisError('invalid landmark timing')
    if source_frame_count is None:
        source_frame_count=round(timeline.source_frames*source_sample_rate/timeline.sample_rate_hz)
    elif type(source_frame_count)is not int or type(source_frame_count)is bool or source_frame_count<0:
        raise AnalysisError('invalid landmark source extent')
    projected_source_frames=round(source_frame_count*timeline.sample_rate_hz/source_sample_rate)
    if abs(projected_source_frames-timeline.source_frames)>1:
        raise AnalysisError('landmark timing metadata does not match analysis timeline')
    rows=[]
    scale=timeline.sample_rate_hz/source_sample_rate
    for segment in annotation.get('segments',[]):
        if segment.get('asset_id')!=asset_id:continue
        start_source=segment.get('start_sample');end_source=segment.get('end_sample')
        if type(start_source)is not int or type(end_source)is not int or not (0<=start_source<end_source<=source_frame_count):
            raise AnalysisError('landmark span outside source extent')
        start=round(start_source*scale);end=round(end_source*scale)
        if start<0 or end>timeline.source_frames or start>end:
            raise AnalysisError('landmark resampling outside analysis extent')
        indices=[i for i,f in enumerate(timeline.frames) if f.support_start_sample<end and f.support_end_sample>start]
        rows.append({'segment_id':segment['id'],'start_sample':start,'end_sample':end,'frame_indices':indices,
                     'label':segment.get('label',''),'section_function':segment.get('section_function','unknown'),
                     'annotation_source':segment.get('source','unknown'),'confidence':segment.get('confidence')})
    return rows
