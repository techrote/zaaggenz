from __future__ import annotations
from dataclasses import dataclass
from copy import deepcopy
import hashlib,math
import numpy as np
from scipy import signal
from zaaggenz_contracts.legacy import adapt_parameters,legacy_object
from zaaggenz_dsp import BitcrushSpec,bitcrush,oversampled_shaper
from .model import ZaagFamilyError,ZaagFamilyRecipe

FORMANT_POLICY='fail-closed-exact-v1'
FORMANT_MIN_HZ=20.0
FORMANT_NYQUIST_FRACTION=.45

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
def _formant_band(sr):return FORMANT_MIN_HZ,FORMANT_NYQUIST_FRACTION*float(sr)
def _formant_active(recipe):return recipe.macros.vowel_motion>0 and abs(recipe.expert.formant_boost_db)>=1e-12
def _validate_formants(recipe,sr):
    low,high=_formant_band(sr);e=recipe.expert;active=_formant_active(recipe)
    requested={'start_hz':float(e.formant_start_hz),'end_hz':float(e.formant_end_hz)}
    if active:
        for label,hz in requested.items():
            if not low<=hz<=high:
                raise ZaagFamilyError(f'{label}={hz:g} outside supported formant band [{low:g}, {high:g}] Hz at {sr} Hz sample rate ({FORMANT_POLICY})')
    return {'policy':FORMANT_POLICY,'active':active,'supported_band_hz':[low,high],'requested_hz':requested,
            'realized_hz':deepcopy(requested) if active else None}
def _band_peak(x,sr,hz,q):
    low,high=_formant_band(sr);hz=float(hz)
    if not low<=hz<=high:raise ZaagFamilyError(f'formant={hz:g} outside supported formant band [{low:g}, {high:g}] Hz at {sr} Hz sample rate ({FORMANT_POLICY})')
    b,a=signal.iirpeak(hz,q,fs=sr);return _safe_filtfilt(b,a,x)

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

CHARACTER_PROFILES={
    'zaag.bloom-bark':'bark',
    'zaag.formant-snarl':'snarl',
    'zaag.upper-chop':'chop',
    'zaag.split-maul':'split',
    'zaag.crushed-teeth':'crush',
    'zaag.harmonic-rip':'rip',
}

def _highpass_delta(x,sr,hz):return np.asarray(x,dtype=np.float64)-_lp(x,sr,hz)

def _character_profile(x,sr,bpm,recipe):
    """Apply the explicit ZG-022 replacement-family character mechanism.

    These are deliberately orthogonal, deterministic offline transforms chosen
    after the original owner pack was rejected as six near-neighbour dull twangs.
    They are not preference scores and they do not touch locked_bloom.
    """
    mode=CHARACTER_PROFILES.get(recipe.id)
    y=np.asarray(x,dtype=np.float64)
    if mode is None:return y,'contrast-reference'
    t=np.arange(len(y),dtype=np.float64)/float(sr);beats=t*float(bpm)/60.
    if mode=='bark':
        edge=_highpass_delta(y,sr,500.)
        z=np.tanh(8.*(y+1.8*edge+.12))-math.tanh(.96)
        bite=_highpass_delta(z,sr,900.)
        bloom=.55+.8*(1.-np.exp(-t/.025))
        return .32*y+bloom*(.62*z+1.15*bite),mode
    if mode=='snarl':
        phase=np.linspace(0.,1.,len(y),endpoint=False,dtype=np.float64)
        cross=.5-.5*np.cos(np.pi*phase)
        r1=_band_peak(y,sr,900.,7.);r2=_band_peak(y,sr,3200.,8.)
        resonance=(1.-cross)*r1+cross*r2
        z=np.tanh(12.*(y+4.*resonance)+.25)-math.tanh(.25)
        return .16*y+.82*z+.85*_highpass_delta(z,sr,1200.),mode
    if mode=='chop':
        low=_lp(y,sr,500.);upper=y-low
        gate=np.where(np.sin(2.*np.pi*beats/.125)>=0.,1.,.03)
        ring=np.sin(2.*np.pi*310.*t)
        z=.65*low+gate*(1.9*upper+.55*y*ring)
        z=np.tanh(8.*z)
        return .18*y+.68*z+1.1*_highpass_delta(z,sr,800.),mode
    if mode=='split':
        low=_lp(y,sr,420.);upper=y-low
        shape=np.where(np.sin(2.*np.pi*beats/.5)>=0.,1.,-1.)
        ring=np.sin(2.*np.pi*(220.+40.*np.sin(2.*np.pi*beats))*t)
        a=np.tanh(9.*low)*np.where(shape>0.,1.5,.22)
        b=np.tanh(11.*(upper+.3*y*ring))*np.where(shape<0.,1.6,.16)
        combined=a+b
        return .12*y+combined+.8*_highpass_delta(combined,sr,1000.),mode
    if mode=='crush':
        upper=_highpass_delta(y,sr,350.)
        z=np.tanh(15.*(y+2.4*upper))
        hold=3;held=np.repeat(z[::hold],hold)[:len(z)]
        levels=15.;quantized=np.round(np.clip(held,-1.,1.)*levels)/levels
        return .08*y+.7*quantized+_highpass_delta(quantized,sr,1200.),mode
    if mode=='rip':
        z=y.copy()
        for delay48,coef in ((11,.95),(23,-.9),(43,.75),(79,-.65)):
            delay=max(1,round(sr*delay48/48000.))
            z+=coef*np.pad(y,(delay,0))[:len(y)]
        ring=np.sin(2.*np.pi*(270.+90.*np.sin(2.*np.pi*beats/.75))*t)
        z=z+.9*z*ring
        z=np.tanh(10.*z)
        return .12*y+.7*z+1.2*_highpass_delta(z,sr,700.),mode
    raise ZaagFamilyError('unknown ZG-022 character profile '+str(mode))

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
    formant=_validate_formants(recipe,sample_rate_hz)
    params=adapt_parameters('synth',{**recipe.synth_overrides,'sr':sample_rate_hz,'beats':beats})
    from uptempo_harmony.synth import synthesize_one
    base=np.asarray(synthesize_one(legacy_object('synth',params))[0],dtype=np.float64)
    if base.ndim!=1 or not np.isfinite(base).all():raise ZaagFamilyError('legacy source returned invalid audio')
    y=_vowel_motion(base,sample_rate_hz,float(params['bpm']),recipe)
    y=_upper_bounce(y,sample_rate_hz,float(params['bpm']),recipe)
    y=_complementary(y,sample_rate_hz,float(params['bpm']),recipe)
    y,character_profile=_character_profile(y,sample_rate_hz,float(params['bpm']),recipe)
    y=_grit(y,recipe)
    if not np.isfinite(y).all():raise ZaagFamilyError('family processing produced nonfinite samples')
    diagnostics={'method':'zg.zaag-family-source.v2','recipe_id':recipe.id,'recipe_sha256':recipe.sha256,'sample_rate_hz':sample_rate_hz,
                 'samples':len(y),'base_pcm_sha256':_sha(base),'output_pcm_sha256':_sha(y),'base_rms':_rms(base),'output_rms':_rms(y),
                 'peak':float(np.max(np.abs(y),initial=0.)),'normalization':'none','phase_policy':recipe.expert.phase_policy,'tail_policy':recipe.expert.tail_policy,
                 'motion_order':['vowel','upper-bounce','complementary','character-profile','grit'],'character_profile':character_profile,'quality_cost':recipe.expert.quality_cost,'formant':formant}
    return ZaagSourceRender(np.asarray(y,dtype=np.float32),recipe.id,recipe.sha256,params,diagnostics)
