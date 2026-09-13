"""Grid alignment, dictionary recommendation, manual correction, and source-independent composition export."""
from __future__ import annotations
from copy import deepcopy
from dataclasses import dataclass
from fractions import Fraction
import math
from zaaggenz_contracts import digest
from zaaggenz_contracts.legacy import envelope
from zaaggenz_contracts.model import fraction
from zaaggenz_contracts.music import beat_to_sample,sample_to_beat
from zaaggenz_melody import note_event,rest_event,make_phrase_plan,make_melodic_recipe
from zaaggenz_project import Project
from zaaggenz_timeline import TimelineDocument,default_document
from zaaggenz_tuning import analyse_frequency,tuning_from_spec,ratio_to_cents
from zaaggenz_textgesture import DictionaryRegistry,starter_registry
from .model import VocalAnalysis,VocalEdit,VocalCaptureError,VERSION

def _rat(q):return f'{q.numerator}/{q.denominator}'
def _nearest_grid(beat,grid):
    q=beat/grid
    n=q.numerator;d=q.denominator;base=n//d;rem=n%d
    if 2*rem<d:k=base
    elif 2*rem>d:k=base+1
    else:k=base if base%2==0 else base+1
    return k*grid

def _recommended_token(segment,dictionary,tuning):
    d=dictionary.to_dict();br=d['brightness_range_hz'];span=max(1.,br['open_hz']-br['closed_hz']);pitch=segment['pitch_hz'];brightness=segment['brightness_hz'];best=None
    for entry in d['entries']:
        m=entry['mapping'];score=0.
        if pitch is not None:
            target=tuning.frequency(d['base_degree']+m['degree_offset'],m['detune_cents']);score+=(ratio_to_cents(max(pitch,1e-9)/target)/350.)**2
        if brightness is not None:
            target=br['closed_hz']+span*m['brightness_fraction'];score+=((brightness-target)/span)**2
        score+=((segment['accent_db']-m['accent_db'])/12.)**2
        candidate=(score,entry['token'])
        if best is None or candidate<best:best=candidate
    return best[1]

def make_edit(analysis,registry=None,dictionary_id='local-soft',base=None,grid_beats='1/4'):
    if not isinstance(analysis,VocalAnalysis):raise VocalCaptureError('VocalAnalysis required')
    registry=starter_registry() if registry is None else registry
    if not isinstance(registry,DictionaryRegistry):raise VocalCaptureError('DictionaryRegistry required')
    dictionary=registry.get(dictionary_id);document=default_document(analysis.to_dict()['source']['sample_rate_hz']) if base is None else base
    if not isinstance(document,TimelineDocument):raise VocalCaptureError('base must be TimelineDocument')
    recipe=Project.from_document(document.to_dict()['project']).head_recipe.to_dict();tm=recipe['time_map'];tuning=tuning_from_spec(recipe['tuning']);grid=fraction(grid_beats)
    rows=[]
    for seg in analysis.to_dict()['segments']:
        beat=sample_to_beat(tm,seg['start_sample']);aligned=_nearest_grid(beat,grid);grid_sample=beat_to_sample(tm,_rat(aligned));token=_recommended_token(seg,dictionary,tuning)
        rows.append({'segment_id':seg['id'],'approved':True,'aligned_beat':_rat(aligned),'alignment_error_samples':seg['start_sample']-grid_sample,'manual_offset_samples':0,
                     'pitch_mode':'estimate' if seg['voicing']=='voiced' else 'unpitched','manual_pitch_hz':None,'manual_brightness_hz':None,'token':token})
    return VocalEdit({'format':'zaaggenz-vocal-edit','version':VERSION,'analysis':analysis.to_dict(),'dictionary_registry_sha256':registry.sha256,'dictionary_id':dictionary_id,
                      'grid_beats':_rat(grid),'time_map':tm,'segments':rows,'source_disposition':'retained-session-local'})

def update_segment(edit,segment_id,**changes):
    if not isinstance(edit,VocalEdit):raise VocalCaptureError('VocalEdit required')
    data=edit.to_dict();allowed={'approved','aligned_beat','manual_offset_samples','pitch_mode','manual_pitch_hz','manual_brightness_hz','token'}
    if set(changes)-allowed:raise VocalCaptureError('unknown edit field')
    for row in data['segments']:
        if row['segment_id']==segment_id:
            row.update(changes);return VocalEdit(data)
    raise VocalCaptureError('unknown segment id')
def mark_source_discarded(edit):
    data=edit.to_dict();data['source_disposition']='discarded';return VocalEdit(data)

@dataclass(frozen=True)
class VocalCompilation:
    phrase:object
    timeline:TimelineDocument
    preview:dict
    automation:dict
    edit_sha256:str
    @property
    def sha256(self):return digest({'phrase':self.phrase.to_dict(),'timeline_revision_id':self.timeline.revision_id,'preview':self.preview,'automation':self.automation,'edit_sha256':self.edit_sha256})

def compile_edit(edit,registry=None,base=None):
    if not isinstance(edit,VocalEdit):raise VocalCaptureError('VocalEdit required')
    registry=starter_registry() if registry is None else registry
    if not isinstance(registry,DictionaryRegistry):raise VocalCaptureError('DictionaryRegistry required')
    if registry.sha256!=edit.to_dict()['dictionary_registry_sha256']:raise VocalCaptureError('dictionary registry identity mismatch')
    data=edit.to_dict();analysis=data['analysis'];dictionary=registry.get(data['dictionary_id']);dd=dictionary.to_dict();sr=analysis['source']['sample_rate_hz']
    document=default_document(sr) if base is None else base
    if not isinstance(document,TimelineDocument):raise VocalCaptureError('base must be TimelineDocument')
    base_data=document.to_dict();source_recipe=Project.from_document(base_data['project']).head_recipe.to_dict();tm=source_recipe['time_map']
    if tm!=data['time_map']:raise VocalCaptureError('edit TimeMap differs from target Compose project')
    tuning=tuning_from_spec(source_recipe['tuning']);segments={s['id']:s for s in analysis['segments']};events=[];gestures=[];notes=[];trace=[];automation=[];max_end=Fraction(0)
    for row in data['segments']:
        seg=segments[row['segment_id']]
        if not row['approved']:continue
        try:mapping=dictionary.mapping(row['token'])
        except KeyError as exc:raise VocalCaptureError(f'token {row["token"]!r} is not in active dictionary') from exc
        aligned_sample=beat_to_sample(tm,row['aligned_beat'])+row['manual_offset_samples'];start_beat=sample_to_beat(tm,aligned_sample)
        end_beat=sample_to_beat(tm,aligned_sample+(seg['end_sample']-seg['start_sample']));duration=end_beat-start_beat
        if start_beat<0 or duration<=0:raise VocalCaptureError('manual timing correction moves segment outside supported phrase')
        pitch=None
        if row['pitch_mode']=='manual':pitch=row['manual_pitch_hz']
        elif row['pitch_mode']=='estimate':pitch=seg['pitch_hz']
        brightness=row['manual_brightness_hz'] if row['manual_brightness_hz'] is not None else seg['brightness_hz']
        gain=float(dd['base_gain_db'])+float(seg['accent_db'])
        if not -120<=gain<=24:raise VocalCaptureError('dictionary base gain + captured accent is outside render range')
        event_id='capture-'+seg['id'];degree=detune=None
        if pitch is None:
            event=rest_event(event_id,_rat(start_beat),_rat(duration))
        else:
            coordinate=analyse_frequency(tuning,pitch);degree=coordinate['degree'];detune=coordinate['detune_cents'];target=tuning.frequency(degree,detune)
            if not 15<=target<=240 or not .25<=target/source_recipe['source']['params']['f0_hz']<=4:raise VocalCaptureError(f'{seg["id"]}: corrected pitch is outside source-preserving render range')
            gesture_id=None;density=int(mapping['density_per_beat'])
            if density>1:
                gesture_id='density-'+event_id
                gestures.append(envelope('GestureSpec',id=gesture_id,duration_beats=_rat(duration),curves=[{'axis':'density_per_beat','unit':'events/beat','interpolation':'step','points':[{'beat':'0/1','value':float(density)}]}]))
            event=note_event(event_id,_rat(start_beat),_rat(duration),tuning.id,degree,detune_cents=detune,gain_db=gain,source_id=source_recipe['source']['id'],gesture_id=gesture_id)
        events.append(event);notes.append({'id':event_id,'beat':_rat(start_beat),'duration_beats':_rat(duration),'degree':degree,'detune_cents':0. if detune is None else detune,'gain_db':gain,'muted':False,'roll_density':mapping['density_per_beat'] if degree is not None else 0})
        br=dd['brightness_range_hz'];fraction_b=None if brightness is None else float(np_clip((brightness-br['closed_hz'])/(br['open_hz']-br['closed_hz']),0,1))
        automation.append({'segment_id':seg['id'],'token':row['token'],'brightness_hz':brightness,'brightness_fraction':fraction_b,
                           'roughness_fraction':mapping['roughness_fraction'],'spectral_occupancy_fraction':mapping['spectral_occupancy_fraction'],'spectral_width_fraction':mapping['spectral_width_fraction'],
                           'apply_mode':'deferred-explicit','protected_topology_rewrite':False})
        trace.append({'segment_id':seg['id'],'event_id':event_id,'token':row['token'],'original_start_sample':seg['start_sample'],'aligned_beat':row['aligned_beat'],'manual_offset_samples':row['manual_offset_samples'],
                      'effective_beat':_rat(start_beat),'pitch_mode':row['pitch_mode'],'pitch_hz':pitch,'pitch_confidence':seg['pitch_confidence'],'degree':degree,'detune_cents':detune,
                      'brightness_hz':brightness,'brightness_confidence':seg['brightness_confidence'],'voicing':seg['voicing'],'compiled_as':'note' if degree is not None else 'unpitched-rest'})
        max_end=max(max_end,end_beat)
    if not events:raise VocalCaptureError('no approved capture segments to compile')
    phrase_end=max(max_end,Fraction(1,64));phrase=make_phrase_plan(tuning.id,events,end_beat=_rat(phrase_end),source_id=source_recipe['source']['id'],gestures=gestures)
    timeline_data=deepcopy(base_data);timeline_data.update(name='Vocal gesture capture',end_beat=_rat(phrase_end),notes=notes,clips=[{'id':'capture-region','name':'Approved vocal gesture','start_beat':'0/1','end_beat':_rat(phrase_end)}],next_id=len(notes)+1)
    timeline=TimelineDocument(timeline_data)
    preview={'format':'zaaggenz-vocal-preview','version':VERSION,'edit_sha256':edit.sha256,'source':analysis['source'],'source_disposition':data['source_disposition'],'dictionary_id':data['dictionary_id'],
             'dictionary_sha256':dictionary.sha256,'tuning':source_recipe['tuning'],'protected_source':source_recipe['source'],'events':trace,'timeline_revision_id':timeline.revision_id,
             'apply_state':'preview-only; timeline export/apply is explicit','unpitched_policy':'abstain-to-rest-unless-manually-corrected'}
    auto={'format':'zaaggenz-vocal-deferred-automation','version':VERSION,'rows':automation,'note':'Capture brightness and dictionary timbral controls are editable evidence; unsupported axes are not silently applied.'}
    return VocalCompilation(phrase,timeline,preview,auto,edit.sha256)

def np_clip(v,lo,hi):return lo if v<lo else hi if v>hi else v

def make_render_recipe(compilation):
    if not isinstance(compilation,VocalCompilation):raise VocalCaptureError('VocalCompilation required')
    base=compilation.timeline.to_dict();source=Project.from_document(base['project']).head_recipe.to_dict()
    recipe=make_melodic_recipe(source['source']['params'],source['time_map'],source['tuning'],compilation.phrase,quality='standard',tail_mode='truncate',master_gain_db=base['master_gain_db'])
    if recipe.to_dict()['source']!=source['source']:raise AssertionError('vocal compilation changed protected source')
    return recipe
