"""Compile safe mnemonic text into previewable gesture, PhrasePlan and ZG-009 timeline state."""
from __future__ import annotations
from dataclasses import dataclass
from fractions import Fraction
import math
from zaaggenz_contracts import Contract,digest
from zaaggenz_contracts.legacy import envelope
from zaaggenz_contracts.model import fraction
from zaaggenz_melody import note_event,make_phrase_plan,make_melodic_recipe
from zaaggenz_project import Project
from zaaggenz_timeline import TimelineDocument,default_document
from zaaggenz_tuning import tuning_from_spec
from zaaggenz_gesture import DirectionalGesture
from .model import DictionaryRegistry,MnemonicDictionary,TextGestureError
from .syntax import TextSyntaxError,parse_text,semantic_ast,MODIFIER_UNITS

def _rat(v):return f'{v.numerator}/{v.denominator}'
def _span_error(text,item,message):
    s=item['span'];raise TextSyntaxError(text,s['start'],message)
def _merge(mapping,mods):
    out=dict(mapping)
    if 'd' in mods:out['duration_beats']=mods['d']
    if 'a' in mods:out['accent_db']=float(out['accent_db'])+float(mods['a'])
    if 'p' in mods:out['degree_offset']=int(out['degree_offset'])+int(mods['p'])
    if 'c' in mods:out['detune_cents']=float(out['detune_cents'])+float(mods['c'])
    for key,field in (('b','brightness_fraction'),('r','roughness_fraction'),('o','spectral_occupancy_fraction'),('w','spectral_width_fraction')):
        if key in mods:out[field]=float(mods[key])
    if 'n' in mods:out['density_per_beat']=int(mods['n'])
    return out
def _direction(a,b):
    if b>a+1e-9:return 'rising'
    if b<a-1e-9:return 'falling'
    return 'flat'
def _trajectory(axis,unit,points,step=False):
    return {'axis':axis,'unit':unit,'interpolation':'step' if step else 'linear','points':[{'beat':beat,'value':value} for beat,value in points],
            'segments':[{'start_beat':points[i][0],'end_beat':points[i+1][0],'direction':_direction(float(points[i][1]),float(points[i+1][1]))} for i in range(len(points)-1)]}

@dataclass(frozen=True)
class TextCompilation:
    ast:dict
    gesture:DirectionalGesture
    phrase:Contract
    timeline:TimelineDocument
    preview:dict
    dictionary_sha256:str
    @property
    def sha256(self):return digest({'ast':semantic_ast(self.ast),'gesture':self.gesture.to_dict(),'phrase':self.phrase.to_dict(),'timeline_revision_id':self.timeline.revision_id,'preview':self.preview,'dictionary_sha256':self.dictionary_sha256})

def compile_text(text,registry,dictionary_id,base=None,*,sample_rate=48000):
    if not isinstance(registry,DictionaryRegistry):raise TextGestureError('DictionaryRegistry required')
    dictionary=registry.get(dictionary_id);ddata=dictionary.to_dict();ast=parse_text(text)
    document=default_document(sample_rate) if base is None else base
    if not isinstance(document,TimelineDocument):raise TextGestureError('base must be a TimelineDocument')
    base_data=document.to_dict();source_recipe=Project.from_document(base_data['project']).head_recipe.to_dict();tuning=tuning_from_spec(source_recipe['tuning'])
    source_id=source_recipe['source']['id'];source_hz=float(source_recipe['source']['params']['f0_hz']);base_degree=int(ddata['base_degree']);base_hz=tuning.frequency(base_degree)
    current=Fraction(0);group_index=0;group_start=Fraction(0);groups=[];events=[];last_event=None;return_event=None
    for item in ast['items']:
        if item['kind']=='group':
            groups.append({'index':group_index,'start_beat':_rat(group_start),'end_beat':_rat(current)});group_index+=1;group_start=current;continue
        if item['kind']=='hold':
            if last_event is None:_span_error(text,item,'hold has no preceding compiled event')
            hold=fraction(item['duration_beats']);last_event['duration']=last_event['duration']+hold;last_event['holds'].append(item['duration_beats']);current+=hold;continue
        if item['kind']=='token':
            try:mapping=dictionary.mapping(item['token'])
            except KeyError:_span_error(text,item,f'token {item["token"]!r} is not defined by dictionary {dictionary_id!r}')
            resolved=_merge(mapping,item['modifiers']);token=item['token'];terminal=False
        else:
            resolved=_merge(ddata['return_mapping'],item['modifiers']);token='@return';terminal=True
        duration=fraction(resolved['duration_beats']);degree=base_degree+int(resolved['degree_offset']);detune=float(resolved['detune_cents']);target_hz=tuning.frequency(degree,detune)
        if not 15<=target_hz<=240 or not .25<=target_hz/source_hz<=4:_span_error(text,item,f'target {target_hz:.3f} Hz is outside the source-preserving renderer range')
        gain=float(ddata['base_gain_db'])+float(resolved['accent_db'])
        if not -120<=gain<=24:_span_error(text,item,'base gain + accent lies outside -120..24 dB')
        event={'id':f'text-{len(events):04d}','token':token,'group_index':group_index,'beat':current,'duration':duration,'degree':degree,'detune_cents':detune,'gain_db':gain,
               'accent_db':float(resolved['accent_db']),'brightness_fraction':float(resolved['brightness_fraction']),'roughness_fraction':float(resolved['roughness_fraction']),
               'spectral_occupancy_fraction':float(resolved['spectral_occupancy_fraction']),'spectral_width_fraction':float(resolved['spectral_width_fraction']),
               'density_per_beat':int(resolved['density_per_beat']),'target_hz':target_hz,'span':dict(item['span']),'holds':[],'terminal_return':terminal}
        events.append(event);last_event=event;current+=duration
        if terminal:return_event=event
    groups.append({'index':group_index,'start_beat':_rat(group_start),'end_beat':_rat(current)})
    if return_event is None or return_event is not events[-1]:raise TextGestureError('terminal return compilation invariant failed')
    landing_at=return_event['beat'];end=current
    if landing_at<=0:raise TextGestureError('at least one syllable event must precede @return')
    if len(events)>128:raise TextGestureError('compiled text exceeds 128 events')

    gestures=[];phrase_events=[]
    for event in events:
        gesture_id=None
        if event['density_per_beat']>1 and not event['terminal_return']:
            gesture_id='density-'+event['id'];gestures.append(envelope('GestureSpec',id=gesture_id,duration_beats=_rat(event['duration']),curves=[
                {'axis':'density_per_beat','unit':'events/beat','interpolation':'step','points':[{'beat':'0/1','value':float(event['density_per_beat'])}]}]))
        phrase_events.append(note_event(event['id'],_rat(event['beat']),_rat(event['duration']),source_recipe['tuning']['id'],event['degree'],
                                        detune_cents=event['detune_cents'],gain_db=event['gain_db'],gesture_id=gesture_id,source_id=source_id))
    phrase=make_phrase_plan(source_recipe['tuning']['id'],phrase_events,start_beat='0/1',end_beat=_rat(end),gestures=gestures,source_id=source_id)

    br=ddata['brightness_range_hz'];brightness=lambda f:float(br['closed_hz'])+(float(br['open_hz'])-float(br['closed_hz']))*f
    point_events=list(events)
    curve_points=[]
    for event in point_events:
        pitch_cents=1200*math.log2(event['target_hz']/base_hz)
        if not -1200<=pitch_cents<=1200:_span_error(text,{'span':event['span']},'pitch contour exceeds the ZG-027 ±1200-cent gesture bound')
        curve_points.append((event['beat'],event,pitch_cents))
    last=return_event;curve_points.append((end,last,1200*math.log2(last['target_hz']/base_hz)))
    if any(a[0]>=b[0] for a,b in zip(curve_points,curve_points[1:])):raise TextGestureError('gesture curve points are not strictly ordered')
    def points(field,convert=lambda x:x):return [(_rat(beat),convert(event[field])) for beat,event,_ in curve_points]
    trajectories=[
        _trajectory('onset_density','events/beat',points('density_per_beat',int),True),
        _trajectory('accent_db','dB',points('accent_db',float)),
        _trajectory('duration_beats','beats',[(_rat(beat),float(event['duration'])) for beat,event,_ in curve_points],True),
        _trajectory('pitch_cents','cents',[(_rat(beat),pc) for beat,_,pc in curve_points]),
        _trajectory('brightness_hz','Hz',points('brightness_fraction',brightness)),
        _trajectory('roughness_fraction','ratio',points('roughness_fraction',float)),
        _trajectory('spectral_occupancy_fraction','ratio',points('spectral_occupancy_fraction',float)),
        _trajectory('spectral_width_fraction','ratio',points('spectral_width_fraction',float))]
    landmark_beats={Fraction(0):'entry',landing_at:'landing',end:'endpoint'}
    landmarks=[{'id':'entry','beat':'0/1','kind':'entry'}]
    internal=sorted({beat for beat,_,_ in curve_points[1:-1]})
    for index,beat in enumerate(internal):landmarks.append({'id':f'turn-{index:03d}','beat':_rat(beat),'kind':'turn'})
    landmarks.append({'id':'landing','beat':_rat(landing_at),'kind':'landing'})
    landmarks.append({'id':'endpoint','beat':_rat(end),'kind':'endpoint'})
    gesture=DirectionalGesture({'format':'zaaggenz-directional-gesture','version':'1.0.0','id':'text-'+digest({'dictionary':dictionary.sha256,'text':text})[:16],
        'description':f'Compiled safe text gesture using project-local dictionary {dictionary_id}; mnemonic tokens make no universal acoustic claim.',
        'duration_beats':_rat(end),'source_family':dictionary_id,'base_degree':base_degree,'base_gain_db':float(ddata['base_gain_db']),
        'landing':{'beat':_rat(landing_at),'duration_beats':_rat(return_event['duration']),'degree':return_event['degree'],'detune_cents':return_event['detune_cents'],'gain_db':return_event['gain_db']},
        'landmarks':landmarks,'trajectories':trajectories})

    timeline_data=base_data;timeline_notes=[]
    for event in events:
        timeline_notes.append({'id':event['id'],'beat':_rat(event['beat']),'duration_beats':_rat(event['duration']),'degree':event['degree'],'detune_cents':event['detune_cents'],
                               'gain_db':event['gain_db'],'muted':False,'roll_density':0 if event['terminal_return'] else event['density_per_beat']})
    timeline_data['name']=f'text gesture · {dictionary_id}'[:80];timeline_data['end_beat']=_rat(end);timeline_data['notes']=timeline_notes
    timeline_data['clips']=[{'id':f'text-group-{g["index"]:02d}','name':f'text group {g["index"]+1}','start_beat':g['start_beat'],'end_beat':g['end_beat']} for g in groups if fraction(g['start_beat'])<fraction(g['end_beat'])]
    timeline_data['next_id']=max(int(timeline_data['next_id']),len(timeline_notes)+len(timeline_data['clips'])+1);timeline=TimelineDocument(timeline_data)
    preview={'format':'zaaggenz-text-gesture-preview','version':'1.0.0','dictionary_id':dictionary_id,'dictionary_sha256':dictionary.sha256,
             'active_tuning_id':source_recipe['tuning']['id'],'active_tuning':source_recipe['tuning'],'base_degree':base_degree,'base_frequency_hz':base_hz,
             'source_id':source_id,'source_frequency_hz':source_hz,'modifier_units':dict(MODIFIER_UNITS),'groups':groups,
             'events':[{'id':e['id'],'token':e['token'],'group_index':e['group_index'],'beat':_rat(e['beat']),'duration_beats':_rat(e['duration']),'degree':e['degree'],'detune_cents':e['detune_cents'],
                        'gain_db':e['gain_db'],'density_per_beat':e['density_per_beat'],'brightness_fraction':e['brightness_fraction'],'target_hz':e['target_hz'],
                        'terminal_return':e['terminal_return'],'source_span':e['span'],'holds':list(e['holds'])} for e in events],
             'gesture':gesture.to_dict(),'phrase_sha256':phrase.sha256,'timeline_revision_id':timeline.revision_id,
             'apply_state':'preview-only; export/apply is explicit'}
    return TextCompilation(ast,gesture,phrase,timeline,preview,dictionary.sha256)

def make_render_recipe(compilation):
    if not isinstance(compilation,TextCompilation):raise TextGestureError('TextCompilation required')
    base=compilation.timeline.to_dict();source_recipe=Project.from_document(base['project']).head_recipe.to_dict()
    recipe=make_melodic_recipe(source_recipe['source']['params'],source_recipe['time_map'],source_recipe['tuning'],compilation.phrase,
                               quality='standard',tail_mode='truncate',master_gain_db=base['master_gain_db'])
    if recipe.to_dict()['source']!=source_recipe['source']:raise AssertionError('text gesture changed protected source')
    return recipe
