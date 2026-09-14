from __future__ import annotations
from copy import deepcopy
from dataclasses import dataclass
import math
import numpy as np
from zaaggenz_components import analyse_components
from zaaggenz_contracts import validate
from zaaggenz_contracts.legacy import envelope
from zaaggenz_dsp import execute_graph
from zaaggenz_dsp.antialias import SUPPORTED_OVERSAMPLE,filter_metadata
from .engine import SpectralRetuneResult,retune_components
from .model import SpectralRetuneRequest

PLACEMENTS=('pre','inter','post')
SHAPERS=('tanh','hard_clip')
MODES=('legacy','antialiased')

class PlacementError(ValueError):pass

def _finite(v,name):
    if type(v) not in (int,float) or type(v)is bool or not math.isfinite(float(v)):raise PlacementError(name+' must be finite')
    return float(v)

@dataclass(frozen=True)
class NonlinearStageSpec:
    kind:str='tanh'
    mode:str='antialiased'
    oversample:int=2
    drive_db:float=12.
    threshold:float=.7
    mix:float=1.
    def __post_init__(self):
        if self.kind not in SHAPERS:raise PlacementError('unsupported shaper kind')
        if self.mode not in MODES:raise PlacementError('unsupported nonlinear mode')
        if type(self.oversample)is not int or type(self.oversample)is bool or self.oversample not in SUPPORTED_OVERSAMPLE:raise PlacementError('oversample must be 1, 2 or 4')
        if self.mode=='legacy' and self.oversample!=1:raise PlacementError('legacy alias mode is fixed at 1x')
        drive=_finite(self.drive_db,'drive_db');threshold=_finite(self.threshold,'threshold');mix=_finite(self.mix,'mix')
        if not -24<=drive<=48:raise PlacementError('drive_db outside graph bounds')
        if not .001<=threshold<=4:raise PlacementError('threshold outside graph bounds')
        if not 0<=mix<=1:raise PlacementError('mix outside [0,1]')
        object.__setattr__(self,'drive_db',drive);object.__setattr__(self,'threshold',threshold);object.__setattr__(self,'mix',mix)
    @property
    def type_id(self):
        suffix='' if self.mode=='legacy' else '_aa'
        return f'core.{self.kind}{suffix}.v1'
    def params(self):
        if self.kind=='tanh':
            out={'drive_db':self.drive_db,'mix':self.mix}
        else:out={'threshold':self.threshold,'mix':self.mix}
        if self.mode=='antialiased':out['oversample']=self.oversample
        return out
    def to_dict(self):
        return {'kind':self.kind,'mode':self.mode,'type_id':self.type_id,'oversample':self.oversample,
                'params':self.params(),'filter':filter_metadata(self.oversample) if self.mode=='antialiased' else filter_metadata(1)}

@dataclass(frozen=True)
class PlacementRequest:
    spectral:SpectralRetuneRequest
    placement:str='inter'
    stage_a:NonlinearStageSpec=NonlinearStageSpec('tanh','antialiased',2,14.,.7,1.)
    stage_b:NonlinearStageSpec=NonlinearStageSpec('hard_clip','antialiased',2,0.,.62,1.)
    def __post_init__(self):
        if not isinstance(self.spectral,SpectralRetuneRequest):raise PlacementError('SpectralRetuneRequest required')
        if self.placement not in PLACEMENTS:raise PlacementError('placement must be pre/inter/post')
        if not isinstance(self.stage_a,NonlinearStageSpec) or not isinstance(self.stage_b,NonlinearStageSpec):raise PlacementError('two nonlinear stage specs required')
    @property
    def order(self):
        if self.placement=='pre':return ('spectral','stage_a','stage_b')
        if self.placement=='inter':return ('stage_a','spectral','stage_b')
        return ('stage_a','stage_b','spectral')
    def to_dict(self):
        return {'kind':'SpectralPlacementRequest','version':'1.0.0','placement':self.placement,'order':list(self.order),
                'spectral':self.spectral.to_dict(),'stage_a':self.stage_a.to_dict(),'stage_b':self.stage_b.to_dict(),
                'output_policy':{'normalization':'none','master_gain_db':0.,'declared_latency_samples':0}}

@dataclass(frozen=True)
class PlacementResult:
    request:PlacementRequest
    source:np.ndarray
    audio:np.ndarray
    taps:dict
    spectral_result:SpectralRetuneResult
    graph_nodes:tuple[dict,...]
    diagnostics:dict
    def __post_init__(self):
        source=np.asarray(self.source);audio=np.asarray(self.audio)
        if source.shape!=audio.shape or not np.isfinite(audio).all():raise PlacementError('placement output shape/nonfinite failure')
        object.__setattr__(self,'taps',{k:np.asarray(v).copy() for k,v in self.taps.items()})
        object.__setattr__(self,'graph_nodes',tuple(deepcopy(self.graph_nodes)));object.__setattr__(self,'diagnostics',deepcopy(self.diagnostics))
    @property
    def inspection(self):
        return {'request':self.request.to_dict(),'graph_nodes':deepcopy(list(self.graph_nodes)),
                'spectral':self.spectral_result.inspection,'diagnostics':deepcopy(self.diagnostics)}

def _node(stage,node_id,input_id,channels):
    node=envelope('DSPNodeSpec',id=node_id,type_id=stage.type_id,inputs=[input_id],channels=channels,params=stage.params(),
                  state_policy='stateless',phase_policy='source-derived',latency_samples=0,lookahead_samples=0,bypass='identity',automation=[])
    validate(node,'DSPNodeSpec');return node

def _stage(audio,sr,stage,label):
    channels=1 if np.asarray(audio).ndim==1 else np.asarray(audio).shape[1]
    node=_node(stage,label,'source',channels);result=execute_graph(audio,sr,[node],label,'source',capture_taps=True)
    return np.asarray(result.output),node

def _spectral(audio,sr,request,checkpoint=None):
    if checkpoint:checkpoint()
    analysis=analyse_components(np.asarray(audio,dtype=np.float32),sr)
    return retune_components(analysis,request,checkpoint=checkpoint)

def run_placement(source,sample_rate_hz,request,*,checkpoint=None):
    if not isinstance(request,PlacementRequest):raise PlacementError('PlacementRequest required')
    raw=np.asarray(source)
    if raw.ndim not in (1,2) or not np.issubdtype(raw.dtype,np.number) or not np.isfinite(raw).all():raise PlacementError('finite mono/stereo source required')
    if type(sample_rate_hz)is not int or not 8000<=sample_rate_hz<=192000:raise PlacementError('sample rate out of range')
    current=np.asarray(raw,dtype=np.float64);taps={'source':current.copy()};nodes=[];spectral_result=None
    for step in request.order:
        if checkpoint:checkpoint()
        if step=='spectral':
            spectral_result=_spectral(current,sample_rate_hz,request.spectral,checkpoint);current=np.asarray(spectral_result.audio,dtype=np.float64);taps['post-spectral']=current.copy()
        elif step=='stage_a':
            current,node=_stage(current,sample_rate_hz,request.stage_a,'stage-a');nodes.append(node);taps['post-stage-a']=current.copy()
        elif step=='stage_b':
            current,node=_stage(current,sample_rate_hz,request.stage_b,'stage-b');nodes.append(node);taps['post-stage-b']=current.copy()
        else:raise PlacementError('unknown placement step')
    if spectral_result is None:raise PlacementError('placement omitted spectral stage')
    taps['output']=current.copy()
    identity=bool(request.spectral.amount==0 and request.stage_a.mix==0 and request.stage_b.mix==0)
    if identity:current=np.asarray(raw).copy();taps['output']=current.copy()
    diagnostics={'method':'zg.spectral_placement.v1','version':'1.0.0','placement':request.placement,'order':list(request.order),
                 'declared_latency_samples':0,'normalization':'none','master_gain_db':0.,'identity_path':identity,
                 'stage_a_filter':request.stage_a.to_dict()['filter'],'stage_b_filter':request.stage_b.to_dict()['filter'],
                 'spectral_changed_frames':spectral_result.diagnostics['changed_frames']}
    return PlacementResult(request,np.asarray(raw).copy(),np.asarray(current).copy(),taps,spectral_result,tuple(nodes),diagnostics)

def run_family(source,sample_rate_hz,spectral,stage_a,stage_b,*,checkpoint=None):
    return {placement:run_placement(source,sample_rate_hz,PlacementRequest(spectral,placement,stage_a,stage_b),checkpoint=checkpoint)
            for placement in PLACEMENTS}
