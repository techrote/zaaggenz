"""NYQ-003 short-support static windowed sinc: independent math and actual PCM.

This opt-in artistic reconstruction must preserve captured aliases; it does
not qualify ordinary Compose, product WAV export or a universal clean filter.
"""
import math
import unittest

import numpy as np

from zaaggenz_contracts import ContractError
from zaaggenz_contracts.nyquismic import (
    ClockSpec, Point, Reset, ResourceBudget, SonicSpec, VirtualRate,
)
from zaaggenz_dsp.nyquismic import FrozenInput, SamplerPlan, sampler_evaluation
from zaaggenz_dsp.nyquismic_delivery import render_sampler_to_delivery


SHORT = 'sinc4_hann_uniform_v1'
LONG = 'sinc8_hann_uniform_v1'


def prepared(pcm, *, method=SHORT, channels=1, clock=None, budget=None,
             wet=1.0, bypass=False):
    source = FrozenInput.from_pcm(pcm, 48000)
    sonic = SonicSpec(clock=clock or ClockSpec(rate=VirtualRate('12000/1')),
                      reconstruction=method, channels=channels,
                      wet=wet, bypass=bypass)
    return SamplerPlan.prepare(source, sonic,
                               sampler_evaluation(48000, budget or ResourceBudget()))


class ShortHannSincTests(unittest.TestCase):
    def test_fractional_output_matches_independently_expanded_radius_four_kernel(self):
        # Event k captures source frame 4*k, exactly. Compare the output at
        # t=10.25 event intervals to a separate finite sine formula.
        pcm = np.zeros(384, dtype=np.float32)
        pcm[::4] = [((k * 7) % 17 - 8) / 8 for k in range(96)]
        short = prepared(pcm)
        long = prepared(pcm, method=LONG)
        owner, fraction, frame = 10, 0.25, 41
        weighted, dc = 0.0, 0.0
        for offset in range(-3, 5):
            x = fraction - offset
            kernel = (math.sin(math.pi * x) / (math.pi * x)) * (
                0.5 + 0.5 * math.cos(math.pi * x / 4))
            weighted += float(pcm[4 * (owner + offset)]) * kernel
            dc += kernel
        expected = weighted / dc
        self.assertAlmostEqual(float(short.render().audio[frame]), expected, delta=1e-12)
        self.assertGreater(abs(float(short.render().audio[frame]) -
                               float(long.render().audio[frame])), 0.02)
        self.assertEqual(short.render().diagnostics['reconstruction_window'],
                         'hann_symmetric_radius_4_v1')
        self.assertEqual(short.render().diagnostics['reconstruction_support_events'], 4)
        self.assertNotEqual(short.spec.sonic_sha256, long.spec.sonic_sha256)
        self.assertEqual(SonicSpec.from_json(short.spec.to_json()), short.spec)

    def test_truncated_dc_stereo_region_and_exact_bypass(self):
        constant = np.ones((480, 2), dtype=np.float32)
        plan = prepared(constant, channels=2)
        whole = plan.render().audio
        np.testing.assert_allclose(whole, constant, rtol=0, atol=1e-12)
        regions = [plan.render(0, 71).audio,
                   plan.render(checkpoint=plan.checkpoint(71), stop_frame=287).audio,
                   plan.render(checkpoint=plan.checkpoint(287)).audio]
        np.testing.assert_array_equal(np.concatenate(regions), whole)
        np.testing.assert_array_equal(prepared(constant, channels=2, wet=0).render().audio,
                                      constant)
        np.testing.assert_array_equal(prepared(constant, channels=2, bypass=True).render().audio,
                                      constant)

    def test_uniform_mode_rejects_irregular_clock_and_insufficient_support(self):
        source = np.zeros(768, dtype=np.float32)
        for clock in (ClockSpec(rate=VirtualRate('12000/1'),
                                points_hz=(Point('1/100', '13000/1'),)),
                      ClockSpec(rate=VirtualRate('12000/1'),
                                resets=(Reset('1/100', '0/1'),))):
            with self.subTest(clock=clock.sha256), self.assertRaises(ContractError):
                prepared(source, clock=clock)
        with self.assertRaises(ContractError):
            prepared(source, budget=ResourceBudget(max_filter_taps=8))
        self.assertEqual(prepared(source, budget=ResourceBudget(max_filter_taps=9)).spec.reconstruction,
                         SHORT)
        with self.assertRaises(ContractError):
            SonicSpec(reconstruction='sinc4_hann_nonuniform_v1')
        self.assertEqual(SonicSpec().reconstruction, 'hold_v1')

    def test_real_dirty_virtual_alias_reaches_48khz_pcm_at_two_numerical_rates(self):
        # An 8 kHz *capture* clock folds the source's 6 kHz sinusoid to 2 kHz.
        # The short sinc may suppress images but must not erase that 2 kHz alias.
        n = np.arange(4800, dtype=np.float64)
        source = FrozenInput.from_pcm(np.sin(2 * np.pi * 6000 * n / 48000).astype(np.float32),
                                      48000)
        sonic = SonicSpec(clock=ClockSpec(rate=VirtualRate('8000/1')),
                          reconstruction=SHORT)
        for rate in (192000, 384000):
            with self.subTest(rate=rate):
                result = render_sampler_to_delivery(source, sonic, numerical_rate_hz=rate)
                self.assertEqual(result.audio.shape, (4800,))
                self.assertEqual(result.diagnostics['numerical_rate_hz'], rate)
                self.assertEqual(result.diagnostics['delivery_rate_hz'], 48000)
                self.assertEqual(result.diagnostics['sonic_sha256'], sonic.sonic_sha256)
                self.assertFalse(result.diagnostics['convergence_qualified'])
                self.assertFalse(result.diagnostics['product_export_verified'])
                self.assertTrue(np.isfinite(result.audio).all())
                interior = result.audio[480:4320]
                alias_magnitude = abs(np.fft.rfft(interior)[160])
                self.assertGreater(alias_magnitude, 100,
                                   'delivery filter silently removed the virtual 2 kHz alias')


if __name__ == '__main__':
    unittest.main()
