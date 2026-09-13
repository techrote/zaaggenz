"""Deterministic role expansion with independent placement/content streams."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from zaaggenz_contracts import Contract, digest
from zaaggenz_contracts.legacy import envelope
from zaaggenz_contracts.model import fraction
from zaaggenz_melody import note_event, rest_event
from .model import PhraseRoleError, PhraseRolePlan

_ROLE_MAP = {
    'establish': 'establish', 'repeat': 'repeat', 'reinforce': 'repeat',
    'vary': 'variation', 'tease': 'fakeout', 'turn': 'transition', 'return': 'return'
}


def _rat(value):
    return f'{value.numerator}/{value.denominator}'


def _draw(seed, label, weights):
    total = sum(weights)
    limit = 2**64 - (2**64 % total)
    counter = 0
    while True:
        message = f'zaaggenz.phrase-role-v1\0{seed}\0{label}\0{counter}'
        value = int.from_bytes(hashlib.sha256(message.encode()).digest()[:8], 'big')
        if value < limit:
            value %= total
            break
        counter += 1
    original = value
    for index, weight in enumerate(weights):
        if value < weight:
            return index, original
        value -= weight
    raise AssertionError('weighted choice fell through')


def _prob(weight, weights):
    return float(weight) / float(sum(weights))


def _contract_root(placement_seed, content_seed):
    payload = f'zaaggenz.phrase-role-root-v1\0{placement_seed}\0{content_seed}'.encode()
    return str(int.from_bytes(hashlib.sha256(payload).digest()[:8], 'big'))


@dataclass(frozen=True)
class RoleExpansion:
    phrase: Contract
    plan_sha256: str
    _trace_json: str

    @property
    def trace(self):
        return json.loads(self._trace_json)

    @property
    def sha256(self):
        return digest({'plan_sha256': self.plan_sha256, 'phrase': self.phrase.to_dict(), 'trace': self.trace})


def expand_role_plan(plan, tuning_id):
    if not isinstance(plan, PhraseRolePlan):
        raise PhraseRoleError('PhraseRolePlan required')
    if type(tuning_id) is not str or not tuning_id:
        raise PhraseRoleError('active tuning id required')
    data = plan.to_dict()
    events, gestures, roles, trace = [], [], [], []
    source_ids = set()
    sequence = 0
    streams = []

    def emit(event, beat, source_family):
        nonlocal sequence
        event_id = f'role-{sequence:04d}'
        sequence += 1
        duration = event['duration_beats']
        gesture_id = None
        if event['roll_density'] > 1:
            gesture_id = f'roll-{event_id}'
            gestures.append(envelope('GestureSpec', id=gesture_id, duration_beats=duration, curves=[
                {'axis': 'density_per_beat', 'unit': 'events/beat', 'interpolation': 'step',
                 'points': [{'beat': '0/1', 'value': float(event['roll_density'])}]}
            ]))
        if event['degree'] is None:
            rendered = rest_event(event_id, _rat(beat), duration, source_id=source_family,
                                  gain_db=event['gain_db'], gesture_id=gesture_id)
        else:
            rendered = note_event(event_id, _rat(beat), duration, tuning_id, event['degree'],
                                  detune_cents=event['detune_cents'], gain_db=event['gain_db'],
                                  gesture_id=gesture_id, source_id=source_family)
        source_ids.add(source_family)
        events.append(rendered)
        return event_id

    for window in data['windows']:
        placement_weights = [x['weight'] for x in window['placements']]
        variant_weights = [x['weight'] for x in window['variants']]
        placement_index, placement_draw = _draw(data['placement_seed'], f'{window["id"]}.placement', placement_weights)
        variant_index, content_draw = _draw(data['content_seed'], f'{window["id"]}.content', variant_weights)
        placement = window['placements'][placement_index]
        variant = window['variants'][variant_index]
        placement_offset = fraction(placement['offset'])
        window_start, window_end = fraction(window['start_beat']), fraction(window['end_beat'])
        event_ids = []
        for event in variant['events']:
            beat = window_start + placement_offset + fraction(event['offset'])
            event_ids.append(emit(event, beat, variant['source_family']))
        destination_id = None
        if window['destination'] is not None:
            d = window['destination']
            event = {'duration_beats': d['duration_beats'], 'degree': d['degree'],
                     'detune_cents': d['detune_cents'], 'gain_db': d['gain_db'], 'roll_density': 0}
            destination_id = emit(event, fraction(d['beat']), d['source_family'])
        role_duration = window_end - window_start
        roles.append({'beat': window['start_beat'], 'duration_beats': _rat(role_duration), 'role': _ROLE_MAP[window['role']]})
        pp = _prob(placement['weight'], placement_weights)
        vp = _prob(variant['weight'], variant_weights)
        trace.append({
            'window_id': window['id'], 'role': window['role'],
            'window_start_beat': window['start_beat'], 'window_end_beat': window['end_beat'],
            'placement_offset': placement['offset'], 'placement_choice_index': placement_index,
            'placement_draw': str(placement_draw), 'declared_placement_probability': pp,
            'variant_id': variant['id'], 'source_family': variant['source_family'],
            'content_choice_index': variant_index, 'content_draw': str(content_draw),
            'declared_content_probability': vp, 'joint_generator_probability': pp * vp,
            'event_ids': event_ids, 'destination_event_id': destination_id,
            'destination_beat': None if window['destination'] is None else window['destination']['beat'],
            'generator_semantics': 'engine-choice-probability-not-listener-certainty'
        })
        streams.extend([f'placement.{window["id"]}', f'content.{window["id"]}'])
    events.sort(key=lambda e: (fraction(e['beat']), e['id']))
    roles.sort(key=lambda r: (fraction(r['beat']), r['role']))
    if not source_ids:
        source_ids.add('source')
    phrase = Contract(envelope('PhrasePlan', start_beat='0/1', end_beat=data['end_beat'], tuning_id=tuning_id,
                               source_ids=sorted(source_ids), gestures=gestures, events=events, roles=roles,
                               bass_role='none', random={'algorithm': 'sha256-named-u64-v1',
                                                        'root': _contract_root(data['placement_seed'], data['content_seed']),
                                                        'streams': sorted(set(streams))}))
    return RoleExpansion(phrase, plan.sha256, json.dumps(trace, sort_keys=True, allow_nan=False))
