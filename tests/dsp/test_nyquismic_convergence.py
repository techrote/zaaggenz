"""NYQ-003 independent optional 3-rate convergence and rejection evidence."""
import unittest

import numpy as np

from zaaggenz_contracts import ContractError
from zaaggenz_contracts.nyquismic import ResourceBudget
from zaaggenz_contracts.nyquismic_clock import ClockCancelled
from zaaggenz_dsp.nyquismic_convergence import (
    METHOD, FrozenConvergencePolicy, NumericalCandidate,
    evaluate_local_convergence,
)

HASHES = dict(source_sha256='1' * 64, sonic_sha256='2' * 64,
              clock_sha256='3' * 64, random_control_sha256='4' * 64)
RATES = (192000, 384000, 768000)


def candidate(rate, *, corrupt=False):
    # Fixed physical duration, fixed 1 kHz artistic signal. No clock-alias
    # rate shift may be introduced by changing the evaluation rate.
    t = np.arange(rate // 50, dtype=np.float64) / rate
    signal = np.sin(2 * np.pi * 1000 * t)
    if corrupt and rate == RATES[-1]:
        signal = signal + .25
    return NumericalCandidate(rate, signal, **HASHES)


class FrozenConvergenceTests(unittest.TestCase):
    def test_frozen_zero_oracle_and_full_snapshot(self):
        policy = FrozenConvergencePolicy()
        self.assertEqual(FrozenConvergencePolicy.from_json(policy.to_json()), policy)
        def zeros(rate):
            return NumericalCandidate(rate, np.zeros(rate // 50), **HASHES)
        result = evaluate_local_convergence(zeros, policy=policy, **HASHES)
        self.assertEqual(result.status, 'inconclusive')
        self.assertEqual(result.diagnostics['method'], METHOD)
        self.assertEqual(result.diagnostics['rates_hz'], list(RATES))
        self.assertIsNone(result.selected_audio)
        for pair in result.diagnostics['successive_metrics']:
            self.assertEqual(pair['relative_rms'], 0)
            self.assertEqual(pair['relative_spectrum'], 0)
            self.assertEqual(pair['relative_transient'], 0)
            self.assertTrue(pair['null_signal'])
            self.assertFalse(pair['within_limits'])
        self.assertFalse(result.diagnostics['analytic_oracle_verified'])
        self.assertFalse(result.diagnostics['product_export_verified'])

    def test_silent_reference_with_spurious_output_does_not_pass(self):
        def spuriously_nonzero(rate):
            # The final numerical rate has a visible DC error; the earlier
            # silent comparison is independently null/inconclusive.
            frames = rate // 50
            audio = np.zeros(frames, dtype=np.float64)
            if rate == RATES[-1]:
                audio[frames // 2] = .001
            return NumericalCandidate(rate, audio, **HASHES)
        result = evaluate_local_convergence(spuriously_nonzero, **HASHES)
        self.assertEqual(result.status, 'inconclusive')
        self.assertIsNone(result.selected_audio)
        self.assertTrue(result.diagnostics['successive_metrics'][0]['null_signal'])
        self.assertFalse(result.diagnostics['successive_metrics'][0]['within_limits'])
        self.assertFalse(result.diagnostics['successive_metrics'][1]['within_limits'])

    def test_relative_metrics_do_not_erase_quiet_numerical_errors(self):
        # An absolute 1e-12 denominator floor made these nonzero signals
        # appear numerically identical despite a full-scale relative error.
        from zaaggenz_dsp.nyquismic_convergence import _metrics
        reference = np.sin(2 * np.pi * np.arange(128) / 128)
        full = _metrics(reference * 1.1, reference)
        for amplitude in (1e-18, 1e-250):
            with self.subTest(amplitude=amplitude):
                quiet = _metrics(reference * 1.1 * amplitude,
                                 reference * amplitude)
                for field in ('relative_rms', 'relative_spectrum',
                              'relative_transient'):
                    self.assertAlmostEqual(quiet[field], full[field], places=10)
                self.assertFalse(quiet['null_signal'])
                self.assertEqual(quiet['zero_reference_metrics'], ())

        def lost_at_highest_rate(rate):
            pcm = np.full(rate // 50, 1e-18, dtype=np.float64)
            if rate == RATES[-1]:
                pcm.fill(0.)
            return NumericalCandidate(rate, pcm, **HASHES)
        result = evaluate_local_convergence(lost_at_highest_rate, **HASHES)
        self.assertEqual(result.status, 'inconclusive')
        self.assertIsNone(result.selected_audio)
        last = result.diagnostics['successive_metrics'][-1]
        self.assertFalse(last['within_limits'])
        self.assertGreaterEqual(last['relative_rms'], .99)
        self.assertIn('rms', last['zero_reference_metrics'])
        self.assertIn('spectrum', last['zero_reference_metrics'])

    def test_undefined_transient_reference_must_not_pass_at_limit_one(self):
        from zaaggenz_dsp.nyquismic_convergence import _metrics
        flat = np.full(128, 1e-250, dtype=np.float64)
        changed = flat.copy()
        changed[64] *= 2
        metrics = _metrics(changed, flat)
        self.assertIn('transient', metrics['zero_reference_metrics'])
        self.assertGreater(metrics['relative_transient'], 0)

    def test_analytic_tone_stays_in_physical_frequency_and_bounded(self):
        result = evaluate_local_convergence(candidate, **HASHES,
            policy=FrozenConvergencePolicy(
                relative_rms_limit=.12,
                relative_spectrum_limit=.12,
                relative_transient_limit=.25))
        self.assertEqual(result.status, 'converged')
        actual = result.selected_audio
        self.assertGreater(float(np.sqrt(np.mean(actual**2))), .6)
        self.assertEqual(actual.shape, (960,))
        self.assertEqual(result.diagnostics['passes'], 3)
        self.assertEqual(result.diagnostics['candidate_conversion'][0]['ratio_down'], 4)

    def test_last_comparator_mismatch_cannot_publish_qualified_pcm(self):
        result = evaluate_local_convergence(
            lambda rate: candidate(rate, corrupt=True), **HASHES,
            policy=FrozenConvergencePolicy(
                relative_rms_limit=.1,
                relative_spectrum_limit=.1,
                relative_transient_limit=.2))
        self.assertEqual(result.status, 'inconclusive')
        self.assertIsNone(result.selected_audio)
        self.assertFalse(result.diagnostics['successive_metrics'][-1]['within_limits'])

    def test_empty_extent_is_explicitly_inconclusive_not_fft_error(self):
        def empty(rate):
            return NumericalCandidate(rate, np.zeros((0, 2)), **HASHES)
        result = evaluate_local_convergence(empty, **HASHES)
        self.assertEqual(result.status, 'inconclusive')
        self.assertIsNone(result.selected_audio)
        self.assertEqual(result.diagnostics['passes'], 3)
        self.assertTrue(all(x['empty_extent'] and not x['within_limits']
                            for x in result.diagnostics['successive_metrics']))

    def test_identity_extent_and_rate_switches_fail_closed(self):
        for callback in (
            lambda r: NumericalCandidate(r + 1, np.zeros(r // 50), **HASHES),
            lambda r: NumericalCandidate(r, np.zeros(r // 50),
                  **{**HASHES, 'clock_sha256': '0' * 64}),
            lambda r: NumericalCandidate(r, np.zeros(r // 50 + (r == RATES[-1])), **HASHES),
            lambda r: NumericalCandidate(r, np.full(r // 50, np.nan), **HASHES),
        ):
            with self.subTest(callback=callback), self.assertRaises(ContractError):
                evaluate_local_convergence(callback, **HASHES)
        with self.assertRaises(ContractError):
            evaluate_local_convergence(candidate, **HASHES,
                budget=ResourceBudget(max_frames=100))
        with self.assertRaises(ContractError):
            evaluate_local_convergence(candidate, **{**HASHES, 'source_sha256': 'invalid'})

    def test_policy_bounds_and_no_implicit_rate_estimation(self):
        for rates in ((192000, 192000, 384000),
                      (192000, 384000),
                      (384000, 192000, 768000),
                      (48000, 384000, 768000, 1536000, 3072000)):
            with self.assertRaises(ContractError):
                FrozenConvergencePolicy(rates_hz=rates)
        with self.assertRaises(ContractError):
            FrozenConvergencePolicy(relative_rms_limit=float('nan'))
        with self.assertRaises(ContractError):
            FrozenConvergencePolicy.from_dict({**FrozenConvergencePolicy().to_dict(),
                                                'extra': 1})
        with self.assertRaises(ContractError):
            evaluate_local_convergence(candidate, delivery_rate_hz=192000,
                policy=FrozenConvergencePolicy(rates_hz=(48000, 96000, 192000)), **HASHES)

    def test_all_conversion_ratios_are_preflighted_before_render(self):
        calls = [0]
        def expensive(rate):
            calls[0] += 1
            return candidate(rate)
        with self.assertRaises(ContractError):
            evaluate_local_convergence(
                expensive, delivery_rate_hz=44100, **HASHES)
        self.assertEqual(calls[0], 0)
        with self.assertRaises(ContractError):
            evaluate_local_convergence(
                expensive, budget=ResourceBudget(max_filter_taps=96), **HASHES)
        self.assertEqual(calls[0], 0)

    def test_cancellation_aborts_without_promoting_partial_results(self):
        with self.assertRaises(ClockCancelled):
            evaluate_local_convergence(candidate, cancelled=lambda: True, **HASHES)
        counts = [0]
        def after_first():
            counts[0] += 1
            return counts[0] >= 3
        with self.assertRaises(ClockCancelled):
            evaluate_local_convergence(candidate, cancelled=after_first, **HASHES)
        self.assertGreaterEqual(counts[0], 3)


if __name__ == '__main__':
    unittest.main()
