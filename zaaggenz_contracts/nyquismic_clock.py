"""Authoritative bounded physical-time geometry for NYQ-001 (not audio DSP).

Exact rational integration of a piecewise constant/linear-Hz clock determines
integer crossings and half-open membership. Only conversion of irrational
crossing timestamps uses Decimal80, then binary64. No evaluation-sample clock,
rounded hold interval or t += 1/f(t) recurrence participates in the definition.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Context, Decimal, localcontext
from fractions import Fraction
from math import ceil, isqrt
import re
from typing import Callable

from .nyquismic import (
    VERSION, MAX_TIME_S, MAX_READ_S, MAX_RATE_HZ, MAX_EVENTS, MAX_RESETS, MAX_LOOP_TRAVERSALS,
    MIN_SPACING_S, ClockSpec, PlaybackMap, SonicSpec, ResourceBudget, Point,
    _Record, require, record, rational_value, qtext, integer, hash_value,
    normalized, choice,
)
from .model import ContractError

METHOD = 'exact_rational_piecewise_affine_decimal80_v1'
MAX_PHASE_BITS = 32768
SPACING_BISECTIONS = 128


class ClockCancelled(ContractError):
    pass


def _bounded_phase(q: Fraction) -> Fraction:
    require(q.numerator.bit_length() <= MAX_PHASE_BITS and q.denominator.bit_length() <= MAX_PHASE_BITS,
            'integrated phase exact-arithmetic budget exceeded')
    return q


def _decimal(q: Fraction) -> Decimal:
    return Decimal(q.numerator) / Decimal(q.denominator)


def _time(value: str) -> Fraction:
    return rational_value(value, 'absolute time seconds', 0, MAX_TIME_S)


def _value_slope(initial: Fraction, points: tuple[Point, ...], interpolation: str,
                 origin: Fraction, at: Fraction) -> tuple[Fraction, Fraction]:
    """Right-continuous controls; linear ramp begins at the preceding point."""
    left, value = origin, initial
    for point in points:
        right, target = Fraction(point.time_s), Fraction(point.value)
        if at < right:
            if interpolation == 'linear':
                slope = (target - value) / (right - left)
                return value + slope * (at - left), slope
            return value, Fraction(0)
        left, value = right, target
    return value, Fraction(0)


def _integral(initial, points, interpolation, origin, start, end):
    cuts = [start, *(Fraction(p.time_s) for p in points if start < Fraction(p.time_s) < end), end]
    result = Fraction(0)
    for a, b in zip(cuts, cuts[1:]):
        rate, slope = _value_slope(initial, points, interpolation, origin, a)
        result = _bounded_phase(result + rate * (b - a) + slope * (b - a) ** 2 / 2)
    return result


@dataclass(frozen=True)
class ClockEvent:
    index: int
    epoch: int
    crossing: int
    time_s: float


@dataclass(frozen=True)
class _Segment:
    start: Fraction
    end: Fraction
    rate: Fraction
    slope: Fraction
    phase: Fraction
    epoch: int
    offset: int

    def phase_at(self, t):
        dt = t - self.start
        return self.phase + self.rate * dt + self.slope * dt * dt / 2

    @property
    def first(self):
        return ceil(self.phase)

    @property
    def stop(self):
        return ceil(self.phase_at(self.end))

    def rational_root(self, crossing):
        q = Fraction(crossing) - self.phase
        if q == 0:
            return self.start
        if self.slope == 0:
            return self.start + q / self.rate
        disc = self.rate * self.rate + 2 * self.slope * q
        require(disc >= 0, 'negative crossing discriminant')
        n, d = isqrt(disc.numerator), isqrt(disc.denominator)
        if n * n == disc.numerator and d * d == disc.denominator:
            return self.start + 2 * q / (self.rate + Fraction(n, d))
        return None

    def timestamp(self, crossing):
        exact = self.rational_root(crossing)
        if exact is not None:
            return float(exact)
        q = Fraction(crossing) - self.phase
        disc = self.rate * self.rate + 2 * self.slope * q
        with localcontext(Context(prec=80)):
            # Cancellation-safe form for both increasing and decreasing ramps.
            dt = 2 * _decimal(q) / (_decimal(self.rate) + _decimal(disc).sqrt())
            return float(_decimal(self.start) + dt)

    def enclosure(self, crossing):
        exact = self.rational_root(crossing)
        if exact is not None:
            return exact, exact
        lo, hi = self.start, self.end
        for _ in range(SPACING_BISECTIONS):
            mid = (lo + hi) / 2
            phase = self.phase_at(mid)
            if phase == crossing:
                return mid, mid
            if phase < crossing:
                lo = mid
            else:
                hi = mid
        return lo, hi


@dataclass(frozen=True)
class ClockCheckpoint(_Record):
    """Clock-only cursor AFTER controls/resets and BEFORE capture at time_s.

    This is NOT an audio/filter-history checkpoint. Restoring must recompute and
    verify all fields against the same ClockSpec, not trust caller-provided phase.
    Hex integers avoid Python's decimal-string conversion resource/global limit.
    """
    clock_sha256: str
    time_s: str
    epoch: int
    next_crossing: int
    events_before: int
    phase_numerator_hex: str
    phase_denominator_hex: str
    version: str = VERSION
    method: str = METHOD

    def __post_init__(self):
        choice(self.version, 'clock checkpoint version', (VERSION,))
        choice(self.method, 'clock checkpoint method', (METHOD,))
        hash_value(self.clock_sha256, 'checkpoint clock')
        normalized(self, 'time_s', 0, MAX_TIME_S)
        integer(self.epoch, 'checkpoint epoch', 0, MAX_RESETS)
        integer(self.next_crossing, 'checkpoint crossing', 0, int(MAX_RATE_HZ) * MAX_TIME_S + 1)
        integer(self.events_before, 'checkpoint count', 0, MAX_EVENTS)
        for name in ('phase_numerator_hex', 'phase_denominator_hex'):
            value = getattr(self, name)
            require(type(value) is str and len(value) <= MAX_PHASE_BITS // 4 and
                    re.fullmatch(r'(?:0|[1-9a-f][0-9a-f]*)', value), 'checkpoint integer encoding/budget')
        n, d = int(self.phase_numerator_hex, 16), int(self.phase_denominator_hex, 16)
        require(d > 0, 'zero phase denominator')
        q = Fraction(n, d)
        require(q.numerator == n and q.denominator == d, 'checkpoint phase must be reduced')

    def require_audio_restore(self):
        from .nyquismic import UnsupportedNyquismic
        raise UnsupportedNyquismic('NYQ-001 checkpoint contains clock state only; audio history restoration requires #251/#252')


@dataclass(frozen=True, init=False)
class ClockPlan:
    spec: ClockSpec
    end_s: str
    budget: ResourceBudget
    _segments: tuple[_Segment, ...]
    event_count: int

    def __init__(self, spec: ClockSpec, end_s: str, budget: ResourceBudget = ResourceBudget()):
        record(spec, ClockSpec, 'clock spec')
        record(budget, ResourceBudget, 'budget')
        spec.require_geometry()
        end, origin = _time(end_s), Fraction(spec.origin_s)
        require(origin <= end, 'clock extent ends before origin')
        resets = {Fraction(r.time_s): (i + 1, Fraction(r.phase_cycles)) for i, r in enumerate(spec.resets)}
        cuts = sorted({origin, end, *(Fraction(p.time_s) for p in spec.points_hz if origin < Fraction(p.time_s) < end),
                       *(at for at in resets if origin < at < end)})
        segments, count = [], 0
        phase, epoch = Fraction(spec.phase_cycles), 0
        previous = None
        for a, b in zip(cuts, cuts[1:]):
            if a in resets:
                epoch, phase = resets[a]
            rate, slope = _value_slope(spec.rate.hz, spec.points_hz, spec.interpolation, origin, a)
            segment = _Segment(a, b, rate, slope, phase, epoch, count)
            count += segment.stop - segment.first
            require(count <= budget.max_events, 'capture event budget exceeded before event allocation')
            if segment.stop > segment.first:
                if previous is not None and previous.epoch != epoch:
                    plo, phi = previous.enclosure(previous.stop - 1)
                    nlo, nhi = segment.enclosure(segment.first)
                    require(nlo - phi >= MIN_SPACING_S,
                            'reset produces insufficient/unprovable minimum event spacing; rejected, not clamped')
                previous = segment
            segments.append(segment)
            phase = _bounded_phase(segment.phase_at(b))
        object.__setattr__(self, 'spec', spec)
        object.__setattr__(self, 'end_s', qtext(end))
        object.__setattr__(self, 'budget', budget)
        object.__setattr__(self, '_segments', tuple(segments))
        object.__setattr__(self, 'event_count', count)

    def phase_at(self, time_s: str) -> tuple[int, Fraction]:
        """Right-hand epoch/phase at an absolute time, including resets at end."""
        at, origin = _time(time_s), Fraction(self.spec.origin_s)
        require(origin <= at <= Fraction(self.end_s), 'phase query outside plan')
        reset_at, phase, epoch = origin, Fraction(self.spec.phase_cycles), 0
        for i, reset in enumerate(self.spec.resets):
            if Fraction(reset.time_s) > at:
                break
            reset_at, phase, epoch = Fraction(reset.time_s), Fraction(reset.phase_cycles), i + 1
        integral = _integral(self.spec.rate.hz, self.spec.points_hz, self.spec.interpolation,
                             origin, reset_at, at)
        return epoch, _bounded_phase(phase + integral)

    def events(self, start_s: str | None = None, end_s: str | None = None,
               cancelled: Callable[[], bool] | None = None) -> tuple[ClockEvent, ...]:
        """Emit only [start,end); absolute IDs and membership do not use floats.

        The full plan is admitted first. A tiny preview cannot evade the full
        absolute-clock event budget. Cancellation never returns a partial list.
        """
        start = Fraction(self.spec.origin_s) if start_s is None else _time(start_s)
        end = Fraction(self.end_s) if end_s is None else _time(end_s)
        require(Fraction(self.spec.origin_s) <= start <= end <= Fraction(self.end_s), 'event query outside plan')
        require(cancelled is None or callable(cancelled), 'cancellation callback must be callable')
        events = []
        for segment in self._segments:
            if cancelled is not None and cancelled():
                raise ClockCancelled('Nyquismic clock generation cancelled; no partial event publication')
            a, b = max(start, segment.start), min(end, segment.end)
            if a >= b:
                continue
            first, stop = ceil(segment.phase_at(a)), ceil(segment.phase_at(b))
            for k in range(first, stop):
                if (len(events) & 255) == 0 and cancelled is not None and cancelled():
                    raise ClockCancelled('Nyquismic clock generation cancelled; no partial event publication')
                events.append(ClockEvent(segment.offset + k - segment.first, segment.epoch, k, segment.timestamp(k)))
        return tuple(events)

    def checkpoint(self, time_s: str) -> ClockCheckpoint:
        at = _time(time_s)
        epoch, phase = self.phase_at(qtext(at))
        count = 0
        for segment in self._segments:
            if at > segment.start:
                count += ceil(segment.phase_at(min(at, segment.end))) - segment.first
        return ClockCheckpoint(self.spec.sha256, qtext(at), epoch, ceil(phase), count,
                               format(phase.numerator, 'x'), format(phase.denominator, 'x'))

    def restore(self, checkpoint: ClockCheckpoint, cancelled: Callable[[], bool] | None = None) -> tuple[ClockEvent, ...]:
        record(checkpoint, ClockCheckpoint, 'checkpoint')
        require(checkpoint == self.checkpoint(checkpoint.time_s), 'foreign/stale/tampered clock checkpoint')
        return self.events(checkpoint.time_s, cancelled=cancelled)


def source_time(spec: SonicSpec, time_s: str, *, bounded: bool = False,
                input_extent_s: str | None = None) -> Fraction | None:
    """Distinct sampler and playback source mapping; does not sample any audio.

    Unbounded returns physical source seconds; bounded maps zero-pad to None,
    edge-hold to the source endpoint, or a half-open loop using exact modulo.
    The endpoint is a coordinate: a later source interpolator owns PCM edge
    evaluation and must not interpret it as an in-range sample array index.
    """
    record(spec, SonicSpec, 'sonic spec')
    require(type(bounded) is bool, 'bounded flag must be bool')
    require(spec.mode != 'cascade', 'cascade time mapping belongs to individual stages')
    at, origin = _time(time_s), Fraction(spec.clock.origin_s)
    require(at >= origin, 'source query before origin')
    if spec.mode == 'sampler':
        u = at - origin
        if not bounded:
            require(input_extent_s is None, 'unused input extent in an unbounded coordinate query')
            return u
        extent = rational_value(input_extent_s, 'sampler input extent seconds', 0, MAX_READ_S)
        if extent == 0:
            return None  # Empty input has no edge sample, even for edge-hold.
        if u < extent:
            return u
        return None if spec.input_boundary == 'zero_pad' else extent
    require(input_extent_s is None, 'playback source extent is part of the saved map, not an override')
    playback = spec.playback
    require(all(Fraction(p.time_s) > origin for p in playback.speed_points), 'speed points must follow clock origin')
    u = Fraction(playback.source_origin_s) + _integral(Fraction(playback.speed), playback.speed_points,
                                                      playback.interpolation, origin, origin, at)
    require(u <= MAX_READ_S, 'source read extent budget exceeded')
    if playback.boundary == 'loop':
        start, end = Fraction(playback.loop_start_s), Fraction(playback.loop_end_s)
        require((u - start) // (end - start) <= MAX_LOOP_TRAVERSALS, 'loop traversal budget exceeded')
    if not bounded:
        return u
    extent = Fraction(playback.source_extent_s)
    if playback.boundary == 'loop':
        start, end = Fraction(playback.loop_start_s), Fraction(playback.loop_end_s)
        return start + (u - start) % (end - start)
    if u < extent:
        return u
    return None if playback.boundary == 'zero_pad' else extent


def admit_foundation(spec: SonicSpec, end_s: str, budget: ResourceBudget = ResourceBudget()) -> tuple[ClockPlan, ...]:
    """Bound a whole sonic declaration before constructing event buffers.

    Admission checks latent bypassed state too. It grants geometry access only,
    never audio execution, rack integration, or a completed render artifact.
    """
    record(spec, SonicSpec, 'sonic spec')
    record(budget, ResourceBudget, 'budget')
    _time(end_s)
    stages = spec.stages if spec.mode == 'cascade' else (spec,)
    require(len(stages) + (spec.mode == 'cascade') <= budget.max_nodes, 'node budget exceeded')
    plans, total = [], 0
    for stage in stages:
        # Bound the unprojected source coordinate in every mode. Sampler time
        # advances too; padding, hold, looping and bypass do not waive admission.
        require(source_time(stage, end_s) <= budget.max_read_s, 'requested read extent exceeds admission budget')
        plan = ClockPlan(stage.clock, end_s, budget)
        total += plan.event_count * (stage.channels if stage.stereo_link == 'independent' else 1)
        require(total <= budget.max_events, 'aggregate stage/channel event budget exceeded')
        plans.append(plan)
    return tuple(plans)
