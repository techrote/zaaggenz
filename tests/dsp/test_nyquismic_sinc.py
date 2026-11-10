"""NYQ-003 independent static-uniform, windowed-sinc reconstruction evidence.

An opt-in event-stream kernel, not output conversion or numerical convergence.
Uses the frozen legacy source representation and existing sampler job contracts.
"""
from dataclasses import replace
from fractions import Fraction
import unittest

import numpy as np

from zaaggenz_contracts import ContractError
from zaaggenz_contracts.nyquismic import (
    ClockSpec, Point, Reset, ResourceBudget, SonicSpec, VirtualRate,
)
from zaaggenz_contracts.nyquismic_clock import ClockCancelled
from zaaggenz_dsp.nyquismic import FrozenInput, SamplerPlan, sampler_evaluation


def plan(signal, *, method='sinc8_hann_uniform_v1', clock=None, budget=None,
         channels=1, wet=1., bypass=False):
    source = FrozenInput.from_pcm(signal, 48000)
    spec = SonicSpec(clock=clock or ClockSpec(rate=VirtualRate('12000/1')),
                     reconstruction=method, channels=channels, wet=wet,
                     bypass=bypass)
    return SamplerPlan.prepare(source, spec, sampler_evaluation(
        48000, budget or ResourceBudget()))


class UniformSincTests(unittest.TestCase):
    def test_constant_dc_is_exact_at_truncated_kernel_boundaries(self):
        x = np.ones((480, 2), dtype=np.float32)
        p = plan(x, channels=2)
        actual = p.render()
        np.testing.assert_allclose(actual.audio, x, rtol=0, atol=1e-12)
        self.assertEqual(actual.diagnostics['reconstruction_window'],
                         'hann_symmetric_radius_8_v1')
        self.assertEqual(actual.diagnostics['reconstruction_support_events'], 8)
        self.assertTrue(actual.diagnostics['finite'])
        self.assertFalse(actual.diagnostics['delivery_conversion_performed'])

    def test_event_grid_identity_and_chunk_checkpoint_equivalence(self):
        n = np.arange(720, dtype=np.float64)
        x = (0.5 * np.sin(2*np.pi*713*n/48000) +
             0.2 * np.sin(2*np.pi*3110*n/48000)).astype(np.float32)
        p = plan(x)
        all_audio = p.render().audio
        for capture, first in zip(p.captures, p._first_frames):
            frame = int(first)
            if frame < len(x) and Fraction(frame, 48000) in p._coordinates:
                self.assertEqual(float(all_audio[frame]), float(capture[0]))
        chunks = []
        for a, b in ((0, 49), (49, 163), (163, 501), (501, len(x))):
            cp = p.checkpoint(a)
            result = p.render(checkpoint=cp, stop_frame=b)
            self.assertEqual(result.checkpoint, p.checkpoint(b))
            chunks.append(result.audio)
        np.testing.assert_array_equal(np.concatenate(chunks), all_audio)
        self.assertTrue(np.isfinite(all_audio).all())

    def test_sinc_reduces_uniform_hold_image_without_removing_virtual_alias(self):
        n = np.arange(4800)
        tone = np.sin(2 * np.pi * 1000 * n / 48000).astype(np.float32)
        hold = plan(tone, method='hold_v1').render().audio
        filtered = plan(tone).render().audio
        # Coherent 3840-frame interior: 1000 and 11000 Hz land on FFT bins.
        def component(y, hz):
            fragment = y[480:4320]
            return abs(np.fft.rfft(fragment)[int(hz * len(fragment) / 48000)])
        self.assertGreater(component(hold, 11000), 1)
        self.assertLess(component(filtered, 11000),
                        0.35 * component(hold, 11000))
        self.assertGreater(component(filtered, 1000), 0.5 * component(hold, 1000))
        # 7kHz captured at a 12kHz virtual clock folds to 5kHz.
        aliased = np.sin(2 * np.pi * 7000 * n / 48000).astype(np.float32)
        damaged = plan(aliased).render().audio
        self.assertGreater(component(damaged, 5000), 10)

    def test_irregular_clocks_and_undersized_support_fail_before_render(self):
        x = np.zeros(128, dtype=np.float32)
        invalid_clocks = (
            ClockSpec(rate=VirtualRate('12000/1'),
                      points_hz=(Point('1/100', '13000/1'),)),
            ClockSpec(rate=VirtualRate('12000/1'),
                      resets=(Reset('1/100', '0/1'),)),
        )
        for clock in invalid_clocks:
            with self.subTest(clock=clock.sha256), self.assertRaises(ContractError):
                plan(x, clock=clock)
        with self.assertRaises(ContractError):
            plan(x, budget=ResourceBudget(max_filter_taps=16))
        with self.assertRaises(ContractError):
            SonicSpec(reconstruction='sinc8_hann_nonuniform_v1')

    def test_no_change_to_legacy_default_zero_wet_bypass_and_cancellation(self):
        x = np.linspace(-.7, .7, 512, dtype=np.float32)
        self.assertEqual(SonicSpec().reconstruction, 'hold_v1')
        self.assertNotEqual(plan(x).spec.sonic_sha256,
                            plan(x, method='hold_v1').spec.sonic_sha256)
        np.testing.assert_array_equal(plan(x, wet=0).render().audio, x)
        np.testing.assert_array_equal(plan(x, bypass=True).render().audio, x)
        p = plan(x)
        count = [0]
        def abort():
            count[0] += 1
            return count[0] >= 7
        with self.assertRaises(ClockCancelled):
            p.render(cancelled=abort)
        self.assertTrue(np.isfinite(p.render().audio).all())


if __name__ == '__main__':
    unittest.main()
