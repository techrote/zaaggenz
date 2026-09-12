from __future__ import annotations
from copy import deepcopy
from dataclasses import dataclass
import numpy as np
from zaaggenz_contracts import Contract,ContractError,validate
from zaaggenz_contracts.legacy import thaw_legacy,envelope
from .graph import execute_graph,apply_output_policy,GraphError

@dataclass(frozen=True)
class RenderResult:
    audio:np.ndarray
    stems:dict
    taps:dict
    events:tuple
    timeline:tuple
    master_diagnostics:dict
    graph_order:tuple[str,...]

def _node(node_id,type_id,input_id,params):
    return envelope('DSPNodeSpec',id=node_id,type_id=type_id,inputs=[input_id],channels=1,params=deepcopy(params),
        state_policy='stateless',phase_policy='source-derived',latency_samples=0,lookahead_samples=0,bypass='identity',automation=[])

def graphify_legacy_recipe(recipe):
    """Move legacy SCULPT into explicit graph order without changing rendered audio."""
    c=recipe if isinstance(recipe,Contract) else Contract(recipe);d=c.to_dict();validate(d,'RenderRecipe')
    if d['nodes'] or d['output_node']!=d['source']['id']:raise GraphError('graphify expects an exact ungraphed legacy recipe')
    # Proves time/tuning/source/mode/output fields are still a legacy-exact projection.
    try:thaw_legacy(c)
    except ContractError as e:raise GraphError('recipe is not a legacy-exact source projection: '+str(e)) from e
    source=d['source']['id'];nodes=[]
    if d['sculpt'] is not None:
        nodes.append(_node('legacy-sculpt','legacy.sculpt.v1',source,d['sculpt']));d['sculpt']=None;d['output_node']='legacy-sculpt'
    d['nodes']=nodes
    return Contract(d)

def _source_projection(d):
    base=deepcopy(d);base['nodes']=[];base['output_node']=base['source']['id'];base['sculpt']=None
    try:return thaw_legacy(Contract(base))
    except ContractError as e:raise GraphError('new musical intent requires a non-legacy source renderer: '+str(e)) from e

def _render_source(d):
    p=_source_projection(d);mode=d['render_mode'];events=();timeline=();stems={}
    try:
        from uptempo_harmony.synth import synthesize_one,synthesize_loop
        from uptempo_harmony.arrangement import synthesize_arrangement
        from uptempo_harmony.reversebass import synthesize_reversebass_arrangement
        if mode=='synth':
            audio=synthesize_loop(p['synth']) if p['synth'].beats>1 else synthesize_one(p['synth'])[0]
        elif mode=='arrange':
            audio,events,timeline=synthesize_arrangement(p['synth'],p['arrangement']);events=tuple(events);timeline=tuple(timeline)
        elif mode in ('arrange_bass','bass'):
            audio,events,stems=synthesize_reversebass_arrangement(p['synth'],p['arrangement'],p['reversebass']);events=tuple(events);stems=dict(stems)
        else:raise GraphError('unsupported render mode')
        return np.asarray(audio),events,timeline,stems
    except ImportError as e:raise GraphError('authenticated legacy engine is not materialized') from e

def render_recipe(recipe,capture_taps=True):
    c=recipe if isinstance(recipe,Contract) else Contract(recipe);d=c.to_dict();validate(d,'RenderRecipe')
    source,events,timeline,stems=_render_source(d);sr=d['time_map']['sample_rate_hz']
    result=execute_graph(source,sr,d['nodes'],d['output_node'],d['source']['id'],capture_taps)
    final,master=apply_output_policy(result.output,d['output'])
    taps=dict(result.taps)
    if capture_taps:
        taps['legacy-source-post-internal-nonlinear']=np.asarray(source).copy()
        taps['pre-master']=np.asarray(result.output).copy();taps['post-master']=np.asarray(final).copy()
    if stems:
        # Diagnostic component stems intentionally remain pre-master; mix is the declared post-master product.
        stems={k:np.asarray(v).copy() for k,v in stems.items()};stems['mix']=final
    return RenderResult(final,stems,taps,events,timeline,master,result.order)
