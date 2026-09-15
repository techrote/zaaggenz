"""Adapters into accepted ZG-008 melody and ZG-009 timeline surfaces."""
from __future__ import annotations
from copy import deepcopy
from dataclasses import dataclass
from zaaggenz_contracts import Contract
from zaaggenz_melody import transform_melodic_recipe
from zaaggenz_project import Project
from zaaggenz_timeline import TimelineDocument, default_document
from .model import PhraseRoleError, PhraseRolePlan
from .expand import RoleExpansion, expand_role_plan


@dataclass(frozen=True)
class RoleRenderBundle:
    expansion: RoleExpansion
    timeline: TimelineDocument
    recipe: Contract


def _base_document(base, sample_rate):
    if base is None:
        return default_document(sample_rate)
    if not isinstance(base, TimelineDocument):
        raise PhraseRoleError('base must be a TimelineDocument')
    return base


def _density_map(phrase):
    out = {}
    for gesture in phrase['gestures']:
        curve = next((c for c in gesture['curves'] if c['axis'] == 'density_per_beat'), None)
        if curve is not None:
            out[gesture['id']] = int(round(float(curve['points'][0]['value'])))
    return out


def _render_phrase_for_source(phrase, source_id):
    """Bind authoring source-family labels to the one source allowed by RenderRecipe v1."""
    data = phrase.to_dict()
    data['source_ids'] = [source_id]
    for event in data['events']:
        event['source_id'] = source_id
    return Contract(data)


def plan_to_timeline(plan, base=None, *, sample_rate=48000):
    if not isinstance(plan, PhraseRolePlan):
        raise PhraseRoleError('PhraseRolePlan required')
    document = _base_document(base, sample_rate)
    data = document.to_dict()
    retained_project = deepcopy(data['project'])
    base_recipe = Project.from_document(retained_project).head_recipe.to_dict()
    expansion = expand_role_plan(plan, base_recipe['tuning']['id'])
    phrase = expansion.phrase.to_dict()
    densities = _density_map(phrase)
    notes = []
    for event in phrase['events']:
        notes.append({'id': event['id'], 'beat': event['beat'], 'duration_beats': event['duration_beats'],
                      'degree': None if event['pitch'] is None else event['pitch']['degree'],
                      'detune_cents': 0. if event['pitch'] is None else float(event['pitch']['detune_cents']),
                      'gain_db': float(event['gain_db']), 'muted': False,
                      'roll_density': densities.get(event['gesture_id'], 0)})
    clips = []
    for index, window in enumerate(plan.to_dict()['windows']):
        clips.append({'id': f'role-clip-{index:02d}', 'name': f'{window["role"]}: {window["id"]}',
                      'start_beat': window['start_beat'], 'end_beat': window['end_beat']})
    data.update(name=plan.to_dict()['id'], end_beat=plan.to_dict()['end_beat'], notes=notes,
                clips=clips, next_id=max(data['next_id'], len(notes) + len(clips) + 1))
    data['project'] = retained_project
    timeline = TimelineDocument(data)
    if timeline.to_dict()['project'] != retained_project:
        raise AssertionError('timeline adapter changed the retained project')
    return timeline, expansion


def compile_role_recipe(plan, base=None, *, sample_rate=48000, quality=None, tail_mode=None):
    timeline, expansion = plan_to_timeline(plan, base, sample_rate=sample_rate)
    timeline_data = timeline.to_dict()
    source_recipe = Project.from_document(timeline_data['project']).head_recipe.to_dict()
    render_phrase = _render_phrase_for_source(expansion.phrase, source_recipe['source']['id'])
    try:
        recipe = transform_melodic_recipe(source_recipe, render_phrase, quality=quality, tail_mode=tail_mode,
                                          master_gain_db=timeline_data['master_gain_db'])
    except Exception as exc:
        raise PhraseRoleError('base recipe is incompatible with source-preserving role compilation: '+str(exc)) from exc
    rendered=recipe.to_dict()
    if rendered['source'] != source_recipe['source']:
        raise AssertionError('role compilation changed the retained protected source')
    if source_recipe['render_mode']=='synth' and source_recipe['arrangement'] is None and source_recipe['reversebass'] is None:
        for key in ('nodes','output_node','sculpt'):
            if rendered[key]!=source_recipe[key]:raise AssertionError('role compilation changed protected base topology')
    return RoleRenderBundle(expansion, timeline, recipe)
