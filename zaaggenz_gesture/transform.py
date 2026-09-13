"""Deterministic surface variation, direction reversal and manual correction."""
from __future__ import annotations
from fractions import Fraction
import hashlib,math
from zaaggenz_contracts.model import fraction,seed_value
from .model import DirectionalGesture,GestureError,AXES

def _rat(v): return f'{v.numerator}/{v.denominator}'
def _copy(plan):
    if not isinstance(plan,DirectionalGesture): raise GestureError('DirectionalGesture required')
    return plan.to_dict()
def _trajectory(data,axis):
    try:return next(t for t in data['trajectories'] if t['axis']==axis)
    except StopIteration as exc: raise GestureError(f'unknown trajectory {axis!r}') from exc

def vary_surface(plan,seed,amount=.65,*,axes=None,source_family=None):
    data=_copy(plan)
    try: seed_value(str(seed))
    except ValueError as exc: raise GestureError(str(exc)) from exc
    if type(amount) not in (int,float) or type(amount)is bool or not math.isfinite(float(amount)) or not 0<=amount<=1: raise GestureError('surface amount must be in [0,1]')
    selected=set(AXES if axes is None else axes)
    if not selected<=set(AXES): raise GestureError('unknown variation axis')
    if source_family is not None:
        if type(source_family)is not str: raise GestureError('source_family must be text')
        data['source_family']=source_family
    protected={fraction(x['beat']) for x in data['landmarks']}
    for traj in data['trajectories']:
        if traj['axis'] not in selected: continue
        protected_axis=protected|{fraction(s['start_beat']) for s in traj['segments']}|{fraction(s['end_beat']) for s in traj['segments']}
        points=traj['points']; original=[fraction(p['beat']) for p in points]
        for i in range(1,len(points)-1):
            beat=original[i]
            if beat in protected_axis: continue
            gap=min(beat-original[i-1],original[i+1]-beat)
            limit=int(float(gap)*960*.4*float(amount))
            if limit<1: continue
            raw=int.from_bytes(hashlib.sha256(f'zg027-surface-v1\0{seed}\0{traj["axis"]}\0{i}'.encode()).digest()[:8],'big')
            steps=raw%limit+1; sign=-1 if (raw>>63)&1 else 1
            points[i]['beat']=_rat(beat+Fraction(sign*steps,960))
    return DirectionalGesture(data)

def reverse_direction(plan,axes=('pitch_cents',),*,source_family=None):
    data=_copy(plan); selected=set(axes)
    if not selected or not selected<=set(AXES): raise GestureError('reverse axes must be known and nonempty')
    if source_family is not None: data['source_family']=source_family
    swap={'rising':'falling','falling':'rising','flat':'flat','free':'free'}
    for axis in selected:
        traj=_trajectory(data,axis); values=[float(p['value']) for p in traj['points']]; lo,hi=min(values),max(values)
        for point in traj['points']:
            value=lo+hi-float(point['value'])
            point['value']=int(round(value)) if axis=='onset_density' else value
        for seg in traj['segments']: seg['direction']=swap[seg['direction']]
    return DirectionalGesture(data)

def replace_trajectory_points(plan,axis,points):
    data=_copy(plan); traj=_trajectory(data,axis); traj['points']=[dict(x) for x in points]
    return DirectionalGesture(data)

def edit_landing(plan,**changes):
    allowed={'degree','detune_cents','gain_db'}
    if not set(changes)<=allowed or not changes: raise GestureError('landing edits are degree/detune_cents/gain_db only')
    data=_copy(plan); data['landing'].update(changes); return DirectionalGesture(data)
