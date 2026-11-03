"""NYQ-004 deterministic rate controls and experimental clock geometry.

The instantaneous-rate inspector and separately bounded affine/step event
compiler share saved SonicSpec controls. The compiler integrates phase and
reports certified timestamp uncertainty, but is NOT a registered ClockPlan,
SamplerPlan adapter, feature tap, rack node or delivered audio path.
The accepted NYQ-001/002 clock geometry rejection remains authoritative
until actual sampler integration is independently qualified.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Context, Decimal, localcontext
from fractions import Fraction

from .nyquismic import (
    MAX_TIME_S, MIN_RATE_HZ, MAX_RATE_HZ, MAX_LEVELS, Point, SonicSpec,
    RateQuantizer, _Record, clock_cell_value, integer, record, require,
    rational_value, qtext,
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
class RatioLadder(_Record):
    """Persist explicit reference Hz + rational ratios before Hz quantization.

    The existing RateQuantizer stores physically realized positive-Hz values.
    This independently serialized control-source record keeps the *intent*
    (ratio and reference) available to callers without changing SonicSpec or
    silently referring to the numerical evaluation rate.
    """
    version: str = 'nyq.ratio-ladder.v1'
    reference_hz: str = '48000/1'
    ratios: tuple[str, ...] = ('1/3',)

    def __post_init__(self):
        require(self.version == 'nyq.ratio-ladder.v1', 'unsupported ratio ladder version')
        reference = rational_value(self.reference_hz, 'ratio ladder reference Hz',
                                   MIN_RATE_HZ, MAX_RATE_HZ)
        object.__setattr__(self, 'reference_hz', qtext(reference))
        require(type(self.ratios) is tuple and 1 <= len(self.ratios) <= MAX_LEVELS,
                'ratio ladder requires 1..64 ratios')
        values = [rational_value(x, 'ladder ratio') for x in self.ratios]
        require(all(x > 0 for x in values), 'ladder ratios must be positive')
        require(all(a < b for a, b in zip(values, values[1:])),
                'ladder ratios must be strictly ordered and unique')
        for ratio in values:
            hz = ratio * reference
            require(MIN_RATE_HZ <= hz <= MAX_RATE_HZ,
                    'ratio ladder resolved Hz outside supported positive bounds')
        object.__setattr__(self, 'ratios', tuple(qtext(x) for x in values))

    @classmethod
    def from_dict(cls, data):
        require(type(data) is dict and set(data) == {'version', 'reference_hz', 'ratios'},
                'ratio ladder requires complete version/reference/ratios snapshot')
        require(type(data['ratios']) is list, 'ratio ladder JSON ratios must be an array')
        return cls(version=data['version'], reference_hz=data['reference_hz'],
                   ratios=tuple(data['ratios']))

    def as_quantizer(self) -> RateQuantizer:
        """Compile to accepted exact-Hz lower-tie quantizer; never round Hz."""
        reference = Fraction(self.reference_hz)
        return RateQuantizer(policy='nearest_hz',
                             levels_hz=tuple(qtext(reference * Fraction(r)) for r in self.ratios))


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
    # Exact for step-rate crossings; for irrational ramp roots this bounds
    # the rational approximation to the true physical timestamp.
    coordinate_error_bound_s: Fraction = Fraction(0)


def _bounded_linear_root(rate: Fraction, slope: Fraction, target: Fraction
                         ) -> tuple[Fraction, Fraction]:
    """Certified rational enclosure for integral(rate+slope*t) == target.

    The stable quadratic root 2*target/(rate+sqrt(rate**2+2*slope*target))
    avoids catastrophic cancellation on shallow ramps. Rational perfect
    squares stay exact. Other roots use enclosing integer square roots on a
    fixed 128-bit dyadic lattice, independent of platform float/libm.
    """
    from math import isqrt

    require(target >= 0 and rate > 0, 'linear clock root must be nonnegative/positive')
    if target == 0:
        return Fraction(0), Fraction(0)
    if slope == 0:
        return target / rate, Fraction(0)
    discriminant = rate * rate + 2 * slope * target
    require(discriminant > 0, 'linear clock crossing has no positive discriminant')
    num = isqrt(discriminant.numerator)
    den = isqrt(discriminant.denominator)
    if num * num == discriminant.numerator and den * den == discriminant.denominator:
        return 2 * target / (rate + Fraction(num, den)), Fraction(0)

    bits = 128
    scale = 1 << bits
    floor_sqrt = isqrt((discriminant.numerator << (2 * bits)) // discriminant.denominator)
    sqrt_low = Fraction(floor_sqrt, scale)
    sqrt_high = Fraction(floor_sqrt + 1, scale)
    require(rate + sqrt_low > 0, 'linear clock root denominator invalid')
    t_low = 2 * target / (rate + sqrt_high)
    t_high = 2 * target / (rate + sqrt_low)
    radius = (t_high - t_low) / 2
    require(radius >= 0 and radius <= Fraction(1, 10**18),
            'linear clock timestamp uncertainty exceeds admitted bound')
    return (t_low + t_high) / 2, radius


def compile_step_clock_events(
    spec: SonicSpec, end_s: str, *, channel: int = 0,
    budget=None, cancelled=None,
) -> tuple[StepClockEvent, ...]:
    """Crossings of bounded piecewise-step or piecewise-linear controlled Hz.

    Constant-rate crossings are exact fractions. Linear-Hz ramps integrate
    exactly in rational phase and return platform-independent, explicitly
    bounded rational timestamp approximations for irrational roots.
    Counter-addressed jitter is permitted when piecewise-constant per cell.
    Quantized ramps, logarithmic routes, derived controls and beat-sync are
    deliberately rejected until their discontinuities/phase are specified.
    
    This is a standalone numerical clock *proof*, not a SamplerPlan adapter.
    It publishes no audio, checkpoints, project migrations or rack capability.
    """
    from math import ceil, isqrt
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
    linear = (clock.interpolation == 'linear' and bool(clock.points_hz)) or any(
        r.interpolation == 'linear' and bool(r.points) for r in clock.routes)
    if linear and clock.quantizer.policy != 'none':
        raise UnsupportedNyquismic('quantized linear-Hz ramp switch crossings need a separate exact solver')
    for route in clock.routes:
        if route.mapping != 'add_hz':
            raise UnsupportedNyquismic('controlled clock logarithmic route integration not implemented')
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
    previous_error = Fraction(0)
    for a, b in zip(ordered, ordered[1:]):
        if cancelled is not None and cancelled():
            raise ClockCancelled('controlled clock cancelled; no partial event publication')
        if a in resets:
            epoch, phase = resets[a]
        # The evaluator must return an exact rational in this supported subset.
        # In particular, no exponential Decimal80 result is silently rounded
        # to the numerical evaluation grid.
        rate = Fraction(evaluate_instantaneous_rate(spec, qtext(a), channel=channel).realized_hz)
        require(rate > 0, 'controlled clock rate must be positive')
        # Every linear breakpoint, step and jitter-cell boundary is a cut.
        # Thus inside [a,b) the realized rate is affine; the midpoint is an
        # exact independent sample for its slope, even when routes overlap.
        midpoint = (a + b) / 2
        middle_rate = (Fraction(evaluate_instantaneous_rate(
            spec, qtext(midpoint), channel=channel).realized_hz) if linear else rate)
        endpoint_rate = 2 * middle_rate - rate
        require(endpoint_rate > 0, 'controlled clock endpoint rate must be positive')
        slope = (endpoint_rate - rate) / (b - a)
        finish = phase + (rate + endpoint_rate) * (b - a) / 2
        require(finish.numerator.bit_length() <= 32768 and
                finish.denominator.bit_length() <= 32768,
                'controlled clock exact phase arithmetic budget exceeded')
        first, stop = ceil(phase), ceil(finish)
        require(stop >= first and len(events) + stop - first <= budget.max_events,
                'controlled clock capture event budget exceeded')
        for crossing in range(first, stop):
            if (len(events) & 255) == 0 and cancelled is not None and cancelled():
                raise ClockCancelled('controlled clock cancelled; no partial event publication')
            delta, uncertainty = _bounded_linear_root(rate, slope, Fraction(crossing) - phase)
            at = a + delta
            # The uncertainty interval itself must remain in the correct
            # half-open interval, not merely its rounded representative.
            require(a <= at - uncertainty and at + uncertainty < b,
                    'controlled clock half-open crossing uncertainty')
            if previous_time is not None:
                require(at - previous_time - uncertainty - previous_error >= MIN_SPACING_S,
                        'controlled clock event spacing below accepted minimum')
            events.append(StepClockEvent(len(events), epoch, crossing, at, uncertainty))
            previous_time, previous_error = at, uncertainty
        phase = finish
    if cancelled is not None and cancelled():
        raise ClockCancelled('controlled clock cancelled; no partial event publication')
    return tuple(events)
