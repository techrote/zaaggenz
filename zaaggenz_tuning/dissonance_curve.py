from __future__ import annotations
from dataclasses import dataclass,replace
import math
from .dissonance_model import (METHOD_ID,METHOD_VERSION,DissonanceError,DissonanceModelSpec,
                               TimbreSpectrum,IntervalGrid)

@dataclass(frozen=True)
class InteractionObservation:
    interval_cents:float
    value:float|None
    confidence:float
    audible_partials_a:int
    audible_partials_b:int
    coverage_a:float
    coverage_b:float
    validity:str
    def to_dict(self):return {'interval_cents':self.interval_cents,'value':self.value,'confidence':self.confidence,
        'audible_partials_a':self.audible_partials_a,'audible_partials_b':self.audible_partials_b,
        'coverage_a':self.coverage_a,'coverage_b':self.coverage_b,'validity':self.validity}

@dataclass(frozen=True)
class IntervalCandidate:
    cents:float
    value:float
    confidence:float
    prominence:float
    stability_fraction:float
    scenario_hits:int
    scenarios:int
    interpretation:str='candidate interval hypothesis; not a scale degree or preference claim'
    def to_dict(self):return self.__dict__.copy()

@dataclass(frozen=True)
class DissonanceCurve:
    spectrum_a_id:str
    spectrum_b_id:str
    grid:IntervalGrid
    model:DissonanceModelSpec
    points:tuple[InteractionObservation,...]
    def __post_init__(self):
        if len(self.points)!=self.grid.point_count:raise DissonanceError('curve/grid length mismatch')
    def to_dict(self):return {'kind':'TimbreDissonanceCurve','version':METHOD_VERSION,'method_id':METHOD_ID,
        'spectrum_a_id':self.spectrum_a_id,'spectrum_b_id':self.spectrum_b_id,'grid':self.grid.to_dict(),
        'model':self.model.to_dict(),'points':[x.to_dict() for x in self.points]}

def _kernel(f1,f2,model):
    df=abs(f2-f1);scale=model.bandwidth_scale*model.bandwidth_numerator/(model.bandwidth_slope*min(f1,f2)+model.bandwidth_offset);x=scale*df
    xmax=math.log(model.kernel_b/model.kernel_a)/(model.kernel_b-model.kernel_a)
    peak=math.exp(-model.kernel_a*xmax)-math.exp(-model.kernel_b*xmax)
    return max(0.,(math.exp(-model.kernel_a*x)-math.exp(-model.kernel_b*x))/peak)

def _audible(spectrum,shift_cents,model):
    ratio=2.**(float(shift_cents)/1200.);rows=[];all_weight=0.;kept_weight=0.
    for f,a in zip(spectrum.frequencies_hz,spectrum.amplitudes):
        w=float(a)**model.amplitude_exponent;all_weight+=w;hz=f*ratio
        if model.audible_min_hz<=hz<=model.audible_max_hz and w>0:rows.append((hz,w));kept_weight+=w
    if kept_weight<=0:return (),0.
    rows=tuple((f,w/kept_weight) for f,w in rows);coverage=kept_weight/max(all_weight,1e-30)
    return rows,coverage

def interaction_roughness(a,b,interval_cents,model=None):
    if not isinstance(a,TimbreSpectrum) or not isinstance(b,TimbreSpectrum):raise DissonanceError('two TimbreSpectrum values required')
    model=model or DissonanceModelSpec()
    if not isinstance(model,DissonanceModelSpec):raise DissonanceError('DissonanceModelSpec required')
    cents=float(interval_cents);rows_a,cov_a=_audible(a,0.,model);rows_b,cov_b=_audible(b,cents,model)
    confidence=min(a.confidence,b.confidence)*math.sqrt(cov_a*cov_b)
    if not rows_a or not rows_b:return InteractionObservation(cents,None,confidence,len(rows_a),len(rows_b),cov_a,cov_b,'insufficient-audible-partials')
    value=sum(wa*wb*_kernel(fa,fb,model) for fa,wa in rows_a for fb,wb in rows_b)
    return InteractionObservation(cents,float(value),float(confidence),len(rows_a),len(rows_b),cov_a,cov_b,'valid')

def dissonance_curve(a,b,grid=None,model=None):
    grid=grid or IntervalGrid();model=model or DissonanceModelSpec();values=grid.values()
    return DissonanceCurve(a.id,b.id,grid,model,tuple(interaction_roughness(a,b,c,model) for c in values))

def _valid_max(values):
    found=[float(x) for x in values if x is not None]
    return max(found) if found else None

def local_minima(curve,*,window_cents=40.):
    if not isinstance(curve,DissonanceCurve):raise DissonanceError('DissonanceCurve required')
    points=curve.points;values=[p.value for p in points];out=[];radius=max(1,int(round(window_cents/curve.grid.step_cents)))
    for i,p in enumerate(points):
        if p.value is None:continue
        left=values[i-1] if i else None;right=values[i+1] if i+1<len(values) else None
        if left is not None and p.value>left:continue
        if right is not None and p.value>right:continue
        if left is None and right is not None and p.value>right:continue
        if right is None and left is not None and p.value>left:continue
        left_max=_valid_max(values[max(0,i-radius):i]);right_max=_valid_max(values[i+1:min(len(values),i+radius+1)])
        boundaries=[x for x in (left_max,right_max) if x is not None]
        prominence=max(0.,min(boundaries)-p.value) if boundaries else 0.
        out.append(IntervalCandidate(p.interval_cents,p.value,p.confidence,prominence,1.,1,1))
    return tuple(out)

def sensitivity_candidates(a,b,grid=None,model=None,*,bandwidth_scales=(.9,1.,1.1),amplitude_exponents=(.85,1.,1.15),match_tolerance_cents=12.,min_stability=.6):
    grid=grid or IntervalGrid();model=model or DissonanceModelSpec();grid_points=grid.point_count
    base=dissonance_curve(a,b,grid,model);base_min=local_minima(base)
    scenarios=[]
    for bs in bandwidth_scales:
        for ae in amplitude_exponents:
            spec=replace(model,bandwidth_scale=float(bs),amplitude_exponent=float(ae));curve=dissonance_curve(a,b,grid,spec);scenarios.append(local_minima(curve))
    candidates=[];count=len(scenarios)
    for candidate in base_min:
        hits=sum(any(abs(other.cents-candidate.cents)<=match_tolerance_cents for other in minima) for minima in scenarios)
        fraction=hits/max(count,1);confidence=candidate.confidence*fraction
        if fraction>=min_stability:candidates.append(IntervalCandidate(candidate.cents,candidate.value,confidence,candidate.prominence,fraction,hits,count))
    candidates.sort(key=lambda x:(-x.stability_fraction,x.value,-x.prominence,x.cents))
    return base,tuple(candidates),{'bandwidth_scales':list(map(float,bandwidth_scales)),'amplitude_exponents':list(map(float,amplitude_exponents)),
        'match_tolerance_cents':float(match_tolerance_cents),'min_stability':float(min_stability),'scenario_count':count,
        'grid_point_count':grid_points,'scenario_point_evaluations':grid_points*count,'total_point_evaluations':grid_points*(count+1),
        'interpretation':'sensitivity agreement supports candidate stability only; it does not establish a preferred scale'}
