"""NYQ-003 opt-in reconstruction character: physical-time nearest/cubic fixtures.

This slice does not advertise prefiltering, sinc, delivery conversion or
numerical convergence. Keep it independent from the legacy bitcrusher/AA paths.
"""
from dataclasses import replace
from decimal import Context, Decimal, localcontext
from fractions import Fraction
import unittest

import numpy as np

from zaaggenz_contracts import ContractError
from zaaggenz_contracts.nyquismic import ClockSpec, Point, SonicSpec, VirtualRate
from zaaggenz_dsp.nyquismic import FrozenInput, SamplerPlan, sampler_evaluation


def prepare(signal, *, reconstruction, rate='11730/1', clock=None, channels=1):
    pcm = FrozenInput.from_pcm(signal, 48000)
    sonic = SonicSpec(reconstruction=reconstruction, channels=channels,
                      clock=clock or ClockSpec(rate=VirtualRate(rate)))
    return SamplerPlan.prepare(pcm, sonic, sampler_evaluation(48000))


class NonuniformReconstructionTests(unittest.TestCase):
    def test_static_nearest_is_time_based_and_left_ties(self):
        x = np.arange(480, dtype=np.float32)
        plan = prepare(x, reconstruction='nearest_time_v1', rate='12000/1')
        actual = plan.render().audio
        # Time-domain midpoints between event captures (four source frames).
        # n=0,1,2 => event 0; n=3..6 => event 4, etc.
        expected = x[np.minimum(((np.arange(480) + 1) // 4) * 4, 476)]
        self.assertEqual(actual[0], 0)
        self.assertEqual(actual[1], 0)
        self.assertEqual(actual[2], 0)
        self.assertEqual(actual[3], 4)
        np.testing.assert_array_equal(actual, expected)

    def test_nonuniform_nearest_midpoint_uses_physical_event_spacing(self):
        x = np.arange(480, dtype=np.float32)
        clock = ClockSpec(rate=VirtualRate('6000/1'),
                          points_hz=(Point('1/200', '18000/1'),),
                          interpolation='linear')
        plan = prepare(x, reconstruction='nearest_time_v1', clock=clock)
        actual = plan.render().audio
        # The reference selection uses physical-time arithmetic and strict
        # half-interval membership, not rounded event display timestamps.
        with localcontext(Context(prec=80)):
            def dec(value):
                return (Decimal(value.numerator) / Decimal(value.denominator)
                        if type(value) is Fraction else value)
            coords = [dec(p) for p in plan._coordinates]
            for n in range(480):
                t = Decimal(n) / Decimal(48000)
                # Event ownership is exact phase membership, not a
                # rounded Decimal80 approximation to an irrational crossing.
                i = plan.clock.capture_count_at(Fraction(n, 48000), inclusive=True) - 1
                if i < 0:
                    expected = 0.
                else:
                    if i + 1 < len(coords) and 2 * (t - coords[i]) > coords[i + 1] - coords[i]:
                        i += 1
                    expected = float(plan.captures[i, 0])
                self.assertAlmostEqual(float(actual[n]), expected, places=10,
                    msg=f'n={n} owner={plan.clock.capture_count_at(Fraction(n, 48000), inclusive=True)-1} '
                        f'current={coords[max(i, 0)]} next={coords[min(max(i,0)+1,len(coords)-1)]}')

    def test_cubic_exact_endpoints_chunk_checkpoint_and_irregular_rate(self):
        t = np.arange(512, dtype=np.float64)
        x = (.45 * np.sin(.13 * t) + .19 * np.cos(.39 * t)).astype(np.float32)
        clock = ClockSpec(rate=VirtualRate('11730/1'),
                          points_hz=(Point('1/200', '17000/1'),),
                          interpolation='linear')
        plan = prepare(x, reconstruction='cubic_time_v1', clock=clock)
        whole = plan.render().audio
        original = prepare(x, reconstruction='linear_time_v1', clock=clock).render().audio
        self.assertTrue(np.isfinite(whole).all())
        self.assertGreater(np.max(np.abs(whole - original)), 1e-7)
        for a, b in ((0, 71), (71, 177), (177, 411), (411, len(x))):
            cp = plan.checkpoint(a)
            piece = plan.render(checkpoint=cp, stop_frame=b)
            np.testing.assert_array_equal(piece.audio, whole[a:b])
            self.assertEqual(piece.checkpoint, plan.checkpoint(b))
        # Grid-aligned event samples are exactly the captured values.
        for idx, first_frame in enumerate(plan._first_frames):
            n = int(first_frame)
            if n < len(whole) and Fraction(n, 48000) == plan._coordinates[idx]:
                self.assertEqual(float(whole[n]), float(plan.captures[idx, 0]))

    def test_independent_cubic_hermite_oracle_on_regular_event_times(self):
        # Four virtual captures at source samples 0,4,8,12; this hand-computed
        # Hermite midpoint uses two neighboring nonlocal secants.
        x = np.zeros(24, dtype=np.float32)
        x[0], x[4], x[8], x[12] = 0, 1, -1, 0
        plan = prepare(x, reconstruction='cubic_time_v1', rate='12000/1')
        result = plan.render().audio
        # At t=6/48000 (halfway between events #1 and #2):
        # slopes: (y2-y0)/8=-1/8, (y3-y1)/8=-1/8
        # Hermite midpoint = .5*(y1+y2) + (m1-m2)*4/8 == 0.
        self.assertAlmostEqual(float(result[6]), 0., places=12)
        self.assertEqual(float(result[4]), 1.)
        self.assertEqual(float(result[8]), -1.)
        self.assertTrue(np.isfinite(result).all())

    def test_stereo_zero_bypass_and_default_identity(self):
        x = np.zeros((93, 2), dtype=np.float32)
        for method in ('nearest_time_v1', 'cubic_time_v1'):
            plan = prepare(x, reconstruction=method, channels=2)
            np.testing.assert_array_equal(plan.render().audio, x)
            changed = replace(plan.spec, bypass=True)
            bypass = SamplerPlan.prepare(plan.source, changed, sampler_evaluation(48000))
            np.testing.assert_array_equal(bypass.render().audio, x)
            self.assertNotEqual(plan.spec.sonic_sha256, replace(plan.spec, reconstruction='hold_v1').sonic_sha256)
        with self.assertRaises(ContractError):
            SonicSpec(reconstruction='future_unverified_sinc_v1')
        self.assertEqual(SonicSpec().reconstruction, 'hold_v1')

    def test_cancelled_cubic_does_not_publish_partial_result(self):
        x = np.linspace(-1, 1, 512, dtype=np.float32)
        plan = prepare(x, reconstruction='cubic_time_v1')
        from zaaggenz_contracts.nyquismic_clock import ClockCancelled
        calls = [0]
        def abort():
            calls[0] += 1
            return calls[0] >= 6
        with self.assertRaises(ClockCancelled):
            plan.render(cancelled=abort)
        self.assertTrue(np.isfinite(plan.render().audio).all())


if __name__ == '__main__':
    unittest.main()
