from __future__ import annotations
from dataclasses import dataclass
import hashlib,math
import numpy as np
from zaaggenz_contracts import Contract

class ComponentError(ValueError):pass

@dataclass(frozen=True)
class ComponentTrackerSpec:
    window_seconds:float=.08533333333333333
    hop_fraction:int=8
    fft_factor:int=4
    min_hz:float=30.
    max_hz:float=6000.
    max_tracks:int=16
    min_snr_db:float=10.
    max_flatness:float=.32
    min_confidence:float=.20
    transform_confidence:float=.55
    max_jump_cents:float=240.
    ambiguity_cents:float=100.
    max_gap_frames:int=2
    min_track_frames:int=3
    min_support_fraction:float=.55
    transient_sigma:float=5.
    transient_guard_ms:float=6.
    def __post_init__(self):
        numeric=(self.window_seconds,self.min_hz,self.max_hz,self.min_snr_db,self.max_flatness,
                 self.min_confidence,self.transform_confidence,self.max_jump_cents,self.ambiguity_cents,
                 self.min_support_fraction,self.transient_sigma,self.transient_guard_ms)
        if any(not isinstance(v,(int,float)) or not math.isfinite(float(v)) for v in numeric):raise ComponentError('finite tracker settings required')
        if not .01<=self.window_seconds<=1.:raise ComponentError('window_seconds out of range')
        if self.hop_fraction not in (2,4,8,16):raise ComponentError('hop_fraction must be 2/4/8/16')
        if self.fft_factor not in (1,2,4,8):raise ComponentError('fft_factor must be 1/2/4/8')
        if not 0<self.min_hz<self.max_hz:raise ComponentError('invalid frequency range')
        if not 1<=self.max_tracks<=64:raise ComponentError('max_tracks out of range')
        if not 0<=self.max_flatness<=1 or not 0<=self.min_confidence<=self.transform_confidence<=1:raise ComponentError('invalid confidence/flatness setting')
        if not 1<=self.min_track_frames<=32 or not 0<=self.max_gap_frames<=16:raise ComponentError('invalid track duration/gap bound')
        if not 0<=self.min_support_fraction<=1:raise ComponentError('invalid support fraction')
    def metadata(self):return dict(window_seconds=self.window_seconds,hop_fraction=self.hop_fraction,fft_factor=self.fft_factor,
        min_hz=self.min_hz,max_hz=self.max_hz,max_tracks=self.max_tracks,min_snr_db=self.min_snr_db,max_flatness=self.max_flatness,
        min_confidence=self.min_confidence,transform_confidence=self.transform_confidence,max_jump_cents=self.max_jump_cents,
        ambiguity_cents=self.ambiguity_cents,max_gap_frames=self.max_gap_frames,min_track_frames=self.min_track_frames,
        min_support_fraction=self.min_support_fraction,transient_sigma=self.transient_sigma,transient_guard_ms=self.transient_guard_ms)


def _audio_shape(array,name):
    a=np.asarray(array)
    if a.ndim==1: return a,1
    if a.ndim==2 and a.shape[1] in (1,2): return a,a.shape[1]
    raise ComponentError(name+' must be mono/stereo audio')


def _pcm_sha(array):
    return hashlib.sha256(np.asarray(array,dtype='<f4',order='C').tobytes()).hexdigest()


def _bind_asset(asset,array,sample_rate_hz,name):
    a,channels=_audio_shape(array,name)
    expected_layout='mono' if channels==1 else 'stereo-lr'
    if asset is None:raise ComponentError(name+' asset required')
    if asset.get('identity_domain')!='pcm-f32le-interleaved-v1':raise ComponentError(name+' asset must identify canonical PCM')
    if asset.get('frame_count')!=a.shape[0]:raise ComponentError(name+' frame_count mismatch')
    if asset.get('channels')!=channels or asset.get('channel_layout')!=expected_layout:raise ComponentError(name+' channel metadata mismatch')
    if asset.get('sample_rate_hz')!=sample_rate_hz:raise ComponentError(name+' sample_rate_hz mismatch')
    if asset.get('content_sha256')!=_pcm_sha(a):raise ComponentError(name+' content identity mismatch')


@dataclass(frozen=True)
class ComponentAnalysis:
    bundle:Contract
    source:np.ndarray
    sinusoidal:np.ndarray
    transient:np.ndarray
    residual:np.ndarray
    transient_mask:np.ndarray
    diagnostics:dict
    sample_rate_hz:int
    def __post_init__(self):
        if not isinstance(self.bundle,Contract):raise ComponentError('PartialTrackBundle required')
        d=self.bundle.to_dict()
        if d.get('kind')!='PartialTrackBundle':raise ComponentError('PartialTrackBundle required')
        if type(self.sample_rate_hz)is not int or not 8000<=self.sample_rate_hz<=192000:raise ComponentError('analysis sample rate out of range')
        source,channels=_audio_shape(self.source,'source');shape=source.shape
        arrays={'source':source}
        for name in ('sinusoidal','transient','residual'):
            a,c=_audio_shape(getattr(self,name),name)
            if a.shape!=shape or c!=channels:raise ComponentError(name+' shape mismatch')
            arrays[name]=a
        mask=np.asarray(self.transient_mask)
        if mask.ndim!=1 or len(mask)!=shape[0]:raise ComponentError('transient mask length mismatch')
        for name,a in (*arrays.items(),('transient_mask',mask)):
            if not np.issubdtype(a.dtype,np.number) or not np.isfinite(a).all():raise ComponentError(name+' must be finite numeric data')
        _bind_asset(d['asset'],source,self.sample_rate_hz,'source')
        _bind_asset(d.get('transient_asset'),arrays['transient'],self.sample_rate_hz,'transient')
        _bind_asset(d.get('residual_asset'),arrays['residual'],self.sample_rate_hz,'residual')
        for a in (self.source,self.sinusoidal,self.transient,self.residual,self.transient_mask):a.setflags(write=False)
    @property
    def reconstruction(self):
        return np.asarray(self.sinusoidal,dtype=np.float64)+np.asarray(self.transient,dtype=np.float64)+np.asarray(self.residual,dtype=np.float64)


def exact_bypass(x):
    a=np.asarray(x)
    if a.ndim not in (1,2):raise ComponentError('mono/stereo array required')
    if a.ndim==2 and a.shape[1] not in (1,2):raise ComponentError('mono/stereo array required')
    if not np.issubdtype(a.dtype,np.number) or not np.isfinite(a).all():raise ComponentError('finite numeric audio required')
    return np.asarray(a,dtype=np.float32).copy()
