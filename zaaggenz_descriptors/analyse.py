from __future__ import annotations
from dataclasses import dataclass
from copy import deepcopy
import math
from zaaggenz_contracts import Contract
from zaaggenz_components import analyse_components
from .model import DescriptorError,DescriptorBundle,feature_projection
from .audio import audio_array,pcm_asset,whole_support,rms_observation,periodicity_observations,envelope_observations,occupancy_observation
from .components import component_observations

@dataclass(frozen=True)
class DescriptorAnalysisSpec:
    version:str='1.0.0'
    max_samples:int=262144
    min_f0_hz:float=30.
    max_f0_hz:float=1200.
    component_cap:int=64
    tolerance_cents:float=35.
    def __post_init__(self):
        if self.version!='1.0.0':raise DescriptorError('unsupported descriptor analysis spec')
        if type(self.max_samples)is not int or not 1024<=self.max_samples<=2_000_000:raise DescriptorError('max_samples must be 1024..2000000')
        vals=(self.min_f0_hz,self.max_f0_hz,self.tolerance_cents)
        if any(type(x) not in (int,float) or type(x)is bool or not math.isfinite(float(x)) for x in vals):raise DescriptorError('analysis bounds must be finite')
        if not 1<self.min_f0_hz<self.max_f0_hz:raise DescriptorError('invalid f0 search range')
        if type(self.component_cap)is not int or not 1<=self.component_cap<=256:raise DescriptorError('component_cap must be 1..256')
        if not 1<=self.tolerance_cents<=600:raise DescriptorError('tolerance_cents must be 1..600')
    def to_dict(self):return dict(version=self.version,max_samples=self.max_samples,min_f0_hz=self.min_f0_hz,max_f0_hz=self.max_f0_hz,component_cap=self.component_cap,tolerance_cents=self.tolerance_cents)

@dataclass(frozen=True)
class DescriptorAnalysis:
    descriptors:DescriptorBundle
    partials:Contract
    feature_bundle:dict
    def __post_init__(self):
        if not isinstance(self.descriptors,DescriptorBundle) or not isinstance(self.partials,Contract):raise DescriptorError('invalid descriptor analysis result')
        object.__setattr__(self,'feature_bundle',deepcopy(self.feature_bundle))

def _partials_contract(value):
    if isinstance(value,Contract):return value
    try:return Contract(value)
    except Exception as exc:raise DescriptorError('valid PartialTrackBundle required') from exc

def analyse_descriptors(x,sample_rate_hz,*,target_hz=None,f0_override_hz=None,partials=None,spec=DescriptorAnalysisSpec()):
    if not isinstance(spec,DescriptorAnalysisSpec):raise DescriptorError('DescriptorAnalysisSpec required')
    a,mono=audio_array(x)
    if len(a)>spec.max_samples:raise DescriptorError(f'excerpt has {len(a)} samples; select an explicit <= {spec.max_samples}-sample analysis excerpt instead of implicit truncation')
    asset=pcm_asset(a[:,0] if mono else a,sample_rate_hz);support=whole_support(len(a))
    observations=[rms_observation(a,support=support)]
    periodic=periodicity_observations(a,sample_rate_hz,min_f0_hz=spec.min_f0_hz,max_f0_hz=spec.max_f0_hz,support=support);observations.extend(periodic)
    observations.extend(envelope_observations(a,sample_rate_hz,support=support));observations.append(occupancy_observation(a,sample_rate_hz,support=support))
    f0_source='periodicity'
    if f0_override_hz is not None:
        if type(f0_override_hz) not in (int,float) or type(f0_override_hz)is bool or not math.isfinite(float(f0_override_hz)) or f0_override_hz<=0:raise DescriptorError('f0_override_hz must be finite and positive')
        f0=float(f0_override_hz);f0_source='explicit-analysis-override'
    else:
        f0_obs=next(o for o in periodic if o.metric=='f0_candidate_hz');f0=f0_obs.value if f0_obs.validity=='valid' else None
    if partials is None:
        component_result=analyse_components(a[:,0] if mono else a,sample_rate_hz);partial_contract=component_result.bundle
    else:partial_contract=_partials_contract(partials)
    pd=partial_contract.to_dict();pa=pd['asset']
    for key in ('content_sha256','identity_domain','sample_rate_hz','channels','frame_count'):
        if pa[key]!=asset[key]:raise DescriptorError('partial analysis asset does not match descriptor audio excerpt')
    observations.extend(component_observations(partial_contract,f0_hz=f0,target_hz=target_hz,support=support,component_cap=spec.component_cap,tolerance_cents=spec.tolerance_cents))
    config={'analysis_spec':spec.to_dict(),'f0_source':f0_source,'target_comb_hz':None if target_hz is None else [float(v) for v in target_hz],
            'component_method':pd['method'],'window_policy':'caller-selected excerpt; no implicit truncation'}
    bundle=DescriptorBundle(asset,tuple(observations),configuration=config);projection=feature_projection(bundle)
    return DescriptorAnalysis(bundle,partial_contract,projection)
