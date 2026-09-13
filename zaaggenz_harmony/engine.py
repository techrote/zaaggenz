from __future__ import annotations
from dataclasses import dataclass
import math
from zaaggenz_tuning import Tuning,tuning_from_spec,cents_to_ratio,analyse_frequency
from .model import (HarmonyError,SonoritySpec,VoicingConstraints,VoicePitch,CostBreakdown,VoicingFrame,ProgressionResult)

@dataclass(frozen=True)
class _Candidate:
    tone_id:str
    frequency_hz:float
    degree:int
    detune_cents:float
    source_coordinate:dict
    required_bit:int


def _tuning(value):
    if isinstance(value,Tuning):return value
    try:return tuning_from_spec(value)
    except Exception as exc:raise HarmonyError('valid Tuning/TuningSpec required') from exc

def _cents_ratio(a,b):return 1200.*math.log2(float(a)/float(b))

def _coordinate_for_hz(tuning,freq):
    r=analyse_frequency(tuning,float(freq));return int(r['degree']),float(r['detune_cents'])

def _tone_candidates(tuning,sonority,tone,voice,constraints,required_bits):
    n=tuning.degrees_per_period;rows=[]
    if tone.degree_offset is not None:
        base_degree=sonority.root_degree+tone.degree_offset
        for shift in range(-constraints.max_register_shifts,constraints.max_register_shifts+1):
            degree=base_degree+shift*n
            try:f=tuning.frequency(degree,tone.detune_cents)
            except Exception:continue
            if voice.min_hz<=f<=voice.max_hz:
                rows.append(_Candidate(tone.id,float(f),degree,float(tone.detune_cents),
                    {'kind':'degree','root_degree':sonority.root_degree,'degree_offset':tone.degree_offset,'register_shift':shift,'detune_cents':float(tone.detune_cents)},required_bits.get(tone.id,0)))
    else:
        root=tuning.frequency(sonority.root_degree);base=root*float(tone.ratio)*cents_to_ratio(tone.detune_cents)
        for shift in range(-constraints.max_register_shifts,constraints.max_register_shifts+1):
            try:f=base*(tuning.period_ratio**shift)
            except OverflowError:continue
            if voice.min_hz<=f<=voice.max_hz and math.isfinite(f):
                degree,detune=_coordinate_for_hz(tuning,f)
                rows.append(_Candidate(tone.id,float(f),degree,detune,
                    {'kind':'ratio','root_degree':sonority.root_degree,'ratio':float(tone.ratio),'register_shift':shift,'detune_cents':float(tone.detune_cents)},required_bits.get(tone.id,0)))
    return rows

def _anchored_candidate(tuning,voice,previous):
    if voice.anchor_policy=='fixed-hz':
        f=float(voice.fixed_hz);degree,detune=_coordinate_for_hz(tuning,f);return _Candidate('__fixed__',f,degree,detune,{'kind':'fixed-hz','frequency_hz':f},0)
    if voice.anchor_policy=='hold-first' and previous is not None:
        f=float(previous.frequency_hz);return _Candidate(previous.tone_id,f,previous.degree,previous.detune_cents,{'kind':'held-from-first','frequency_hz':f,'original_tone_id':previous.tone_id},0)
    return None

def _candidate_key(c):return (round(c.frequency_hz,12),c.tone_id,c.degree,round(c.detune_cents,9))

def _candidate_sets(tuning,sonority,constraints,previous):
    required=[t.id for t in sonority.tones if t.required]
    if len(required)>len(constraints.voices):raise HarmonyError('more required sonority tones than voices')
    bits={tone_id:1<<i for i,tone_id in enumerate(required)};full=(1<<len(required))-1
    prev_by={} if previous is None else {v.voice_id:v for v in previous.voices}
    rows=[];lowest_moving=None
    for i,voice in enumerate(constraints.voices):
        prev=prev_by.get(voice.id);anchor=_anchored_candidate(tuning,voice,prev)
        if anchor is not None:candidates=[anchor]
        else:
            if lowest_moving is None:lowest_moving=i
            candidates=[]
            for tone in sonority.tones:candidates.extend(_tone_candidates(tuning,sonority,tone,voice,constraints,bits))
            dedup={_candidate_key(c):c for c in candidates};candidates=list(dedup.values())
            if previous is not None and prev is not None:
                candidates.sort(key=lambda c:(abs(_cents_ratio(c.frequency_hz,prev.frequency_hz)),abs(_cents_ratio(c.frequency_hz,voice.preferred_hz)),_candidate_key(c)))
            else:candidates.sort(key=lambda c:(abs(_cents_ratio(c.frequency_hz,voice.preferred_hz)),_candidate_key(c)))
            candidates=candidates[:constraints.candidate_cap_per_voice]
        if not candidates:raise HarmonyError(f'voice {voice.id} has no candidates in range')
        rows.append(candidates)
    if full and lowest_moving is None:raise HarmonyError('all voices are anchored, so required sonority tones cannot be assigned')
    if sonority.bass_tone_id is not None:
        if lowest_moving is None:raise HarmonyError('bass-tone inversion requires at least one moving voice')
        eligible=[c for c in rows[lowest_moving] if c.tone_id==sonority.bass_tone_id]
        if not eligible:raise HarmonyError('requested inversion/bass tone is unavailable in the lowest moving voice range')
        rows[lowest_moving]=eligible
    return rows,full

def _voice_cost(candidate,voice,previous,constraints):
    movement=0.
    if previous is not None:
        movement=abs(_cents_ratio(candidate.frequency_hz,previous.frequency_hz))
        if movement>voice.max_leap_cents+1e-9:return None
    register=abs(_cents_ratio(candidate.frequency_hz,voice.preferred_hz))
    total=constraints.movement_weight*movement+constraints.register_weight*register
    return movement,register,total

def _target_comb(fundamentals,constraints):
    teeth=[]
    for f in fundamentals:
        for h in range(1,constraints.target_harmonics+1):
            q=f*h
            if q<=constraints.target_max_hz:teeth.append(float(q))
    teeth.sort();out=[]
    for f in teeth:
        if not out or abs(_cents_ratio(f,out[-1]))>.5:out.append(f)
        if len(out)>=constraints.target_max_teeth:break
    return tuple(out)

def solve_voicing(tuning,sonority,constraints,previous=None):
    tuning=_tuning(tuning)
    if not isinstance(sonority,SonoritySpec) or not isinstance(constraints,VoicingConstraints):raise HarmonyError('SonoritySpec and VoicingConstraints required')
    if previous is not None and not isinstance(previous,VoicingFrame):raise HarmonyError('previous must be VoicingFrame')
    candidate_sets,full_mask=_candidate_sets(tuning,sonority,constraints,previous);prev_by={} if previous is None else {v.voice_id:v for v in previous.voices};states={}
    for j,c in enumerate(candidate_sets[0]):
        voice=constraints.voices[0];cost=_voice_cost(c,voice,prev_by.get(voice.id),constraints)
        if cost is None:continue
        movement,register,total=cost;states[(j,c.required_bit)]=(total,movement,register,(c,))
    for i in range(1,len(constraints.voices)):
        next_states={};voice=constraints.voices[i]
        for (prev_j,mask),(total,movement_sum,register_sum,path) in states.items():
            last=path[-1]
            for j,c in enumerate(candidate_sets[i]):
                spacing=_cents_ratio(c.frequency_hz,last.frequency_hz)
                if spacing<=0 or spacing+1e-9<constraints.min_spacing_cents:continue
                cost=_voice_cost(c,voice,prev_by.get(voice.id),constraints)
                if cost is None:continue
                movement,register,local=cost;newmask=mask|c.required_bit;new=(total+local,movement_sum+movement,register_sum+register,path+(c,));key=(j,newmask)
                old=next_states.get(key)
                if old is None or (new[0],tuple(_candidate_key(x) for x in new[3]))<(old[0],tuple(_candidate_key(x) for x in old[3])):next_states[key]=new
        states=next_states
        if not states:raise HarmonyError(f'no non-crossing voicing satisfies constraints through voice {voice.id}')
    valid=[v for (j,mask),v in states.items() if (mask&full_mask)==full_mask]
    if not valid:raise HarmonyError('no voicing covers all required sonority tones within voice/range/spacing/leap constraints')
    total,movement,register,path=min(valid,key=lambda x:(x[0],tuple(_candidate_key(c) for c in x[3])));pitches=[]
    for voice,c in zip(constraints.voices,path):pitches.append(VoicePitch(voice.id,voice.role,c.tone_id,c.frequency_hz,c.degree,c.detune_cents,c.source_coordinate))
    fundamentals=tuple(float(v.frequency_hz) for v in pitches);comb=_target_comb(fundamentals,constraints);costs=CostBreakdown(movement,register,total,None,None)
    return VoicingFrame(sonority.id,sonority.root_degree,tuple(pitches),costs,fundamentals,comb)

def solve_progression(tuning,sonorities,constraints):
    tuning=_tuning(tuning);sonorities=tuple(sonorities)
    if not sonorities or any(not isinstance(s,SonoritySpec) for s in sonorities):raise HarmonyError('progression requires SonoritySpec sequence')
    frames=[];previous=None
    for sonority in sonorities:
        frame=solve_voicing(tuning,sonority,constraints,previous);frames.append(frame);previous=frame
    return ProgressionResult(tuning.id,constraints.sha256,tuple(frames),sum(f.costs.voice_leading_cost for f in frames))
