"""Exact beat-domain clock expansion and frozen-TimeMap sample mapping."""
from __future__ import annotations
from fractions import Fraction
from zaaggenz_contracts import Contract
from zaaggenz_contracts.model import fraction
from zaaggenz_contracts.music import beat_to_sample, beat_to_seconds
from zaaggenz_contracts.validation import validate
from .model import MeterError, MeterPlan


def _rat(value):
    return f'{value.numerator}/{value.denominator}'


def _time_map_dict(time_map):
    data = time_map.to_dict() if isinstance(time_map, Contract) else time_map
    try:
        validate(data, 'TimeMap')
    except (ValueError, TypeError) as exc:
        raise MeterError('valid TimeMap required') from exc
    return data


def _ceil_fraction(value):
    return -((-value.numerator) // value.denominator)


def _clock(plan, clock_id):
    if not isinstance(plan, MeterPlan):
        raise MeterError('MeterPlan required')
    for clock in plan.to_dict()['clocks']:
        if clock['id'] == clock_id:
            return clock
    raise MeterError(f'unknown clock {clock_id!r}')


def clock_relation(plan, clock_id):
    clock = _clock(plan, clock_id)
    relation = clock['relation']
    if clock['kind'] == 'nested':
        return {'clock_id': clock_id, 'kind': 'nested', 'reference_id': None if relation is None else relation['reference_id'],
                'period_ratio': None if relation is None else f"{relation['period_numerator']}/{relation['period_denominator']}",
                'binary_nested': True, 'cross_label': None}
    if clock['kind'] == 'cross':
        return {'clock_id': clock_id, 'kind': 'cross', 'reference_id': relation['reference_id'],
                'period_ratio': f"{relation['reference_cycles']}/{relation['pulses']}",
                'binary_nested': False, 'cross_label': f"{relation['pulses']}:{relation['reference_cycles']}"}
    return {'clock_id': clock_id, 'kind': 'cycle', 'reference_id': None, 'period_ratio': None,
            'binary_nested': False, 'cross_label': None}


def generate_ticks(plan, clock_id, time_map=None):
    clock = _clock(plan, clock_id)
    period, phase = fraction(clock['period_beats']), fraction(clock['phase_beats'])
    resets = [fraction(x) for x in clock['reset_beats']]
    tm = None if time_map is None else _time_map_dict(time_map)
    ticks = []; sequence = 0; segment_number = 0
    for window_index, window in enumerate(clock['active_windows']):
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
            while beat < hi:
                row = {'clock_id': clock_id, 'kind': clock['kind'], 'tick_index': sequence,
                       'beat': _rat(beat), 'active_window_index': window_index,
                       'phase_segment_index': segment_number, 'phase_origin_beat': _rat(origin)}
                if tm is not None:
                    exact_sample = Fraction(int(tm['origin_sample'])) + beat_to_seconds(tm, _rat(beat)) * int(tm['sample_rate_hz'])
                    rounded = beat_to_sample(tm, _rat(beat))
                    error = Fraction(rounded) - exact_sample
                    row.update(sample=rounded, exact_sample=_rat(exact_sample), rounding_error_samples=_rat(error))
                ticks.append(row); sequence += 1; beat += period
            segment_number += 1
    return ticks


def generate_all_ticks(plan, time_map=None):
    return {clock['id']: generate_ticks(plan, clock['id'], time_map) for clock in plan.to_dict()['clocks']}


def control_schedule(plan, time_map=None):
    if not isinstance(plan, MeterPlan):
        raise MeterError('MeterPlan required')
    data = plan.to_dict(); rows = []
    ticks = generate_all_ticks(plan, time_map)
    for binding in data['bindings']:
        values = binding['values']
        for tick in ticks[binding['clock_id']]:
            index = tick['tick_index']
            rows.append({**tick, 'binding_id': binding['id'], 'layer': binding['layer'],
                         'control': binding['control'], 'value': float(values[index % len(values)]),
                         'stability': binding['stability'],
                         'stable_clock': binding['clock_id'] == data['stable_clock_id']})
    rows.sort(key=lambda x: (fraction(x['beat']), x['binding_id'], x['tick_index']))
    return rows
