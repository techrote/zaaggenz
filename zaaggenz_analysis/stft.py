from __future__ import annotations
from dataclasses import dataclass
import math
import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from scipy import signal

class AnalysisError(ValueError):pass

STFT_RESOURCE_POLICY='zg-stft-resource-bounds-v1'
MAX_STFT_WINDOW_SAMPLES=32768
MAX_STFT_FFT_SAMPLES=32768


def _validate_stft_values(window_samples,hop_samples,fft_samples,window,padding,scaling,role):
    n=window_samples
    if type(n)is not int or n<16 or n%2:raise AnalysisError('window must be even integer >=16')
    if n>MAX_STFT_WINDOW_SAMPLES:raise AnalysisError(f'window exceeds {MAX_STFT_WINDOW_SAMPLES}-sample resource bound')
    if type(hop_samples)is not int or not 1<=hop_samples<=n//2:raise AnalysisError('hop must be <= half window')
    if type(fft_samples)is not int or fft_samples<n or fft_samples%2:raise AnalysisError('FFT size must be even and >= window')
    if fft_samples>MAX_STFT_FFT_SAMPLES:raise AnalysisError(f'FFT size exceeds {MAX_STFT_FFT_SAMPLES}-sample resource bound')
    if window!='hann-periodic-v1' or padding!='half-window-zero-v1' or scaling!='raw-rfft-v1':raise AnalysisError('unsupported STFT convention')
    if role not in ('canonical-resynthesis','observation'):raise AnalysisError('invalid STFT role')


@dataclass(frozen=True)
class STFTSpec:
    window_samples:int
    hop_samples:int
    fft_samples:int
    window:str='hann-periodic-v1'
    padding:str='half-window-zero-v1'
    scaling:str='raw-rfft-v1'
    role:str='observation'
    def __post_init__(self):
        _validate_stft_values(self.window_samples,self.hop_samples,self.fft_samples,self.window,self.padding,self.scaling,self.role)
    def metadata(self):return dict(window_samples=self.window_samples,hop_samples=self.hop_samples,fft_samples=self.fft_samples,window=self.window,padding=self.padding,scaling=self.scaling,role=self.role)


@dataclass(frozen=True)
class STFTResourceEstimate:
    policy:str
    source_frames:int
    channels:int
    frame_count:int
    padded_frames:int
    padding_extra_frames:int
    window_samples:int
    hop_samples:int
    fft_samples:int
    source_float64_bytes:int
    padded_bytes:int
    window_bytes:int
    weighted_bytes:int
    spectra_bytes:int
    result_metadata_bytes:int
    estimated_live_bytes:int
    fft_point_count:int
    def metadata(self):
        return dict(policy=self.policy,source_frames=self.source_frames,channels=self.channels,frame_count=self.frame_count,
                    padded_frames=self.padded_frames,padding_extra_frames=self.padding_extra_frames,
                    window_samples=self.window_samples,hop_samples=self.hop_samples,fft_samples=self.fft_samples,
                    source_float64_bytes=self.source_float64_bytes,padded_bytes=self.padded_bytes,window_bytes=self.window_bytes,
                    weighted_bytes=self.weighted_bytes,spectra_bytes=self.spectra_bytes,result_metadata_bytes=self.result_metadata_bytes,
                    estimated_live_bytes=self.estimated_live_bytes,fft_point_count=self.fft_point_count)


def estimate_stft_resources(source_frames,channels,spec):
    if type(source_frames)is not int or source_frames<0:raise AnalysisError('source frame count must be non-negative integer')
    if type(channels)is not int or channels not in (1,2):raise AnalysisError('mono/stereo channel count required')
    if not isinstance(spec,STFTSpec):raise AnalysisError('STFTSpec required')
    _validate_stft_values(spec.window_samples,spec.hop_samples,spec.fft_samples,spec.window,spec.padding,spec.scaling,spec.role)
    n=spec.window_samples;hop=spec.hop_samples;fft=spec.fft_samples
    extra=(-source_frames)%hop
    padded_frames=source_frames+n+extra
    frame_count=(source_frames+extra)//hop+1
    source_float64_bytes=source_frames*channels*8
    padded_bytes=padded_frames*channels*8
    window_bytes=n*8
    weighted_bytes=frame_count*channels*n*8
    spectra_bytes=frame_count*channels*(fft//2+1)*16
    # anchors (int64), supports (2*int64), clipped support (int64), valid fraction (float64)
    result_metadata_bytes=frame_count*40
    estimated_live_bytes=(source_float64_bytes+padded_bytes+window_bytes+weighted_bytes+spectra_bytes+result_metadata_bytes)
    return STFTResourceEstimate(STFT_RESOURCE_POLICY,source_frames,channels,frame_count,padded_frames,extra,n,hop,fft,
                                source_float64_bytes,padded_bytes,window_bytes,weighted_bytes,spectra_bytes,
                                result_metadata_bytes,estimated_live_bytes,frame_count*channels*fft)


@dataclass(frozen=True)
class STFTResult:
    spec:STFTSpec
    sample_rate_hz:int
    source_frames:int
    channels:int
    spectra:np.ndarray  # frame, channel, rfft-bin
    anchors:np.ndarray
    supports:np.ndarray # frame, [start,end), may exceed source because padding is explicit
    valid_fraction:np.ndarray
    def frequencies_hz(self):return np.fft.rfftfreq(self.spec.fft_samples,1/self.sample_rate_hz)


def _audio(x):
    a=np.asarray(x)
    if a.ndim==1:a=a[:,None]
    if a.ndim!=2 or a.shape[1] not in (1,2):raise AnalysisError('mono/stereo audio required')
    if not np.issubdtype(a.dtype,np.number) or not np.isfinite(a).all():raise AnalysisError('finite numeric audio required')
    return np.asarray(a,dtype=np.float64)


def _window(n):return signal.windows.hann(n,sym=False).astype(np.float64)


def stft(x,sample_rate_hz,spec):
    if not isinstance(spec,STFTSpec):raise AnalysisError('STFTSpec required')
    _validate_stft_values(spec.window_samples,spec.hop_samples,spec.fft_samples,spec.window,spec.padding,spec.scaling,spec.role)
    if type(sample_rate_hz)is not int or not 8000<=sample_rate_hz<=192000:raise AnalysisError('sample rate out of range')
    a=_audio(x);n=spec.window_samples;hop=spec.hop_samples
    # Exact cardinality/resource accounting happens before padding, window materialisation or FFT allocation.
    estimate_stft_resources(len(a),a.shape[1],spec)
    padded=np.pad(a,((n//2,n//2),(0,0)))
    remaining=max(0,len(padded)-n);extra=(-remaining)%hop
    if extra:padded=np.pad(padded,((0,extra),(0,0)))
    frames=sliding_window_view(padded,n,axis=0)[::hop] # frame, channel, sample
    # NumPy returns (frame,channel,sample) for axis=0 on a 2-D input.
    w=_window(n);weighted=frames*w[None,None,:]
    spectra=np.fft.rfft(weighted,n=spec.fft_samples,axis=-1)
    anchors=np.arange(len(frames),dtype=np.int64)*hop
    supports=np.column_stack((anchors-n//2,anchors+n//2)).astype(np.int64)
    clipped=np.maximum(0,np.minimum(supports[:,1],len(a))-np.maximum(supports[:,0],0))
    valid_fraction=clipped.astype(np.float64)/n
    for arr in (spectra,anchors,supports,valid_fraction):arr.setflags(write=False)
    return STFTResult(spec,sample_rate_hz,len(a),a.shape[1],spectra,anchors,supports,valid_fraction)


def istft(result):
    if not isinstance(result,STFTResult):raise AnalysisError('STFTResult required')
    spec=result.spec
    if spec.role!='canonical-resynthesis':raise AnalysisError('observation-only spectra cannot be used for resynthesis')
    n=spec.window_samples;hop=spec.hop_samples;w=_window(n)
    frames=np.fft.irfft(result.spectra,n=spec.fft_samples,axis=-1)[...,:n]
    total=(len(frames)-1)*hop+n;y=np.zeros((total,result.channels));norm=np.zeros(total)
    for i,frame in enumerate(frames):
        start=i*hop;y[start:start+n]+=frame.T*w[:,None];norm[start:start+n]+=w*w
    valid=norm>1e-14;y[valid]/=norm[valid,None]
    out=y[n//2:n//2+result.source_frames]
    return out[:,0] if result.channels==1 else out


def _power2_near(samples,lo=32,hi=MAX_STFT_WINDOW_SAMPLES):
    n=2**round(math.log2(max(lo,min(hi,samples))));return int(max(lo,min(hi,n)))


def resolution_specs(sample_rate_hz):
    if type(sample_rate_hz)is not int or not 8000<=sample_rate_hz<=192000:raise AnalysisError('sample rate out of range')
    windows={name:_power2_near(sample_rate_hz*seconds) for name,seconds in [('short',.011),('medium',.043),('long',.341)]}
    # Canonical representation is medium only. Others are explicitly observation-only.
    return {name:STFTSpec(n,n//4,n,role='canonical-resynthesis' if name=='medium' else 'observation') for name,n in windows.items()}
