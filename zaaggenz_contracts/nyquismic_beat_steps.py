"""NYQ-004 exact musical beat-grid steps into the existing physical-clock routes.

This opt-in source compiles a looping step pattern at cumulative *musical beat*
boundaries under a piecewise-constant physical-time tempo map. No step is
scheduled on a render-block grid, and a tempo change does not reset the beat
phase or the virtual capture clock. Product graph registration is separate.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from fractions import Fraction

from .nyquismic import (
    MAX_POINTS, MAX_TIME_S, ModulationRoute, Point, UnsupportedNyquismic, _Record, identifier,
    integer, qtext, rational_value, record, require,
)
from .nyquismic_clock import ClockCancelled

METHOD = 'nyq.beat-grid-step-source.v1'
_MAX_STEPS = 32


@dataclass(frozen=True)
class BeatStepSource(_Record):
    """Immutable repeating beat-synchronised control with explicit tempo.

    Levels are normalized, exact rational values in [-1, 1]. A step is held
    until the next cumulative step-beat boundary; the first level owns the
    physical origin. Tempo changes preserve accumulated beat position and
    do not manufacture a trigger by themselves. Before a delayed origin,
    the compiled route is neutral zero.
    """
    version: str = METHOD
    origin_s: str = '0/1'
    base_bpm: str = '120/1'
    tempo_points: tuple[Point, ...] = ()
    step_beats: str = '1/2'
    levels: tuple[str, ...] = ('-1/1', '1/1')
    phase_steps: int = 0
    _children = {'tempo_points': (Point,)}

    def __post_init__(self):
        require(self.version == METHOD, 'unsupported musical beat-step method')
        origin = rational_value(self.origin_s, 'beat-step origin seconds', 0, MAX_TIME_S)
        bpm = rational_value(self.base_bpm, 'beat-step BPM', 20, 360)
        width = rational_value(self.step_beats, 'beat-step duration beats',
                               Fraction(1, 1024), 64)
        require(type(self.levels) is tuple and 1 <= len(self.levels) <= _MAX_STEPS,
                'beat-step level count must be 1..32')
        values = tuple(qtext(rational_value(level, 'beat-step normalized level', -1, 1))
                       for level in self.levels)
        integer(self.phase_steps, 'beat-step pattern phase', 0, len(values) - 1)
        require(type(self.tempo_points) is tuple and len(self.tempo_points) <= MAX_POINTS,
                'beat-step tempo point budget exceeded')
        previous = origin
        for point in self.tempo_points:
            record(point, Point, 'beat-step tempo point')
            stamp = Fraction(point.time_s)
            require(stamp > previous, 'beat-step tempo times must increase after origin')
            rational_value(point.value, 'beat-step tempo BPM', 20, 360)
            previous = stamp
        object.__setattr__(self, 'origin_s', qtext(origin))
        object.__setattr__(self, 'base_bpm', qtext(bpm))
        object.__setattr__(self, 'step_beats', qtext(width))
        object.__setattr__(self, 'levels', values)

    @classmethod
    def from_dict(cls, data):
        require(type(data) is dict and set(data) == {f.name for f in fields(cls)},
                'beat-step source requires complete versioned fields')
        require(type(data['tempo_points']) is list and type(data['levels']) is list,
                'beat-step tempo and level arrays required')
        return cls(**{**data,
                      'tempo_points': tuple(Point.from_dict(v) for v in data['tempo_points']),
                      'levels': tuple(data['levels'])})

    def _beats_at(self, time: Fraction) -> Fraction:
        start = Fraction(self.origin_s)
        bpm = Fraction(self.base_bpm)
        beats = Fraction(0)
        for point in self.tempo_points:
            at = Fraction(point.time_s)
            if at > time:
                break
            beats += bpm * (at - start) / 60
            start, bpm = at, Fraction(point.value)
        return beats + bpm * (time - start) / 60

    def value_at(self, time_s: str) -> Fraction:
        """Exact right-continuous step value at physical time >= origin."""
        time = rational_value(time_s, 'beat-step sample seconds',
                              Fraction(self.origin_s), MAX_TIME_S)
        position = self._beats_at(time) // Fraction(self.step_beats)
        return Fraction(self.levels[(self.phase_steps + position) % len(self.levels)])

    def compile_route(self, end_s: str, *, route_id: str, depth: float,
                      mapping: str = 'add_hz', cancelled=None) -> ModulationRoute:
        """Freeze tempo-integrated steps as an additive-Hz or integral-octave route.

        The emitted lane is exact on [0, end_s]. Compiling a shorter preview
        produces the same route prefix as a full render. A final endpoint
        transition, when present, documents the right-continuous end state.
        All budget/cancellation failure occurs before route publication.
        """
        identifier(route_id, 'beat-step route ID')
        require(mapping in ('add_hz', 'log2_ratio'),
                'beat-step route mapping must be add_hz or log2_ratio')
        require(cancelled is None or callable(cancelled),
                'beat-step cancellation hook must be callable')

        def check_cancel():
            if cancelled is not None and cancelled():
                raise ClockCancelled('beat-step compilation cancelled; no partial route')

        check_cancel()
        origin = Fraction(self.origin_s)
        end = rational_value(end_s, 'beat-step end seconds', origin, MAX_TIME_S)
        width = Fraction(self.step_beats)
        first_level = Fraction(self.levels[self.phase_steps])
        points: list[Point] = []
        if origin > 0:
            require(end >= origin, 'beat-step source has not reached its origin')
            points.append(Point(qtext(origin), qtext(first_level)))
        tempo = [(origin, Fraction(self.base_bpm))]
        tempo += [(Fraction(p.time_s), Fraction(p.value)) for p in self.tempo_points
                  if Fraction(p.time_s) < end]
        beats = Fraction(0)
        for i, (a, bpm) in enumerate(tempo):
            check_cancel()
            b = tempo[i+1][0] if i+1 < len(tempo) else end
            if b == a:
                continue
            complete = beats + bpm * (b-a) / 60
            first = beats // width + 1
            last = complete // width
            count = max(0, last - first + 1)
            require(count <= MAX_POINTS - len(points),
                    'beat-step exact transition budget exceeded; no decimation')
            for k in range(first, last+1):
                if ((k-first) & 31) == 0:
                    check_cancel()
                at = a + (k*width - beats) * 60 / bpm
                require(a < at <= b, 'beat-step physical transition outside tempo interval')
                level = Fraction(self.levels[(self.phase_steps+k) % len(self.levels)])
                points.append(Point(qtext(at), qtext(level)))
            beats = complete
        check_cancel()
        route = ModulationRoute(
            id=route_id, mapping=mapping, depth=depth,
            initial='0/1' if origin else qtext(first_level),
            points=tuple(points), interpolation='step',
        )
        if mapping == 'log2_ratio':
            # The existing exact event compiler supports integer-octave
            # step exponents, not fractional powers or exponential ramps.
            # Validate *every saved pattern level*, including values outside
            # this particular preview, so no unqualified route is published.
            for level in self.levels:
                exponent = Fraction.from_float(route.depth) * Fraction(level)
                if exponent.denominator != 1:
                    raise UnsupportedNyquismic(
                        'beat-step octave control requires exact integral log2 '
                        'exponents at every saved level; no implicit rounding')
        check_cancel()
        return route
