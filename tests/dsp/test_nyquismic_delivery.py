"""NYQ-003 opt-in final numerical conversion component, independent oracles.

This does not qualify the real export path, production convergence gate,
Nyquismic graph integration or a universal 'cleaner sounds better' claim.
"""
from dataclasses import replace
import unittest

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
        np.testing.assert_array_equal(result.audio, 0.)
        self.assertEqual(result.diagnostics['output_frames'], 26)
        for sample in (np.zeros((0,2), dtype=np.float64),
                       np.zeros(0, dtype=np.float64)):
            actual = convert_numerical_to_delivery(sample, 192000, 48000)
            self.assertEqual(actual.audio.shape, sample.shape)
        policy = DeliveryConversionPolicy()
        self.assertEqual(DeliveryConversionPolicy.from_json(policy.to_json()), policy)
        self.assertNotEqual(
            policy.sha256,
            replace(policy, version='nyq.delivery-conversion.v1').sha256 + 'X')

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
