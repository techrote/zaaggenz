from __future__ import annotations
from copy import deepcopy
from dataclasses import dataclass
import math
import numpy as np
from zaaggenz_contracts import Contract
from zaaggenz_components import ComponentAnalysis,exact_bypass,reconstruct_components
from .lattice import build_target_lattice,cents_distance,cents_ratio,nearest_tooth
from .model import (METHOD_ID,METHOD_VERSION,FrameDecision,SpectralRetuneError,
                    SpectralRetuneRequest,TargetTooth)

def _wrap_phase(v):return (float(v)+math.pi)%(2*math.pi)-math.pi

def _clamp(v,lo,hi):return min(max(v,lo),hi)

@dataclass(frozen=True)
class SpectralRetunePlan:
    request:SpectralRetuneRequest
    teeth:tuple[TargetTooth,...]
    decisions:tuple[FrameDecision,...]
    method_id:str=METHOD_ID
    version:str=METHOD_VERSION
    def inspection(self):
        return {'method':{'id':self.method_id,'version':self.version},
                'teeth':[dict(id=x.id,voice_index=x.voice_index,degree=x.degree,
                              partial_index=x.partial_index,ratio=x.ratio,
                              frequency_hz=x.frequency_hz,label=x.label) for x in self.teeth],
                'frames':[x.to_dict() for x in self.decisions]}

@dataclass(frozen=True)
class SpectralRetuneResult:
    request:SpectralRetuneRequest
    plan:SpectralRetunePlan
    bundle:Contract
    source:np.ndarray
    audio:np.ndarray
    sinusoidal:np.ndarray
    transient:np.ndarray
    residual:np.ndarray
    diagnostics:dict
    def __post_init__(self):
        if not isinstance(self.bundle,Contract) or self.bundle.to_dict().get('kind')!='PartialTrackBundle':raise SpectralRetuneError('PartialTrackBundle required')
        shape=np.asarray(self.source).shape
        for name in ('source','audio','sinusoidal','transient','residual'):
            a=np.asarray(getattr(self,name))
            if a.shape!=shape or not np.isfinite(a).all():raise SpectralRetuneError(name+' invalid')
            a.setflags(write=False)
        object.__setattr__(self,'diagnostics',deepcopy(self.diagnostics))
    @property
    def inspection(self):return self.plan.inspection()

def _preserve_reason(track,row,request):
    if row.get('action')!='transform':return 'component-policy-preserve'
    if float(row.get('confidence',0.))<request.min_confidence:return 'low-confidence'
    if request.preserve_ambiguous and track.get('continuity')!='continuous':return 'ambiguous-or-reanchored-track'
    return None

def _plan_and_bundle(analysis,request,checkpoint=None,progress=None):
    source=analysis.bundle.to_dict();out=deepcopy(source);teeth=build_target_lattice(request);decisions=[]
    total=max(1,sum(len(t['frames']) for t in source['tracks']));done=0;sr=source['asset']['sample_rate_hz']
    for ti,(src_track,dst_track) in enumerate(zip(source['tracks'],out['tracks'])):
        prev_anchor=None;prev_corr=0.;prev_delta=0.;prev_phase=0.;prev_tooth=None
        for fi,(row,newrow) in enumerate(zip(src_track['frames'],dst_track['frames'])):
            if checkpoint and done%16==0:checkpoint()
            f=float(row['frequency_hz']);anchor=int(row['support']['anchor_sample']);confidence=float(row['confidence'])
            reason=_preserve_reason(src_track,row,request);tooth=None;requested=None;corr=0.;phasecorr=0.;realised=f;decision='preserve'
            if request.amount==0:
                reason='amount-zero-exact-bypass'
            elif reason is None:
                tooth,distance=nearest_tooth(f,teeth,prev_tooth,request.assignment_hysteresis_cents)
                requested=tooth.frequency_hz
                if distance>request.max_displacement_cents:
                    reason='no-target-within-displacement'
                else:
                    desired=cents_distance(requested,f)*request.amount
                    if prev_anchor is not None:
                        dt=max(0.,(anchor-prev_anchor)/sr);step=request.max_correction_slew_cents_per_second*dt
                        corr=_clamp(desired,prev_corr-step,prev_corr+step)
                    else:corr=desired
                    corr=_clamp(corr,-request.max_displacement_cents,request.max_displacement_cents)
                    realised=f*cents_ratio(corr);delta=realised-f
                    if prev_anchor is not None:
                        dt=max(0.,(anchor-prev_anchor)/sr)
                        phasecorr=_wrap_phase(prev_phase+2*math.pi*.5*(prev_delta+delta)*dt)
                    for ci,p in enumerate(row['phases_radians']):newrow['phases_radians'][ci]=_wrap_phase(p+phasecorr)
                    newrow['frequency_hz']=float(realised);decision='transform';reason='retuned';prev_tooth=tooth.id
            if decision!='transform':
                prev_tooth=None;corr=0.;phasecorr=0.;realised=f;newrow['frequency_hz']=f
                newrow['phases_radians']=list(row['phases_radians']);delta=0.
            else:delta=realised-f
            decisions.append(FrameDecision(src_track['id'],fi,anchor,f,requested,float(realised),float(corr),confidence,
                                           row.get('action','preserve'),decision,reason,tooth.id if tooth else None,float(phasecorr)))
            prev_anchor=anchor;prev_corr=corr;prev_delta=delta;prev_phase=phasecorr;done+=1
            if progress:progress(min(.8,.8*done/total))
    return SpectralRetunePlan(request,teeth,tuple(decisions)),Contract(out)

def retune_components(analysis,request,*,checkpoint=None,progress=None):
    if not isinstance(analysis,ComponentAnalysis):raise SpectralRetuneError('ComponentAnalysis required')
    if not isinstance(request,SpectralRetuneRequest):raise SpectralRetuneError('SpectralRetuneRequest required')
    plan,bundle=_plan_and_bundle(analysis,request,checkpoint,progress)
    changed=[d for d in plan.decisions if d.decision=='transform' and abs(d.correction_cents)>1e-9]
    if checkpoint:checkpoint()
    if not changed:
        audio=exact_bypass(analysis.source);sin=np.asarray(analysis.sinusoidal,dtype=np.float32).copy()
    else:
        raw=reconstruct_components(bundle);mask=np.asarray(analysis.transient_mask,dtype=np.float32)
        sin=np.asarray(raw,dtype=np.float32)*(1-mask if np.asarray(raw).ndim==1 else (1-mask[:,None]))
        audio=np.asarray(sin,dtype=np.float32)+np.asarray(analysis.transient,dtype=np.float32)+np.asarray(analysis.residual,dtype=np.float32)
    if progress:progress(.95)
    transformed=[d for d in plan.decisions if d.decision=='transform'];preserved=len(plan.decisions)-len(transformed)
    errors=[abs(cents_distance(d.realised_hz,d.requested_hz)) for d in transformed if d.requested_hz]
    diag={'method':METHOD_ID,'version':METHOD_VERSION,'frames':len(plan.decisions),'transformed_frames':len(transformed),
          'changed_frames':len(changed),'preserved_frames':preserved,'identity_path':not changed,
          'max_abs_correction_cents':max((abs(d.correction_cents) for d in plan.decisions),default=0.),
          'median_target_error_cents':float(np.median(errors)) if errors else None,
          'transient_unchanged':True,'residual_unchanged':True,'stereo_phase_policy':'shared-correction-per-track'}
    if checkpoint:checkpoint()
    if progress:progress(1.)
    return SpectralRetuneResult(request,plan,bundle,np.asarray(analysis.source,dtype=np.float32).copy(),
                                np.asarray(audio,dtype=np.float32).copy(),np.asarray(sin,dtype=np.float32).copy(),
                                np.asarray(analysis.transient,dtype=np.float32).copy(),np.asarray(analysis.residual,dtype=np.float32).copy(),diag)

def inspection_payload(result):
    if not isinstance(result,SpectralRetuneResult):raise SpectralRetuneError('SpectralRetuneResult required')
    payload=result.inspection;payload['diagnostics']=deepcopy(result.diagnostics);return payload
