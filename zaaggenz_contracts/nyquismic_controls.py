"""NYQ-004 bounded instantaneous-rate control and rate-ladder evaluator.

A saved-rate inspector for NYQ-004. It is intentionally NOT a virtual-clock
phase integrator, event scheduler, sampler adapter, feature tap or audio path.
The NYQ-001/002 geometry rejection remains authoritative until full NYQ-004
event integration is validated. No silent approximate event times.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Context, Decimal, localcontext
from fractions import Fraction

from .nyquismic import (
    MAX_TIME_S, MIN_RATE_HZ, MAX_RATE_HZ, Point, SonicSpec,
    clock_cell_value, integer, record, require, rational_value, qtext,
)

METHOD = 'nyq.instantaneous-controls.v1'


def _d(value: Fraction | Decimal) -> Decimal:
    if type(value) is Fraction:
        return Decimal(value.numerator) / Decimal(value.denominator)
    return value


def _text(value: Fraction | Decimal) -> str:
    return qtext(value) if type(value) is Fraction else str(value)


def _range(value: Fraction | Decimal, context: str) -> None:
    require(_d(MIN_RATE_HZ) <= _d(value) <= _d(MAX_RATE_HZ),
            context + ': instantaneous rate outside admitted positive bounds')


def _curve(initial: Fraction, points: tuple[Point, ...], interpolation: str,
           origin: Fraction, t: Fraction) -> Fraction:
    """Right-continuous piecewise control in exact rational physical time."""
    left, value = origin, initial
    for point in points:
        right, target = Fraction(point.time_s), Fraction(point.value)
        if t < right:
            if interpolation == 'linear':
                return value + (target - value) * (t - left) / (right - left)
            return value
        left, value = right, target
    return value


def nearest_ladder_hz(value: Fraction | Decimal, levels: tuple[str, ...]) -> Fraction:
    """Select nearest saved positive-Hz ladder entry, lower value on exact tie.

    Callers must supply an accepted ordered RateQuantizer ladder: this helper
    validates sorting, presence and physical frequency bounds independently.
    """
    require(type(value) in (Fraction, Decimal), 'rate ladder input must be exact rational or Decimal')
    require(type(levels) is tuple and 0 < len(levels) <= 64, 'rate ladder requires 1..64 entries')
    parsed = [rational_value(s, 'rate ladder entry', MIN_RATE_HZ, MAX_RATE_HZ) for s in levels]
    require(all(a < b for a, b in zip(parsed, parsed[1:])), 'rate ladder must be ascending/unique')
    with localcontext(Context(prec=80)):
        _range(value, 'unquantized rate')
        return min(parsed, key=lambda hz: (abs(_d(value) - _d(hz)), hz))


@dataclass(frozen=True)
class RateControlSample:
    """Disclosed one-time control values, not an executable event-grid claim."""
    method: str
    clock_sha256: str
    sonic_sha256: str
    at_s: str
    base_hz: str
    routed_hz: str
    quantized_hz: str
    realized_hz: str
    route_values: tuple[str, ...]
    jitter_cell_index: int | None
    jitter_value: str | None
    channel: int


def evaluate_instantaneous_rate(spec: SonicSpec, time_s: str, *, channel: int = 0) -> RateControlSample:
    """Evaluate saved automation, ordered routes, ladder and jitter at time_s.

    No phase integration or implicit smoothing. The input time is a normalized
    rational absolute second; source/evaluation/output rates never enter it.
    Jitter cells are physical-time counter-addressed SHA256 values, not a
    mutable random stream and not evaluation-sample-index-dependent.
    """
    record(spec, SonicSpec, 'Nyquismic sonic spec')
    require(spec.mode == 'sampler' and spec.clock is not None,
            'rate inspector requires a sampler clock; warp/cascade not yet executable')
    clock = spec.clock
    t = rational_value(time_s, 'control sample time', 0, MAX_TIME_S)
    origin = Fraction(clock.origin_s)
    require(t >= origin, 'control sample before saved clock origin')
    integer(channel, 'control channel', 0, spec.channels - 1)
    # Include unused and latent controls in validation. This is conservative
    # full-range admission rather than an optimistic point-sample check.
    clock.rate_bounds()
    with localcontext(Context(prec=80)):
        base = _curve(clock.rate.hz, clock.points_hz, clock.interpolation, origin, t)
        routed: Fraction | Decimal = base
        control_values: list[str] = []
        for route in clock.routes:
            control = _curve(Fraction(route.initial), route.points,
                             route.interpolation, origin, t)
            control_values.append(qtext(control))
            if route.mapping == 'add_hz':
                delta = Fraction.from_float(route.depth) * control
                routed = routed + delta if type(routed) is Fraction else routed + _d(delta)
            else:
                exponent = _d(Fraction.from_float(route.depth) * control)
                routed = _d(routed) * (Decimal(2) ** exponent)
            _range(routed, 'routed rate')
        quantized: Fraction | Decimal = routed
        if clock.quantizer.policy == 'nearest_hz':
            quantized = nearest_ladder_hz(routed, clock.quantizer.levels_hz)
        cell = None
        draw = None
        realized = quantized
        if clock.jitter.model == 'uniform_frequency_cells_v1':
            cell = (t - origin) // Fraction(clock.jitter.cell_s)
            draw = clock_cell_value(spec, cell_index=cell, channel=channel)
            multiplier = Fraction(1) + Fraction.from_float(clock.jitter.amount) * draw
            realized = (quantized * multiplier if type(quantized) is Fraction
                        else quantized * _d(multiplier))
        _range(realized, 'jittered rate')
        return RateControlSample(
            method=METHOD, clock_sha256=clock.sha256, sonic_sha256=spec.sonic_sha256,
            at_s=qtext(t), base_hz=_text(base), routed_hz=_text(routed),
            quantized_hz=_text(quantized), realized_hz=_text(realized),
            route_values=tuple(control_values), jitter_cell_index=cell,
            jitter_value=_text(draw) if draw is not None else None,
            channel=channel,
        )
