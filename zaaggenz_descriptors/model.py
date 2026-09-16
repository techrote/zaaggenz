from __future__ import annotations
from dataclasses import dataclass
from copy import deepcopy
import json,math
from zaaggenz_contracts import digest,validate

class DescriptorError(ValueError):pass

VALIDITY={'valid','unknown','abstained'}
ROLES={'measurement','estimate'}

_REGISTRY={
 'rms':dict(label='RMS level',unit='linear_amplitude',category='acoustic',method='zg.rms.v1',bounds=(0.,None)),
 'periodicity_peak':dict(label='Autocorrelation periodicity',unit='ratio',category='periodicity',method='zg.periodicity.acf.v1',bounds=(0.,1.)),
 'f0_candidate_hz':dict(label='Periodic f0 candidate',unit='Hz',category='periodicity',method='zg.periodicity.acf.v1',bounds=(0.,None)),
 'envelope_modulation_hz':dict(label='Envelope modulation peak',unit='Hz',category='modulation',method='zg.envelope.rmsmod.v1',bounds=(0.,None)),
 'envelope_modulation_depth':dict(label='Envelope modulation depth',unit='ratio',category='modulation',method='zg.envelope.rmsmod.v1',bounds=(0.,4.)),
 'spectral_occupancy':dict(label='Entropy spectral occupancy',unit='ratio',category='spectrum',method='zg.spectral.occupancy.v1',bounds=(0.,1.)),
 'harmonicity_comb_fit':dict(label='Component harmonic-comb fit',unit='ratio',category='harmonic',method='zg.components.harmonicity.v1',bounds=(0.,1.)),
 'roughness_pairwise':dict(label='Relative pairwise roughness',unit='ratio',category='roughness',method='zg.components.roughness.v1',bounds=(0.,1.)),
 'target_comb_coverage':dict(label='Target-comb source coverage (density-biased raw fit)',unit='ratio',category='target_comb',method='zg.target_comb.v1',bounds=(0.,1.)),
 'target_comb_precision':dict(label='Target-comb tooth precision',unit='ratio',category='target_comb',method='zg.target_comb.v1',bounds=(0.,1.)),
 'target_comb_fit':dict(label='Target-comb balanced fit',unit='ratio',category='target_comb',method='zg.target_comb.v1',bounds=(0.,1.)),
 'target_comb_mismatch_cents':dict(label='Target-comb mean absolute mismatch',unit='cents',category='target_comb',method='zg.target_comb.v1',bounds=(0.,4800.)),
 'target_comb_density':dict(label='Target-comb tooth count',unit='count',category='target_comb',method='zg.target_comb.v1',bounds=(0.,128.)),
}

def descriptor_catalogue():return deepcopy(_REGISTRY)

def _finite(value):return type(value) in (int,float) and type(value)is not bool and math.isfinite(float(value))
def _support(d):
    if type(d)is not dict or set(d)!={'start_sample','end_sample','anchor_sample','padding'}:raise DescriptorError('invalid support metadata')
    s,e,a=d['start_sample'],d['end_sample'],d['anchor_sample']
    if any(type(v)is not int for v in (s,e,a)) or not s<=a<e or d['padding'] not in ('none','zero','reflect'):raise DescriptorError('invalid support span')

def _details(value):
    if value is None:return {}
    try:text=json.dumps(value,ensure_ascii=False,allow_nan=False,sort_keys=True,separators=(',',':'))
    except (TypeError,ValueError) as exc:raise DescriptorError('details must be bounded JSON') from exc
    if len(text.encode('utf-8'))>32768:raise DescriptorError('descriptor details too large')
    return deepcopy(value)

@dataclass(frozen=True)
class DescriptorObservation:
    metric:str
    method_id:str
    method_version:str
    unit:str
    value:float|None
    role:str
    validity:str
    confidence:float|None
    support:dict
    details:dict
    def __post_init__(self):
        spec=_REGISTRY.get(self.metric)
        if spec is None:raise DescriptorError('unregistered descriptor metric')
        if self.method_id!=spec['method'] or self.method_version!='1.0.0':raise DescriptorError('descriptor method/version disagrees with registry')
        if self.unit!=spec['unit'] or self.role not in ROLES or self.validity not in VALIDITY:raise DescriptorError('invalid descriptor metadata')
        _support(self.support)
        if self.validity=='valid':
            if not _finite(self.value):raise DescriptorError('valid descriptor requires finite value')
            lo,hi=spec['bounds'];v=float(self.value)
            if (lo is not None and v<lo) or (hi is not None and v>hi):raise DescriptorError('descriptor value outside registry bounds')
        elif self.value is not None:raise DescriptorError('unknown/abstained descriptor value must be null')
        if self.role=='estimate':
            if not _finite(self.confidence) or not 0<=float(self.confidence)<=1:raise DescriptorError('estimate requires confidence in [0,1]')
        elif self.confidence is not None:raise DescriptorError('measurement confidence must be null')
        object.__setattr__(self,'support',deepcopy(self.support));object.__setattr__(self,'details',_details(self.details))
    def to_dict(self):
        return dict(metric=self.metric,label=_REGISTRY[self.metric]['label'],category=_REGISTRY[self.metric]['category'],method_id=self.method_id,method_version=self.method_version,
                    unit=self.unit,value=None if self.value is None else float(self.value),role=self.role,validity=self.validity,
                    confidence=None if self.confidence is None else float(self.confidence),support=deepcopy(self.support),details=deepcopy(self.details))

@dataclass(frozen=True)
class DescriptorBundle:
    asset:dict
    observations:tuple[DescriptorObservation,...]
    method_id:str='zg.descriptor_bundle.v1'
    method_version:str='1.0.0'
    configuration:dict=None
    def __post_init__(self):
        try:validate(self.asset,'AudioAssetRef')
        except Exception as exc:raise DescriptorError('invalid AudioAssetRef') from exc
        if self.method_id!='zg.descriptor_bundle.v1' or self.method_version!='1.0.0':raise DescriptorError('unsupported descriptor bundle method/version')
        obs=tuple(self.observations)
        if len(obs)>8192 or any(not isinstance(x,DescriptorObservation) for x in obs):raise DescriptorError('invalid descriptor observations')
        keys=[(x.metric,x.support['start_sample'],x.support['end_sample']) for x in obs]
        if len(keys)!=len(set(keys)):raise DescriptorError('duplicate metric/support descriptor observation')
        n=self.asset['frame_count']
        for o in obs:
            s=o.support
            if n==0:
                if s['padding']=='none':raise DescriptorError('empty asset observations require explicit padding')
                continue
            if not 0<=s['anchor_sample']<n:raise DescriptorError('descriptor support anchor lies outside source asset')
            if s['padding']=='none' and not (0<=s['start_sample']<=s['anchor_sample']<s['end_sample']<=n):raise DescriptorError('unpadded descriptor support lies outside asset')
        object.__setattr__(self,'asset',deepcopy(self.asset));object.__setattr__(self,'observations',obs);object.__setattr__(self,'configuration',_details(self.configuration or {}))
    def to_dict(self):
        return dict(format='zaaggenz-descriptors',version='1.0.0',asset=deepcopy(self.asset),method=dict(id=self.method_id,version=self.method_version,configuration=deepcopy(self.configuration)),observations=[x.to_dict() for x in self.observations])
    @property
    def sha256(self):return digest(self.to_dict())
    def get(self,metric):return tuple(x for x in self.observations if x.metric==metric)

def observation(metric,value,support,*,validity='valid',confidence=None,role='measurement',details=None):
    spec=_REGISTRY.get(metric)
    if spec is None:raise DescriptorError('unregistered descriptor metric')
    return DescriptorObservation(metric,spec['method'],'1.0.0',spec['unit'],value,role,validity,confidence,support,details or {})

def feature_projection(bundle):
    """Project only metrics already admitted by frozen FeatureBundle v1; no schema widening occurs here."""
    if not isinstance(bundle,DescriptorBundle):raise DescriptorError('DescriptorBundle required')
    mapping={'rms':('rms','linear_amplitude'),'f0_candidate_hz':('f0','Hz'),'roughness_pairwise':('roughness_score','unitless'),'target_comb_fit':('chord_fit_score','unitless')}
    rows=[]
    # Frozen FeatureBundle v1 deliberately permits an empty asset only with an
    # empty observation list. DescriptorBundle can retain explicit padded
    # abstentions/zero-valued measurements, but the compatibility projection
    # must not fabricate an anchor inside a zero-frame source.
    if bundle.asset['frame_count']>0:
        for o in bundle.observations:
            if o.metric not in mapping:continue
            feature,unit=mapping[o.metric];role='measurement' if o.role=='measurement' else 'estimate'
            confidence=o.confidence if role=='estimate' and o.validity=='valid' else None
            rows.append(dict(feature=feature,unit=unit,value=o.value,role=role,validity=o.validity,
                             confidence=confidence,support=deepcopy(o.support)))
    d=dict(kind='FeatureBundle',version='1.0.0',asset=deepcopy(bundle.asset),
           method=dict(id='zg.descriptor_projection.v1',version='1.0.0',configuration={'descriptor_bundle_sha256':bundle.sha256}),observations=rows)
    validate(d,'FeatureBundle');return d
