from __future__ import annotations
from fractions import Fraction
from zaaggenz_contracts.model import fraction
from zaaggenz_melody import note_event,make_phrase_plan
from .model import HarmonyError,ProgressionResult

def _beats(values,name):
    try:return tuple(fraction(v) for v in values)
    except Exception as exc:raise HarmonyError(f'invalid rational {name}') from exc

def _rat(v):return f'{v.numerator}/{v.denominator}'

def progression_events(progression,frame_beats,duration_beats,*,gain_db=-12.,source_id='source',audition_synthline=False):
    if not isinstance(progression,ProgressionResult):raise HarmonyError('ProgressionResult required')
    starts=_beats(frame_beats,'frame beats');durations=_beats(duration_beats,'durations') if not isinstance(duration_beats,str) else tuple(fraction(duration_beats) for _ in progression.frames)
    if len(starts)!=len(progression.frames) or len(durations)!=len(progression.frames):raise HarmonyError('frame beat/duration counts must match progression')
    if any(q<0 for q in starts) or any(q<=0 for q in durations):raise HarmonyError('event beats must be nonnegative and durations positive')
    if type(gain_db) in (int,float) and type(gain_db)is not bool:gains={v.voice_id:float(gain_db) for v in progression.frames[0].voices}
    elif type(gain_db)is dict:gains={str(k):float(v) for k,v in gain_db.items()}
    else:raise HarmonyError('gain_db must be scalar or voice-id mapping')
    events=[]
    for i,(frame,start,duration) in enumerate(zip(progression.frames,starts,durations)):
        for voice in frame.voices:
            if voice.voice_id not in gains:raise HarmonyError(f'missing gain for voice {voice.voice_id}')
            role='synthline' if audition_synthline else voice.role
            events.append(note_event(f'{voice.voice_id}-{i:04d}',_rat(start),_rat(duration),progression.tuning_id,voice.degree,
                                     detune_cents=voice.detune_cents,gain_db=gains[voice.voice_id],layer_role=role,source_id=source_id))
    return events

def voice_event_groups(progression,frame_beats,duration_beats,*,gain_db=-12.,source_id='source'):
    events=progression_events(progression,frame_beats,duration_beats,gain_db=gain_db,source_id=source_id,audition_synthline=True)
    groups={v.voice_id:[] for v in progression.frames[0].voices}
    for event in events:groups[event['id'].rsplit('-',1)[0]].append(event)
    return groups

def voice_phrase_plans(progression,frame_beats,duration_beats,*,gain_db=-12.,source_id='source'):
    starts=_beats(frame_beats,'frame beats');durations=_beats(duration_beats,'durations') if not isinstance(duration_beats,str) else tuple(fraction(duration_beats) for _ in progression.frames)
    if len(starts)!=len(progression.frames) or len(durations)!=len(progression.frames):raise HarmonyError('frame beat/duration counts must match progression')
    end=max(s+d for s,d in zip(starts,durations));groups=voice_event_groups(progression,frame_beats,duration_beats,gain_db=gain_db,source_id=source_id)
    return {voice_id:make_phrase_plan(progression.tuning_id,events,start_beat='0/1',end_beat=_rat(end),source_id=source_id) for voice_id,events in groups.items()}
