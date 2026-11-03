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


# NYQ-004 narrow but executable phase/event geometry.  This intentionally
# lives alongside the frozen NYQ-001/002 ClockPlan, which must continue to
# reject routed/quantized/jitter execution until full adapter qualification.
@dataclass(frozen=True)
class StepClockEvent:
    index: int
    epoch: int
    crossing: int
    coordinate_s: Fraction


def compile_step_clock_events(
    spec: SonicSpec, end_s: str, *, channel: int = 0,
    budget=None, cancelled=None,
) -> tuple[StepClockEvent, ...]:
    """Exact crossings of a bounded piecewise-constant controlled rate.

    Supports static/step base automation and additive-Hz routes, nearest-Hz
    quantization and counter-addressed fractional-frequency jitter cells.
    Every change in rate creates a physical-time segment; the continuous
    phase is integrated across segments, not reset at block/cell boundaries.
    Reset epochs explicitly change the phase. Linear ramps, logarithmic
    routes, envelopes, beat-sync and audio-derived controls are rejected
    until their mathematically correct integration is implemented.

    This is a standalone numerical clock *proof*, not a SamplerPlan adapter.
    It publishes no audio, checkpoints, project migrations or rack capability.
    """
    from math import ceil
    from .nyquismic import MAX_EVENTS, MIN_SPACING_S, ResourceBudget, UnsupportedNyquismic
    from .nyquismic_clock import ClockCancelled

    record(spec, SonicSpec, 'NYQ step clock sonic spec')
    require(spec.mode == 'sampler' and spec.clock is not None,
            'step event compilation requires sampler mode')
    clock = spec.clock
    budget = ResourceBudget() if budget is None else budget
    record(budget, ResourceBudget, 'step clock budget')
    integer(channel, 'step clock channel', 0, spec.channels - 1)
    require(cancelled is None or callable(cancelled), 'cancellation hook must be callable')
    origin = Fraction(clock.origin_s)
    end = rational_value(end_s, 'step clock end seconds', origin, MAX_TIME_S)
    if clock.interpolation == 'linear' and clock.points_hz:
        raise UnsupportedNyquismic('linear-Hz controlled clock geometry not yet supported')
    for route in clock.routes:
        if route.mapping != 'add_hz' or (route.interpolation == 'linear' and route.points):
            raise UnsupportedNyquismic('step clock supports step/add-Hz routes only')
    if cancelled is not None and cancelled():
        raise ClockCancelled('controlled clock cancelled; no partial event publication')

    cuts = {origin, end}
    cuts.update(Fraction(p.time_s) for p in clock.points_hz
                if origin < Fraction(p.time_s) < end)
    for route in clock.routes:
        cuts.update(Fraction(p.time_s) for p in route.points
                    if origin < Fraction(p.time_s) < end)
    resets = {Fraction(reset.time_s): (i + 1, Fraction(reset.phase_cycles))
              for i, reset in enumerate(clock.resets)}
    cuts.update(t for t in resets if origin < t < end)

    if clock.jitter.model == 'uniform_frequency_cells_v1':
        width = Fraction(clock.jitter.cell_s)
        cells = ceil((end - origin) / width)
        # Refuse oversized stochastic lattices before creating a large set.
        require(cells <= min(MAX_EVENTS, budget.max_events),
                'step clock jitter-cell admission budget exceeded')
        cuts.update(origin + i * width for i in range(1, cells))
    require(len(cuts) <= MAX_EVENTS + 2, 'step clock segment budget exceeded')
    ordered = sorted(cuts)
    phase = Fraction(clock.phase_cycles)
    epoch = 0
    events: list[StepClockEvent] = []
    previous_time: Fraction | None = None
    for a, b in zip(ordered, ordered[1:]):
        if cancelled is not None and cancelled():
            raise ClockCancelled('controlled clock cancelled; no partial event publication')
        if a in resets:
            epoch, phase = resets[a]
        # The evaluator must return an exact rational in this supported subset.
        # In particular, no exponential Decimal80 result is silently rounded
        # to the numerical evaluation grid.
        rate = Fraction(evaluate_instantaneous_rate(spec, qtext(a), channel=channel).realized_hz)
        require(rate > 0, 'step clock rate must be positive')
        finish = phase + rate * (b - a)
        require(finish.numerator.bit_length() <= 32768 and
                finish.denominator.bit_length() <= 32768,
                'controlled clock exact phase arithmetic budget exceeded')
        first, stop = ceil(phase), ceil(finish)
        require(stop >= first and len(events) + stop - first <= budget.max_events,
                'controlled clock capture event budget exceeded')
        for crossing in range(first, stop):
            if (len(events) & 255) == 0 and cancelled is not None and cancelled():
                raise ClockCancelled('controlled clock cancelled; no partial event publication')
            at = a + (crossing - phase) / rate
            require(a <= at < b, 'controlled clock half-open crossing violation')
            if previous_time is not None:
                require(at - previous_time >= MIN_SPACING_S,
                        'controlled clock event spacing below accepted minimum')
            events.append(StepClockEvent(len(events), epoch, crossing, at))
            previous_time = at
        phase = finish
    if cancelled is not None and cancelled():
        raise ClockCancelled('controlled clock cancelled; no partial event publication')
    return tuple(events)
