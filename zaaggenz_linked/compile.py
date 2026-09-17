"""Controlled variants, linked bridge trace, meter/harmony checks, and Compose adapters."""
from __future__ import annotations
from dataclasses import dataclass
from fractions import Fraction
import json, math
from copy import deepcopy
from zaaggenz_contracts import Contract,digest
from zaaggenz_contracts.model import fraction
from zaaggenz_melody import note_event,make_phrase_plan,transform_melodic_recipe
from zaaggenz_project import Project
from zaaggenz_timeline import TimelineDocument,default_document
from zaaggenz_tuning import tuning_from_spec,analyse_frequency,ratio_to_cents
from zaaggenz_meter import MeterPlan,generate_ticks
from .model import LinkedEventError,LinkedEventPlan,ControlledVariant

def _rat(q):return f'{q.numerator}/{q.denominator}'
def _roles(data):
    out=[]
    for p in data['phases']:
        start,stop=fraction(p['start_beat']),fraction(p['end_beat'])
        out.append({'beat':p['start_beat'],'duration_beats':_rat(stop-start),'role':p['role']})
    return out

def _coordinate(tuning,hz):
    row=analyse_frequency(tuning,float(hz));return int(row['degree']),float(row['detune_cents'])
def _linked_coord(tuning,start_degree,start_detune,target_degree,target_detune,progress):
    a=tuning.frequency(start_degree,start_detune);b=tuning.frequency(target_degree,target_detune)
    hz=math.exp(math.log(a)+(math.log(b)-math.log(a))*progress)
    return _coordinate(tuning,hz),hz
def _distance_to_return_cents(tuning,degree,detune_cents,return_degree,return_detune_cents):
    event_hz=tuning.frequency(degree,detune_cents);return_hz=tuning.frequency(return_degree,return_detune_cents)
    return abs(ratio_to_cents(event_hz/return_hz))

@dataclass(frozen=True)
class LinkedExpansion:
    phrase:Contract
    variant:ControlledVariant
    trace:tuple
    automation:tuple
    anchor_trace:tuple
    model_state:dict
    plan_sha256:str
    @property
    def sha256(self):return digest({'phrase':self.phrase.to_dict(),'variant':self.variant.to_dict(),'trace':list(self.trace),'automation':list(self.automation),'anchor_trace':list(self.anchor_trace),'model_state':self.model_state,'plan_sha256':self.plan_sha256})

@dataclass(frozen=True)
class LinkedRenderBundle:
    expansion:LinkedExpansion
    timeline:TimelineDocument
    recipe:Contract

def expand_linked(plan,variant,tuning,*,source_id='source'):
    if not isinstance(plan,LinkedEventPlan):raise LinkedEventError('LinkedEventPlan required')
    if isinstance(variant,str):variant=ControlledVariant(variant)
    if not isinstance(variant,ControlledVariant):raise LinkedEventError('ControlledVariant required')
    td=tuning.to_dict() if isinstance(tuning,Contract) else tuning
    try:t=tuning_from_spec(td)
    except Exception as exc:raise LinkedEventError('valid TuningSpec required') from exc
    d=plan.to_dict();events=[];trace=[]
    prep=d['preparation'];pstart=fraction(d['phases'][0]['start_beat']);step=fraction(prep['step_beats'])
    for i,degree in enumerate(prep['degrees']):
        beat=pstart+i*step;eid=f'linked-prep-{i:02d}';events.append(note_event(eid,_rat(beat),prep['duration_beats'],t.id,degree,gain_db=prep['gain_db'],source_id=source_id));trace.append({'event_id':eid,'phase':'preparation','beat':_rat(beat),'degree':degree,'detune_cents':0.0,'gain_db':prep['gain_db'],'link_progress':None,'expected_local_degree':d['local_expectation']['expected_degree'],'actual_local_violation':False,'source_family':d['source_family']})
    loc=d['local_expectation'];actual=loc['substitute_degree'] if variant.violation else loc['expected_degree'];eid='linked-local-event';events.append(note_event(eid,loc['beat'],loc['duration_beats'],t.id,actual,detune_cents=loc['detune_cents'],gain_db=loc['gain_db'],source_id=source_id));trace.append({'event_id':eid,'phase':'violation','beat':loc['beat'],'degree':actual,'detune_cents':loc['detune_cents'],'gain_db':loc['gain_db'],'link_progress':0.0 if variant.recovery else None,'expected_local_degree':loc['expected_degree'],'actual_local_violation':variant.violation,'source_family':d['source_family']})
    bridge=d['bridge'];bstart=fraction(d['phases'][2]['start_beat']);bstop=fraction(d['phases'][2]['end_beat']);bstep=fraction(bridge['step_beats']);count=int((bstop-bstart)/bstep);ret=d['return_destination']
    linked_dist=[]
    for i in range(count):
        beat=bstart+i*bstep;progress=(i+1)/(count+1)
        if variant.linkage=='linked':
            (degree,detune),_= _linked_coord(t,actual,loc['detune_cents'],ret['degree'],ret['detune_cents'],progress);link=progress;distance=_distance_to_return_cents(t,degree,detune,ret['degree'],ret['detune_cents']);linked_dist.append(distance)
        elif variant.linkage=='unrelated':
            degree=loc['expected_degree']+bridge['unrelated_degree_offsets'][i];detune=0.;link=0.0;distance=_distance_to_return_cents(t,degree,detune,ret['degree'],ret['detune_cents']);linked_dist.append(distance)
        else:
            degree=loc['expected_degree']+bridge['neutral_degree_offsets'][i];detune=0.;link=None;distance=None
        eid=f'linked-bridge-{i:02d}';events.append(note_event(eid,_rat(beat),bridge['duration_beats'],t.id,degree,detune_cents=detune,gain_db=bridge['gain_db'],source_id=source_id));trace.append({'event_id':eid,'phase':'bridge','beat':_rat(beat),'degree':degree,'detune_cents':detune,'gain_db':bridge['gain_db'],'link_progress':link,'distance_to_return_cents':distance,'expected_local_degree':loc['expected_degree'],'actual_local_violation':variant.violation,'source_family':d['source_family']})
    if variant.linkage=='linked' and any(b>=a-1e-7 for a,b in zip(linked_dist,linked_dist[1:])):raise LinkedEventError('linked bridge failed monotonic convergence invariant')
    eid='linked-return';events.append(note_event(eid,ret['beat'],ret['duration_beats'],t.id,ret['degree'],detune_cents=ret['detune_cents'],gain_db=ret['gain_db'],source_id=source_id));trace.append({'event_id':eid,'phase':'return','beat':ret['beat'],'degree':ret['degree'],'detune_cents':ret['detune_cents'],'gain_db':ret['gain_db'],'link_progress':1.0 if variant.recovery else None,'distance_to_return_cents':_distance_to_return_cents(t,ret['degree'],ret['detune_cents'],ret['degree'],ret['detune_cents']),'expected_local_degree':loc['expected_degree'],'actual_local_violation':variant.violation,'source_family':d['source_family']})
    events.sort(key=lambda x:(fraction(x['beat']),x['id']))
    phrase=make_phrase_plan(t.id,events,end_beat=d['end_beat'],roles=_roles(d),seed='0',source_id=source_id)
    meter=MeterPlan(d['meter_plan']);anchors=tuple(generate_ticks(meter,d['stable_clock_id']))
    automation=[]
    for tr in d['transforms']:
        active=(tr['kind']=='motif-completion' and variant.recovery) or (tr['kind']=='withheld-low-band-arrival' and variant.violation) or (tr['kind'] in ('spectral-emergence','envelope-morph','restore-phase-alignment') and variant.recovery)
        row={**tr,'active':active,'variant':variant.name,'protected_topology_rewrite':False,'engine_semantics':'compositional-control-not-listener-outcome'}
        if tr['phase']=='bridge':row['progress']=[{'beat':_rat(bstart+i*bstep),'value':(i+1)/(count+1) if variant.linkage=='linked' and active else 0.0} for i in range(count)]
        automation.append(row)
    model_state={**deepcopy(d['engine_model']),'variant':variant.name,'actual_local_violation':variant.violation,'recovery_present':variant.recovery,'linkage':variant.linkage}
    return LinkedExpansion(phrase,variant,tuple(trace),tuple(automation),anchors,model_state,plan.sha256)

def plan_to_timeline(plan,variant,base=None,*,sample_rate=48000):
    document=default_document(sample_rate) if base is None else base
    if not isinstance(document,TimelineDocument):raise LinkedEventError('base must be TimelineDocument')
    original=document.to_dict();retained=deepcopy(original['project']);source=Project.from_document(retained).head_recipe.to_dict();exp=expand_linked(plan,variant,source['tuning'],source_id=source['source']['id'])
    notes=[]
    for e in exp.phrase.to_dict()['events']:
        notes.append({'id':e['id'],'beat':e['beat'],'duration_beats':e['duration_beats'],'degree':e['pitch']['degree'],'detune_cents':e['pitch']['detune_cents'],'gain_db':e['gain_db'],'muted':False,'roll_density':0})
    clips=[]
    for i,p in enumerate(plan.to_dict()['phases']):clips.append({'id':f'linked-phase-{i}','name':f'{p["name"]}: {p["role"]}','start_beat':p['start_beat'],'end_beat':p['end_beat']})
    data=deepcopy(original);data.update(name=f'{plan.to_dict()["id"]}-{exp.variant.name}',end_beat=plan.to_dict()['end_beat'],notes=notes,clips=clips,next_id=max(data['next_id'],len(notes)+len(clips)+1),project=retained)
    timeline=TimelineDocument(data)
    if timeline.to_dict()['project']!=retained:raise AssertionError('linked timeline adapter changed retained project')
    return timeline,exp

def compile_linked_recipe(plan,variant,base=None,*,sample_rate=48000,quality=None,tail_mode=None):
    timeline,exp=plan_to_timeline(plan,variant,base,sample_rate=sample_rate);td=timeline.to_dict();source=Project.from_document(td['project']).head_recipe.to_dict()
    try:
        recipe=transform_melodic_recipe(source,exp.phrase,quality=quality,tail_mode=tail_mode,master_gain_db=td['master_gain_db'])
    except Exception as exc:raise LinkedEventError('base recipe is incompatible with source-preserving linked compilation: '+str(exc)) from exc
    rendered=recipe.to_dict()
    if rendered['source']!=source['source']:raise AssertionError('linked compilation changed protected source')
    if source['render_mode']=='synth' and source['arrangement'] is None and source['reversebass'] is None:
        for key in ('nodes','output_node','sculpt'):
            if rendered[key]!=source[key]:raise AssertionError('linked compilation changed protected base topology')
    return LinkedRenderBundle(exp,timeline,recipe)
