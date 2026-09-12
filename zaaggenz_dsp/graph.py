from __future__ import annotations
from dataclasses import dataclass
import numpy as np
from zaaggenz_contracts import validate, ContractError
from zaaggenz_contracts.registry import node_definition
from .multiband import multiband_gain, BandError

class GraphError(ValueError):pass

@dataclass(frozen=True)
class GraphResult:
    output:np.ndarray
    taps:dict
    order:tuple[str,...]

def _audio(x,channels=None):
    raw=np.asarray(x)
    mono=raw.ndim==1
    if mono:raw=raw[:,None]
    if raw.ndim!=2 or raw.shape[1] not in (1,2) or (channels is not None and raw.shape[1]!=channels) or not np.issubdtype(raw.dtype,np.number) or not np.isfinite(raw).all():
        raise GraphError('finite mono/stereo input with declared channel count required')
    return np.asarray(raw,dtype=np.float64),raw.shape[1],mono

def _toposort(nodes,source_id,output_id):
    by={n['id']:n for n in nodes}
    if len(by)!=len(nodes):raise GraphError('duplicate graph node id')
    if source_id in by:raise GraphError('source/node id collision')
    if output_id!=source_id and output_id not in by:raise GraphError('unknown output node')
    allids=set(by)|{source_id}
    for n in nodes:
        if not set(n['inputs'])<=allids:raise GraphError('dangling graph input')
    order=[];visiting=set();done=set()
    def visit(k):
        if k==source_id or k in done:return
        if k in visiting:raise GraphError('DSP graph cycle; delayed feedback is not registered in v1')
        visiting.add(k)
        for p in by[k]['inputs']:visit(p)
        visiting.remove(k);done.add(k);order.append(k)
    visit(output_id)
    if done!=set(by):raise GraphError('disconnected DSP nodes are not allowed')
    return tuple(order),by

def _curve(node,param,n,base):
    lane=next((a for a in node['automation'] if a['parameter']==param),None)
    if lane is None:return float(base)
    spec=node_definition(node['type_id'])['parameters'][param]
    if not spec.get('x-automatable',False):raise GraphError(f'{node["type_id"]}.{param} is not automatable')
    points=lane['points'];samples=np.arange(n,dtype=np.float64);xp=[p['sample'] for p in points];yp=[p['value'] for p in points]
    if lane['interpolation']=='linear':
        if xp[0]>0:xp=[0,*xp];yp=[base,*yp]
        return np.interp(samples,xp,yp,left=base,right=yp[-1])
    idx=np.searchsorted(np.asarray(xp),samples,side='right')-1;out=np.full(n,float(base));mask=idx>=0;out[mask]=np.asarray(yp)[idx[mask]];return out

def _broadcast(v,x):
    if np.isscalar(v):return v
    return np.asarray(v)[:,None]

def _execute_node(node,x,sr):
    try:validate(node,'DSPNodeSpec')
    except ContractError as e:raise GraphError(str(e)) from e
    definition=node_definition(node['type_id'])
    if definition.get('availability')!='executable':raise GraphError('node type is not executable')
    t=node['type_id'];n=len(x);p=node['params']
    if t=='core.identity.v1':return x.copy()
    if t=='core.gain.v1':
        db=_curve(node,'gain_db',n,p['gain_db']);return x*_broadcast(10**(np.asarray(db)/20),x)
    if t=='core.tanh.v1':
        drive=_curve(node,'drive_db',n,p['drive_db']);mix=_curve(node,'mix',n,p['mix']);wet=np.tanh(x*_broadcast(10**(np.asarray(drive)/20),x));m=_broadcast(mix,x);return (1-m)*x+m*wet
    if t=='core.hard_clip.v1':
        threshold=_curve(node,'threshold',n,p['threshold']);mix=_curve(node,'mix',n,p['mix']);th=_broadcast(threshold,x);wet=np.clip(x,-th,th);m=_broadcast(mix,x);return (1-m)*x+m*wet
    if t=='core.multiband_gain.v1':
        if node['automation']:raise GraphError('multiband gain automation is not registered in v1')
        cross=(p['low_xover_hz'],p['mid_xover_hz'],p['high_xover_hz']);g=(p['sub_gain_db'],p['lowmid_gain_db'],p['highmid_gain_db'],p['air_gain_db'])
        try:return np.asarray(multiband_gain(x,sr,cross,g,p['confine_delta']),dtype=np.float64)
        except BandError as e:raise GraphError(str(e)) from e
    if t=='legacy.sculpt.v1':
        if node['automation']:raise GraphError('legacy SCULPT automation is not registered in v1')
        try:
            from uptempo_harmony.multiband import SpectralSculptParams, process_spectral_sculpt
            y=process_spectral_sculpt((x[:,0] if x.shape[1]==1 else x).astype(np.float32),sr,SpectralSculptParams(**p))
            a,_,_= _audio(y,x.shape[1]);return a
        except (ImportError,TypeError,ValueError) as e:raise GraphError('legacy SCULPT adapter failed: '+str(e)) from e
    raise GraphError('no executor for '+t)

def execute_graph(source,sample_rate_hz,nodes,output_node,source_id='source',capture_taps=True):
    x,channels,mono=_audio(source)
    if type(sample_rate_hz)is not int or not 8000<=sample_rate_hz<=192000:raise GraphError('sample rate out of range')
    if type(nodes)is not list or len(nodes)>128:raise GraphError('bounded node list required')
    for n in nodes:
        try:validate(n,'DSPNodeSpec')
        except ContractError as e:raise GraphError(str(e)) from e
        if n['channels']!=channels:raise GraphError('node channel count mismatch')
    order,by=_toposort(nodes,source_id,output_node);values={source_id:x};taps={source_id:x.copy()} if capture_taps else {}
    for key in order:
        node=by[key];inp=values[node['inputs'][0]];y=_execute_node(node,inp,sample_rate_hz);y,c,_=_audio(y,channels)
        if y.shape!=inp.shape:raise GraphError('node changed signal shape')
        values[key]=y
        if capture_taps:taps[key]=y.copy()
    out=values[output_node]
    if mono:out=out[:,0]
    if capture_taps and mono:taps={k:v[:,0] for k,v in taps.items()}
    return GraphResult(np.asarray(out),taps,order)

def apply_output_policy(x,output):
    a,_,mono=_audio(x);gain_db=float(output['master_gain_db']);gain=10**(gain_db/20);y=a*gain;driven=float(np.max(np.abs(y))) if y.size else 0.;clip_fraction=float(np.mean(np.abs(y)>1)) if y.size else 0.
    policy=output['clipping']
    if policy=='clip_at_full_scale' and clip_fraction:y=np.clip(y,-1,1)
    elif policy=='error' and clip_fraction:raise GraphError('output exceeds full scale under error clipping policy')
    elif policy not in ('clip_at_full_scale','error','unbounded_float'):raise GraphError('unsupported clipping policy')
    out=y.astype(np.float32);out=out[:,0] if mono else out
    return out,{'gain_db':gain_db,'gain_linear':gain,'driven_peak':driven,'clip_fraction':clip_fraction,'output_peak':float(np.max(np.abs(out))) if out.size else 0.}
