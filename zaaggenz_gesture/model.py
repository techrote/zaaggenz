"""Versioned directional-gesture authoring above frozen musical contracts."""
from __future__ import annotations
from dataclasses import dataclass
from fractions import Fraction
import json
import math
import re
from zaaggenz_contracts import digest
from zaaggenz_contracts.model import check_json, fraction, loads

VERSION='1.0.0'
AXES={
 'onset_density':('events/beat',1.,16.), 'accent_db':('dB',-24.,24.),
 'duration_beats':('beats',1/64,4.), 'pitch_cents':('cents',-1200.,1200.),
 'brightness_hz':('Hz',0.,96000.), 'roughness_fraction':('ratio',0.,1.),
 'spectral_occupancy_fraction':('ratio',0.,1.), 'spectral_width_fraction':('ratio',0.,1.)}
DIRECTIONS=('rising','falling','flat','free')
LANDMARK_KINDS=('entry','accent','turn','landing','endpoint')
EVENT_GAIN_DB_MIN=-120.
EVENT_GAIN_DB_MAX=24.
_ID=re.compile(r'[a-z][a-z0-9_.-]{0,63}\Z')

class GestureError(ValueError): pass

def exact(v,keys,name):
    if type(v)is not dict or set(v)!=set(keys): raise GestureError(f'{name}: missing or unknown fields')
def identifier(v,name):
    if type(v)is not str or not _ID.fullmatch(v): raise GestureError(f'{name}: lowercase identifier required')
def integer(v,lo,hi,name):
    if type(v)is not int or not lo<=v<=hi: raise GestureError(f'{name}: integer {lo}..{hi} required')
def number(v,lo,hi,name):
    if type(v) not in (int,float) or type(v)is bool or not math.isfinite(float(v)) or not lo<=float(v)<=hi: raise GestureError(f'{name}: finite {lo}..{hi} required')
    return float(v)

def _trajectory(data,axis): return next(t for t in data['trajectories'] if t['axis']==axis)

def trajectory_value(trajectory,beat):
    """Evaluate authored control points using the compilation interpolation policy."""
    beat=fraction(beat) if isinstance(beat,str) else beat
    points=[(fraction(p['beat']),float(p['value'])) for p in trajectory['points']]
    if beat<=points[0][0]: return points[0][1]
    if beat>=points[-1][0]: return points[-1][1]
    left=points[0]
    for right in points[1:]:
        if beat==right[0]: return right[1]
        if beat<right[0]:
            if trajectory['interpolation']=='step': return left[1]
            alpha=float((beat-left[0])/(right[0]-left[0])); return left[1]+alpha*(right[1]-left[1])
        left=right
    return points[-1][1]

def effective_event_gains(data,landing_at=None):
    """Return pre-landing event starts/gains and enforce frozen PhrasePlan bounds."""
    if landing_at is None: landing_at=fraction(data['landing']['beat'])
    density=_trajectory(data,'onset_density');accent=_trajectory(data,'accent_db')
    base=float(data['base_gain_db']);rows=[];at=Fraction(0);count=0
    while at<landing_at:
        density_value=trajectory_value(density,at);density_int=int(round(density_value))
        if density_int<1 or abs(density_value-density_int)>1e-9: raise GestureError('compiled onset density must be an integer')
        gain=base+trajectory_value(accent,at)
        if not EVENT_GAIN_DB_MIN<=gain<=EVENT_GAIN_DB_MAX:
            beat=f'{at.numerator}/{at.denominator}'
            raise GestureError(f'effective event gain at beat {beat} lies outside -120..24 dB')
        rows.append((at,gain));count+=1
        if count>1024: raise GestureError('effective event-gain expansion exceeds bounded gesture domain')
        at+=Fraction(1,density_int)
    return tuple(rows)

def _direction_ok(values,direction):
    pairs=list(zip(values,values[1:])); eps=1e-9
    if direction=='rising': return all(b>a+eps for a,b in pairs)
    if direction=='falling': return all(b<a-eps for a,b in pairs)
    if direction=='flat': return all(abs(b-a)<=eps for a,b in pairs)
    return True

def validate_plan(data):
    try: check_json(data)
    except (ValueError,TypeError) as exc: raise GestureError(str(exc)) from exc
    exact(data,{'format','version','id','description','duration_beats','source_family','base_degree','base_gain_db','landing','landmarks','trajectories'},'gesture')
    if data['format']!='zaaggenz-directional-gesture' or data['version']!=VERSION: raise GestureError('unsupported gesture format/version')
    identifier(data['id'],'gesture.id'); identifier(data['source_family'],'source_family')
    if type(data['description'])is not str or not data['description'].strip() or len(data['description'])>1024: raise GestureError('bounded description required')
    try: duration=fraction(data['duration_beats'])
    except (ValueError,TypeError) as exc: raise GestureError(str(exc)) from exc
    if not 0<duration<=64: raise GestureError('duration must be positive and at most 64 beats')
    integer(data['base_degree'],-4096,4096,'base_degree'); number(data['base_gain_db'],EVENT_GAIN_DB_MIN,EVENT_GAIN_DB_MAX,'base_gain_db')
    landing=data['landing']; exact(landing,{'beat','duration_beats','degree','detune_cents','gain_db'},'landing')
    try: landing_at,landing_duration=fraction(landing['beat']),fraction(landing['duration_beats'])
    except (ValueError,TypeError) as exc: raise GestureError(str(exc)) from exc
    if landing_at<=0 or landing_duration<=0 or landing_at+landing_duration!=duration: raise GestureError('landing must be terminal and end exactly at gesture duration')
    integer(landing['degree'],-4096,4096,'landing.degree'); number(landing['detune_cents'],-4800,4800,'landing.detune_cents'); number(landing['gain_db'],EVENT_GAIN_DB_MIN,EVENT_GAIN_DB_MAX,'landing.gain_db')
    landmarks=data['landmarks']
    if type(landmarks)is not list or not 3<=len(landmarks)<=64: raise GestureError('3..64 landmarks required')
    ids=set(); landmark_beats={kind:set() for kind in LANDMARK_KINDS}
    for i,item in enumerate(landmarks):
        exact(item,{'id','beat','kind'},f'landmark[{i}]'); identifier(item['id'],'landmark.id')
        if item['id'] in ids: raise GestureError('duplicate landmark id')
        ids.add(item['id'])
        if item['kind'] not in LANDMARK_KINDS: raise GestureError('unknown landmark kind')
        try: beat=fraction(item['beat'])
        except (ValueError,TypeError) as exc: raise GestureError(str(exc)) from exc
        if not 0<=beat<=duration: raise GestureError('landmark outside gesture span')
        landmark_beats[item['kind']].add(beat)
    if Fraction(0) not in landmark_beats['entry'] or duration not in landmark_beats['endpoint'] or landing_at not in landmark_beats['landing']:
        raise GestureError('entry, landing and endpoint landmarks must match gesture boundaries')
    trajectories=data['trajectories']
    if type(trajectories)is not list or {x.get('axis') for x in trajectories}!=set(AXES): raise GestureError('exactly one trajectory for every required axis')
    turn_boundaries=set()
    for ti,traj in enumerate(trajectories):
        exact(traj,{'axis','unit','interpolation','points','segments'},f'trajectory[{ti}]')
        axis=traj['axis']; unit,lo,hi=AXES[axis]
        if traj['unit']!=unit: raise GestureError(f'{axis}: unit mismatch')
        if traj['interpolation'] not in ('linear','step'): raise GestureError('interpolation must be linear or step')
        if axis in ('onset_density','duration_beats') and traj['interpolation']!='step': raise GestureError(f'{axis}: step interpolation required')
        points=traj['points']
        if type(points)is not list or not 2<=len(points)<=64: raise GestureError('trajectory requires 2..64 points')
        parsed=[]
        for pi,p in enumerate(points):
            exact(p,{'beat','value'},f'point[{pi}]')
            try: beat=fraction(p['beat'])
            except (ValueError,TypeError) as exc: raise GestureError(str(exc)) from exc
            value=number(p['value'],lo,hi,f'{axis}.value')
            if axis=='onset_density' and abs(value-round(value))>1e-9: raise GestureError('onset_density points must be integers')
            parsed.append((beat,value))
        if parsed[0][0]!=0 or parsed[-1][0]!=duration or any(a[0]>=b[0] for a,b in zip(parsed,parsed[1:])): raise GestureError('trajectory points must be strictly ordered from 0 to full duration')
        segments=traj['segments']
        if type(segments)is not list or not 1<=len(segments)<=16: raise GestureError('trajectory requires 1..16 directional segments')
        previous=Fraction(0); boundaries={Fraction(0),duration}
        for si,seg in enumerate(segments):
            exact(seg,{'start_beat','end_beat','direction'},f'segment[{si}]')
            try: start,end=fraction(seg['start_beat']),fraction(seg['end_beat'])
            except (ValueError,TypeError) as exc: raise GestureError(str(exc)) from exc
            if start!=previous or start>=end or end>duration: raise GestureError('directional segments must contiguously cover the gesture')
            if seg['direction'] not in DIRECTIONS: raise GestureError('unknown direction constraint')
            segment_values=[value for beat,value in parsed if start<=beat<=end]
            if len(segment_values)<2 or not _direction_ok(segment_values,seg['direction']): raise GestureError(f'{axis}: points violate {seg["direction"]} direction constraint')
            boundaries.add(end); previous=end
        if previous!=duration: raise GestureError('directional segments must end at gesture duration')
        point_beats={beat for beat,_ in parsed}
        if not boundaries<=point_beats: raise GestureError('every directional segment boundary must be an explicit trajectory point')
        turn_boundaries|={beat for beat in boundaries if beat not in (0,duration)}
    if not turn_boundaries<=landmark_beats['turn']: raise GestureError('every internal directional boundary requires a turn landmark')
    effective_event_gains(data,landing_at)

@dataclass(frozen=True,init=False)
class DirectionalGesture:
    _json:str
    def __init__(self,data):
        validate_plan(data); object.__setattr__(self,'_json',json.dumps(data,sort_keys=True,separators=(',',':'),allow_nan=False))
    def to_dict(self): return loads(self._json)
    @property
    def sha256(self): return digest(self.to_dict())
    @classmethod
    def from_json(cls,text): return cls(loads(text))
