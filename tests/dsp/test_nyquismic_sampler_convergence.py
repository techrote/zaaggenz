"""NYQ-003 actual physical-time sampler and frozen three-rate PCM comparator."""
import unittest

import numpy as np

from zaaggenz_contracts import ContractError
from zaaggenz_contracts.nyquismic import (
    ClockSpec, Point, ResourceBudget, SonicSpec, VirtualRate,
)
from zaaggenz_contracts.nyquismic_clock import ClockCancelled
from zaaggenz_dsp.nyquismic import FrozenInput
from zaaggenz_dsp.nyquismic_convergence import evaluate_sampler_convergence
from zaaggenz_dsp.nyquismic_sampler_convergence import (
    METHOD as LEGACY_BRIDGE_METHOD, evaluate_sampler_model_convergence,
)
from unittest.mock import patch
from zaaggenz_dsp.nyquismic_delivery import render_sampler_to_delivery

RATES = (192000, 384000, 768000)


def input_pcm(n=4800, stereo=False):
    t = np.arange(n, dtype=np.float64) / 48000
    # Deliberate 6 kHz -> 2 kHz alias at an 8 kHz virtual capture clock.
    left = np.sin(2 * np.pi * 6000 * t) + .12 * np.sin(2 * np.pi * 530 * t)
    if stereo:
        return FrozenInput.from_pcm(np.column_stack(
            (left, .4 * left + .21 * np.sin(2 * np.pi * 1200 * t))).astype('<f4'), 48000)
    return FrozenInput.from_pcm(left.astype('<f4'), 48000)


class RealSamplerConvergenceTests(unittest.TestCase):
    def test_real_dirty_alias_and_original_ledger_across_three_rates(self):
        source = input_pcm()
        sonic = SonicSpec(clock=ClockSpec(rate=VirtualRate('8000/1')))
        result = evaluate_sampler_convergence(source, sonic)
        d = result.diagnostics
        self.assertEqual(d['passes'], 3)
        self.assertEqual(d['rates_hz'], list(RATES))
        self.assertEqual(d['event_counts_by_rate'], [800] * 3)
        self.assertEqual(len(set(d['event_ledger_sha256_by_rate'])), 1)
        self.assertEqual(d['frozen_source_pcm_sha256'],
                         source.asset.to_dict()['content_sha256'])
        self.assertTrue(d['physical_event_geometry_equal'])
        self.assertFalse(d['analytic_oracle_verified'])
        self.assertFalse(d['product_export_verified'])
        self.assertFalse(d['nyq004_adapter_qualified'])
        self.assertEqual(result.selected_audio is not None, result.status == 'converged')
        # The highest comparator's exact delivered PCM digest must agree with
        # a separate actual sampler -> delivery execution.
        direct = render_sampler_to_delivery(source, sonic, numerical_rate_hz=RATES[-1])
        self.assertEqual(d['candidate_conversion'][-1]['output_pcm_sha256'],
                         direct.diagnostics['output_pcm_sha256'])
        self.assertGreater(float(2 * abs(np.fft.rfft(direct.audio)[200]) /
                                 len(direct.audio)), .3)

    def test_irregular_stereo_lattice_remains_identical_across_grid_rates(self):
        source = input_pcm(1440, stereo=True)
        sonic = SonicSpec(channels=2, reconstruction='linear_time_v1',
                          clock=ClockSpec(rate=VirtualRate('8000/1'),
                              points_hz=(Point('1/100', '12000/1'),)))
        result = evaluate_sampler_convergence(source, sonic)
        d = result.diagnostics
        self.assertEqual(len(set(d['event_ledger_sha256_by_rate'])), 1)
        self.assertEqual(len(set(d['event_counts_by_rate'])), 1)
        self.assertGreater(d['event_counts_by_rate'][0], 240)
        self.assertEqual([row['output_frames'] for row in
                          d['candidate_conversion']], [1440] * 3)
        self.assertEqual(result.selected_audio is not None, result.status == 'converged')

    def test_unaligned_extent_budget_and_source_channels_refuse(self):
        spec = SonicSpec(clock=ClockSpec(rate=VirtualRate('8000/1')))
        with self.assertRaisesRegex(ContractError, 'integral numerical extents'):
            evaluate_sampler_convergence(FrozenInput.from_pcm(
                np.ones(1, dtype='<f4'), 44100), spec)
        with self.assertRaisesRegex(ContractError, 'frame budget'):
            evaluate_sampler_convergence(input_pcm(), spec,
                                         budget=ResourceBudget(max_frames=4000))
        with self.assertRaises(ContractError):
            evaluate_sampler_convergence(input_pcm(stereo=True), spec)

    def test_legacy_bridge_is_one_authoritative_sampler_comparator(self):
        # The two historic entrypoints must not privately disagree on which
        # frozen source, physical crossings or delivered PCM were qualified.
        source = input_pcm(960, stereo=True)
        spec = SonicSpec(channels=2, clock=ClockSpec(rate=VirtualRate('8000/1')))
        canonical = evaluate_sampler_convergence(source, spec)
        legacy = evaluate_sampler_model_convergence(source, spec)
        self.assertEqual(legacy.status, canonical.status)
        self.assertEqual(legacy.diagnostics['compatibility_entrypoint'],
                         LEGACY_BRIDGE_METHOD)
        self.assertEqual(legacy.diagnostics['source_sha256'],
                         canonical.diagnostics['source_sha256'])
        self.assertEqual(legacy.diagnostics['exact_event_ledger_sha256'],
                         canonical.diagnostics['exact_event_ledger_sha256'])
        self.assertEqual(legacy.diagnostics['numerical_pcm_sha256_by_rate'],
                         canonical.diagnostics['numerical_pcm_sha256_by_rate'])
        self.assertEqual([d['output_pcm_sha256'] for d in
                          legacy.diagnostics['candidate_conversion']],
                         [d['output_pcm_sha256'] for d in
                          canonical.diagnostics['candidate_conversion']])
        self.assertEqual(legacy.selected_audio is None,
                         canonical.selected_audio is None)
        if canonical.selected_audio is not None:
            np.testing.assert_array_equal(legacy.selected_audio,
                                          canonical.selected_audio)

    def test_legacy_bridge_refuses_wrong_delivery_or_pass_budget_before_audio(self):
        source = input_pcm(480)
        spec = SonicSpec(clock=ClockSpec(rate=VirtualRate('8000/1')))
        with patch('zaaggenz_dsp.nyquismic.SamplerPlan.prepare',
                   side_effect=AssertionError('must not prepare sampler')):
            with self.assertRaisesRegex(ContractError, 'delivery rate must match'):
                evaluate_sampler_model_convergence(
                    source, spec, delivery_rate_hz=44100)
            with self.assertRaisesRegex(ContractError, 'pass budget exceeded'):
                evaluate_sampler_model_convergence(
                    source, spec, budget=ResourceBudget(max_reference_passes=2))
            with self.assertRaisesRegex(ContractError, 'pass budget exceeded'):
                evaluate_sampler_convergence(
                    source, spec, budget=ResourceBudget(max_reference_passes=2))

    def test_cancellation_and_no_synthetic_success_for_silence(self):
        spec = SonicSpec(clock=ClockSpec(rate=VirtualRate('8000/1')))
        with self.assertRaises(ClockCancelled):
            evaluate_sampler_convergence(input_pcm(), spec, cancelled=lambda: True)
        silent = FrozenInput.from_pcm(np.zeros(480, dtype='<f4'), 48000)
        result = evaluate_sampler_convergence(silent, spec)
        self.assertEqual(result.status, 'inconclusive')
        self.assertIsNone(result.selected_audio)


if __name__ == '__main__':
    unittest.main()
