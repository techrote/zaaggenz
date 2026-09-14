from __future__ import annotations
from dataclasses import dataclass
from copy import deepcopy
import math
from .adaptive_model import (ADAPTIVE_METHOD_ID,ADAPTIVE_VERSION,AdaptiveState,AdaptiveTuningRequest,AdaptiveVoice)
from .dissonance_curve import interaction_roughness
from .dissonance_model import DissonanceError

@dataclass(frozen=True)
class PairPrediction:
    voice_a:str
    voice_b:str
    interval_cents:float
    roughness:float
    confidence:float
    candidate_distance_cents:float
    def to_dict(self):return self.__dict__.copy()

@dataclass(frozen=True)
class AdaptiveProposal:
    request:AdaptiveTuningRequest
    status:str
    reason:str
    previous_state:AdaptiveState
    offsets_cents:tuple[tuple[str,float],...]
    adjusted_cents:tuple[tuple[str,float],...]
    pair_predictions:tuple[PairPrediction,...]
    objective:dict
    source_confidence:float
    search:dict
    def __post_init__(self):
        if self.status not in ('proposed','abstained'):raise DissonanceError('invalid proposal status')
    def offset_mapping(self):return dict(self.offsets_cents)
    def to_dict(self):return {'kind':'AdaptiveTuningProposal','version':ADAPTIVE_VERSION,'method_id':ADAPTIVE_METHOD_ID,
        'status':self.status,'reason':self.reason,'request':self.request.to_dict(),'previous_state':self.previous_state.to_dict(),
        'offsets_cents':dict(self.offsets_cents),'adjusted_cents':dict(self.adjusted_cents),'pair_predictions':[x.to_dict() for x in self.pair_predictions],
        'objective':deepcopy(self.objective),'source_confidence':self.source_confidence,'search':deepcopy(self.search),
        'manual_review_required':True,'interpretation':'model proposal only; no liking, style, or perceptual preference is inferred'}

def _circular_distance(interval,candidate):
    delta=abs(float(interval)-float(candidate))%1200.;return min(delta,1200.-delta)

def _candidate_distance(interval,candidates):return min(_circular_distance(interval,c) for c in candidates)

def _previous(request,state):
    state=state or AdaptiveState();known={v.id for v in request.voices};mapping=state.mapping()
    extra=set(mapping)-known
    if extra:raise DissonanceError('adaptive state contains unknown voice ids')
    out={v.id:float(mapping.get(v.id,0.)) for v in request.voices}
    for voice in request.voices:
        if abs(out[voice.id])>request.max_total_drift_cents+1e-9:raise DissonanceError('state exceeds cumulative drift bound')
    if request.root_lock:out[request.root_voice_id]=0.
    return state,out

def _constraints(request,offsets):
    for voice in request.voices:
        if abs(offsets[voice.id])>request.max_total_drift_cents+1e-9:return False,'cumulative-drift-bound'
    ordered=sorted(request.voices,key=lambda v:(v.nominal_cents,v.id))
    for a,b in zip(ordered,ordered[1:]):
        nominal_gap=b.nominal_cents-a.nominal_cents;gap=(b.nominal_cents+offsets[b.id])-(a.nominal_cents+offsets[a.id])
        if nominal_gap>1e-9 and gap<=0:return False,'voice-order-crossing'
        if abs(gap)<request.min_separation_cents-1e-9:return False,'minimum-separation'
    if request.root_lock and abs(offsets[request.root_voice_id])>1e-9:return False,'root-lock'
    return True,'ok'

def _score(request,offsets,previous):
    ok,reason=_constraints(request,offsets)
    if not ok:return None,reason,()
    pairs=[];weighted_rough=0.;weight_total=0.;candidate_total=0.
    voices=request.voices
    for i,a in enumerate(voices):
        sa=a.spectrum.shifted(offsets[a.id],id=a.spectrum.id)
        for b in voices[i+1:]:
            sb=b.spectrum.shifted(offsets[b.id],id=b.spectrum.id);obs=interaction_roughness(sa,sb,0.,request.model)
            if obs.value is None or obs.confidence<request.min_source_confidence:return None,'low-pair-confidence',()
            interval=abs((b.nominal_cents+offsets[b.id])-(a.nominal_cents+offsets[a.id]))%1200.
            distance=_candidate_distance(interval,request.candidate_intervals_cents);pairs.append(PairPrediction(a.id,b.id,interval,obs.value,obs.confidence,distance))
            weighted_rough+=obs.value*obs.confidence;weight_total+=obs.confidence;candidate_total+=distance
    tension=weighted_rough/max(weight_total,1e-30);tension_error=abs(tension-request.desired_tension)
    movable=max(1,len(voices));max_step=max(request.max_step_cents,1e-12);max_drift=max(request.max_total_drift_cents,1e-12)
    voice_leading=sum(abs(offsets[v.id]-previous[v.id]) for v in voices)/(movable*max_step)
    drift=sum(abs(offsets[v.id]) for v in voices)/(movable*max_drift) if request.max_total_drift_cents else 0.
    candidate_proximity=(candidate_total/max(len(pairs),1))/600.
    w=request.weights;terms={'tension_error':w.tension*tension_error,'voice_leading':w.voice_leading*voice_leading,
        'drift':w.drift*drift,'candidate_proximity':w.candidate_proximity*candidate_proximity}
    objective={'configured_total':sum(terms.values()),'terms':terms,'predicted_tension':tension,'desired_tension':request.desired_tension,
        'mean_candidate_distance_cents':candidate_total/max(len(pairs),1),
        'interpretation':'configured bounded search objective; lower is not a general musical-quality or preference score'}
    return objective,'ok',tuple(pairs)

def _offset_candidates(request,voice,current,previous):
    if voice.locked or voice.role=='pedal' or (request.root_lock and voice.id==request.root_voice_id):return (previous[voice.id],)
    total=request.max_total_drift_cents;step=request.max_step_cents;prev=previous[voice.id]
    lo=max(-total,prev-step);hi=min(total,prev+step);values={prev,lo,hi}
    if step>0:
        n=int(math.floor((hi-lo)/request.search_step_cents))
        values.update(lo+i*request.search_step_cents for i in range(n+1));values.add(hi)
    pos=voice.nominal_cents
    for other in request.voices:
        if other.id==voice.id:continue
        other_pos=other.nominal_cents+current[other.id];current_sep=abs((pos+prev)-other_pos)
        octave=int(round(current_sep/1200.))
        for interval in request.candidate_intervals_cents:
            for k in range(max(0,octave-1),octave+2):
                sep=interval+1200.*k
                for sign in (-1.,1.):
                    candidate=other_pos+sign*sep-pos
                    if lo-1e-9<=candidate<=hi+1e-9:values.add(candidate)
    return tuple(sorted(values))

def propose_adaptive_tuning(request,state=None):
    if not isinstance(request,AdaptiveTuningRequest):raise DissonanceError('AdaptiveTuningRequest required')
    state,previous=_previous(request,state);source_confidence=min(v.spectrum.confidence for v in request.voices)
    adjusted=lambda offsets:tuple(sorted((v.id,v.nominal_cents+offsets[v.id]) for v in request.voices))
    if source_confidence<request.min_source_confidence:
        return AdaptiveProposal(request,'abstained','low-source-confidence',state,tuple(sorted(previous.items())),adjusted(previous),(),{},source_confidence,
            {'passes':0,'evaluated_candidates':0,'accepted_changes':0})
    current=dict(previous);initial,reason,pairs=_score(request,current,previous)
    if initial is None:
        return AdaptiveProposal(request,'abstained','initial-state-'+reason,state,tuple(sorted(previous.items())),adjusted(previous),pairs,{},source_confidence,
            {'passes':0,'evaluated_candidates':0,'accepted_changes':0})
    evaluated=0;changes=0;passes=0
    voice_order=tuple(sorted(request.voices,key=lambda v:(v.nominal_cents,v.id)))
    for pass_index in range(request.max_passes):
        passes=pass_index+1;changed=False
        for voice in voice_order:
            choices=_offset_candidates(request,voice,current,previous);best_value=current[voice.id];best_obj,best_reason,best_pairs=_score(request,current,previous)
            for candidate in choices:
                trial=dict(current);trial[voice.id]=float(candidate);obj,why,pred=_score(request,trial,previous);evaluated+=1
                if obj is None:continue
                key=(obj['configured_total'],abs(candidate-previous[voice.id]),candidate)
                best_key=(best_obj['configured_total'],abs(best_value-previous[voice.id]),best_value)
                if key<best_key:best_value=float(candidate);best_obj=obj;best_pairs=pred;best_reason=why
            if abs(best_value-current[voice.id])>1e-9:current[voice.id]=best_value;changes+=1;changed=True
        if not changed:break
    objective,reason,pairs=_score(request,current,previous)
    if objective is None:
        return AdaptiveProposal(request,'abstained','no-feasible-proposal-'+reason,state,tuple(sorted(previous.items())),adjusted(previous),(),{},source_confidence,
            {'passes':passes,'evaluated_candidates':evaluated,'accepted_changes':changes})
    return AdaptiveProposal(request,'proposed','bounded-candidate-search',state,tuple(sorted(current.items())),adjusted(current),pairs,objective,source_confidence,
        {'passes':passes,'evaluated_candidates':evaluated,'accepted_changes':changes,'deterministic_coordinate_descent':True})

def commit_proposal(proposal):
    if not isinstance(proposal,AdaptiveProposal) or proposal.status!='proposed':raise DissonanceError('only a proposed adaptive tuning can be committed')
    return AdaptiveState(proposal.offsets_cents,proposal.previous_state.step_index+1)

def reject_proposal(proposal):
    if not isinstance(proposal,AdaptiveProposal):raise DissonanceError('AdaptiveProposal required')
    return proposal.previous_state
