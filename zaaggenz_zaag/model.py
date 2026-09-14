from __future__ import annotations
from dataclasses import dataclass
from copy import deepcopy
import hashlib,json,math,re

VERSION='1.0.0'
ID=re.compile(r'^[a-z][a-z0-9_.-]{0,63}$')
CLASSIFICATIONS={'candidate','contrast'}
QUALITY_COSTS={'low','medium','high'}

class ZaagFamilyError(ValueError):pass

def _unit(v,name):
    if type(v) not in (int,float) or type(v)is bool or not math.isfinite(float(v)) or not 0<=float(v)<=1:
        raise ZaagFamilyError(f'{name} must be finite in [0,1]')
    return float(v)

def _finite(v,name):
    if type(v) not in (int,float) or type(v)is bool or not math.isfinite(float(v)):raise ZaagFamilyError(f'{name} must be finite')
    return float(v)

def canonical_sha256(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()

@dataclass(frozen=True)
class ZaagMacros:
    attack_relax:float=0.
    vowel_motion:float=0.
    upper_bounce:float=0.
    complementary_motion:float=0.
    grit:float=0.
    harmonic_motion:float=0.
    def __post_init__(self):
        for name in ('attack_relax','vowel_motion','upper_bounce','complementary_motion','grit','harmonic_motion'):
            object.__setattr__(self,name,_unit(getattr(self,name),name))
    def to_dict(self):return {name:getattr(self,name) for name in ('attack_relax','vowel_motion','upper_bounce','complementary_motion','grit','harmonic_motion')}

@dataclass(frozen=True)
class ExpertControls:
    formant_start_hz:float=900.
    formant_end_hz:float=1800.
    formant_q:float=2.2
    formant_boost_db:float=0.
    upper_bounce_depth_db:float=0.
    upper_bounce_rate_beats:float=2.
    complementary_depth_db:float=0.
    grit_drive_db:float=0.
    grit_mix:float=0.
    grit_oversample:int=2
    bit_depth:int=16
    hold_samples:int=1
    bitcrush_wet:float=0.
    pitch_ratio_min:float=.5
    pitch_ratio_max:float=2.
    phase_policy:str='source-derived'
    tail_policy:str='preserve'
    quality_cost:str='medium'
    def __post_init__(self):
        for name in ('formant_start_hz','formant_end_hz','formant_q','upper_bounce_rate_beats','pitch_ratio_min','pitch_ratio_max'):
            v=_finite(getattr(self,name),name)
            if v<=0:raise ZaagFamilyError(name+' must be positive')
            object.__setattr__(self,name,v)
        for name in ('formant_boost_db','upper_bounce_depth_db','complementary_depth_db','grit_drive_db'):
            object.__setattr__(self,name,_finite(getattr(self,name),name))
        object.__setattr__(self,'grit_mix',_unit(self.grit_mix,'grit_mix'));object.__setattr__(self,'bitcrush_wet',_unit(self.bitcrush_wet,'bitcrush_wet'))
        if type(self.grit_oversample)is not int or self.grit_oversample not in (1,2,4):raise ZaagFamilyError('grit_oversample must be 1,2,4')
        if type(self.bit_depth)is not int or not 2<=self.bit_depth<=24:raise ZaagFamilyError('bit_depth must be 2..24')
        if type(self.hold_samples)is not int or not 1<=self.hold_samples<=64:raise ZaagFamilyError('hold_samples must be 1..64')
        if not self.formant_start_hz<24000 or not self.formant_end_hz<24000:raise ZaagFamilyError('formants must be below 24 kHz')
        if not .25<=self.formant_q<=12:raise ZaagFamilyError('formant_q outside bound')
        if not .2<=self.upper_bounce_rate_beats<=16:raise ZaagFamilyError('upper bounce rate outside bound')
        if not .25<=self.pitch_ratio_min<1<self.pitch_ratio_max<=4:raise ZaagFamilyError('invalid pitch ratio range')
        if self.phase_policy not in ('source-derived','reset-event'):raise ZaagFamilyError('invalid phase policy')
        if self.tail_policy not in ('preserve','truncate'):raise ZaagFamilyError('invalid tail policy')
        if self.quality_cost not in QUALITY_COSTS:raise ZaagFamilyError('invalid quality cost')
    def to_dict(self):return deepcopy(self.__dict__)

@dataclass(frozen=True)
class ZaagFamilyRecipe:
    id:str
    label:str
    intent:str
    classification:str
    macros:ZaagMacros
    synth_overrides:dict
    expert:ExpertControls
    useful_pitch_range_hz:tuple[float,float]
    tuning_guidance:str
    limitations:tuple[str,...]
    version:str=VERSION
    approved_default:bool=False
    def __post_init__(self):
        if type(self.id)is not str or not ID.fullmatch(self.id):raise ZaagFamilyError('invalid family id')
        if self.version!=VERSION:raise ZaagFamilyError('unsupported family version')
        if type(self.label)is not str or not self.label or len(self.label)>96:raise ZaagFamilyError('invalid label')
        if type(self.intent)is not str or not self.intent or len(self.intent)>240:raise ZaagFamilyError('invalid intent')
        if self.classification not in CLASSIFICATIONS:raise ZaagFamilyError('invalid classification')
        if not isinstance(self.macros,ZaagMacros) or not isinstance(self.expert,ExpertControls):raise ZaagFamilyError('typed controls required')
        if type(self.synth_overrides)is not dict:raise ZaagFamilyError('synth_overrides must be mapping')
        lo,hi=map(float,self.useful_pitch_range_hz)
        if not 15<=lo<hi<=240:raise ZaagFamilyError('useful pitch range must lie inside legacy source bounds')
        if type(self.tuning_guidance)is not str or not self.tuning_guidance:raise ZaagFamilyError('tuning guidance required')
        limitations=tuple(self.limitations)
        if not limitations or any(type(x)is not str or not x for x in limitations):raise ZaagFamilyError('limitations required')
        if type(self.approved_default)is not bool:raise ZaagFamilyError('approved_default must be bool')
        if self.approved_default:raise ZaagFamilyError('ZG-022 cannot approve a new default; explicit owner approval is external')
        object.__setattr__(self,'synth_overrides',deepcopy(self.synth_overrides));object.__setattr__(self,'useful_pitch_range_hz',(lo,hi));object.__setattr__(self,'limitations',limitations)
    def to_dict(self):
        return {'kind':'ZaagFamilyRecipe','version':self.version,'id':self.id,'label':self.label,'intent':self.intent,
                'classification':self.classification,'macros':self.macros.to_dict(),'synth_overrides':deepcopy(self.synth_overrides),
                'expert':self.expert.to_dict(),'useful_pitch_range_hz':list(self.useful_pitch_range_hz),'tuning_guidance':self.tuning_guidance,
                'limitations':list(self.limitations),'approved_default':self.approved_default}
    @property
    def sha256(self):return canonical_sha256(self.to_dict())

@dataclass(frozen=True)
class ProtectedAnchor:
    id:str
    canonical_json_sha256:str
    invariants:dict
    render_hashes:dict
    owner_listening_required_before_default_change:bool=True
    def __post_init__(self):
        if self.id!='locked_bloom':raise ZaagFamilyError('only recovered locked_bloom is protected by this anchor type')
        if not re.fullmatch(r'[0-9a-f]{64}',self.canonical_json_sha256):raise ZaagFamilyError('invalid anchor hash')
        object.__setattr__(self,'invariants',deepcopy(self.invariants));object.__setattr__(self,'render_hashes',deepcopy(self.render_hashes))
    def to_dict(self):return deepcopy(self.__dict__)
