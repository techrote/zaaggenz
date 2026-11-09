"""NYQ-004 opt-in musical LFO phase resets, independent of capture-clock resets.

A reset may jump the triangle's level. One linear ModulationRoute cannot model
that jump, so freeze an exact ordered step/continuous-motion additive-Hz pair.
This is source-native controlled-event proof authoring, not a product adapter.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from fractions import Fraction

from .nyquismic import (
    MAX_POINTS, MAX_RATE_HZ, MAX_RESETS, MAX_TIME_S, ModulationRoute,
    Point, Reset, _Record, identifier, number, qtext, rational_value,
    record, records, require,
)
from .nyquismic_clock import ClockCancelled
from .nyquismic_controls import SampledLfoSource

METHOD = 'nyq.triangle-lfo-physical-phase-reset-pair.v1'


def _triangle(phase: Fraction) -> Fraction:
    return Fraction(1) - 4 * abs(phase - Fraction(1, 2))


@dataclass(frozen=True)
class PhaseResetLfoSource(_Record):
    """An immutable LFO with physical-time, source-independent phase resets.

    These Reset records target the MODULATOR, never ClockSpec.resets or the
    project's source/read/output clock. A right-continuous reset replaces the
    triangle phase at exactly its saved timestamp, without moving prior events.
    """
    version: str = 'nyq.triangle-lfo-phase-resets.v1'
    lfo: SampledLfoSource = SampledLfoSource()
    resets: tuple[Reset, ...] = ()
    _children = {'lfo': SampledLfoSource, 'resets': (Reset,)}

    def __post_init__(self):
        require(self.version == 'nyq.triangle-lfo-phase-resets.v1',
                'unsupported LFO phase-reset source version')
        record(self.lfo, SampledLfoSource, 'phase-reset LFO')
        require(self.lfo.origin_s == '0/1',
                'phase-reset LFO v1 requires physical origin zero')
        require(type(self.resets) is tuple and 1 <= len(self.resets) <= MAX_RESETS,
                'phase-reset LFO needs 1..256 explicitly ordered resets')
        records(self.resets, Reset, 'phase-reset LFO resets', MAX_RESETS)
        prev = Fraction(0)
        for reset in self.resets:
            at = Fraction(reset.time_s)
            require(prev < at <= MAX_TIME_S,
                    'LFO phase resets must have increasing positive physical times')
            prev = at


@dataclass(frozen=True)
class PhaseResetLfoRoutePair:
    method: str
    source_sha256: str
    through_s: str
    active_resets: int
    routes: tuple[ModulationRoute, ModulationRoute]


def compile_phase_reset_lfo_additive_routes(
    source: PhaseResetLfoSource, end_s: str, *, route_id: str,
    depth: float, cancelled=None,
) -> PhaseResetLfoRoutePair:
    """Freeze exact physical-time triangle segments and discontinuous resets.

    A step lane accumulates the signed LFO-level jumps at each physical reset.
    A separate piecewise-linear lane subtracts this accumulated offset, making
    it continuous at every reset. Their ordered sum reconstructs the original
    right-continuous LFO exactly without fake near-coincident timestamps.
    Each lane is independently bounded to [-1,1] via power-of-two scaling,
    preserving exact binary floating-depth products. ClockSpec still performs
    its conservative complete-range positive-rate admission; it may refuse
    highly correlated, high-depth pairs without weakening safeguards.

    Future resets beyond the requested end are retained in source identity,
    not introduced into the shorter compiled region. Extension requires
    recompilation from the original source.
    """
    record(source, PhaseResetLfoSource, 'LFO phase-reset source')
    identifier(route_id, 'LFO phase-reset route id')
    require(cancelled is None or callable(cancelled),
            'LFO phase-reset cancellation hook must be callable')

    def check_cancel():
        if cancelled is not None and cancelled():
            raise ClockCancelled('LFO phase-reset compilation cancelled; no partial routes')

    check_cancel()
    end = rational_value(end_s, 'LFO phase-reset end seconds', 0, MAX_TIME_S)
    require(end > 0, 'LFO phase-reset extent must be positive')
    active = tuple(r for r in source.resets if Fraction(r.time_s) < end)
    # For a short preview before the first reset, still emit deterministic
    # direct modulation, with an inactive zero step lane.
    n = len(active)
    step_scale = 1 << max(0, (2*n - 1).bit_length())
    motion_scale = 1 << (2*n).bit_length()
    number(depth, 'LFO phase-reset depth Hz',
           -float(MAX_RATE_HZ) / motion_scale,
           float(MAX_RATE_HZ) / motion_scale)

    lfo = source.lfo
    offset = Fraction(0)
    motion_points: list[Point] = []
    step_points: list[Point] = []
    motion_initial = _triangle(Fraction(lfo.phase_cycles)) / motion_scale
    for i in range(n + 1):
        check_cancel()
        start = Fraction(0) if i == 0 else Fraction(active[i-1].time_s)
        stop = Fraction(active[i].time_s) if i < n else end
        phase = lfo.phase_cycles if i == 0 else active[i-1].phase_cycles
        bpm = Fraction(lfo.base_bpm)
        for point in lfo.tempo_points:
            if Fraction(point.time_s) <= start:
                bpm = Fraction(point.value)
            else:
                break
        tempos = tuple(Point(qtext(Fraction(p.time_s) - start), p.value)
                       for p in lfo.tempo_points if Fraction(p.time_s) > start)
        segment = replace(lfo, origin_s='0/1', phase_cycles=phase,
                          base_bpm=qtext(bpm), tempo_points=tempos)
        # No duplicate value at the reset: the previous segment ends there,
        # and the new continuous residual has exactly that same value.
        if i:
            current = (segment.value_at('0/1') - offset) / motion_scale
            require(bool(motion_points) and
                    Fraction(motion_points[-1].time_s) == start and
                    Fraction(motion_points[-1].value) == current,
                    'LFO reset continuous-residual identity violation')
        lane = segment.compile_route(
            qtext(stop-start), route_id=route_id+'-segment',
            depth=0.0, cancelled=cancelled)
        for p in lane.points:
            check_cancel()
            t = start + Fraction(p.time_s)
            motion_points.append(Point(qtext(t),
                                       qtext((Fraction(p.value)-offset)/motion_scale)))
            require(len(motion_points) <= MAX_POINTS,
                    'LFO phase-reset motion point budget exceeded')
        if i < n:
            old = segment.value_at(qtext(stop-start))
            new = _triangle(Fraction(active[i].phase_cycles))
            offset += new - old
            require(abs(offset) <= step_scale,
                    'LFO phase-reset jump normalization exceeded')
            step_points.append(Point(qtext(stop), qtext(offset / step_scale)))
    check_cancel()
    step_route = ModulationRoute(
        id=route_id+'-phase-jumps', mapping='add_hz',
        depth=depth*step_scale, initial='0/1',
        points=tuple(step_points), interpolation='step')
    motion_route = ModulationRoute(
        id=route_id+'-motion', mapping='add_hz',
        depth=depth*motion_scale, initial=qtext(motion_initial),
        points=tuple(motion_points), interpolation='linear')
    return PhaseResetLfoRoutePair(
        method=METHOD, source_sha256=source.sha256, through_s=qtext(end),
        active_resets=n, routes=(step_route, motion_route))
