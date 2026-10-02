"""NYQ-001 independent analytic oracles. No production imports.

Fixture revision 1 is authored before numerical implementation comparisons.
Times and rates below are exact decimal/rational mathematical inputs. Decimal
precision is 80; quadratic roots are computed directly, NOT by a scheduler or
by the production cancellation-safe inverse. Small nonzero slopes are tested
separately using an 80-digit bisection oracle.
"""
from decimal import Decimal, localcontext
from fractions import Fraction
import hashlib
import json
from pathlib import Path

PRECISION = 80
# Absolute 2 ps plus 8 ulps of the absolute timestamp. Counting/epoch/crossing
# identity, endpoint membership and exact rational phases have NO tolerance.
TIME_ABS_TOL_S = 2e-12
TIME_ULPS = 8


def dec(value):
    q = Fraction(str(value))
    return Decimal(q.numerator) / Decimal(q.denominator)


def constant(rate, phase, extent):
    f, p, end = map(Fraction, (rate, phase, extent))
    first = 0 if p == 0 else 1
    rows = []
    for k in range(first, int(p + f * end) + 1):
        t = (k - p) / f
        if t < end:
            rows.append((k, t))
    return rows


def ramp(rate, slope, extent):
    with localcontext() as ctx:
        ctx.prec = PRECISION
        f, a, end = map(dec, (rate, slope, extent))
        rows = []
        for k in range(int(f * end + a * end * end / 2) + 1):
            t = Decimal(k) / f if a == 0 else ((f * f + 2 * a * k).sqrt() - f) / a
            if t < end:
                rows.append((k, +t))
        return rows


def bisected_ramp(rate, slope, phase_target, extent):
    with localcontext() as ctx:
        ctx.prec = PRECISION
        f, a, target, high = map(dec, (rate, slope, phase_target, extent))
        low = Decimal(0)
        for _ in range(260):
            mid = (low + high) / 2
            if f * mid + a * mid * mid / 2 < target:
                low = mid
            else:
                high = mid
        return +(low + high) / 2


def text(q):
    with localcontext() as ctx:
        ctx.prec = PRECISION
        return str(dec(str(q)) if isinstance(q, Fraction) else +q)


def build_fixture():
    cases = []
    for name, rate, phase, extent in (
        ('constant-8', '8', '0', '1'),
        ('fractional-15-over-2', '15/2', '0', '1'),
        ('nonzero-phase', '8', '1/4', '1'),
        ('11730-at-48k-reference', '11730', '0', '1/1000'),
        ('11137-at-48k-reference', '11137', '0', '1/1000'),
        ('ratio-one-third', '16000', '0', '1/1000'),
        ('irrational-like-finite', '1414213562373/100000000', '0', '1/1000'),
        ('below-integer-hold', '159999999/10000', '0', '1/1000'),
        ('above-integer-hold', '160000001/10000', '0', '1/1000'),
    ):
        cases.append(dict(name=name, kind='constant', rate=rate, phase=phase,
                          extent=extent, events=[dict(crossing=k, time_s=text(t))
                                                 for k, t in constant(rate, phase, extent)]))
    for name, rate, slope, extent in (
        ('ramp-up', '4', '8', '1'), ('ramp-down', '12', '-8', '1'),
        ('fractional-ramp', '15/2', '7/3', '1'),
        ('zero-slope', '8', '0', '1'),
    ):
        cases.append(dict(name=name, kind='ramp', rate=rate, slope=slope,
                          extent=extent, events=[dict(crossing=k, time_s=text(t))
                                                 for k, t in ramp(rate, slope, extent)]))
    # Hand-derived, independent piecewise integration: phase=4t up to t=1/2;
    # thereafter phase=2+8(t-1/2). The rate change itself does not reset phase.
    cases.append(dict(name='step-on-crossing', kind='step', rate='4', phase='0',
                      step_time='1/2', next_rate='8', extent='1',
                      events=[dict(crossing=k, time_s=text(Fraction(t))) for k, t in
                              enumerate(('0', '1/4', '1/2', '5/8', '3/4', '7/8'))]))
    # Right-continuous reset replaces the old event at the same time. New epoch
    # phase zero emits one event, not both the old and new crossings.
    cases.append(dict(name='reset-on-crossing', kind='reset', rate='4', phase='0',
                      reset_time='1/2', reset_phase='0', extent='1',
                      events=[dict(epoch=e, crossing=k, time_s=text(Fraction(t))) for e, k, t in
                              ((0, 0, '0'), (0, 1, '1/4'), (1, 0, '1/2'), (1, 1, '3/4'))]))
    cases.append(dict(name='reset-nonzero-phase', kind='reset', rate='4', phase='0',
                      reset_time='1/2', reset_phase='1/4', extent='1',
                      events=[dict(epoch=e, crossing=k, time_s=text(Fraction(t))) for e, k, t in
                              ((0, 0, '0'), (0, 1, '1/4'), (1, 1, '11/16'), (1, 2, '15/16'))]))
    aliases = []
    for tone, rate in (('6000', '8000'), ('2000', '8000'), ('14000', '8000'),
                       ('6000', '15999/2'), ('11730', '11730'), ('4000', '8000')):
        f, v = Fraction(tone), Fraction(rate)
        alias = abs((f + v / 2) % v - v / 2)
        aliases.append(dict(tone_hz=tone, virtual_hz=rate,
                            magnitude_alias_hz=f'{alias.numerator}/{alias.denominator}'))
    return dict(version='nyq.analytic-fixtures.v1', precision_digits=PRECISION,
                time_abs_tolerance_s=TIME_ABS_TOL_S, time_ulps=TIME_ULPS,
                exact=['event-count', 'epoch', 'crossing', 'half-open-membership', 'rational-phase'],
                clock_cases=cases, static_alias_cases=aliases)


def fixture_bytes():
    return (json.dumps(build_fixture(), indent=2, sort_keys=True) + '\n').encode('utf-8')


if __name__ == '__main__':
    # Explicit generator; normal tests compare, never overwrite a frozen fixture.
    import sys
    payload = fixture_bytes()
    if len(sys.argv) != 2:
        raise SystemExit('usage: nyquismic_oracles.py NEW_OUTPUT_PATH')
    with Path(sys.argv[1]).open('xb') as out:
        out.write(payload)
    print(hashlib.sha256(payload).hexdigest())
