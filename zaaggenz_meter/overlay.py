"""Multi-hypothesis periodicity overlays; deliberately no single-BPM winner."""
from __future__ import annotations
from fractions import Fraction
import math
import statistics
from zaaggenz_contracts import Contract
from zaaggenz_contracts.model import fraction
from zaaggenz_contracts.music import sample_to_beat
from .model import MeterError, MeterPlan
from .engine import generate_ticks, _time_map_dict


def _rat(value):
    return f'{value.numerator}/{value.denominator}'


def _measurements(time_map, measured_beats, measured_samples):
    if (measured_beats is None) == (measured_samples is None):
        raise MeterError('provide exactly one of measured_beats or measured_samples')
    if measured_samples is not None:
        tm = _time_map_dict(time_map)
        if type(measured_samples) not in (list, tuple) or any(type(x) is not int for x in measured_samples):
            raise MeterError('measured_samples must be integer sample positions')
        values = [sample_to_beat(tm, value) for value in measured_samples]
    else:
        if type(measured_beats) not in (list, tuple):
            raise MeterError('measured_beats must be a list/tuple')
        try:
            values = [fraction(value) for value in measured_beats]
        except (ValueError, TypeError) as exc:
            raise MeterError(str(exc)) from exc
    if values != sorted(values) or len(values) != len(set(values)):
        raise MeterError('measured positions must be strictly increasing and unique')
    return values


def periodicity_overlay(plan, *, time_map=None, measured_beats=None, measured_samples=None,
                        tolerance_fraction='1/8', support_threshold=0.8):
    if not isinstance(plan, MeterPlan):
        raise MeterError('MeterPlan required')
    try:
        tolerance = fraction(tolerance_fraction)
    except (ValueError, TypeError) as exc:
        raise MeterError(str(exc)) from exc
    if not 0 < tolerance <= Fraction(1, 2):
        raise MeterError('tolerance_fraction must be in (0, 1/2]')
    if type(support_threshold) not in (int, float) or type(support_threshold) is bool or not math.isfinite(float(support_threshold)) or not 0 <= support_threshold <= 1:
        raise MeterError('support_threshold must be in [0,1]')
    measured = _measurements(time_map, measured_beats, measured_samples)
    end = fraction(plan.to_dict()['end_beat'])
    measured = [x for x in measured if 0 <= x < end]
    candidates = []
    for clock in plan.to_dict()['clocks']:
        period = fraction(clock['period_beats'])
        tick_rows = generate_ticks(plan, clock['id'], time_map if measured_samples is not None else None)
        ticks = [fraction(row['beat']) for row in tick_rows]
        window = period * tolerance
        if ticks:
            nearest_tick_errors = [min(abs(m - t) for t in ticks) for m in measured] if measured else []
            nearest_measure_errors = [min(abs(t - m) for m in measured) for t in ticks] if measured else []
            alignment = sum(e <= window for e in nearest_tick_errors) / len(nearest_tick_errors) if nearest_tick_errors else 0.0
            coverage = sum(e <= window for e in nearest_measure_errors) / len(nearest_measure_errors) if nearest_measure_errors else 0.0
            med = statistics.median(float(e) for e in nearest_measure_errors) if nearest_measure_errors else None
        else:
            alignment = coverage = 0.0; med = None
        sample_intervals = []
        if tick_rows and 'sample' in tick_rows[0]:
            for a, b in zip(tick_rows, tick_rows[1:]):
                if a['phase_segment_index'] == b['phase_segment_index']:
                    sample_intervals.append(b['sample'] - a['sample'])
        candidates.append({'clock_id': clock['id'], 'kind': clock['kind'], 'period_beats': clock['period_beats'],
                           'tick_count': len(ticks), 'measured_event_count': len(measured),
                           'tick_coverage': coverage, 'measurement_alignment': alignment,
                           'median_nearest_tick_error_beats': med,
                           'supported': coverage >= float(support_threshold),
                           'sample_interval_min': min(sample_intervals) if sample_intervals else None,
                           'sample_interval_max': max(sample_intervals) if sample_intervals else None})
    supported = [row['clock_id'] for row in candidates if row['supported']]
    adjacent = [float(b - a) for a, b in zip(measured, measured[1:])]
    return {'method': 'zg026-multi-periodicity-overlay-v1', 'plan_sha256': plan.sha256,
            'measured_event_count': len(measured),
            'measured_adjacent_interval_beats_median': statistics.median(adjacent) if adjacent else None,
            'tolerance_fraction': _rat(tolerance), 'support_threshold': float(support_threshold),
            'candidates': candidates, 'ambiguity_clock_ids': supported,
            'winner_policy': 'none; multiple metrical levels may be simultaneously supported',
            'extra_events_do_not_penalize_tick_coverage': True}


def feature_flux_samples(feature_timeline, threshold):
    """Adapter for accepted ZG-012 FeatureTimeline; returns measured landmark anchors."""
    if not hasattr(feature_timeline, 'frames') or not hasattr(feature_timeline, 'sample_rate_hz'):
        raise MeterError('ZG-012 FeatureTimeline required')
    if type(threshold) not in (int, float) or type(threshold) is bool or not math.isfinite(float(threshold)) or threshold < 0:
        raise MeterError('nonnegative finite spectral-flux threshold required')
    return [int(frame.anchor_sample) for frame in feature_timeline.frames
            if bool(frame.valid) and frame.spectral_flux is not None and frame.spectral_flux >= threshold]


def overlay_feature_flux(plan, time_map, feature_timeline, threshold, **kwargs):
    tm = _time_map_dict(time_map)
    if int(feature_timeline.sample_rate_hz) != int(tm['sample_rate_hz']):
        raise MeterError('FeatureTimeline and TimeMap sample rates differ')
    samples = feature_flux_samples(feature_timeline, threshold)
    return periodicity_overlay(plan, time_map=tm, measured_samples=samples, **kwargs)
