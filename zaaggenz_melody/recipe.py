from __future__ import annotations
from copy import deepcopy
import math
from zaaggenz_contracts import Contract,validate
from zaaggenz_contracts.legacy import freeze_legacy,envelope
from .model import MelodyError,NoteMode

def _number(value,name):
    if type(value) not in (int,float) or type(value)is bool or not math.isfinite(float(value)):raise MelodyError(f'{name} must be finite numeric')
    return float(value)

def note_event(event_id,beat,duration_beats,tuning_id,degree,*,detune_cents=0.,gain_db=0.,gesture_id=None,layer_role='synthline',source_id='source'):
    if type(degree)is not int or type(degree)is bool:raise MelodyError('degree must be an integer tuning coordinate')
    return dict(id=event_id,beat=beat,duration_beats=duration_beats,source_id=source_id,
               pitch=dict(tuning_id=tuning_id,degree=degree,detune_cents=_number(detune_cents,'detune_cents')),
               gain_db=_number(gain_db,'gain_db'),gesture_id=gesture_id,layer_role=layer_role)

def rest_event(event_id,beat,duration_beats,*,source_id='source',gain_db=0.,gesture_id=None,layer_role='synthline'):
    return dict(id=event_id,beat=beat,duration_beats=duration_beats,source_id=source_id,pitch=None,
                gain_db=_number(gain_db,'gain_db'),gesture_id=gesture_id,layer_role=layer_role)

def make_phrase_plan(tuning_id,events,*,start_beat='0/1',end_beat='4/1',gestures=(),roles=(),bass_role='none',seed='0',source_id='source'):
    d=envelope('PhrasePlan',start_beat=start_beat,end_beat=end_beat,tuning_id=tuning_id,source_ids=[source_id],
               gestures=[deepcopy(g.to_dict() if isinstance(g,Contract) else g) for g in gestures],events=[deepcopy(x) for x in events],
               roles=[deepcopy(x) for x in roles],bass_role=bass_role,
               random=dict(algorithm='sha256-named-u64-v1',root=str(seed),streams=[]))
    try:return Contract(d)
    except Exception as exc:raise MelodyError('invalid phrase plan') from exc

def make_melodic_recipe(synth_params,time_map,tuning,phrase,*,mode=NoteMode.SOURCE_DERIVED,tail_mode='preserve',tail_maximum_samples=0,quality='high',master_gain_db=0.):
    try:mode=NoteMode(mode)
    except ValueError as exc:raise MelodyError('unknown note render mode') from exc
    if tail_mode not in ('preserve','truncate'):raise MelodyError('melodic tail mode must be preserve or truncate')
    if quality not in ('standard','high'):raise MelodyError('melodic quality must be standard or high')
    if type(tail_maximum_samples)is not int or type(tail_maximum_samples)is bool or tail_maximum_samples<0:raise MelodyError('tail_maximum_samples must be a non-negative integer')
    tm=deepcopy(time_map.to_dict() if isinstance(time_map,Contract) else time_map);tu=deepcopy(tuning.to_dict() if isinstance(tuning,Contract) else tuning);ph=deepcopy(phrase.to_dict() if isinstance(phrase,Contract) else phrase)
    try:validate(tm,'TimeMap');validate(tu,'TuningSpec');validate(ph,'PhrasePlan')
    except Exception as exc:raise MelodyError('invalid time/tuning/phrase contract') from exc
    d=freeze_legacy(synth_params).to_dict();d['time_map']=tm;d['tuning']=tu;d['phrase']=ph;d['phase_policy']=mode.phase_policy
    d['tail']=dict(mode=tail_mode,maximum_samples=tail_maximum_samples);d['quality']=quality;d['output']['master_gain_db']=_number(master_gain_db,'master_gain_db')
    try:return Contract(d)
    except Exception as exc:raise MelodyError('melodic recipe violates shared contract') from exc
