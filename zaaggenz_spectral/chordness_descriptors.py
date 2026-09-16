from __future__ import annotations
import math
from zaaggenz_descriptors import roughness_observation,target_comb_observations
from .chordness_model import ChordnessError,CombTemplate
from .chordness_request import ChordnessRequest

MAX_SELECTED_UNION_TEETH=128

def usable_teeth(template,sample_rate_hz):
    if not isinstance(template,CombTemplate):raise ChordnessError('CombTemplate required')
    nyquist=float(sample_rate_hz)/2.
    teeth=tuple(x for x in template.teeth_hz if x<nyquist)
    if not teeth:raise ChordnessError(f'comb {template.id} has no teeth below Nyquist')
    return teeth

def combined_usable_teeth(templates,sample_rate_hz,*,enforce_limit=True):
    templates=tuple(templates)
    if not templates:raise ChordnessError('selected target requires at least one comb')
    teeth=tuple(sorted({x for template in templates for x in usable_teeth(template,sample_rate_hz)}))
    if not teeth:raise ChordnessError('selected target has no teeth below Nyquist')
    if enforce_limit and len(teeth)>MAX_SELECTED_UNION_TEETH:
        raise ChordnessError(
            f'combined selected target contains {len(teeth)} unique teeth below Nyquist; '
            f'maximum is {MAX_SELECTED_UNION_TEETH}'
        )
    return teeth

def _values(observations):
    return {x.metric:{'value':x.value,'validity':x.validity,'confidence':x.confidence,
                      'method_id':x.method_id,'method_version':x.method_version,'unit':x.unit,
                      'details':x.details} for x in observations}

def _sample_rate(bundle):
    d=bundle.to_dict() if hasattr(bundle,'to_dict') else bundle
    return d['asset']['sample_rate_hz']

def evaluate_template(bundle,template,*,tolerance_cents=35.):
    sample_rate=_sample_rate(bundle)
    teeth=usable_teeth(template,sample_rate)
    metrics=_values(target_comb_observations(bundle,teeth,tolerance_cents=tolerance_cents))
    return {'template_id':template.id,'usable_teeth_hz':list(teeth),'metrics':metrics}

def evaluate_union(bundle,templates,*,tolerance_cents=35.):
    sr=_sample_rate(bundle)
    teeth=combined_usable_teeth(templates,sr)
    target=_values(target_comb_observations(bundle,teeth,tolerance_cents=tolerance_cents))
    rough=_values([roughness_observation(bundle)])['roughness_pairwise']
    return {'target_teeth_hz':list(teeth),'target':target,'roughness':rough}

def select_templates(bundle,request):
    if not isinstance(request,ChordnessRequest):raise ChordnessError('ChordnessRequest required')
    sr=_sample_rate(bundle)
    by_id={x.id:x for x in request.templates}

    if request.mode=='off':
        selected=()
    elif request.selection_mode=='manual':
        selected=tuple(x for x in request.templates if x.id in request.selected_template_ids)
        combined_usable_teeth(selected,sr)
    else:
        selected=None

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

    if request.mode=='off':
        return selected,evaluations
    if request.selection_mode=='manual':
        union_size=len(combined_usable_teeth(selected,sr))
        selected_ids={x.id for x in selected}
        for row in evaluations:
            row['selection_budget']={'selected':row['template_id'] in selected_ids,
                                     'reason':'manual_selection' if row['template_id'] in selected_ids else 'not_manually_selected',
                                     'selected_union_teeth':union_size if row['template_id'] in selected_ids else None,
                                     'limit':MAX_SELECTED_UNION_TEETH}
        return selected,evaluations

    ranked=sorted(evaluations,key=lambda x:(float('-inf') if x['selection_terms']['configured_score'] is None else x['selection_terms']['configured_score'],x['template_id']),reverse=True)
    chosen=[]
    chosen_ids=set()
    for row in ranked:
        score=row['selection_terms']['configured_score']
        if score is None:
            row['selection_budget']={'selected':False,'reason':'descriptor_abstained','union_teeth_if_selected':None,'limit':MAX_SELECTED_UNION_TEETH}
            continue
        if len(chosen)>=request.max_selected_templates:
            row['selection_budget']={'selected':False,'reason':'template_count_limit','union_teeth_if_selected':None,'limit':MAX_SELECTED_UNION_TEETH}
            continue
        template=by_id[row['template_id']]
        union=combined_usable_teeth((*chosen,template),sr,enforce_limit=False)
        if len(union)>MAX_SELECTED_UNION_TEETH:
            row['selection_budget']={'selected':False,'reason':'combined_target_teeth_limit','union_teeth_if_selected':len(union),'limit':MAX_SELECTED_UNION_TEETH}
            continue
        chosen.append(template);chosen_ids.add(template.id)
        row['selection_budget']={'selected':True,'reason':'selected','union_teeth_if_selected':len(union),'limit':MAX_SELECTED_UNION_TEETH}
    selected=tuple(x for x in request.templates if x.id in chosen_ids)
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
