from __future__ import annotations
from copy import deepcopy
import math
import numpy as np
from zaaggenz_contracts import Contract,validate
from .chordness_assign import assign_components
from .chordness_model import ChordnessError
from .chordness_request import ChordnessRequest
from .chordness_result import ChordnessFrameDecision
from .lattice import cents_distance,cents_ratio

def _wrap(v):return (float(v)+math.pi)%(2*math.pi)-math.pi
def _clamp(v,lo,hi):return min(max(v,lo),hi)
def _amp(row):
    a=np.asarray(row['amplitudes'],dtype=np.float64);return float(np.sqrt(np.mean(a*a)))

def transform_bundle(analysis,request,selected_templates,*,checkpoint=None,progress=None):
    if not isinstance(request,ChordnessRequest):raise ChordnessError('ChordnessRequest required')
    source=analysis.bundle.to_dict();out=deepcopy(source);sr=source['asset']['sample_rate_hz']
    assignments,preserved,occupancy=assign_components(analysis.bundle,selected_templates,request)
    decisions=[];changed=0;total=max(1,sum(len(x['frames']) for x in source['tracks']));done=0
    for ti,(track,dst_track) in enumerate(zip(source['tracks'],out['tracks'])):
        prev_anchor=None;prev_corr=0.;prev_delta=0.;prev_phase=0.;prev_gain=0.
        for fi,(row,newrow) in enumerate(zip(track['frames'],dst_track['frames'])):
            if checkpoint and done%16==0:checkpoint()
            key=(ti,fi);assignment=assignments.get(key);reason=preserved.get(key);f=float(row['frequency_hz']);anchor=int(row['support']['anchor_sample']);confidence=float(row['confidence'])
            source_amp=_amp(row);realised=f;corr=0.;phasecorr=0.;gain=0.;decision='preserve';delta=0.;assignment_confidence=None
            if reason is None and assignment is not None:
                distance=float(assignment['distance_cents']);target=float(assignment['target_hz']);parts=[]
                assignment_confidence=float(confidence*math.exp(-.5*(distance/request.tolerance_cents)**2))
                if request.mode in ('retune','hybrid'):
                    if distance<=request.max_displacement_cents:
                        desired=cents_distance(target,f)*request.retune_amount
                        if prev_anchor is None:corr=desired
                        else:
                            dt=max(0.,(anchor-prev_anchor)/sr);step=request.max_correction_slew_cents_per_second*dt
                            corr=_clamp(desired,prev_corr-step,prev_corr+step)
                        corr=_clamp(corr,-request.max_displacement_cents,request.max_displacement_cents)
                        realised=f*cents_ratio(corr);delta=realised-f
                        if prev_anchor is not None:
                            dt=max(0.,(anchor-prev_anchor)/sr);phasecorr=_wrap(prev_phase+2*math.pi*.5*(prev_delta+delta)*dt)
                        newrow['frequency_hz']=float(realised);newrow['phases_radians']=[_wrap(p+phasecorr) for p in row['phases_radians']]
                        if abs(corr)>1e-12:parts.append('retune')
                    else:reason='assigned-retune-outside-displacement'
                if request.mode in ('reweight','hybrid'):
                    fit=math.exp(-.5*(distance/request.tolerance_cents)**2);desired_gain=request.max_gain_db*request.reweight_amount*(2.*fit-1.)
                    if prev_anchor is None:gain=desired_gain
                    else:
                        dt=max(0.,(anchor-prev_anchor)/sr);step=request.max_gain_slew_db_per_second*dt
                        gain=_clamp(desired_gain,prev_gain-step,prev_gain+step)
                    gain=_clamp(gain,-request.max_gain_db,request.max_gain_db);scale=10.**(gain/20.)
                    newrow['amplitudes']=[float(x*scale) for x in row['amplitudes']]
                    if abs(gain)>1e-12:parts.append('reweight')
                if parts:decision='+'.join(parts);reason='assigned'
                elif reason is None:reason='assigned-no-nonzero-change'
            else:
                if reason is None:reason='unassigned'
            if decision=='preserve':
                newrow['frequency_hz']=f;newrow['phases_radians']=list(row['phases_radians']);newrow['amplitudes']=list(row['amplitudes'])
                realised=f;corr=phasecorr=gain=delta=0.;prev_anchor=None;prev_corr=prev_delta=prev_phase=prev_gain=0.
            else:
                prev_anchor=anchor;prev_corr=corr;prev_delta=delta;prev_phase=phasecorr;prev_gain=gain
            realised_amp=_amp(newrow)
            if abs(realised-f)>1e-10 or any(abs(a-b)>1e-12 for a,b in zip(newrow['amplitudes'],row['amplitudes'])):changed+=1
            a=assignment or {}
            decisions.append(ChordnessFrameDecision(track['id'],fi,anchor,f,float(realised),source_amp,realised_amp,float(corr),float(gain),confidence,
                                                     assignment_confidence,decision,reason,a.get('template_id'),a.get('tooth_index'),a.get('target_hz'),
                                                     a.get('distance_cents'),a.get('occupancy'),a.get('capacity'),float(phasecorr)))
            done+=1
            if progress:progress(min(.75,.75*done/total))
    bundle=Contract(out);validate(bundle.to_dict(),'PartialTrackBundle')
    return bundle,tuple(decisions),occupancy,changed
