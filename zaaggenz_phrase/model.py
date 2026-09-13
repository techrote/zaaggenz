"""Versioned phrase-role plans with explicit probability and return semantics."""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
import re
from zaaggenz_contracts import digest
from zaaggenz_contracts.model import check_json, fraction, loads, seed_value

VERSION = '1.0.0'
ROLES = ('establish', 'repeat', 'reinforce', 'vary', 'tease', 'turn', 'return')
_ID = re.compile(r'[a-z][a-z0-9_.-]{0,39}\Z')


class PhraseRoleError(ValueError):
    """Invalid role plan or an infeasible bounded expansion."""


def exact(value, keys, name):
    if type(value) is not dict or set(value) != set(keys):
        raise PhraseRoleError(f'{name}: expected exactly {", ".join(sorted(keys))}')


def integer(value, low, high, name):
    if type(value) is not int or not low <= value <= high:
        raise PhraseRoleError(f'{name}: integer {low}..{high} required')
    return value


def number(value, low, high, name):
    if type(value) not in (int, float) or type(value) is bool or not math.isfinite(float(value)) or not low <= value <= high:
        raise PhraseRoleError(f'{name}: finite number {low}..{high} required')
    return float(value)


def identifier(value, name):
    if type(value) is not str or not _ID.fullmatch(value):
        raise PhraseRoleError(f'{name}: lowercase identifier up to 40 characters required')
    return value


def text(value, name, maximum=1024):
    if type(value) is not str or not value.strip() or len(value) > maximum or any(ord(c) < 32 and c not in '\t' for c in value):
        raise PhraseRoleError(f'{name}: nonempty bounded text required')
    return value


def _event_count(plan):
    total = 0
    for window in plan['windows']:
        total += max(len(v['events']) for v in window['variants'])
        total += int(window['destination'] is not None)
    return total


def validate_plan(plan):
    try:
        check_json(plan)
    except ValueError as exc:
        raise PhraseRoleError(str(exc)) from exc
    exact(plan, {'format', 'version', 'id', 'description', 'end_beat', 'placement_seed', 'content_seed', 'windows'}, 'plan')
    if plan['format'] != 'zaaggenz-phrase-role-plan' or plan['version'] != VERSION:
        raise PhraseRoleError('unsupported phrase-role plan format/version')
    identifier(plan['id'], 'plan.id')
    text(plan['description'], 'plan.description')
    try:
        end = fraction(plan['end_beat'])
        seed_value(plan['placement_seed'])
        seed_value(plan['content_seed'])
    except ValueError as exc:
        raise PhraseRoleError(str(exc)) from exc
    if not 0 < end <= 256:
        raise PhraseRoleError('end_beat must be positive and at most 256 quarter-note beats')
    windows = plan['windows']
    if type(windows) is not list or not 1 <= len(windows) <= 64:
        raise PhraseRoleError('plan requires 1..64 role windows')
    seen = set()
    previous_end = fraction('0/1')
    for wi, window in enumerate(windows):
        exact(window, {'id', 'role', 'start_beat', 'end_beat', 'placements', 'variants', 'destination'}, f'window[{wi}]')
        identifier(window['id'], f'window[{wi}].id')
        if window['id'] in seen:
            raise PhraseRoleError('duplicate role-window id')
        seen.add(window['id'])
        if window['role'] not in ROLES:
            raise PhraseRoleError(f'window {window["id"]}: unsupported phrase role')
        try:
            start, stop = fraction(window['start_beat']), fraction(window['end_beat'])
        except ValueError as exc:
            raise PhraseRoleError(f'window {window["id"]}: {exc}') from exc
        if not previous_end <= start < stop <= end:
            raise PhraseRoleError('role windows must be ordered, non-overlapping and inside the phrase')
        previous_end = stop
        placements = window['placements']
        if type(placements) is not list or not 1 <= len(placements) <= 32:
            raise PhraseRoleError(f'window {window["id"]}: 1..32 placement choices required')
        placement_offsets = []
        for pi, placement in enumerate(placements):
            exact(placement, {'offset', 'weight'}, f'placement[{pi}]')
            try:
                offset = fraction(placement['offset'])
            except ValueError as exc:
                raise PhraseRoleError(str(exc)) from exc
            if offset < 0:
                raise PhraseRoleError('placement offsets are nonnegative')
            integer(placement['weight'], 1, 1024, 'placement.weight')
            placement_offsets.append(offset)
        if len(set(placement_offsets)) != len(placement_offsets):
            raise PhraseRoleError('duplicate placement offsets')
        variants = window['variants']
        if type(variants) is not list or not 1 <= len(variants) <= 32:
            raise PhraseRoleError(f'window {window["id"]}: 1..32 content variants required')
        variant_ids = set()
        window_length = stop - start
        for vi, variant in enumerate(variants):
            exact(variant, {'id', 'weight', 'source_family', 'events'}, f'variant[{vi}]')
            identifier(variant['id'], 'variant.id')
            identifier(variant['source_family'], 'variant.source_family')
            integer(variant['weight'], 1, 1024, 'variant.weight')
            if variant['id'] in variant_ids:
                raise PhraseRoleError('duplicate variant id within role window')
            variant_ids.add(variant['id'])
            events = variant['events']
            if type(events) is not list or len(events) > 64:
                raise PhraseRoleError('variant events must be a list of at most 64 entries')
            if not events and window['role'] not in ('vary', 'tease', 'turn'):
                raise PhraseRoleError('no-fill variants are limited to variation/tease/turn roles')
            for ei, event in enumerate(events):
                exact(event, {'offset', 'duration_beats', 'degree', 'detune_cents', 'gain_db', 'roll_density'}, f'event[{ei}]')
                try:
                    offset, duration = fraction(event['offset']), fraction(event['duration_beats'])
                except ValueError as exc:
                    raise PhraseRoleError(str(exc)) from exc
                if offset < 0 or duration <= 0:
                    raise PhraseRoleError('event offset/duration must be nonnegative/positive')
                if event['degree'] is not None:
                    integer(event['degree'], -4096, 4096, 'event.degree')
                number(event['detune_cents'], -4800, 4800, 'event.detune_cents')
                number(event['gain_db'], -120, 24, 'event.gain_db')
                density = integer(event['roll_density'], 0, 16, 'event.roll_density')
                if density > 1 and math.ceil(float(duration) * density) - 1 > 64:
                    raise PhraseRoleError('roll event exceeds 64 retriggers')
                for placement in placement_offsets:
                    if placement + offset + duration > window_length:
                        raise PhraseRoleError(f'window {window["id"]}: variant {variant["id"]} cannot fit every declared placement')
        destination = window['destination']
        if destination is not None:
            exact(destination, {'beat', 'duration_beats', 'degree', 'detune_cents', 'gain_db', 'source_family'}, 'destination')
            identifier(destination['source_family'], 'destination.source_family')
            integer(destination['degree'], -4096, 4096, 'destination.degree')
            number(destination['detune_cents'], -4800, 4800, 'destination.detune_cents')
            number(destination['gain_db'], -120, 24, 'destination.gain_db')
            try:
                at, duration = fraction(destination['beat']), fraction(destination['duration_beats'])
            except ValueError as exc:
                raise PhraseRoleError(str(exc)) from exc
            if not start <= at < at + duration <= stop:
                raise PhraseRoleError('destination anchor must lie wholly inside its role window')
        if window['role'] == 'return' and destination is None:
            raise PhraseRoleError('return role requires a destination anchor')
    if _event_count(plan) > 256:
        raise PhraseRoleError('worst-case expansion exceeds the accepted 256-event timeline bound')


@dataclass(frozen=True, init=False)
class PhraseRolePlan:
    _json: str

    def __init__(self, data):
        validate_plan(data)
        object.__setattr__(self, '_json', json.dumps(data, sort_keys=True, separators=(',', ':'), allow_nan=False))

    def to_dict(self):
        return loads(self._json)

    @property
    def sha256(self):
        return digest(self.to_dict())

    @classmethod
    def from_json(cls, text_value):
        return cls(loads(text_value))
