"""Independent NYQ-002 signal oracle, revision 1.

Only the standard library is used. Source values are the exact binary32 values
passed in by a fixture, not regenerated oscillators. Constant-clock coordinates
are Fractions; other event coordinates come from the separately frozen analytic
clock fixture. Capture and output interpolation are evaluated with Decimal80.

For unit-scale signals, ABS_TOL and REL_TOL are 2e-12. This is a conservative
binary64 arithmetic allowance (over 8,000 machine epsilons), not a fit to a
renderer. Event membership, counts, divisible holds and partition identity are
tested exactly instead. No quality, final-conversion or preference claim follows.
"""
from bisect import bisect_right
from decimal import Decimal, Context, ROUND_FLOOR, localcontext
from fractions import Fraction
from math import ceil

ABS_TOL = 2e-12
REL_TOL = 2e-12
PRECISION = 80


def decimal(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, Fraction):
        return Decimal(value.numerator) / Decimal(value.denominator)
    if isinstance(value, float):
        return Decimal.from_float(value)
    return Decimal(value)


def constant_events(rate, phase, extent, origin=Fraction(0)):
    """Analytic half-open grid, no clock scheduler or period recurrence."""
    rate, phase, extent, origin = map(Fraction, (rate, phase, extent, origin))
    return [origin + (k - phase) / rate
            for k in range(ceil(phase), ceil(phase + rate * extent))]


def _rows(source):
    if not source:
        return []
    if isinstance(source[0], (list, tuple)):
        return [tuple(float(x) for x in row) for row in source]
    return [(float(x),) for x in source]


def _sample(rows, channels, rate, relative_time, capture, boundary):
    position = decimal(relative_time) * rate
    left = int(position.to_integral_value(rounding=ROUND_FLOOR))
    fraction = position - left

    def value(index):
        if not rows:
            return (Decimal(0),) * channels
        if boundary == 'edge_hold':
            index = max(0, min(len(rows) - 1, index))
        if not 0 <= index < len(rows):
            return (Decimal(0),) * channels
        return tuple(Decimal.from_float(v) for v in rows[index])

    if capture == 'nearest_left_tie_v1':
        return value(left + int(fraction > Decimal('0.5')))
    if capture != 'linear_v1':
        raise ValueError('oracle capture policy')
    return tuple(a + fraction * (b - a)
                 for a, b in zip(value(left), value(left + 1)))


def capture_values(source, source_rate, event_times, *, origin=Fraction(0),
                   capture='linear_v1', boundary='zero_pad', channels=1):
    rows = _rows(source)
    with localcontext(Context(prec=PRECISION)):
        origin = decimal(origin)
        return [tuple(float(v) for v in _sample(rows, channels, source_rate,
                      decimal(t) - origin, capture, boundary))
                for t in event_times]


def render(source, source_rate, event_times, output_rate, frame_count, *,
           origin=Fraction(0), capture='linear_v1', reconstruction='hold_v1',
           boundary='zero_pad', channels=1, wet=1.0):
    """Direct mathematical evaluation; does not call a production audio path."""
    rows = _rows(source)
    with localcontext(Context(prec=PRECISION)):
        origin = decimal(origin)
        times = [decimal(t) for t in event_times]
        captured = [_sample(rows, channels, source_rate, t - origin,
                            capture, boundary) for t in times]
        mix = decimal(float(wet))
        result = []
        for n in range(frame_count):
            relative_time = Decimal(n) / output_rate
            at = origin + relative_time
            index = bisect_right(times, at) - 1
            value = (Decimal(0),) * channels if index < 0 else captured[index]
            if reconstruction == 'linear_time_v1' and 0 <= index < len(times) - 1:
                fraction = (at - times[index]) / (times[index + 1] - times[index])
                value = tuple(a + fraction * (b - a)
                              for a, b in zip(value, captured[index + 1]))
            elif reconstruction not in ('hold_v1', 'linear_time_v1'):
                raise ValueError('oracle reconstruction policy')
            if mix != 1:
                dry = _sample(rows, channels, source_rate, relative_time,
                              'linear_v1', boundary)
                value = tuple((1 - mix) * a + mix * b for a, b in zip(dry, value))
            result.append(tuple(float(v) for v in value))
        return result
