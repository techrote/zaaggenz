"""NYQ-003 opt-in final numerical conversion component, independent oracles.

This does not qualify the real export path, production convergence gate,
Nyquismic graph integration or a universal 'cleaner sounds better' claim.
"""
import hashlib
import unittest
from unittest.mock import patch

import numpy as np

from zaaggenz_contracts import ContractError
from zaaggenz_contracts.nyquismic import ResourceBudget
from zaaggenz_contracts.nyquismic_clock import ClockCancelled
from zaaggenz_dsp.nyquismic_delivery import (
    METHOD, DeliveryConversionPolicy, convert_numerical_to_delivery,
)


def rms(values):
    return float(np.sqrt(np.mean(np.square(values))))


class DeliveryConversionTests(unittest.TestCase):
    def test_identity_has_no_hidden_gain_or_channel_rewrite(self):
        times = np.arange(47, dtype=np.float64)
        stereo = np.column_stack((np.sin(times / 7), -np.cos(times / 11)))
        stereo[0, 0] = -0.
        result = convert_numerical_to_delivery(stereo, 48000, 48000)
        np.testing.assert_array_equal(result.audio, stereo)
        self.assertTrue(np.signbit(result.audio[0,0]))
        self.assertFalse(result.audio.flags.writeable)
        self.assertEqual(result.diagnostics['kernel_taps'], 1)
        self.assertEqual(result.diagnostics['ratio_up'], 1)
        self.assertEqual(result.diagnostics['ratio_down'], 1)
        self.assertEqual(result.diagnostics['method'], METHOD)
        self.assertEqual(result.audio.shape, (47,2))

    def test_kaiser_fir_preserves_passband_and_rejects_evaluation_clock_alias(self):
        rate = 192000
        t = np.arange(19200, dtype=np.float64) / rate
        low = np.sin(2 * np.pi * 1000 * t)
        high = np.sin(2 * np.pi * 36000 * t)
        low_result = convert_numerical_to_delivery(low, rate, 48000)
        high_result = convert_numerical_to_delivery(high, rate, 48000)
        self.assertEqual(low_result.audio.shape, (4800,))
        self.assertEqual(low_result.diagnostics['kernel_taps'], 97)
        interior = slice(250, -250)
        self.assertGreater(rms(low_result.audio[interior]), .65)
        self.assertLess(rms(high_result.audio[interior]), .01)
        self.assertEqual(
            low_result.diagnostics['kernel_sha256'],
            convert_numerical_to_delivery(low, rate, 48000).diagnostics['kernel_sha256'])
        self.assertNotEqual(low_result.diagnostics['policy_sha256'], '')

    def test_nonlinear_difference_product_survives_when_conversion_is_last(self):
        rate = 192000
        t = np.arange(19200, dtype=np.float64) / rate
        # Neither 28 kHz nor 33 kHz enters 48 kHz delivery bandwidth.
        # A nonlinear square in the numerical island creates a 5 kHz
        # difference product which IS in-band. Pre-trimming both parents
        # would incorrectly erase that intentional musical interaction.
        parents = (.5 * np.sin(2*np.pi*28000*t) +
                   .5 * np.sin(2*np.pi*33000*t))
        after_nonlinearity = convert_numerical_to_delivery(
            parents * parents, rate, 48000).audio
        wrongly_pretrimmed = convert_numerical_to_delivery(
            parents, rate, 48000).audio ** 2
        interior = slice(250,-250)
        self.assertGreater(rms(after_nonlinearity[interior] -
                               np.mean(after_nonlinearity[interior])), .1)
        self.assertLess(rms(wrongly_pretrimmed[interior]), .001)

    def test_finite_stereo_zero_and_partial_terminal_extent(self):
        silence = np.zeros((101, 2), dtype=np.float32)
        result = convert_numerical_to_delivery(silence, 192000, 48000)
        self.assertEqual(result.audio.shape, (26, 2))
        self.assertTrue(np.isfinite(result.audio).all())
        np.testing.assert_array_equal(result.audio, np.zeros((26, 2)))
        self.assertEqual(result.diagnostics['output_frames'], 26)
        for sample in (np.zeros((0,2), dtype=np.float64),
                       np.zeros(0, dtype=np.float64)):
            actual = convert_numerical_to_delivery(sample, 192000, 48000)
            self.assertEqual(actual.audio.shape, sample.shape)
        policy = DeliveryConversionPolicy()
        self.assertEqual(DeliveryConversionPolicy.from_json(policy.to_json()), policy)
        self.assertEqual(policy.sha256, DeliveryConversionPolicy().sha256)
        self.assertEqual(result.diagnostics['policy_sha256'], policy.sha256)

    def test_rejects_unqualified_ratios_and_nonfinite_unbounded_inputs(self):
        source = np.ones(256, dtype=np.float64)
        invalid_cases = (
            (source, 48000, 96000, None),
            (source, 192000, 44100, None),  # 15,361 taps > 4096
            (source, 192000, 48000, ResourceBudget(max_filter_taps=96)),
            (source, 192000, 48000, ResourceBudget(max_frames=100)),
            (np.full(32, float('nan')), 48000, 48000, None),
            (np.ones(32, dtype=np.int16), 48000, 48000, None),
            (np.ones((32, 3), dtype=np.float64), 48000, 48000, None),
        )
        for signal, numeric_hz, delivery_hz, budget in invalid_cases:
            with self.subTest(rate=(numeric_hz,delivery_hz),
                              shape=signal.shape), self.assertRaises(ContractError):
                convert_numerical_to_delivery(
                    signal, numeric_hz, delivery_hz,
                    **({'budget': budget} if budget else {}))
        with self.assertRaises(ContractError):
            DeliveryConversionPolicy(boundary='edge_hold')
        with self.assertRaises(ContractError):
            DeliveryConversionPolicy(clipping='hard_clip')
        with self.assertRaises(ContractError):
            DeliveryConversionPolicy.from_dict(
                {**DeliveryConversionPolicy().to_dict(), 'new_unknown': True})
        with self.assertRaises(ContractError):
            convert_numerical_to_delivery(source, True, 48000)

    def test_mutable_caller_pcm_cannot_replace_checked_fir_input(self):
        # The converter used to give SciPy the caller's float64 array directly.
        # Simulate a hostile/concurrent owner mutation exactly at the external
        # DSP boundary. The declared conversion must process its OWN snapshot.
        from scipy.signal import resample_poly
        rate = 192000
        t = np.arange(960, dtype=np.float64) / rate
        caller = (0.3 * np.sin(2 * np.pi * 1200 * t) +
                  0.1 * np.cos(2 * np.pi * 4200 * t))
        accepted = caller.copy()
        expected = convert_numerical_to_delivery(accepted, rate, 48000)
        original = resample_poly
        calls = []

        def mutate_caller_then_convert(pcm, up, down, **kwargs):
            calls.append((up, down, np.shares_memory(pcm, caller)))
            caller[:] = 0.0
            return original(pcm, up, down, **kwargs)

        with patch('scipy.signal.resample_poly', new=mutate_caller_then_convert):
            actual = convert_numerical_to_delivery(caller, rate, 48000)
        self.assertEqual(calls, [(1, 4, False)])
        self.assertTrue(np.all(caller == 0.0))
        np.testing.assert_array_equal(actual.audio, expected.audio)
        self.assertFalse(actual.audio.flags.writeable)
        self.assertEqual(actual.diagnostics['source_frames'], 960)
        self.assertEqual(actual.diagnostics['kernel_sha256'],
                         expected.diagnostics['kernel_sha256'])
        self.assertEqual(actual.diagnostics['source_pcm_sha256'],
                         expected.diagnostics['source_pcm_sha256'])
        self.assertEqual(actual.diagnostics['output_pcm_sha256'],
                         expected.diagnostics['output_pcm_sha256'])

    def test_delivered_physical_alias_survives_without_implicit_virtual_cleaning(self):
        # A real 6 kHz source sampled on an 8 kHz physical event lattice
        # produces a 2 kHz alias. Delivery anti-aliasing must remove
        # numerical-grid foldover, not undo the ALREADY CAPTURED dirty alias.
        # A separate explicitly selected source prefilter may attenuate it.
        from dataclasses import replace
        from zaaggenz_contracts.nyquismic import (
            ClockSpec, SonicSpec, VirtualRate, GUARDED_CLEAN_PREFILTER,
        )
        from zaaggenz_dsp.nyquismic import (
            FrozenInput, SamplerPlan, sampler_evaluation,
        )
        source = FrozenInput.from_pcm(
            np.sin(2 * np.pi * 6000 * np.arange(12000) / 48000).astype('<f4'),
            48000,
        )
        dirty = SonicSpec(clock=ClockSpec(rate=VirtualRate('8000/1')),
                          reconstruction='hold_v1', prefilter='off_v1')
        guarded = replace(dirty, prefilter=GUARDED_CLEAN_PREFILTER)

        def amplitude_at_2000_hz(audio):
            # 0.05..0.2 seconds is a coherent 7,200-frame comparison window,
            # excluding physical start/end and FIR edge transients.
            interior = audio[2400:9600]
            return float(2 * abs(np.fft.rfft(interior)[300]) / len(interior))

        amplitudes = []
        for evaluation_rate in (192000, 384000):
            captures = []
            outputs = []
            for sonic in (dirty, guarded):
                plan = SamplerPlan.prepare(
                    source, sonic, sampler_evaluation(evaluation_rate),
                    frame_count=evaluation_rate // 4,
                )
                numerical = plan.render().audio
                final = convert_numerical_to_delivery(
                    numerical, evaluation_rate, 48000)
                self.assertEqual(final.audio.shape, (12000,))
                self.assertEqual(final.diagnostics['source_pcm_sha256'],
                                 hashlib.sha256(np.asarray(
                                     numerical, dtype='<f8').tobytes()).hexdigest())
                self.assertEqual(final.diagnostics['output_pcm_sha256'],
                                 hashlib.sha256(np.asarray(
                                     final.audio, dtype='<f8').tobytes()).hexdigest())
                self.assertFalse(final.audio.flags.writeable)
                captures.append(plan._coordinates)
                outputs.append(final.audio)
            self.assertEqual(captures[0], captures[1])
            aliased = amplitude_at_2000_hz(outputs[0])
            cleaned = amplitude_at_2000_hz(outputs[1])
            self.assertGreater(aliased, .75)
            self.assertLess(cleaned, .03)
            amplitudes.append(aliased)
        self.assertLess(abs(amplitudes[0] - amplitudes[1]), .02)

    def test_cancellation_can_abort_before_and_after_atomic_calculation(self):
        source = np.arange(512, dtype=np.float64)
        with self.assertRaises(ClockCancelled):
            convert_numerical_to_delivery(
                source, 192000, 48000, cancelled=lambda: True)
        checks = [0]
        def cancel_at_publication():
            checks[0] += 1
            return checks[0] == 2
        with self.assertRaises(ClockCancelled):
            convert_numerical_to_delivery(
                source, 192000, 48000, cancelled=cancel_at_publication)
        self.assertEqual(checks[0], 2)
        self.assertTrue(np.isfinite(
            convert_numerical_to_delivery(source, 192000, 48000).audio).all())


if __name__ == '__main__':
    unittest.main()


class SamplerDeliveryBridgeTests(unittest.TestCase):
    """Real sampled/converted PCM; not product WAV or Compose integration."""

    def test_virtual_alias_survives_actual_final_pcm_at_two_evaluation_rates(self):
        from dataclasses import replace
        from zaaggenz_contracts.nyquismic import (
            ClockSpec, SonicSpec, VirtualRate, GUARDED_CLEAN_PREFILTER)
        from zaaggenz_dsp.nyquismic import FrozenInput
        from zaaggenz_dsp.nyquismic_delivery import render_sampler_to_delivery

        t = np.arange(4800, dtype=np.float64) / 48000
        src = FrozenInput.from_pcm(
            np.sin(2 * np.pi * 6000 * t).astype('<f4'), 48000)
        dirty = SonicSpec(clock=ClockSpec(rate=VirtualRate('8000/1')),
                          prefilter='off_v1', reconstruction='hold_v1')
        clean = replace(dirty, prefilter=GUARDED_CLEAN_PREFILTER)
        amplitudes = []
        for rate in (192000, 384000):
            a = render_sampler_to_delivery(src, dirty, numerical_rate_hz=rate)
            b = render_sampler_to_delivery(src, clean, numerical_rate_hz=rate)
            self.assertEqual(a.audio.shape, (4800,))
            self.assertFalse(a.audio.flags.writeable)
            self.assertEqual(a.diagnostics['event_count'], 800)
            self.assertEqual(a.diagnostics['clock_sha256'],
                             b.diagnostics['clock_sha256'])
            for out in (a, b):
                self.assertEqual(out.diagnostics['sampler']['pcm_sha256'],
                                 out.diagnostics['delivery']['source_pcm_sha256'])
                self.assertEqual(out.diagnostics['output_pcm_sha256'],
                                 hashlib.sha256(np.asarray(
                                     out.audio, dtype='<f8').tobytes()).hexdigest())
                self.assertFalse(out.diagnostics['product_export_verified'])
            def fold(signal):
                interior = signal[1200:3600]
                return 2 * abs(np.fft.rfft(interior)[100]) / len(interior)
            self.assertGreater(fold(a.audio), .75)
            self.assertLess(fold(b.audio), .03)
            amplitudes.append(fold(a.audio))
        self.assertLess(abs(amplitudes[0] - amplitudes[1]), .02)

    def test_stereo_empty_alignment_budget_and_cancellation(self):
        from zaaggenz_contracts.nyquismic import ClockSpec, SonicSpec, VirtualRate
        from zaaggenz_dsp.nyquismic import FrozenInput
        from zaaggenz_dsp.nyquismic_delivery import render_sampler_to_delivery

        n = np.arange(96, dtype=np.float64)
        s = np.sin(2 * np.pi * 500 * n / 48000).astype('<f4')
        source = FrozenInput.from_pcm(np.column_stack((s, -s)), 48000)
        spec = SonicSpec(channels=2, clock=ClockSpec(rate=VirtualRate('12000/1')))
        actual = render_sampler_to_delivery(source, spec, numerical_rate_hz=192000)
        self.assertEqual(actual.audio.shape, (96, 2))
        np.testing.assert_allclose(actual.audio[:,0], -actual.audio[:,1],
                                   rtol=0, atol=1e-13)
        empty = FrozenInput.from_pcm(np.zeros((0, 2), dtype='<f4'), 48000)
        self.assertEqual(render_sampler_to_delivery(
            empty, spec, numerical_rate_hz=192000).audio.shape, (0, 2))
        with self.assertRaises(ContractError):
            render_sampler_to_delivery(source, spec, numerical_rate_hz=192000,
                                       delivery_rate_hz=44100)
        with self.assertRaises(ContractError):
            render_sampler_to_delivery(source, spec, numerical_rate_hz=32000)
        with self.assertRaises(ContractError):
            render_sampler_to_delivery(source, spec, numerical_rate_hz=192000,
                                       budget=ResourceBudget(max_frames=100))
        unaligned = FrozenInput.from_pcm(np.zeros(95, dtype='<f4'), 44100)
        with self.assertRaises(ContractError):
            render_sampler_to_delivery(unaligned, SonicSpec(clock=ClockSpec(
                rate=VirtualRate('11025/1'))), numerical_rate_hz=192000)
        with self.assertRaises(ClockCancelled):
            render_sampler_to_delivery(source, spec, numerical_rate_hz=192000,
                                       cancelled=lambda: True)
