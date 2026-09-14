from __future__ import annotations
from dataclasses import dataclass
from copy import deepcopy
import hashlib,math
import numpy as np
from scipy import signal
from zaaggenz_contracts.legacy import adapt_parameters,legacy_object
from zaaggenz_dsp import BitcrushSpec,bitcrush,oversampled_shaper
from .model import ZaagFamilyError,ZaagFamilyRecipe

@dataclass(frozen=True)
class ZaagSourceRender:
    audio:np.ndarray
    recipe_id:str
    recipe_sha256:str
    source_params:dict
    diagnostics:dict
    def __post_init__(self):
        a=np.asarray(self.audio,dtype=np.float32)
        if a.ndim!=1 or not np.isfinite(a).all():raise ZaagFamilyError('finite mono source render required')
        a.setflags(write=False);object.__setattr__(self,'audio',a);object.__setattr__(self,'source_params',deepcopy(self.source_params));object.__setattr__(self,'diagnostics',deepcopy(self.diagnostics))

def _rms(x):
    a=np.asarray(x,dtype=np.float64);return float(np.sqrt(np.mean(a*a))) if a.size else 0.
def _sha(x):return hashlib.sha256(np.asarray(x,dtype='<f4',order='C').tobytes()).hexdigest()
def _safe_filtfilt(b,a,x):
    if len(x)<16:return signal.lfilter(b,a,x)
    pad=min(len(x)-1,3*max(len(a),len(b)));return signal.filtfilt(b,a,x,padlen=pad)
def _lp(x,sr,hz):
    hz=min(float(hz),.45*sr);b,a=signal.butter(3,hz,fs=sr);return _safe_filtfilt(b,a,x)
def _band_peak(x,sr,hz,q):
    hz=min(max(20.,float(hz)),.45*sr);b,a=signal.iirpeak(hz,q,fs=sr);return _safe_filtfilt(b,a,x)

def _vowel_motion(x,sr,bpm,recipe):
    m=recipe.macros.vowel_motion;e=recipe.expert
    if m<=0 or abs(e.formant_boost_db)<1e-12:return x
    a=_band_peak(x,sr,e.formant_start_hz,e.formant_q);b=_band_peak(x,sr,e.formant_end_hz,e.formant_q)
    phase=np.linspace(0,1,len(x),endpoint=False,dtype=np.float64);cross=.5-.5*np.cos(np.pi*phase)
    resonance=(1-cross)*a+cross*b;gain=(10**(e.formant_boost_db*m/20.)-1.)
    return x+gain*resonance

def _upper_bounce(x,sr,bpm,recipe):
    m=recipe.macros.upper_bounce;e=recipe.expert
    if m<=0 or abs(e.upper_bounce_depth_db)<1e-12:return x
    low=_lp(x,sr,700.);upper=x-low;t=np.arange(len(x),dtype=np.float64)/sr;beats=t*bpm/60.
    mod=np.sin(2*np.pi*beats/e.upper_bounce_rate_beats);gain=np.power(10.,(e.upper_bounce_depth_db*m*mod)/20.)-1.
    return x+upper*gain

def _complementary(x,sr,bpm,recipe):
    m=recipe.macros.complementary_motion;e=recipe.expert
    if m<=0 or abs(e.complementary_depth_db)<1e-12:return x
    low=_lp(x,sr,650.);upper=x-low;t=np.arange(len(x),dtype=np.float64)/sr;beats=t*bpm/60.;shape=np.sin(2*np.pi*beats/4.)
    db=e.complementary_depth_db*m*shape;gl=np.power(10.,db/20.);gu=np.power(10.,-db/20.)
    return low*gl+upper*gu

def _grit(x,recipe):
    m=recipe.macros.grit;e=recipe.expert
    y=np.asarray(x,dtype=np.float64)
    if m>0 and e.grit_mix>0:
        y=oversampled_shaper(y,kind='tanh',factor=e.grit_oversample,drive_db=e.grit_drive_db*m,mix=e.grit_mix*m)
    if m>0 and e.bitcrush_wet>0:
        y=bitcrush(y,BitcrushSpec(bit_depth=e.bit_depth,hold_samples=e.hold_samples,wet=e.bitcrush_wet*m)).audio
    return np.asarray(y,dtype=np.float64)

def render_family_source(recipe,sample_rate_hz=48000,*,beats=1):
    if not isinstance(recipe,ZaagFamilyRecipe):raise ZaagFamilyError('ZaagFamilyRecipe required')
    if type(sample_rate_hz)is not int or not 8000<=sample_rate_hz<=96000:raise ZaagFamilyError('sample rate outside recovered source bounds')
    if type(beats)is not int or not 1<=beats<=8:raise ZaagFamilyError('beats must be integer 1..8')
    params=adapt_parameters('synth',{**recipe.synth_overrides,'sr':sample_rate_hz,'beats':beats})
    from uptempo_harmony.synth import synthesize_one
    base=np.asarray(synthesize_one(legacy_object('synth',params))[0],dtype=np.float64)
    if base.ndim!=1 or not np.isfinite(base).all():raise ZaagFamilyError('legacy source returned invalid audio')
    y=_vowel_motion(base,sample_rate_hz,float(params['bpm']),recipe)
    y=_upper_bounce(y,sample_rate_hz,float(params['bpm']),recipe)
    y=_complementary(y,sample_rate_hz,float(params['bpm']),recipe)
    y=_grit(y,recipe)
    if not np.isfinite(y).all():raise ZaagFamilyError('family processing produced nonfinite samples')
    diagnostics={'method':'zg.zaag-family-source.v1','recipe_id':recipe.id,'recipe_sha256':recipe.sha256,'sample_rate_hz':sample_rate_hz,
                 'samples':len(y),'base_pcm_sha256':_sha(base),'output_pcm_sha256':_sha(y),'base_rms':_rms(base),'output_rms':_rms(y),
                 'peak':float(np.max(np.abs(y),initial=0.)),'normalization':'none','phase_policy':recipe.expert.phase_policy,'tail_policy':recipe.expert.tail_policy,
                 'motion_order':['vowel','upper-bounce','complementary','grit'],'quality_cost':recipe.expert.quality_cost}
    return ZaagSourceRender(np.asarray(y,dtype=np.float32),recipe.id,recipe.sha256,params,diagnostics)
