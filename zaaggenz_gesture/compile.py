"""Compile directional gestures into source-preserving note events plus explicit deferred automation."""
from __future__ import annotations
from dataclasses import dataclass
from fractions import Fraction
from zaaggenz_contracts import Contract,digest
from zaaggenz_contracts.model import fraction
from zaaggenz_melody import note_event,make_phrase_plan,transform_melodic_recipe
from zaaggenz_project import Project
from zaaggenz_timeline import TimelineDocument,default_document
from .model import DirectionalGesture,GestureError

DEFERRED_AXES={'brightness_hz':('post-shaper','synthline'),
               'roughness_fraction':('post-shaper','synthline'),
               'spectral_occupancy_fraction':('stem-space','synthline'),
               'spectral_width_fraction':('stem-space','synthline')}

def _rat(q): return f'{q.numerator}/{q.denominator}'
def _trajectory(data,axis): return next(t for t in data['trajectories'] if t['axis']==axis)
def _beat_value(v): return Fraction(str(float(v))).limit_denominator(960)

def trajectory_value(trajectory,beat):
    """Evaluate authored control points; step values change at the point itself."""
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

@dataclass(frozen=True)
class GestureCompilation:
    phrase:Contract
    automation:dict
    trace:tuple
    plan_sha256:str
    @property
    def sha256(self): return digest({'plan_sha256':self.plan_sha256,'phrase':self.phrase.to_dict(),'automation':self.automation,'trace':list(self.trace)})

@dataclass(frozen=True)
class GestureRenderBundle:
    compilation:GestureCompilation
    recipe:Contract
    source_project:dict

def compile_gesture(plan,tuning_id,*,source_id='source'):
    if not isinstance(plan,DirectionalGesture): raise GestureError('DirectionalGesture required')
    if type(tuning_id)is not str or not tuning_id: raise GestureError('active tuning id required')
    data=plan.to_dict(); landing=data['landing']; landing_at=fraction(landing['beat'])
    density=_trajectory(data,'onset_density'); accent=_trajectory(data,'accent_db'); durations=_trajectory(data,'duration_beats'); pitch=_trajectory(data,'pitch_cents')
    events=[]; trace=[]; at=Fraction(0); index=0
    while at<landing_at:
        density_value=trajectory_value(density,at); density_int=int(round(density_value))
        if density_int<1 or abs(density_value-density_int)>1e-9: raise GestureError('compiled onset density must be an integer')
        event_duration=_beat_value(trajectory_value(durations,at)); event_duration=min(event_duration,landing_at-at)
        if event_duration<=0: raise GestureError('compiled event duration collapsed')
        cents=trajectory_value(pitch,at); gain=float(data['base_gain_db'])+trajectory_value(accent,at)
        event_id=f'gesture-{index:04d}'
        events.append(note_event(event_id,_rat(at),_rat(event_duration),tuning_id,data['base_degree'],detune_cents=cents,gain_db=gain,source_id=source_id))
        trace.append({'event_id':event_id,'beat':_rat(at),'duration_beats':_rat(event_duration),'pitch_cents':cents,'gain_db':gain,
                      'density_per_beat':density_int,'source_family':data['source_family'],'terminal_landing':False})
        index+=1
        if index>256: raise GestureError('gesture expansion exceeds 256 source-preserving events')
        at+=Fraction(1,density_int)
    events.append(note_event('gesture-landing',landing['beat'],landing['duration_beats'],tuning_id,landing['degree'],
                             detune_cents=landing['detune_cents'],gain_db=landing['gain_db'],source_id=source_id))
    trace.append({'event_id':'gesture-landing','beat':landing['beat'],'duration_beats':landing['duration_beats'],
                  'pitch_cents':landing['detune_cents'],'gain_db':landing['gain_db'],'density_per_beat':None,
                  'source_family':data['source_family'],'terminal_landing':True})
    phrase=make_phrase_plan(tuning_id,events,start_beat='0/1',end_beat=data['duration_beats'],source_id=source_id)
    automation_rows=[]
    for axis,(stage,layer) in DEFERRED_AXES.items():
        traj=_trajectory(data,axis)
        automation_rows.append({'axis':axis,'unit':traj['unit'],'interpolation':traj['interpolation'],'stage':stage,'layer':layer,
                                'points':[dict(p) for p in traj['points']],'apply_mode':'deferred-explicit'})
    automation={'format':'zaaggenz-gesture-automation','version':'1.0.0','plan_sha256':plan.sha256,
                'protected_topology_rewrite':False,'rows':automation_rows,
                'note':'Deferred rows require an explicit compatible graph/stem consumer; source-preserving render does not apply them silently.'}
    return GestureCompilation(phrase,automation,tuple(trace),plan.sha256)

def compile_gesture_recipe(plan,base=None,*,sample_rate=48000,quality=None,tail_mode=None):
    document=default_document(sample_rate) if base is None else base
    if not isinstance(document,TimelineDocument): raise GestureError('base must be a TimelineDocument')
    document_data=document.to_dict();project=document_data['project'];source_recipe=Project.from_document(project).head_recipe.to_dict()
    compilation=compile_gesture(plan,source_recipe['tuning']['id'],source_id=source_recipe['source']['id'])
    try:
        recipe=transform_melodic_recipe(source_recipe,compilation.phrase,quality=quality,tail_mode=tail_mode,
                                        master_gain_db=document_data['master_gain_db'])
    except Exception as exc:raise GestureError('base recipe is incompatible with source-preserving gesture compilation: '+str(exc)) from exc
    rendered=recipe.to_dict()
    if rendered['source']!=source_recipe['source']: raise AssertionError('gesture compilation changed protected source')
    if source_recipe['render_mode']=='synth' and source_recipe['arrangement'] is None and source_recipe['reversebass'] is None:
        for key in ('nodes','output_node','sculpt'):
            if rendered[key]!=source_recipe[key]:raise AssertionError('gesture compilation changed protected base topology')
    return GestureRenderBundle(compilation,recipe,project)
