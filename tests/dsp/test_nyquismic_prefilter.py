"""NYQ-003 static FIR virtual prefilter: analytic attenuation and edge evidence.

This verifies a named opt-in capture-stage filter, not final conversion,
modulated cutoff tracking or instrument/rack availability.
"""
from dataclasses import replace
import unittest

import numpy as np

from zaaggenz_contracts import ContractError
from zaaggenz_contracts.nyquismic import (
    ClockSpec, Point, ResourceBudget, SonicSpec, VirtualRate,
)
from zaaggenz_contracts.nyquismic_clock import ClockCancelled
from zaaggenz_dsp.nyquismic import FrozenInput, SamplerPlan, sampler_evaluation


FILTER = 'fir33_hann_static_0p45_v1'


def prepare(source, *, policy=FILTER, rate='8000/1', budget=None, points=()):
    pcm = FrozenInput.from_pcm(source, 48000)
    spec = SonicSpec(prefilter=policy, clock=ClockSpec(
        rate=VirtualRate(rate), points_hz=points))
    return SamplerPlan.prepare(pcm, spec,
                               sampler_evaluation(48000, budget or ResourceBudget()))


class StaticFIRPrefilterTests(unittest.TestCase):
    def test_high_frequency_folded_tone_is_primarily_suppressed_before_capture(self):
        time = np.arange(4800, dtype=np.float64) / 48000
        high = np.sin(2 * np.pi * 11000 * time).astype(np.float32)
        dirty = prepare(high, policy='off_v1').captures[:, 0]
        filtered = prepare(high).captures[:, 0]
        rms = lambda data: float(np.sqrt(np.mean(data[20:-20] ** 2)))
        self.assertGreater(rms(dirty), .65)
        self.assertLess(rms(filtered), .1 * rms(dirty))
        self.assertTrue(np.isfinite(filtered).all())

    def test_passband_and_zero_phase_impulse_support(self):
        time = np.arange(4800, dtype=np.float64) / 48000
        low = np.sin(2 * np.pi * 900 * time).astype(np.float32)
        dirty = prepare(low, policy='off_v1').captures[:, 0]
        filtered = prepare(low).captures[:, 0]
        self.assertLess(float(np.max(np.abs(filtered[20:-20] - dirty[20:-20]))), .08)
        impulse = np.zeros(512, dtype=np.float32)
        impulse[96] = 1.
        plan = prepare(impulse)
        self.assertAlmostEqual(float(plan.captures[15, 0]),
                               float(plan.captures[17, 0]), places=14)
        self.assertGreater(abs(float(plan.captures[15, 0])), 0)
        self.assertGreater(abs(float(plan.captures[16, 0])), 0)
        self.assertTrue(np.isfinite(plan.render().audio).all())

    def test_identity_is_opt_in_and_serialized_without_source_mutation(self):
        x = np.linspace(-.5, .5, 480, dtype=np.float32)
        source = FrozenInput.from_pcm(x, 48000)
        spec = SonicSpec(prefilter=FILTER, clock=ClockSpec(
            rate=VirtualRate('8000/1')))
        self.assertEqual(SonicSpec.from_json(spec.to_json()), spec)
        self.assertEqual(SonicSpec().prefilter, 'off_v1')
        self.assertNotEqual(spec.sonic_sha256,
                            replace(spec, prefilter='off_v1').sonic_sha256)
        original = source.pcm.tobytes()
        plan = SamplerPlan.prepare(source, spec, sampler_evaluation(48000))
        full = plan.render().audio
        for a, b in ((0, 71), (71, 201), (201, 480)):
            np.testing.assert_array_equal(plan.render(a, b).audio, full[a:b])
        self.assertEqual(source.pcm.tobytes(), original)
        diag = plan.render().diagnostics
        self.assertEqual(diag['prefilter'], FILTER)
        self.assertEqual(diag['prefilter_support_source_frames'], 16)
        self.assertEqual(diag['prefilter_cutoff_hz'], 3600)
        self.assertEqual(len(diag['prefilter_coefficients_sha256']), 64)
        for identity in (replace(spec, wet=0.), replace(spec, bypass=True)):
            dry_plan = SamplerPlan.prepare(source, identity, sampler_evaluation(48000))
            np.testing.assert_array_equal(dry_plan.render().audio, x)

    def test_reject_unsupported_dynamic_cutoff_and_budget_before_execution(self):
        x = np.zeros(480, dtype=np.float32)
        with self.assertRaises(ContractError):
            prepare(x, points=(Point('1/200', '7000/1'),))
        with self.assertRaises(ContractError):
            prepare(x, rate='48000/1')
        with self.assertRaises(ContractError):
            prepare(x, budget=ResourceBudget(max_filter_taps=16))
        with self.assertRaises(ClockCancelled):
            SamplerPlan.prepare(
                FrozenInput.from_pcm(x, 48000),
                SonicSpec(prefilter=FILTER, clock=ClockSpec(rate=VirtualRate('8000/1'))),
                sampler_evaluation(48000), cancelled=lambda: True,
            )

    def test_empty_stereo_and_boundary_padding_are_finite(self):
        silence = np.zeros((93, 2), dtype=np.float32)
        source = FrozenInput.from_pcm(silence, 48000)
        for boundary in ('zero_pad', 'edge_hold'):
            spec = SonicSpec(prefilter=FILTER, channels=2,
                             input_boundary=boundary,
                             clock=ClockSpec(rate=VirtualRate('8000/1')))
            plan = SamplerPlan.prepare(source, spec, sampler_evaluation(48000))
            np.testing.assert_array_equal(plan.render().audio, silence)
        empty = prepare(np.zeros(0, dtype=np.float32))
        self.assertEqual(empty.render().audio.size, 0)

    def test_named_cutoff_and_strength_are_separate_opt_in_sonic_choices(self):
        n = 4800
        time = np.arange(n, dtype=np.float64) / 48000
        high = np.sin(2 * np.pi * 11000 * time).astype(np.float32)
        dry = prepare(high, policy='off_v1').captures[:, 0]
        wide = prepare(high, policy=FILTER).captures[:, 0]
        narrow_plan = prepare(high, policy='fir33_hann_static_0p30_v1')
        half_plan = prepare(high, policy='fir33_hann_static_0p45_mix0p5_v1')
        narrow = narrow_plan.captures[:, 0]
        half = half_plan.captures[:, 0]
        # A 50% wet FIR is exactly the 50/50 source-filter blend for a
        # linear capture operator; no hidden amplitude normalization.
        np.testing.assert_allclose(half, (dry + wide) / 2, atol=2e-14, rtol=0)
        self.assertGreater(np.max(np.abs(dry[20:-20] - wide[20:-20])), .1)
        self.assertGreater(np.max(np.abs(dry[20:-20] - half[20:-20])), .05)
        self.assertNotEqual(narrow_plan.spec.sonic_sha256, half_plan.spec.sonic_sha256)
        self.assertNotEqual(narrow_plan.render().diagnostics['prefilter_coefficients_sha256'],
                            half_plan.render().diagnostics['prefilter_coefficients_sha256'])
        self.assertEqual(narrow_plan.render().diagnostics['prefilter_cutoff_hz'], 2400)
        self.assertEqual(half_plan.render().diagnostics['prefilter_cutoff_hz'], 3600)
        self.assertEqual(half_plan.render().diagnostics['prefilter_strength'], .5)
        for plan in (narrow_plan, half_plan):
            full = plan.render().audio
            np.testing.assert_array_equal(
                np.concatenate([plan.render(0, 117).audio,
                                plan.render(117, 2401).audio,
                                plan.render(2401, n).audio]), full)
            self.assertEqual(SonicSpec.from_json(plan.spec.to_json()), plan.spec)
        with self.assertRaises(ContractError):
            SonicSpec(prefilter='fir33_hann_static_0p12_v1')

    def test_named_cutoff_changes_spectral_character_without_touching_bypass(self):
        time = np.arange(4800, dtype=np.float64) / 48000
        signal = np.sin(2 * np.pi * 3000 * time).astype(np.float32)
        narrow = prepare(signal, policy='fir33_hann_static_0p30_v1').captures[:, 0]
        wide = prepare(signal, policy=FILTER).captures[:, 0]
        self.assertGreater(float(np.sqrt(np.mean((narrow[20:-20] -
                                                   wide[20:-20]) ** 2))), 1e-3)
        original = FrozenInput.from_pcm(signal, 48000)
        for policy in ('fir33_hann_static_0p30_v1',
                       'fir33_hann_static_0p45_mix0p5_v1'):
            spec = SonicSpec(prefilter=policy, wet=0.)
            plan = SamplerPlan.prepare(original, spec, sampler_evaluation(48000))
            np.testing.assert_array_equal(plan.render().audio, signal)

    def test_source_fir_blocks_match_full_context_convolution_bit_for_bit(self):
        from fractions import Fraction
        from unittest.mock import patch
        from zaaggenz_dsp.nyquismic import _fir33_kernel, _prefilter_static_source
        frames = 17031  # cross two 8192-frame boundaries and a short tail
        positions = np.arange(frames, dtype=np.float64)
        source = np.column_stack((
            np.sin(positions / 13), np.cos(positions / 19))).astype(np.float32)
        kernel, _ = _fir33_kernel(48000, Fraction(8000), FILTER)
        actual_convolve = np.convolve
        for boundary in ('edge_hold', 'zero_pad'):
            with self.subTest(boundary=boundary):
                padded = np.pad(source.astype(np.float64),
                                ((16, 16), (0, 0)),
                                mode='edge' if boundary == 'edge_hold' else 'constant')
                expected = np.column_stack([
                    actual_convolve(padded[:, channel], kernel, mode='valid')
                    for channel in range(2)])
                visited = []
                def bounded_convolve(signal, taps, mode):
                    visited.append(len(signal))
                    self.assertLessEqual(len(signal), 8192 + 32)
                    return actual_convolve(signal, taps, mode=mode)
                with patch('zaaggenz_dsp.nyquismic.np.convolve',
                           side_effect=bounded_convolve):
                    actual = _prefilter_static_source(source, kernel, boundary)
                np.testing.assert_array_equal(actual, expected)
                self.assertEqual(len(visited), 6)  # 3 windows * 2 channels

    def test_source_fir_cancels_before_processing_remaining_windows(self):
        from fractions import Fraction
        from unittest.mock import patch
        from zaaggenz_dsp.nyquismic import _fir33_kernel, _prefilter_static_source
        source = np.zeros((60000, 2), dtype=np.float32)
        kernel, _ = _fir33_kernel(48000, Fraction(8000), FILTER)
        actual_convolve = np.convolve
        calls = []
        windows = []
        def cancelled():
            calls.append(True)
            return len(calls) == 4
        def instrumented(signal, taps, mode):
            windows.append(len(signal))
            return actual_convolve(signal, taps, mode=mode)
        with patch('zaaggenz_dsp.nyquismic.np.convolve',
                   side_effect=instrumented):
            with self.assertRaises(ClockCancelled):
                _prefilter_static_source(source, kernel, 'zero_pad',
                                         cancelled=cancelled)
        self.assertEqual(len(calls), 4)
        self.assertEqual(windows, [8192 + 32, 8192 + 32])


    def test_guarded_kaiser_comparison_suppresses_near_fold_without_erasing_bass(self):
        from zaaggenz_contracts.nyquismic import GUARDED_CLEAN_PREFILTER
        time = np.arange(4800, dtype=np.float64) / 48000
        high = np.sin(2 * np.pi * 5000 * time).astype(np.float32)
        narrow_legacy = prepare(high, policy=FILTER).captures[:, 0]
        guarded_plan = prepare(high, policy=GUARDED_CLEAN_PREFILTER)
        guarded = guarded_plan.captures[:, 0]
        rms = lambda x: float(np.sqrt(np.mean(x[24:-24] ** 2)))
        self.assertGreater(rms(narrow_legacy), .05)
        self.assertLess(rms(guarded), .02 * rms(narrow_legacy))
        low = np.sin(2 * np.pi * 900 * time).astype(np.float32)
        clean_low = prepare(low, policy=GUARDED_CLEAN_PREFILTER).captures[:, 0]
        dirty_low = prepare(low, policy='off_v1').captures[:, 0]
        self.assertLess(np.max(np.abs(clean_low[24:-24] - dirty_low[24:-24])), .005)
        diag = guarded_plan.render().diagnostics
        self.assertEqual(diag['prefilter_cutoff_hz'], 3200)
        self.assertEqual(diag['prefilter_support_source_frames'], 64)
        self.assertEqual(diag['prefilter_window'], 'kaiser_beta10_129_v1')
        self.assertEqual(diag['prefilter_strength'], 1.0)
        self.assertEqual(len(diag['prefilter_coefficients_sha256']), 64)
        self.assertEqual(SonicSpec.from_json(guarded_plan.spec.to_json()),
                         guarded_plan.spec)
        self.assertEqual(SonicSpec().prefilter, 'off_v1')

    def test_guarded_kernel_stereo_context_and_checkpoint_equivalence(self):
        from fractions import Fraction
        from zaaggenz_contracts.nyquismic import GUARDED_CLEAN_PREFILTER
        from zaaggenz_dsp.nyquismic import (
            _static_fir_kernel, _prefilter_static_source)
        n = 17031
        frames = np.arange(n, dtype=np.float64)
        stereo = np.column_stack((np.sin(frames / 17),
                                  np.cos(frames / 23))).astype(np.float32)
        taps, cutoff = _static_fir_kernel(48000, Fraction(8000),
                                          GUARDED_CLEAN_PREFILTER)
        self.assertEqual(len(taps), 129)
        self.assertEqual(cutoff, Fraction(3200))
        self.assertAlmostEqual(np.sum(taps), 1., places=14)
        self.assertTrue(np.array_equal(taps, taps[::-1]))
        for boundary in ('zero_pad', 'edge_hold'):
            with self.subTest(boundary=boundary):
                padded = np.pad(stereo.astype(np.float64),
                                ((64, 64), (0, 0)),
                                mode='constant' if boundary == 'zero_pad' else 'edge')
                expected = np.column_stack([
                    np.convolve(padded[:, channel], taps, mode='valid')
                    for channel in range(2)])
                actual = _prefilter_static_source(stereo, taps, boundary)
                np.testing.assert_array_equal(actual, expected)
        spec = SonicSpec(channels=2, prefilter=GUARDED_CLEAN_PREFILTER,
                         clock=ClockSpec(rate=VirtualRate('8000/1')))
        plan = SamplerPlan.prepare(FrozenInput.from_pcm(stereo[:512], 48000),
                                   spec, sampler_evaluation(48000))
        full = plan.render().audio
        np.testing.assert_array_equal(
            np.concatenate((plan.render(0, 149).audio,
                            plan.render(149, 512).audio)), full)
        np.testing.assert_array_equal(
            plan.render(checkpoint=plan.checkpoint(149)).audio,
            full[149:])

    def test_guarded_filter_admission_and_bypass_are_fail_closed(self):
        from zaaggenz_contracts.nyquismic import GUARDED_CLEAN_PREFILTER
        source = FrozenInput.from_pcm(
            np.linspace(-1, 1, 480, dtype=np.float32), 48000)
        def spec(rate, **changes):
            return SonicSpec(prefilter=GUARDED_CLEAN_PREFILTER,
                             clock=ClockSpec(rate=VirtualRate(rate)), **changes)
        for rate in ('4000/1', '30000/1'):
            with self.subTest(rate=rate), self.assertRaises(ContractError):
                SamplerPlan.prepare(source, spec(rate), sampler_evaluation(48000))
        with self.assertRaises(ContractError):
            SamplerPlan.prepare(source, spec('8000/1'),
                                sampler_evaluation(48000, ResourceBudget(max_filter_taps=128)))
        with self.assertRaises(ContractError):
            SamplerPlan.prepare(source, SonicSpec(prefilter=GUARDED_CLEAN_PREFILTER,
                clock=ClockSpec(rate=VirtualRate('8000/1'),
                                points_hz=(Point('1/200', '7000/1'),))),
                sampler_evaluation(48000))
        for dry in (spec('8000/1', bypass=True), spec('8000/1', wet=0.)):
            np.testing.assert_array_equal(
                SamplerPlan.prepare(source, dry, sampler_evaluation(48000)).render().audio,
                source.pcm)
        with self.assertRaises(ClockCancelled):
            SamplerPlan.prepare(source, spec('8000/1'), sampler_evaluation(48000),
                                cancelled=lambda: True)



if __name__ == '__main__':
    unittest.main()
