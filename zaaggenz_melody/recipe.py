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

def _check_graph_topology(d):
    """Preflight graph identity/connectivity without executing user audio."""
    nodes=d['nodes'];source=d['source']['id'];output=d['output_node']
    if not nodes:
        if output!=source:raise MelodyError('base recipe has an output node without an explicit DSP graph')
        return
    by={n['id']:n for n in nodes}
    if len(by)!=len(nodes) or source in by:raise MelodyError('base recipe has invalid DSP node identity')
    if output not in by:raise MelodyError('base recipe DSP output node is missing')
    all_ids=set(by)|{source}
    from zaaggenz_contracts.registry import node_definition
    for node in nodes:
        if node['channels']!=d['channels']:raise MelodyError('base DSP node channel count disagrees with recipe')
        if not set(node['inputs'])<=all_ids:raise MelodyError('base recipe DSP graph has a dangling input')
        try:definition=node_definition(node['type_id'])
        except Exception as exc:raise MelodyError('base recipe contains an unknown DSP node type') from exc
        if definition.get('availability')!='executable':raise MelodyError('base recipe contains a non-executable DSP node type')
    visiting=set();done=set()
    def visit(key):
        if key==source or key in done:return
        if key in visiting:raise MelodyError('base recipe DSP graph contains a cycle')
        visiting.add(key)
        for parent in by[key]['inputs']:visit(parent)
        visiting.remove(key);done.add(key)
    visit(output)
    if done!=set(by):raise MelodyError('base recipe DSP graph contains disconnected nodes')

def transform_melodic_recipe(base_recipe,phrase,*,mode=NoteMode.SOURCE_DERIVED,quality=None,tail_mode=None,master_gain_db=None):
    """Replace only melody-owned intent while retaining compatible base render semantics.

    Legacy arrangement/bass recipes are projected to their SYNTHLINE source branch; the full
    project remains retained by TimelineDocument.  Explicit DSP topology is only inherited
    when the base itself is an unambiguous synth recipe.  Ambiguous full-mix topology fails
    rather than being silently rebound to the melodic branch.
    """
    try:mode=NoteMode(mode)
    except ValueError as exc:raise MelodyError('unknown note render mode') from exc
    try:
        d=deepcopy(base_recipe.to_dict() if isinstance(base_recipe,Contract) else base_recipe);validate(d,'RenderRecipe')
        ph=deepcopy(phrase.to_dict() if isinstance(phrase,Contract) else phrase);validate(ph,'PhrasePlan')
    except Exception as exc:raise MelodyError('valid base RenderRecipe and PhrasePlan required') from exc
    if d['channels']!=1:raise MelodyError('source-preserving melodic base must be mono in v1')
    source_id=d['source']['id']
    if ph['tuning_id']!=d['tuning']['id']:raise MelodyError('phrase tuning differs from base recipe tuning')
    if set(ph['source_ids'])!={source_id} or any(e['source_id']!=source_id for e in ph['events']):
        raise MelodyError('phrase source identity differs from base protected source')
    synth_base=d['render_mode']=='synth' and d['arrangement'] is None and d['reversebass'] is None
    if synth_base:
        if d['sculpt'] is not None and d['nodes']:
            raise MelodyError('base synth recipe combines legacy SCULPT and explicit DSP graph without a declared order')
        _check_graph_topology(d)
    else:
        if d['nodes'] or d['output_node']!=source_id:
            raise MelodyError('explicit DSP topology on a non-synth base has ambiguous layer ownership; migrate it to the synth branch before melody compilation')
        # Arrangement/reversebass/legacy full-mix SCULPT remain in the retained project.  Applying
        # them to SYNTHLINE here would create a new audible default and duplicate layer ownership.
        d['nodes']=[];d['output_node']=source_id;d['sculpt']=None
    d['render_mode']='synth';d['arrangement']=None;d['reversebass']=None;d['phrase']=ph;d['phase_policy']=mode.phase_policy
    if quality is None:
        if d['quality']=='legacy':d['quality']='standard'
    else:
        if quality not in ('standard','high'):raise MelodyError('melodic quality must be standard or high')
        d['quality']=quality
    if tail_mode is None:
        if d['tail']['mode']=='legacy':d['tail']={'mode':'truncate','maximum_samples':0}
    else:
        if tail_mode not in ('preserve','truncate'):raise MelodyError('melodic tail mode must be preserve or truncate')
        d['tail']['mode']=tail_mode
    if d['quality'] not in ('standard','high') or d['tail']['mode'] not in ('preserve','truncate'):
        raise MelodyError('base quality/tail policy is incompatible with melodic execution')
    if master_gain_db is not None:d['output']['master_gain_db']=_number(master_gain_db,'master_gain_db')
    try:return Contract(d)
    except Exception as exc:raise MelodyError('base-preserving melodic transformation violates shared contract') from exc
