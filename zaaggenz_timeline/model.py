"""Bounded timeline authoring snapshots, independent of frozen contract formats."""
from __future__ import annotations
from copy import deepcopy
from dataclasses import dataclass
import json
import math
import re
from zaaggenz_contracts import Contract, digest, validate
from zaaggenz_contracts.legacy import envelope, freeze_legacy
from zaaggenz_contracts.model import check_json, fraction, loads
from zaaggenz_contracts.music import beat_to_sample
from zaaggenz_melody import make_phrase_plan, make_melodic_recipe, note_event, rest_event
from zaaggenz_project import Project
from zaaggenz_tuning import tuning_from_spec

VERSION = '1.0.0'
OWNERSHIP = {'synthline': 'complete-source-derived-notes', 'exciter': 'source-derived-roll-slices',
             'body': 'retained-legacy-project', 'aux': 'retained-legacy-project', 'sub': 'retained-legacy-project'}
MAX_NOTES = 256


class TimelineError(ValueError):
    pass


def exact(value, keys, name):
    if type(value) is not dict or set(value) != set(keys):
        raise TimelineError(f'{name}: missing or unknown fields')


def number(value, low, high, name, integer=False):
    if type(value) not in ((int,) if integer else (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise TimelineError(f'{name}: expected {low}..{high}' + (' integer' if integer else ''))


def rat(value):
    return f'{value.numerator}/{value.denominator}'


def text(value, name, maximum=80):
    if type(value) is not str or not value.strip() or len(value) > maximum or any(ord(c) < 32 for c in value):
        raise TimelineError(f'{name}: nonempty text up to {maximum} characters required')


@dataclass(frozen=True, init=False)
class TimelineDocument:
    _json: str

    def __init__(self, data):
        check_json(data)
        exact(data, {'format', 'version', 'name', 'project', 'end_beat', 'notes', 'clips',
                     'next_id', 'layer_ownership', 'master_gain_db'}, 'timeline')
        if data['format'] != 'zaaggenz-timeline' or data['version'] != VERSION:
            raise TimelineError('unsupported timeline format/version')
        text(data['name'], 'name')
        number(data['next_id'], 0, 1_000_000, 'next_id', integer=True)
        number(data['master_gain_db'], -120, 24, 'master_gain_db')
        if data['layer_ownership'] != OWNERSHIP:
            raise TimelineError('layer ownership cannot be silently reassigned')
        base = Project.from_document(data['project']).head_recipe.to_dict()
        if base['source']['method'] != 'legacy.synth.1.2.1':
            raise TimelineError('unsupported source; retained project must have a legacy synth source')
        end = fraction(data['end_beat'])
        if not 0 < end <= 256:
            raise TimelineError('timeline length must be positive and at most 256 quarter-note beats')
        notes = data['notes']
        if type(notes) is not list or len(notes) > MAX_NOTES:
            raise TimelineError(f'at most {MAX_NOTES} note/rest objects')
        ids = set()
        for row in notes:
            exact(row, {'id', 'beat', 'duration_beats', 'degree', 'detune_cents', 'gain_db', 'muted', 'roll_density'}, 'note')
            text(row['id'], 'note.id', 59)
            if not re.fullmatch(r'[A-Za-z0-9_.-]+', row['id']) or row['id'] in ids:
                raise TimelineError('invalid or duplicate note id')
            ids.add(row['id'])
            start, duration = fraction(row['beat']), fraction(row['duration_beats'])
            if start < 0 or duration <= 0 or start + duration > end:
                raise TimelineError('note/rest lies outside the timeline')
            if row['degree'] is not None:
                number(row['degree'], -4096, 4096, 'degree', integer=True)
            number(row['detune_cents'], -4800, 4800, 'detune_cents')
            number(row['gain_db'], -120, 24, 'gain_db')
            number(row['roll_density'], 0, 16, 'roll_density', integer=True)
            if row['roll_density'] > 1 and math.ceil(duration * row['roll_density']) - 1 > 64:
                raise TimelineError('roll exceeds 64 retriggers; split into shorter events')
            if type(row['muted']) is not bool:
                raise TimelineError('muted must be boolean')
        if sum(bool(r['roll_density']) for r in notes) > 128:
            raise TimelineError('at most 128 roll gestures')
        clips = data['clips']
        if type(clips) is not list or len(clips) > 128:
            raise TimelineError('at most 128 named phrase regions')
        ids = set()
        for clip in clips:
            exact(clip, {'id', 'name', 'start_beat', 'end_beat'}, 'clip')
            text(clip['id'], 'clip.id', 64)
            text(clip['name'], 'clip.name')
            if clip['id'] in ids:
                raise TimelineError('duplicate clip id')
            ids.add(clip['id'])
            if not 0 <= fraction(clip['start_beat']) < fraction(clip['end_beat']) <= end:
                raise TimelineError('clip lies outside timeline')
        object.__setattr__(self, '_json', json.dumps(data, sort_keys=True, allow_nan=False, separators=(',', ':')))

    def to_dict(self):
        return loads(self._json)

    @property
    def revision_id(self):
        return digest({'domain': 'zaaggenz.timeline-revision-v1', 'document': self.to_dict()})

    @classmethod
    def from_json(cls, value):
        return cls(loads(value))


def default_document(sample_rate=48000):
    from uptempo_harmony.synth import PRESETS
    from uptempo_harmony.arrangement import make_arrangement_template
    from uptempo_harmony.reversebass import REVERSEBASS_PRESETS
    from uptempo_harmony.multiband import SCULPT_PRESETS
    params = {**PRESETS['locked_bloom'].to_dict(), 'sr': sample_rate, 'bpm': 200., 'beats': 1}
    # Preserve all mature layer settings, not just an exciter or a reconstructed preset.
    legacy = freeze_legacy(params, mode='arrange_bass',
                           arrangement=make_arrangement_template('flat_test', bpm=200., bars=4, seed=1337).to_dict(),
                           reversebass=REVERSEBASS_PRESETS['layered_reverse'].to_dict(),
                           sculpt=SCULPT_PRESETS['gentle_separation'].to_dict())
    return TimelineDocument({'format': 'zaaggenz-timeline', 'version': VERSION, 'name': 'Untitled melody',
                             'project': Project(legacy).to_document(), 'end_beat': '16/1', 'notes': [], 'clips': [],
                             'next_id': 0, 'layer_ownership': deepcopy(OWNERSHIP), 'master_gain_db': 0.})


def compile_recipe(document):
    """Compile only the explicitly declared melody branch; retain the full legacy project."""
    if not isinstance(document, TimelineDocument):
        raise TimelineError('TimelineDocument required')
    data = document.to_dict()
    base = Project.from_document(data['project']).head_recipe.to_dict()
    events, gestures = [], []
    tuning = tuning_from_spec(base['tuning'])
    for row in sorted(data['notes'], key=lambda r: (fraction(r['beat']), r['id'])):
        silent = row['muted'] or row['degree'] is None
        gid = None
        if row['roll_density'] and not silent:
            gid = 'roll-' + row['id']
            gestures.append(envelope('GestureSpec', id=gid, duration_beats=row['duration_beats'], curves=[
                {'axis': 'density_per_beat', 'unit': 'events/beat', 'interpolation': 'step',
                 'points': [{'beat': '0/1', 'value': float(row['roll_density'])}]}]))
        if silent:
            event = rest_event(row['id'], row['beat'], row['duration_beats'])
        else:
            hz = tuning.frequency(row['degree'], row['detune_cents'])
            if not 15 <= hz <= 240 or not .25 <= hz / base['source']['params']['f0_hz'] <= 4:
                raise TimelineError(f"note {row['id']}: target outside the source-derived renderer's range")
            event = note_event(row['id'], row['beat'], row['duration_beats'], tuning.id, row['degree'],
                               detune_cents=row['detune_cents'], gain_db=row['gain_db'], gesture_id=gid)
        events.append(event)
    phrase = make_phrase_plan(tuning.id, events, end_beat=data['end_beat'], gestures=gestures)
    return make_melodic_recipe(base['source']['params'], base['time_map'], base['tuning'], phrase,
                               quality='standard', tail_mode='truncate', master_gain_db=data['master_gain_db'])


def render_region(recipe, region):
    end = recipe.to_dict()['phrase']['end_beat']
    if region is None:
        return {'start_beat': '0/1', 'end_beat': end}
    exact(region, {'start_beat', 'end_beat'}, 'render region')
    if not 0 <= fraction(region['start_beat']) < fraction(region['end_beat']) <= fraction(end):
        raise TimelineError('render region lies outside timeline')
    return deepcopy(region)


def memory_estimate(recipe):
    d = recipe.to_dict()
    tm, p = d['time_map'], d['source']['params']
    frames = beat_to_sample(tm, d['phrase']['end_beat']) - beat_to_sample(tm, '0/1')
    if frames / tm['sample_rate_hz'] > 60:
        raise TimelineError('render exceeds the 60-second timeline limit; shorten the phrase or raise tempo')
    source = math.ceil(p['sr'] * 60 / p['bpm'] * p['beat_fill'])
    return 16 * 1024**2 + (frames + source) * 96 + source * 512


def describe(document):
    base = Project.from_document(document.to_dict()['project']).head_recipe.to_dict()
    tuning = tuning_from_spec(base['tuning'])
    return {'revision_id': document.revision_id, 'source_hz': base['source']['params']['f0_hz'],
            'tuning': base['tuning'], 'time_map': base['time_map'], 'layer_ownership': deepcopy(OWNERSHIP),
            'targets': {r['id']: None if r['degree'] is None else tuning.frequency(r['degree'], r['detune_cents'])
                        for r in document.to_dict()['notes']}}
