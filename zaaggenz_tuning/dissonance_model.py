from __future__ import annotations
from dataclasses import dataclass
from copy import deepcopy
import math,re

METHOD_ID='zg.timbre_interaction_roughness.v1'
METHOD_VERSION='1.0.0'
ID=re.compile(r'^[a-z][a-z0-9_.-]{0,63}$')
INTERVAL_GRID_MAX_POINTS=2401
INTERVAL_GRID_ENDPOINT_TOLERANCE_CENTS=1e-9

class DissonanceError(ValueError):pass

def _finite(v,name):
    if type(v) not in (int,float) or type(v)is bool or not math.isfinite(float(v)):raise DissonanceError(f'{name} must be finite')
    return float(v)

def _positive(v,name):
    v=_finite(v,name)
    if v<=0:raise DissonanceError(f'{name} must be positive')
    return v

def _unit(v,name):
    v=_finite(v,name)
    if not 0<=v<=1:raise DissonanceError(f'{name} must be in [0,1]')
    return v

def _interval_grid_layout(start,stop,step):
    """Return stepped count, endpoint-replacement flag, and realised point count.

    The endpoint policy is intentionally shared by validation and materialisation:
    a final stepped point within one nanocent below the requested stop (or one
    rounded just above it) represents that endpoint and is canonicalised to the
    exact stop.  Otherwise the exact stop is appended once.
    """
    span=stop-start
    if not math.isfinite(span):raise DissonanceError('interval grid span must be finite')
    quotient=span/step
    if not math.isfinite(quotient):raise DissonanceError('interval grid span/step must be finite')
    stepped_points=math.floor(quotient)+1
    last_stepped=start+(stepped_points-1)*step
    endpoint_replaces_last=last_stepped>=stop-INTERVAL_GRID_ENDPOINT_TOLERANCE_CENTS
    points=stepped_points if endpoint_replaces_last else stepped_points+1
    return stepped_points,endpoint_replaces_last,points

def _validated_interval_grid_layout(start,stop,step):
    layout=_interval_grid_layout(start,stop,step)
    if not 2<=layout[2]<=INTERVAL_GRID_MAX_POINTS:
        raise DissonanceError(f'interval grid requires 2..{INTERVAL_GRID_MAX_POINTS} points')
    return layout

@dataclass(frozen=True)
class TimbreSpectrum:
    id:str
    frequencies_hz:tuple[float,...]
    amplitudes:tuple[float,...]
    confidence:float=1.
    source:dict|None=None
    def __post_init__(self):
        if type(self.id)is not str or not ID.fullmatch(self.id):raise DissonanceError('invalid spectrum id')
        if len(self.frequencies_hz)!=len(self.amplitudes):raise DissonanceError('frequency/amplitude lengths must match')
        try:rows=sorted((float(f),float(a)) for f,a in zip(self.frequencies_hz,self.amplitudes))
        except Exception as exc:raise DissonanceError('numeric frequency/amplitude values required') from exc
        if not 1<=len(rows)<=64:raise DissonanceError('spectrum requires 1..64 matched partials')
        if any(not math.isfinite(f) or f<=0 or not math.isfinite(a) or a<0 for f,a in rows) or not any(a>0 for _,a in rows):raise DissonanceError('invalid spectrum values')
        if self.source is not None and type(self.source)is not dict:raise DissonanceError('source must be a mapping')
        object.__setattr__(self,'frequencies_hz',tuple(f for f,_ in rows));object.__setattr__(self,'amplitudes',tuple(a for _,a in rows))
        object.__setattr__(self,'confidence',_unit(self.confidence,'confidence'));object.__setattr__(self,'source',deepcopy(self.source or {}))
    def shifted(self,cents,*,id=None):
        ratio=2.**(_finite(cents,'cents')/1200.)
        return TimbreSpectrum(id or self.id,tuple(f*ratio for f in self.frequencies_hz),self.amplitudes,self.confidence,self.source)
    def to_dict(self):return {'id':self.id,'frequencies_hz':list(self.frequencies_hz),'amplitudes':list(self.amplitudes),'confidence':self.confidence,'source':deepcopy(self.source)}

@dataclass(frozen=True)
class DissonanceModelSpec:
    audible_min_hz:float=20.
    audible_max_hz:float=20000.
    kernel_a:float=3.5
    kernel_b:float=5.75
    bandwidth_numerator:float=.24
    bandwidth_slope:float=.021
    bandwidth_offset:float=19.
    bandwidth_scale:float=1.
    amplitude_exponent:float=1.
    amplitude_policy:str='l1-per-spectrum'
    def __post_init__(self):
        lo=_positive(self.audible_min_hz,'audible_min_hz');hi=_positive(self.audible_max_hz,'audible_max_hz')
        if lo>=hi:raise DissonanceError('audible band must increase')
        a=_positive(self.kernel_a,'kernel_a');b=_positive(self.kernel_b,'kernel_b')
        if a>=b:raise DissonanceError('kernel_a must be below kernel_b')
        for name in ('bandwidth_numerator','bandwidth_slope','bandwidth_offset','bandwidth_scale','amplitude_exponent'):
            object.__setattr__(self,name,_positive(getattr(self,name),name))
        if self.amplitude_policy!='l1-per-spectrum':raise DissonanceError('only l1-per-spectrum amplitude policy is registered in v1')
        object.__setattr__(self,'audible_min_hz',lo);object.__setattr__(self,'audible_max_hz',hi);object.__setattr__(self,'kernel_a',a);object.__setattr__(self,'kernel_b',b)
    def to_dict(self):
        return {'id':METHOD_ID,'version':METHOD_VERSION,'audible_band_hz':[self.audible_min_hz,self.audible_max_hz],
                'kernel':{'a':self.kernel_a,'b':self.kernel_b,'bandwidth_numerator':self.bandwidth_numerator,
                          'bandwidth_slope':self.bandwidth_slope,'bandwidth_offset':self.bandwidth_offset,'bandwidth_scale':self.bandwidth_scale},
                'amplitude':{'policy':self.amplitude_policy,'exponent':self.amplitude_exponent,'global_gain_invariant':True},
                'interpretation':'pairwise engineering interaction model; not preference, liking, style, or scale truth'}

@dataclass(frozen=True)
class IntervalGrid:
    start_cents:float=0.
    stop_cents:float=1200.
    step_cents:float=2.
    def __post_init__(self):
        start=_finite(self.start_cents,'start_cents');stop=_finite(self.stop_cents,'stop_cents');step=_positive(self.step_cents,'step_cents')
        if start>=stop:raise DissonanceError('interval grid must increase')
        _validated_interval_grid_layout(start,stop,step)
        object.__setattr__(self,'start_cents',start);object.__setattr__(self,'stop_cents',stop);object.__setattr__(self,'step_cents',step)
    @property
    def point_count(self):
        return _validated_interval_grid_layout(self.start_cents,self.stop_cents,self.step_cents)[2]
    def values(self):
        n,endpoint_replaces_last,_=_validated_interval_grid_layout(self.start_cents,self.stop_cents,self.step_cents)
        values=[self.start_cents+i*self.step_cents for i in range(n)]
        if endpoint_replaces_last:values[-1]=self.stop_cents
        else:values.append(self.stop_cents)
        return tuple(values)
    def to_dict(self):return {'start_cents':self.start_cents,'stop_cents':self.stop_cents,'step_cents':self.step_cents,'points':self.point_count}
