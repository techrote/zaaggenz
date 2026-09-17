"""Versioned exact-beat metrical clocks; no tempo estimator or DSP side effects."""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import json
import math
import re
from zaaggenz_contracts import digest
from zaaggenz_contracts.model import check_json, fraction, loads

VERSION = '1.0.0'
KINDS = ('nested', 'cross', 'cycle')
CONTROLS = ('accent_db', 'density_per_beat', 'pitch_cents', 'brightness_hz',
            'roughness_fraction', 'spectral_width_fraction')
LAYERS = ('synthline', 'exciter', 'body', 'aux', 'sub')
_ID = re.compile(r'[a-z][a-z0-9_.-]{0,63}\Z')

# Executable-work limits. 65,536 ticks permits a continuous 64th-note clock
# (1/16 quarter-note beat) over the maximum 4,096-beat plan, while preventing
# compact rational authoring from expanding into unbounded practical work.
MAX_TICKS_PER_CLOCK = 65_536
MAX_TOTAL_TICKS = 131_072
MAX_CONTROL_ROWS = 262_144


class MeterError(ValueError):
    """Invalid metrical authoring state or infeasible clock relation."""


def exact(value, keys, name):
    if type(value) is not dict or set(value) != set(keys):
        raise MeterError(f'{name}: expected exactly {", ".join(sorted(keys))}')


def identifier(value, name):
    if type(value) is not str or not _ID.fullmatch(value):
        raise MeterError(f'{name}: lowercase identifier required')
    return value


def integer(value, low, high, name):
    if type(value) is not int or not low <= value <= high:
        raise MeterError(f'{name}: integer {low}..{high} required')
    return value


def number(value, low, high, name):
    if type(value) not in (int, float) or type(value) is bool or not math.isfinite(float(value)) or not low <= float(value) <= high:
        raise MeterError(f'{name}: finite number {low}..{high} required')
    return float(value)


def text(value, name, maximum=1024):
    if type(value) is not str or not value.strip() or len(value) > maximum:
        raise MeterError(f'{name}: nonempty bounded text required')
    return value


def _canonical_positive_ratio(numerator, denominator, name):
    integer(numerator, 1, 64, name + '.numerator')
    integer(denominator, 1, 64, name + '.denominator')
    value = Fraction(numerator, denominator)
    if value.numerator != numerator or value.denominator != denominator:
        raise MeterError(f'{name}: ratio must be reduced')
    return value


def _power_of_two(value):
    return value > 0 and value & (value - 1) == 0


def _binary_ratio(value):
    return _power_of_two(value.numerator) and _power_of_two(value.denominator)


def _ceil_fraction(value):
    return -((-value.numerator) // value.denominator)


def _clock_tick_count(clock):
    """Return the exact rows generate_ticks() would emit, without iteration."""
    period, phase = fraction(clock['period_beats']), fraction(clock['phase_beats'])
    resets = [fraction(x) for x in clock['reset_beats']]
    count = 0
    for window in clock['active_windows']:
        start, stop = fraction(window['start_beat']), fraction(window['end_beat'])
        interior = [r for r in resets if start < r < stop]
        boundaries = [start, *interior, stop]
        for part in range(len(boundaries) - 1):
            lo, hi = boundaries[part], boundaries[part + 1]
            if part > 0:
                origin = lo
            elif window['reset_on_entry']:
                origin = start
            else:
                earlier = [r for r in resets if r <= start]
                origin = earlier[-1] if earlier else Fraction(0)
            first = origin + phase
            k = max(0, _ceil_fraction((lo - first) / period))
            beat = first + k * period
            if beat < hi:
                count += _ceil_fraction((hi - beat) / period)
    return count


def _work_estimate_data(data, *, enforce=True):
    counts = {}
    total = 0
    for clock in data['clocks']:
        count = _clock_tick_count(clock)
        counts[clock['id']] = count
        if enforce and count > MAX_TICKS_PER_CLOCK:
            raise MeterError(
                f'clock {clock["id"]}: implied tick count {count} exceeds executable limit '
                f'{MAX_TICKS_PER_CLOCK}')
        total += count
    if enforce and total > MAX_TOTAL_TICKS:
        raise MeterError(
            f'plan implied tick count {total} exceeds executable limit {MAX_TOTAL_TICKS}')

    schedule_rows = sum(counts[binding['clock_id']] for binding in data['bindings'])
    if enforce and schedule_rows > MAX_CONTROL_ROWS:
        raise MeterError(
            f'control schedule row count {schedule_rows} exceeds executable limit '
            f'{MAX_CONTROL_ROWS}')
    return {
        'clock_tick_counts': counts,
        'total_ticks': total,
        'control_schedule_rows': schedule_rows,
        'limits': {
            'ticks_per_clock': MAX_TICKS_PER_CLOCK,
            'total_ticks': MAX_TOTAL_TICKS,
            'control_schedule_rows': MAX_CONTROL_ROWS,
        },
    }


def _validate_windows(clock, end):
    windows = clock['active_windows']
    if type(windows) is not list or not 1 <= len(windows) <= 64:
        raise MeterError(f'clock {clock["id"]}: 1..64 active windows required')
    previous = Fraction(0)
    first = True
    for i, window in enumerate(windows):
        exact(window, {'start_beat', 'end_beat', 'reset_on_entry'}, f'active_window[{i}]')
        try:
            start, stop = fraction(window['start_beat']), fraction(window['end_beat'])
        except (ValueError, TypeError) as exc:
            raise MeterError(str(exc)) from exc
        if type(window['reset_on_entry']) is not bool:
            raise MeterError('reset_on_entry must be boolean')
        if start < 0 or start >= stop or stop > end or (not first and start < previous):
            raise MeterError('active windows must be ordered, non-overlapping and inside the plan')
        previous = stop; first = False
    resets = clock['reset_beats']
    if type(resets) is not list or len(resets) > 128:
        raise MeterError('reset_beats must be a bounded list')
    parsed = []
    for value in resets:
        try:
            beat = fraction(value)
        except (ValueError, TypeError) as exc:
            raise MeterError(str(exc)) from exc
        if not 0 <= beat < end:
            raise MeterError('reset beat outside plan')
        parsed.append(beat)
    if parsed != sorted(set(parsed)):
        raise MeterError('reset beats must be strictly increasing and unique')


def _control_bounds(control):
    return {
        'accent_db': (-120., 24.), 'density_per_beat': (0., 64.), 'pitch_cents': (-4800., 4800.),
        'brightness_hz': (0., 96000.), 'roughness_fraction': (0., 1.),
        'spectral_width_fraction': (0., 1.)
    }[control]


def validate_plan(data):
    try:
        check_json(data)
    except (ValueError, TypeError) as exc:
        raise MeterError(str(exc)) from exc
    exact(data, {'format', 'version', 'id', 'description', 'end_beat', 'stable_clock_id', 'clocks', 'bindings'}, 'meter plan')
    if data['format'] != 'zaaggenz-meter-plan' or data['version'] != VERSION:
        raise MeterError('unsupported meter plan format/version')
    identifier(data['id'], 'plan.id'); text(data['description'], 'plan.description')
    try:
        end = fraction(data['end_beat'])
    except (ValueError, TypeError) as exc:
        raise MeterError(str(exc)) from exc
    if not 0 < end <= 4096:
        raise MeterError('end_beat must be positive and at most 4096 quarter-note beats')
    clocks = data['clocks']
    if type(clocks) is not list or not 1 <= len(clocks) <= 64:
        raise MeterError('plan requires 1..64 clocks')
    by_id = {}
    for index, clock in enumerate(clocks):
        exact(clock, {'id', 'kind', 'period_beats', 'phase_beats', 'relation', 'active_windows', 'reset_beats'}, f'clock[{index}]')
        identifier(clock['id'], 'clock.id')
        if clock['id'] in by_id:
            raise MeterError('duplicate clock id')
        if clock['kind'] not in KINDS:
            raise MeterError('clock.kind must be nested, cross or cycle')
        try:
            period, phase = fraction(clock['period_beats']), fraction(clock['phase_beats'])
        except (ValueError, TypeError) as exc:
            raise MeterError(str(exc)) from exc
        if not 0 < period <= end or not 0 <= phase < period:
            raise MeterError('clock period must be positive/in-span and phase must lie in [0, period)')
        _validate_windows(clock, end)
        by_id[clock['id']] = (clock, period, phase)
    identifier(data['stable_clock_id'], 'stable_clock_id')
    if data['stable_clock_id'] not in by_id:
        raise MeterError('stable_clock_id does not name a clock')

    parents = {}
    for clock_id, (clock, period, phase) in by_id.items():
        relation = clock['relation']
        if clock['kind'] == 'cycle':
            if relation is not None:
                raise MeterError(f'clock {clock_id}: cycle clocks are explicitly independent and require relation=null')
            continue
        if clock['kind'] == 'nested' and relation is None:
            continue  # exact-beat root of a nested hierarchy
        if relation is None:
            raise MeterError(f'clock {clock_id}: {clock["kind"]} relation required')
        if clock['kind'] == 'nested':
            exact(relation, {'reference_id', 'period_numerator', 'period_denominator'}, 'nested relation')
            ref = identifier(relation['reference_id'], 'relation.reference_id')
            ratio = _canonical_positive_ratio(relation['period_numerator'], relation['period_denominator'], 'nested relation')
            if ratio.denominator != 1 or ratio.numerator < 1:
                raise MeterError('nested clocks require an integer period multiple of their reference')
        else:
            exact(relation, {'reference_id', 'pulses', 'reference_cycles'}, 'cross relation')
            ref = identifier(relation['reference_id'], 'relation.reference_id')
            pulses = integer(relation['pulses'], 1, 64, 'cross.pulses')
            cycles = integer(relation['reference_cycles'], 1, 64, 'cross.reference_cycles')
            if math.gcd(pulses, cycles) != 1:
                raise MeterError('cross ratio must be reduced')
            if _binary_ratio(Fraction(pulses, cycles)):
                raise MeterError('power-of-two relations belong in nested clocks, not cross clocks')
        if ref == clock_id or ref not in by_id:
            raise MeterError(f'clock {clock_id}: relation reference missing/self-referential')
        parents[clock_id] = ref

    # relation graph must be acyclic.
    for clock_id in by_id:
        seen = set(); here = clock_id
        while here in parents:
            if here in seen:
                raise MeterError('clock relation cycle')
            seen.add(here); here = parents[here]

    for clock_id, ref in parents.items():
        clock, period, phase = by_id[clock_id]
        parent, parent_period, parent_phase = by_id[ref]
        relation = clock['relation']
        if clock['kind'] == 'nested':
            ratio = Fraction(relation['period_numerator'], relation['period_denominator'])
            if period != parent_period * ratio:
                raise MeterError(f'clock {clock_id}: declared nested period disagrees with relation')
            if clock['active_windows'] != parent['active_windows'] or clock['reset_beats'] != parent['reset_beats']:
                raise MeterError('nested clocks must share active/re-entry/reset windows with their reference')
            if (phase - parent_phase) % parent_period != 0:
                raise MeterError('nested clock phase is not aligned to its reference')
        else:
            expected = parent_period * Fraction(relation['reference_cycles'], relation['pulses'])
            if period != expected:
                raise MeterError(f'clock {clock_id}: cross period disagrees with pulses/reference_cycles')

    bindings = data['bindings']
    if type(bindings) is not list or len(bindings) > 128:
        raise MeterError('bindings must be a list of at most 128 control lanes')
    binding_ids = set(); anchor_count = 0
    for index, binding in enumerate(bindings):
        exact(binding, {'id', 'clock_id', 'layer', 'control', 'values', 'stability'}, f'binding[{index}]')
        identifier(binding['id'], 'binding.id')
        if binding['id'] in binding_ids:
            raise MeterError('duplicate binding id')
        binding_ids.add(binding['id'])
        if binding['clock_id'] not in by_id:
            raise MeterError('binding references unknown clock')
        if binding['layer'] not in LAYERS or binding['control'] not in CONTROLS:
            raise MeterError('binding has unsupported layer/control')
        if binding['stability'] not in ('anchor', 'variable'):
            raise MeterError('binding.stability must be anchor or variable')
        if binding['stability'] == 'anchor':
            anchor_count += 1
            if binding['clock_id'] != data['stable_clock_id']:
                raise MeterError('anchor binding must use stable_clock_id')
        values = binding['values']
        if type(values) is not list or not 1 <= len(values) <= 64:
            raise MeterError('binding values require 1..64 entries')
        lo, hi = _control_bounds(binding['control'])
        for value in values:
            number(value, lo, hi, f'binding {binding["id"]}.value')
    if bindings and anchor_count == 0:
        raise MeterError('plans with bindings require at least one explicit stable anchor binding')

    # Exact arithmetic at the authoring boundary prevents tiny valid rationals,
    # reset segmentation or binding fan-out from becoming unbounded execution.
    _work_estimate_data(data, enforce=True)


def work_estimate(plan):
    """Return exact bounded execution cardinalities for scheduler/integration use."""
    if not isinstance(plan, MeterPlan):
        raise MeterError('MeterPlan required')
    return _work_estimate_data(plan.to_dict(), enforce=True)


@dataclass(frozen=True, init=False)
class MeterPlan:
    _json: str

    def __init__(self, data):
        validate_plan(data)
        object.__setattr__(self, '_json', json.dumps(data, allow_nan=False, sort_keys=True, separators=(',', ':')))

    def to_dict(self):
        return loads(self._json)

    @property
    def sha256(self):
        return digest(self.to_dict())

    @classmethod
    def from_json(cls, text_value):
        return cls(loads(text_value))
