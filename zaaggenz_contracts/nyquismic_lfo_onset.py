"""NYQ-004: exact delayed LFO onset through two frozen, ordered additive routes.

The v1 SampledLfoSource rightly refuses a nonzero delayed onset in a *single*
linear route: that would introduce an audible pre-onset ramp. This bounded,
versioned adapter freezes an exact step plus an exact linear residual instead.
It is consumed by the existing controlled-event/native-grid proof path, NOT
registered SamplerPlan, Compose, or graph execution.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from fractions import Fraction

from .nyquismic import (
    MAX_POINTS, MAX_RATE_HZ, ModulationRoute, Point, identifier, number,
    qtext, rational_value, record, require,
)
from .nyquismic_clock import ClockCancelled
from .nyquismic_controls import SampledLfoSource

METHOD = 'nyq.delayed-lfo-additive-route-pair.v1'


@dataclass(frozen=True)
class DelayedLfoRoutePair:
    method: str
    source_sha256: str
    onset_s: str
    through_s: str
    routes: tuple[ModulationRoute, ModulationRoute]


def compile_delayed_lfo_additive_routes(
    source: SampledLfoSource, end_s: str, *, route_id: str,
    depth: float, cancelled=None,
) -> DelayedLfoRoutePair:
    """Freeze an arbitrary-phase delayed triangle LFO without pre-onset leak.

    A step lane carries onset value v0, followed by a linear residual lane
    carrying (v(t)-v0)/2 with twice the depth. Thus the ordered sum is exactly
    depth*v(t) after onset and exactly zero before onset. The /2 normalization
    keeps both lane controls within the accepted [-1, 1] SonicSpec contract.
    The conservative independent-lane positive-rate guard still applies and
    may refuse an otherwise admissible correlated pair. No guard is weakened.

    The source intent must be saved separately: SonicSpec freezes only the
    two compiled routes. Extension past end_s holds its terminal value; a
    longer render requires recompilation using the original source.
    """
    record(source, SampledLfoSource, 'delayed LFO source')
    identifier(route_id, 'delayed LFO route id')
    number(depth, 'delayed LFO additive depth Hz',
           -float(MAX_RATE_HZ) / 2, float(MAX_RATE_HZ) / 2)
    require(cancelled is None or callable(cancelled),
            'delayed LFO cancellation hook must be callable')
    if cancelled is not None and cancelled():
        raise ClockCancelled('delayed LFO compilation cancelled')
    start = Fraction(source.origin_s)
    require(start > 0, 'delayed LFO adapter requires a positive source onset')
    end = rational_value(end_s, 'delayed LFO end seconds', 0)
    if end < start:
        # A preview that ends before the saved onset has no active LFO.
        # Preserve both stable lane IDs and the exact source/depth intent,
        # without translating future BPM points or evaluating negative time.
        if cancelled is not None and cancelled():
            raise ClockCancelled('delayed LFO compilation cancelled; no partial routes')
        neutral = (
            ModulationRoute(
                id=route_id + '-onset', mapping='add_hz', depth=depth,
                initial='0/1', points=(), interpolation='step'),
            ModulationRoute(
                id=route_id + '-motion', mapping='add_hz', depth=2 * depth,
                initial='0/1', points=(), interpolation='linear'),
        )
        return DelayedLfoRoutePair(
            method=METHOD, source_sha256=source.sha256,
            onset_s=qtext(start), through_s=qtext(end), routes=neutral)
    duration = end - start

    # A translated *physical-time* source has precisely the same phase,
    # onsets, and tempo-change times relative to the requested source onset.
    # In particular it avoids allocating or bounding any pre-onset grid.
    relative_tempos = tuple(
        Point(qtext(Fraction(p.time_s) - start), p.value)
        for p in source.tempo_points
    )
    relative = replace(source, origin_s='0/1', tempo_points=relative_tempos)
    sampled = relative.compile_route(
        qtext(duration), route_id=route_id, mapping='add_hz',
        depth=depth, cancelled=cancelled,
    )
    onset = source.value_at(qtext(start))
    require(len(sampled.points) + 1 <= MAX_POINTS,
            'delayed LFO motion route exceeds point budget after onset')
    onset_point = Point(qtext(start), qtext(onset))
    motion_points = (Point(qtext(start), '0/1'),) + tuple(
        Point(qtext(start + Fraction(p.time_s)),
              qtext((Fraction(p.value) - onset) / 2))
        for p in sampled.points
    )
    if cancelled is not None and cancelled():
        raise ClockCancelled('delayed LFO compilation cancelled; no partial route')
    onset_route = ModulationRoute(
        id=route_id + '-onset', mapping='add_hz', depth=depth,
        initial='0/1', points=(onset_point,), interpolation='step',
    )
    motion_route = ModulationRoute(
        id=route_id + '-motion', mapping='add_hz', depth=2 * depth,
        initial='0/1', points=motion_points, interpolation='linear',
    )
    return DelayedLfoRoutePair(
        method=METHOD, source_sha256=source.sha256,
        onset_s=qtext(start), through_s=qtext(end),
        routes=(onset_route, motion_route),
    )
