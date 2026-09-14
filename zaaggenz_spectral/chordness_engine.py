from __future__ import annotations
import numpy as np
from zaaggenz_components import ComponentAnalysis,exact_bypass,reconstruct_components
from .chordness_descriptors import evaluate_union,objective_terms,select_templates
from .chordness_model import ChordnessError
from .chordness_request import ChordnessRequest
from .chordness_result import ChordnessResult
from .chordness_transform import transform_bundle

def _metric(snapshot,name):
    if not snapshot:return None
    if name=='roughness_pairwise':return snapshot['roughness']['value']
    return snapshot['target'][name]['value']

def apply_chordness(analysis,request,*,checkpoint=None,progress=None):
    if not isinstance(analysis,ComponentAnalysis):raise ChordnessError('ComponentAnalysis required')
    if not isinstance(request,ChordnessRequest):raise ChordnessError('ChordnessRequest required')
    selected,candidates=select_templates(analysis.bundle,request)
    if checkpoint:checkpoint()
    if request.mode=='off':
        source=np.asarray(analysis.source,dtype=np.float32).copy();audio=exact_bypass(source)
        diagnostics={'method':'zg.multi_comb_chordness.v1','version':'1.0.0','mode':'off','identity_path':True,
                     'selected_templates':0,'frames':sum(len(t['frames']) for t in analysis.bundle.to_dict()['tracks']),
                     'changed_frames':0,'retuned_frames':0,'reweighted_frames':0,'preserved_frames':sum(len(t['frames']) for t in analysis.bundle.to_dict()['tracks']),
                     'transient_unchanged':True,'residual_unchanged':True,
                     'interpretation':'configured engineering transform; no preference or pleasure claim'}
        if progress:progress(1.)
        return ChordnessResult(request,(),analysis.bundle,source,audio,np.asarray(analysis.sinusoidal,dtype=np.float32).copy(),
                               np.asarray(analysis.transient,dtype=np.float32).copy(),np.asarray(analysis.residual,dtype=np.float32).copy(),
                               (),tuple(candidates),(),None,None,None,None,diagnostics)
    before=evaluate_union(analysis.bundle,selected,tolerance_cents=request.tolerance_cents)
    bundle,decisions,occupancy,changed=transform_bundle(analysis,request,selected,checkpoint=checkpoint,progress=progress)
    if checkpoint:checkpoint()
    if changed==0:
        audio=exact_bypass(analysis.source);sin=np.asarray(analysis.sinusoidal,dtype=np.float32).copy()
    else:
        raw=np.asarray(reconstruct_components(bundle),dtype=np.float32);mask=np.asarray(analysis.transient_mask,dtype=np.float32)
        sin=raw*(1-mask if raw.ndim==1 else (1-mask[:,None]))
        audio=sin+np.asarray(analysis.transient,dtype=np.float32)+np.asarray(analysis.residual,dtype=np.float32)
    after=evaluate_union(bundle,selected,tolerance_cents=request.tolerance_cents)
    corrections=[abs(x.correction_cents) for x in decisions if abs(x.correction_cents)>1e-12]
    gains=[abs(x.gain_db) for x in decisions if abs(x.gain_db)>1e-12]
    before_objective=objective_terms(before,request)
    after_objective=objective_terms(after,request,mean_reassignment_cents=float(np.mean(corrections)) if corrections else 0.,
                                    mean_gain_motion_db=float(np.mean(gains)) if gains else 0.)
    retuned=sum(abs(x.correction_cents)>1e-12 for x in decisions);reweighted=sum(abs(x.gain_db)>1e-12 for x in decisions)
    assigned=sum(x.template_id is not None for x in decisions);preserved=sum(x.decision=='preserve' for x in decisions)
    diagnostics={'method':'zg.multi_comb_chordness.v1','version':'1.0.0','mode':request.mode,'identity_path':changed==0,
                 'selected_templates':len(selected),'selected_template_ids':[x.id for x in selected],'frames':len(decisions),
                 'assigned_frames':assigned,'changed_frames':changed,'retuned_frames':retuned,'reweighted_frames':reweighted,
                 'preserved_frames':preserved,'target_comb_fit_before':_metric(before,'target_comb_fit'),
                 'target_comb_fit_after':_metric(after,'target_comb_fit'),'roughness_before':_metric(before,'roughness_pairwise'),
                 'roughness_after':_metric(after,'roughness_pairwise'),'transient_unchanged':True,'residual_unchanged':True,
                 'interpretation':'configured engineering transform; descriptor changes are not preference or pleasure scores'}
    if progress:progress(1.)
    return ChordnessResult(request,tuple(x.id for x in selected),bundle,np.asarray(analysis.source,dtype=np.float32).copy(),
                           np.asarray(audio,dtype=np.float32).copy(),np.asarray(sin,dtype=np.float32).copy(),
                           np.asarray(analysis.transient,dtype=np.float32).copy(),np.asarray(analysis.residual,dtype=np.float32).copy(),
                           decisions,tuple(candidates),occupancy,before,after,before_objective,after_objective,diagnostics)

def chordness_inspection(result):
    if not isinstance(result,ChordnessResult):raise ChordnessError('ChordnessResult required')
    return result.inspection
