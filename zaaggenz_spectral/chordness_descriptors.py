from __future__ import annotations
import math
from zaaggenz_descriptors import roughness_observation,target_comb_observations
from .chordness_model import ChordnessError,CombTemplate
from .chordness_request import ChordnessRequest

def usable_teeth(template,sample_rate_hz):
    if not isinstance(template,CombTemplate):raise ChordnessError('CombTemplate required')
    nyquist=float(sample_rate_hz)/2.
    teeth=tuple(x for x in template.teeth_hz if x<nyquist)
    if not teeth:raise ChordnessError(f'comb {template.id} has no teeth below Nyquist')
    return teeth

def _values(observations):
    return {x.metric:{'value':x.value,'validity':x.validity,'confidence':x.confidence,
                      'method_id':x.method_id,'method_version':x.method_version,'unit':x.unit,
                      'details':x.details} for x in observations}

def evaluate_template(bundle,template,*,tolerance_cents=35.):
    sample_rate=bundle.to_dict()['asset']['sample_rate_hz'] if hasattr(bundle,'to_dict') else bundle['asset']['sample_rate_hz']
    teeth=usable_teeth(template,sample_rate)
    metrics=_values(target_comb_observations(bundle,teeth,tolerance_cents=tolerance_cents))
    return {'template_id':template.id,'usable_teeth_hz':list(teeth),'metrics':metrics}

def evaluate_union(bundle,templates,*,tolerance_cents=35.):
    d=bundle.to_dict() if hasattr(bundle,'to_dict') else bundle;sr=d['asset']['sample_rate_hz']
    teeth=tuple(sorted({x for template in templates for x in usable_teeth(template,sr)}))
    target=_values(target_comb_observations(bundle,teeth,tolerance_cents=tolerance_cents))
    rough=_values([roughness_observation(bundle)])['roughness_pairwise']
    return {'target_teeth_hz':list(teeth),'target':target,'roughness':rough}

def select_templates(bundle,request):
    if not isinstance(request,ChordnessRequest):raise ChordnessError('ChordnessRequest required')
    evaluations=[evaluate_template(bundle,x,tolerance_cents=request.tolerance_cents) for x in request.templates]
    coeff=request.coefficients
    for row in evaluations:
        fit=row['metrics']['target_comb_fit']['value'];density=row['metrics']['target_comb_density']['value']
        if fit is None:score=None
        else:score=coeff.target_fit*fit-coeff.density_penalty*math.log1p(float(density))
        row['selection_terms']={'target_fit':None if fit is None else coeff.target_fit*fit,
                                'density_penalty':-coeff.density_penalty*math.log1p(float(density)),
                                'configured_score':score,
                                'interpretation':'configured engineering score; not preference or pleasure'}
    if request.mode=='off':selected=()
    elif request.selection_mode=='manual':selected=tuple(x for x in request.templates if x.id in request.selected_template_ids)
    else:
        ranked=sorted(evaluations,key=lambda x:(float('-inf') if x['selection_terms']['configured_score'] is None else x['selection_terms']['configured_score'],x['template_id']),reverse=True)
        chosen={x['template_id'] for x in ranked[:request.max_selected_templates] if x['selection_terms']['configured_score'] is not None}
        selected=tuple(x for x in request.templates if x.id in chosen)
        if not selected:raise ChordnessError('descriptor selection abstained for all candidates')
    return selected,evaluations

def objective_terms(descriptor_snapshot,request,*,mean_reassignment_cents=0.,mean_gain_motion_db=0.):
    target=descriptor_snapshot['target']['target_comb_fit']['value'];rough=descriptor_snapshot['roughness']['value'];density=len(descriptor_snapshot['target_teeth_hz']);c=request.coefficients
    terms={'target_fit':None if target is None else c.target_fit*target,
           'roughness':None if rough is None else -c.roughness*rough,
           'density_penalty':-c.density_penalty*math.log1p(density),
           'reassignment':-c.reassignment_cents*(float(mean_reassignment_cents)/1200.),
           'gain_motion':-c.gain_motion_db*(float(mean_gain_motion_db)/max(request.max_gain_db,1e-12) if request.max_gain_db else 0.)}
    valid=[v for v in terms.values() if v is not None]
    return {'terms':terms,'configured_total':sum(valid) if valid else None,
            'interpretation':'configured engineering objective only; not objective truth, preference or pleasure'}
