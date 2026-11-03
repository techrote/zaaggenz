"""NYQ-003 physical-time irregular-event Shepard/Hann reconstruction contract tests.

This explicitly non-bandlimited interpolation is not a uniform-grid sinc or a
final delivery-rate conversion. All comparisons use the same immutable source.
"""
from dataclasses import replace
from fractions import Fraction
from decimal import Context, Decimal, localcontext
import math
import unittest

import numpy as np

from zaaggenz_contracts import ContractError
from zaaggenz_contracts.nyquismic import ClockSpec, Point, ResourceBudget, SonicSpec, VirtualRate
from zaaggenz_contracts.nyquismic_clock import ClockCancelled
from zaaggenz_dsp.nyquismic import FrozenInput, SamplerPlan, sampler_evaluation


METHOD = 'shepard8_hann_local_time_v1'


def make(signal, *, clock=None, channels=1, reconstruction=METHOD, budget=None, wet=1.0):
    source = FrozenInput.from_pcm(signal, 48000)
    spec = SonicSpec(clock=clock or ClockSpec(rate=VirtualRate('12000/1')),
                     channels=channels, reconstruction=reconstruction, wet=wet)
    return SamplerPlan.prepare(source, spec, sampler_evaluation(
        48000, budget or ResourceBudget()))


def expected_local_capture(plan, frame):
    """Independent scalar/reference implementation of positive local weights."""
    t = Fraction(frame, 48000)
    times = plan._coordinates
    def dec(v):
        return (Decimal(v.numerator) / Decimal(v.denominator)
                if type(v) is Fraction else v)
    k0 = plan.clock.capture_count_at(t, inclusive=True) - 1
    if k0 < 0:
        return 0.0
    if k0 >= len(times) - 1:
        return float(plan.captures[k0, 0])
    with localcontext(Context(prec=80)):
        if dec(t) == dec(times[k0]):
            return float(plan.captures[k0, 0])
        weighted = 0.0
        mass = 0.0
        for k in range(max(0, k0 - 8), min(len(times), k0 + 9)):
            if k == 0:
                scale = dec(times[1]) - dec(times[0])
            elif k == len(times) - 1:
                scale = dec(times[-1]) - dec(times[-2])
            else:
                scale = (dec(times[k+1]) - dec(times[k-1])) / 2
            x = float((dec(t) - dec(times[k])) / scale)
            if x == 0:
                return float(plan.captures[k, 0])
            if abs(x) < 8:
                w = (1 + math.cos(math.pi * x / 8)) / (2 * x * x)
                mass += w
                weighted += w * float(plan.captures[k, 0])
    if not mass:
        raise AssertionError('missing nonuniform kernel mass')
    return weighted / mass


class LocalTimeShepardTests(unittest.TestCase):
    def clock(self):
        return ClockSpec(rate=VirtualRate('6000/1'),
                         points_hz=(Point('1/240', '16000/1'),),
                         interpolation='linear')

    def test_irregular_event_clock_independent_oracle_and_exact_captures(self):
        x = np.sin(np.arange(720) * .17).astype(np.float32)
        p = make(x, clock=self.clock())
        actual = p.render()
        self.assertTrue(np.isfinite(actual.audio).all())
        for frame in (0, 1, 14, 50, 101, 133, 171, 201, 255, 315, 470, 611, 700):
            self.assertAlmostEqual(float(actual.audio[frame]),
                                   expected_local_capture(p, frame), places=10)
        for k, at in enumerate(p._coordinates):
            frame = int(at * 48000)
            if frame < len(x) and at == Fraction(frame, 48000):
                self.assertEqual(float(actual.audio[frame]), float(p.captures[k, 0]))
        self.assertEqual(actual.diagnostics['reconstruction_support_events'], 8)
        self.assertEqual(actual.diagnostics['reconstruction_window'],
                         'hann_symmetric_radius_8_local_shepard_inverse_square_v1')
        self.assertFalse(actual.diagnostics['delivery_conversion_performed'])

    def test_nonuniform_dc_stereo_chunk_and_identity_preservation(self):
        x = np.ones((720, 2), dtype=np.float32)
        p = make(x, clock=self.clock(), channels=2)
        whole = p.render().audio
        # The existing zero_pad *source capture* interpolator can ramp down
        # at the excluded source endpoint. It is not the reconstruction's
        # responsibility to turn those non-DC captures into constant ones.
        # Assert unity DC in the full-context interior, and finite bounded
        # fade caused by the already admitted source boundary policy.
        np.testing.assert_allclose(whole[32:-64], x[32:-64], rtol=0, atol=1e-12)
        self.assertTrue(np.isfinite(whole).all())
        self.assertGreaterEqual(float(np.min(whole)), 0)
        self.assertLessEqual(float(np.max(whole)), 1 + 1e-12)
        split = [p.render(checkpoint=p.checkpoint(a), stop_frame=b).audio
                 for a, b in ((0, 29), (29, 154), (154, 430), (430, len(x)))]
        np.testing.assert_array_equal(np.concatenate(split), whole)
        self.assertNotEqual(p.spec.sonic_sha256,
                            replace(p.spec, reconstruction='hold_v1').sonic_sha256)
        np.testing.assert_array_equal(make(x, clock=self.clock(), channels=2, wet=0).render().audio, x)
        bypass = replace(p.spec, bypass=True)
        np.testing.assert_array_equal(SamplerPlan.prepare(p.source, bypass,
                               sampler_evaluation(48000)).render().audio, x)

    def test_kernel_not_uniform_sinc_and_output_is_bounded_by_captures(self):
        x = (np.sin(.21 * np.arange(720)) + .25 * np.cos(.41 * np.arange(720))).astype(np.float32)
        p = make(x, clock=self.clock())
        result = p.render().audio
        hold = make(x, clock=self.clock(), reconstruction='hold_v1').render().audio
        self.assertGreater(float(np.max(np.abs(result - hold))), 1e-5)
        self.assertLessEqual(float(np.max(result)), float(np.max(p.captures)) + 1e-12)
        self.assertGreaterEqual(float(np.min(result)), min(0, float(np.min(p.captures))) - 1e-12)
        self.assertTrue(np.isfinite(result).all())

    def test_short_empty_silent_and_bounded_admission(self):
        for x in (np.empty(0, dtype=np.float32), np.zeros(1, dtype=np.float32),
                  np.zeros(17, dtype=np.float32)):
            p = make(x)
            self.assertTrue(np.isfinite(p.render().audio).all())
            self.assertEqual(len(p.render().audio), len(x))
        with self.assertRaises(ContractError):
            make(np.zeros(120, dtype=np.float32), budget=ResourceBudget(max_filter_taps=16))
        with self.assertRaises(ContractError):
            SonicSpec(reconstruction='unqualified_nonuniform_sinc_v1')

    def test_cancel_before_publication_then_recover(self):
        p = make(np.arange(2200, dtype=np.float32), clock=self.clock())
        calls = [0]
        def stop():
            calls[0] += 1
            return calls[0] >= 8
        with self.assertRaises(ClockCancelled):
            p.render(cancelled=stop)
        self.assertEqual(len(p.render().audio), 2200)


if __name__ == '__main__':
    unittest.main()
