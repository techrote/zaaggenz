"""Versioned, data-only modal grammar; no cultural or perceptual claims."""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from zaaggenz_contracts import digest
from zaaggenz_contracts.model import check_json, fraction, seed_value, loads

VERSION = '1.0.0'
_ID = re.compile(r'[a-z][a-z0-9_.-]{0,63}\Z')


class GrammarError(ValueError):
    """Invalid grammar or an infeasible bounded expansion."""


def fields(value, expected, name):
    if type(value) is not dict or set(value) != set(expected):
        raise GrammarError(f'{name}: expected exactly {", ".join(sorted(expected))}')


def integer(value, low, high, name):
    if type(value) is not int or not low <= value <= high:
        raise GrammarError(f'{name}: integer {low}..{high} required')
    return value


def identifier(value, name):
    if type(value) is not str or not _ID.fullmatch(value):
        raise GrammarError(f'{name}: lowercase identifier required')


def _unique_ints(value, low, high, name, minimum=1, maximum=256):
    if type(value) is not list or not minimum <= len(value) <= maximum:
        raise GrammarError(f'{name}: bounded nonempty list required')
    for item in value:
        integer(item, low, high, name)
    if len(set(value)) != len(value):
        raise GrammarError(f'{name}: duplicate entries')


def validate_grammar(data):
    try:
        check_json(data)
    except ValueError as exc:
        raise GrammarError(str(exc)) from exc
    fields(data, {'format', 'version', 'id', 'description', 'provenance',
                  'period_degrees', 'degrees', 'register', 'ascending_steps',
                  'descending_steps', 'resting_degrees', 'motifs', 'return_path',
                  'boundary'}, 'grammar')
    if data['format'] != 'zaaggenz-modal-grammar' or data['version'] != VERSION:
        raise GrammarError('unsupported modal grammar format/version')
    identifier(data['id'], 'grammar.id')
    if type(data['description']) is not str or not 1 <= len(data['description']) <= 1024:
        raise GrammarError('grammar description required (1..1024 characters)')
    fields(data['provenance'], {'kind', 'source', 'license'}, 'provenance')
    if data['provenance']['kind'] not in ('synthetic', 'source-reviewed'):
        raise GrammarError('provenance.kind must be synthetic or source-reviewed')
    for key in ('source', 'license'):
        value = data['provenance'][key]
        if type(value) is not str or not 1 <= len(value) <= 2048:
            raise GrammarError(f'provenance.{key}: nonempty bounded text required')
    period = integer(data['period_degrees'], 1, 256, 'period_degrees')
    degrees = data['degrees']
    if type(degrees) is not list or not 1 <= len(degrees) <= period:
        raise GrammarError('degrees: one weighted entry per allowed degree')
    for item in degrees:
        fields(item, {'degree', 'weight'}, 'degree hierarchy entry')
        integer(item['degree'], 0, period - 1, 'degree')
        integer(item['weight'], 1, 1024, 'degree weight')
    allowed = [item['degree'] for item in degrees]
    if allowed != sorted(set(allowed)) or allowed[0] != 0:
        raise GrammarError('degrees must be increasing, unique and include tonic 0')
    fields(data['register'], {'minimum', 'maximum'}, 'register')
    low = integer(data['register']['minimum'], -256, 256, 'register.minimum')
    high = integer(data['register']['maximum'], -256, 256, 'register.maximum')
    if not low <= 0 <= high:
        raise GrammarError('register must contain tonic zero')
    for key, sign in (('ascending_steps', 1), ('descending_steps', -1)):
        entries = data[key]
        if type(entries) is not list or not 1 <= len(entries) <= 16:
            raise GrammarError(f'{key}: 1..16 weighted scale-index steps required')
        steps = []
        for entry in entries:
            fields(entry, {'step', 'weight'}, key)
            integer(entry['step'], 1 if sign == 1 else -16, 16 if sign == 1 else -1, key)
            integer(entry['weight'], 1, 1024, key + '.weight')
            steps.append(entry['step'])
        if len(set(steps)) != len(steps):
            raise GrammarError(f'{key}: duplicate steps')
    _unique_ints(data['resting_degrees'], 0, period - 1, 'resting_degrees')
    if not set(data['resting_degrees']) <= set(allowed):
        raise GrammarError('resting degrees must be allowed')
    if data['boundary'] not in ('reflect', 'error'):
        raise GrammarError('boundary must be reflect or error')
    notes = [n for n in range(low, high + 1) if n % period in allowed]
    if len(notes) < 2:
        raise GrammarError('register needs at least two allowed pitches')
    # Directional transitions are never silently replaced by unconstrained leaps.
    for key in ('ascending_steps', 'descending_steps'):
        if not any(abs(item['step']) < len(notes) for item in data[key]):
            raise GrammarError(f'{key}: no transition fits the register')
    path = data['return_path']
    if type(path) is not list or not 1 <= len(path) <= 32:
        raise GrammarError('return_path: 1..32 absolute relative-tonic degrees required')
    for n in path:
        integer(n, low, high, 'return_path degree')
        if n % period not in allowed:
            raise GrammarError('return_path leaves the allowed pitches')
    if path[-1] % period not in data['resting_degrees']:
        raise GrammarError('return_path must land on a resting degree')
    motifs = data['motifs']
    if type(motifs) is not list or len(motifs) > 64:
        raise GrammarError('motifs: at most 64 entries')
    ids = set()
    for motif in motifs:
        fields(motif, {'id', 'kind', 'direction', 'steps', 'weight'}, 'motif')
        identifier(motif['id'], 'motif.id')
        if motif['id'] in ids:
            raise GrammarError('duplicate motif id')
        ids.add(motif['id'])
        if motif['kind'] not in ('motif', 'ornament') or motif['direction'] not in ('up', 'down', 'any'):
            raise GrammarError('invalid motif kind/direction')
        integer(motif['weight'], 1, 1024, 'motif.weight')
        offsets = motif['steps']
        if type(offsets) is not list or not 2 <= len(offsets) <= 32:
            raise GrammarError('motif.steps: 2..32 scale-index offsets required')
        for n in offsets:
            integer(n, -32, 32, 'motif step')
        if offsets[0] != 0 or len(set(offsets)) < 2:
            raise GrammarError('motif starts at zero and must contain movement')
        if max(offsets) - min(offsets) >= len(notes):
            raise GrammarError('motif cannot fit in register')
        if motif['direction'] == 'up' and offsets[-1] < 0 or motif['direction'] == 'down' and offsets[-1] > 0:
            raise GrammarError('motif direction contradicts its endpoint')
        if motif['kind'] == 'ornament' and offsets[-1] != 0:
            raise GrammarError('ornament must return to its entry pitch')


@dataclass(frozen=True, init=False)
class GrammarSpec:
    _json: str

    def __init__(self, data):
        validate_grammar(data)
        object.__setattr__(self, '_json', json.dumps(data, sort_keys=True, allow_nan=False, separators=(',', ':')))

    def to_dict(self):
        return loads(self._json)

    @property
    def sha256(self):
        return digest(self.to_dict())

    @classmethod
    def from_json(cls, text):
        return cls(loads(text))


@dataclass(frozen=True)
class ExpansionRequest:
    event_count: int = 16
    step_beats: str = '1/2'
    start_beat: str = '0/1'
    tonic_degree: int = 0
    seed: str = '0'
    directions: tuple[str, ...] = ('up', 'up', 'down', 'down')
    motif_every: int = 0
    ornament_every: int = 0
    rest_every: int = 0
    gain_db: float = -18.0
    enabled: bool = True

    def __post_init__(self):
        integer(self.event_count, 1, 2048, 'event_count')
        integer(self.tonic_degree, -3840, 3840, 'tonic_degree')
        for key in ('motif_every', 'ornament_every', 'rest_every'):
            integer(getattr(self, key), 0, 2048, key)
        if type(self.enabled) is not bool:
            raise GrammarError('enabled must be boolean')
        if type(self.gain_db) not in (int, float) or not math.isfinite(self.gain_db) or not -120 <= self.gain_db <= 24:
            raise GrammarError('gain_db must be finite dB in -120..24')
        if type(self.directions) not in (list, tuple) or not 1 <= len(self.directions) <= 2048:
            raise GrammarError('directions must be a bounded nonempty cycle')
        if any(d not in ('up', 'down', 'hold') for d in self.directions):
            raise GrammarError('directions must contain up/down/hold')
        object.__setattr__(self, 'directions', tuple(self.directions))
        try:
            step, start = fraction(self.step_beats), fraction(self.start_beat)
            seed_value(self.seed)
        except ValueError as exc:
            raise GrammarError(str(exc)) from exc
        if not 0 < step <= 16 or start < 0:
            raise GrammarError('positive step <=16 beats and nonnegative start required')
        # Preserve the frozen rational contract, including denominator/size limits.
        end = start + self.event_count * step
        fraction(f'{end.numerator}/{end.denominator}')

    def to_dict(self):
        return {**self.__dict__, 'directions': list(self.directions), 'gain_db': float(self.gain_db)}

    @classmethod
    def from_dict(cls, data):
        fields(data, cls.__dataclass_fields__, 'expansion request')
        return cls(**data)
