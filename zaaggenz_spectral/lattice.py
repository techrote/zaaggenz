from __future__ import annotations
import math
from zaaggenz_tuning import tuning_from_spec
from .model import SpectralRetuneError,SpectralRetuneRequest,TargetTooth,retune_request_work_counts

def cents_distance(a,b):
    if a<=0 or b<=0:raise SpectralRetuneError('positive frequencies required')
    return 1200.*math.log2(a/b)

def cents_ratio(cents):return 2.**(float(cents)/1200.)

def _build(request,voices,segment_index,checkpoint=None):
    tuning=tuning_from_spec(request.tuning_spec);teeth=[];visited=0
    for vi,voice in enumerate(voices):
        root=tuning.frequency(voice.degree)
        for pi,ratio in enumerate(voice.partial_ratios):
            if checkpoint is not None and visited%256==0:checkpoint()
            visited+=1
            hz=root*ratio
            if request.min_hz<=hz<=request.max_hz:
                teeth.append(TargetTooth(f's{segment_index}:v{vi}:d{voice.degree}:p{pi}',vi,voice.degree,pi,ratio,hz,voice.label,segment_index))
    if checkpoint is not None:checkpoint()
    teeth.sort(key=lambda x:(x.frequency_hz,x.voice_index,x.partial_index))
    if not teeth:raise SpectralRetuneError('target lattice has no teeth in requested band')
    return tuple(teeth)

def build_target_lattice(request,checkpoint=None):
    if not isinstance(request,SpectralRetuneRequest):raise SpectralRetuneError('SpectralRetuneRequest required')
    retune_request_work_counts(request)
    return _build(request,request.voices,0,checkpoint)

def build_target_schedule(request,checkpoint=None):
    if not isinstance(request,SpectralRetuneRequest):raise SpectralRetuneError('SpectralRetuneRequest required')
    retune_request_work_counts(request)
    if checkpoint is not None:checkpoint()
    schedule=[(0,0,_build(request,request.voices,0,checkpoint))]
    for si,segment in enumerate(request.segments,1):
        if checkpoint is not None:checkpoint()
        schedule.append((segment.start_sample,si,_build(request,segment.voices,si,checkpoint)))
    return tuple(schedule)

def lattice_at(schedule,anchor_sample):
    active=schedule[0]
    for item in schedule[1:]:
        if anchor_sample<item[0]:break
        active=item
    return active[1],active[2]

def nearest_tooth(frequency_hz,teeth,previous_id=None,hysteresis_cents=0.):
    if not teeth:raise SpectralRetuneError('target lattice is empty')
    ranked=sorted(((abs(cents_distance(t.frequency_hz,frequency_hz)),t) for t in teeth),key=lambda x:(x[0],x[1].id))
    best_distance,best=ranked[0]
    if previous_id:
        old=next((t for t in teeth if t.id==previous_id),None)
        if old is not None:
            old_distance=abs(cents_distance(old.frequency_hz,frequency_hz))
            if old_distance<=best_distance+hysteresis_cents:return old,old_distance
    return best,best_distance
