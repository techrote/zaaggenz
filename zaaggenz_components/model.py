from __future__ import annotations
from dataclasses import dataclass
import hashlib,math
import numpy as np
from zaaggenz_contracts import Contract,validate

class ComponentError(ValueError):pass

PCM_IDENTITY_DOMAIN='pcm-f32le-interleaved-v1'

def _finite_audio_array(value,name):
    a=np.asarray(value)
    if a.ndim not in (1,2) or (a.ndim==2 and a.shape[1] not in (1,2)):
        raise ComponentError(name+' must be mono/stereo audio')
    if not np.issubdtype(a.dtype,np.number) or not np.isfinite(a).all():
        raise ComponentError(name+' must be finite numeric audio')
    f32=np.asarray(a,dtype=np.float32)
    if not np.isfinite(f32).all():
        raise ComponentError(name+' must be finite float32 audio')
    return a

def pcm_f32le_bytes(value):
    a=_finite_audio_array(value,'audio')
    return np.asarray(a,dtype='<f4',order='C').tobytes()

def pcm_asset_ref(value,sample_rate_hz,level='source'):
    if type(sample_rate_hz)is not int or not 8000<=sample_rate_hz<=192000:
        raise ComponentError('sample rate out of range')
    a=_finite_audio_array(value,'audio')
    channels=1 if a.ndim==1 else a.shape[1]
    payload=np.asarray(a,dtype='<f4',order='C').tobytes()
    return dict(kind='AudioAssetRef',version='1.0.0',
                content_sha256=hashlib.sha256(payload).hexdigest(),
                identity_domain=PCM_IDENTITY_DOMAIN,
                sample_rate_hz=sample_rate_hz,channels=channels,
                channel_layout='mono' if channels==1 else 'stereo-lr',
                frame_count=a.shape[0],level_domain=level,
                sample_policy='unclamped_float')

def bind_pcm_asset(asset,value,sample_rate_hz,name='asset'):
    if not isinstance(asset,dict):
        raise ComponentError(name+' AudioAssetRef required')
    a=_finite_audio_array(value,name)
    channels=1 if a.ndim==1 else a.shape[1]
    expected_layout='mono' if channels==1 else 'stereo-lr'
    expected=(('identity_domain',PCM_IDENTITY_DOMAIN),
              ('sample_rate_hz',sample_rate_hz),
              ('channels',channels),
              ('channel_layout',expected_layout),
              ('frame_count',a.shape[0]))
    for field,value_expected in expected:
        if asset.get(field)!=value_expected:
            raise ComponentError(f'{name} {field} mismatch')
    payload=np.asarray(a,dtype='<f4',order='C').tobytes()
    if asset.get('content_sha256')!=hashlib.sha256(payload).hexdigest():
        raise ComponentError(name+' content_sha256 mismatch')
    return a

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

@dataclass(frozen=True)
class ComponentAnalysis:
    bundle:Contract
    source:np.ndarray
    sinusoidal:np.ndarray
    transient:np.ndarray
    residual:np.ndarray
    transient_mask:np.ndarray
    diagnostics:dict
    sample_rate_hz:int|None=None
    def __post_init__(self):
        if not isinstance(self.bundle,Contract):raise ComponentError('PartialTrackBundle required')
        try:
            data=self.bundle.to_dict()
            validate(data,'PartialTrackBundle')
        except Exception as exc:
            raise ComponentError('valid PartialTrackBundle required') from exc
        if data.get('kind')!='PartialTrackBundle':raise ComponentError('PartialTrackBundle required')
        if type(self.sample_rate_hz)is not int or not 8000<=self.sample_rate_hz<=192000:
            raise ComponentError('trusted sample_rate_hz required')
        source=_finite_audio_array(self.source,'source')
        shape=source.shape
        for name in ('sinusoidal','transient','residual'):
            a=_finite_audio_array(getattr(self,name),name)
            if a.shape!=shape:raise ComponentError(name+' shape mismatch')
        mask=np.asarray(self.transient_mask)
        if mask.ndim!=1 or mask.shape!=(shape[0],):
            raise ComponentError('transient mask shape mismatch')
        if not np.issubdtype(mask.dtype,np.number) or not np.isfinite(mask).all():
            raise ComponentError('transient mask must be finite numeric')
        bind_pcm_asset(data.get('asset'),source,self.sample_rate_hz,'source asset')
        bind_pcm_asset(data.get('transient_asset'),self.transient,self.sample_rate_hz,'transient asset')
        bind_pcm_asset(data.get('residual_asset'),self.residual,self.sample_rate_hz,'residual asset')
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
