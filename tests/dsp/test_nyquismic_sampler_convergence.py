"""NYQ-003 real NYQ-002 sampler-backed numerical convergence tests."""
import unittest
import hashlib
from fractions import Fraction

import numpy as np

from zaaggenz_contracts import ContractError
from zaaggenz_contracts.nyquismic import (
    ClockSpec, ResourceBudget, SonicSpec, VirtualRate, ModulationRoute,
)
from zaaggenz_contracts.nyquismic_clock import ClockCancelled
from zaaggenz_dsp.nyquismic import FrozenInput, SamplerPlan, sampler_evaluation
from zaaggenz_dsp.nyquismic_delivery import convert_numerical_to_delivery
from zaaggenz_dsp.nyquismic_sampler_convergence import (
    METHOD, evaluate_sampler_model_convergence,
)
from zaaggenz_dsp.nyquismic_convergence import FrozenConvergencePolicy


def setup(audio=None, rate=48000):
    if audio is None:
        audio = np.zeros(96, dtype='<f4')
    source = FrozenInput.from_pcm(audio, rate)
    sonic = SonicSpec(clock=ClockSpec(rate=VirtualRate('12000/1')))
    return source, sonic


class SamplerBackedConvergenceTests(unittest.TestCase):
    def test_zero_fixture_verifies_event_ledger_but_not_numerical_quality(self):
        source, sonic = setup()
        result = evaluate_sampler_model_convergence(source, sonic)
        self.assertEqual(result.status, 'inconclusive')
        self.assertEqual(result.diagnostics['sampler_bridge_method'], METHOD)
        self.assertTrue(result.diagnostics['event_schedule_verified_across_rates'])
        self.assertGreater(result.diagnostics['event_count'], 0)
        self.assertEqual(len(result.diagnostics['event_ledger_sha256']), 64)
        self.assertEqual(len(set(result.diagnostics['sampler_render_sha256_by_rate'].values())), 3)
        self.assertIsNone(result.selected_audio)
        self.assertTrue(all(row['null_signal'] and not row['within_limits']
                            for row in result.diagnostics['successive_metrics']))
        self.assertFalse(result.diagnostics['analytic_oracle_verified'])
        self.assertFalse(result.diagnostics['product_export_verified'])

    def test_nonzero_sampler_and_final_conversion_not_unbound_callback(self):
        x = np.zeros(96, dtype='<f4')
        x[7:12] = np.array([.3, -.8, 1.2, -.3, .1], dtype='<f4')
        source, sonic = setup(x)
        policy = FrozenConvergencePolicy(
            relative_rms_limit=.8, relative_spectrum_limit=.8,
            relative_transient_limit=.8,
        )
        result = evaluate_sampler_model_convergence(source, sonic, policy=policy)
        self.assertEqual(result.diagnostics['rates_hz'], [192000, 384000, 768000])
        self.assertGreater(result.diagnostics['event_count'], 0)
        self.assertEqual(len(result.diagnostics['sampler_render_sha256_by_rate']), 3)
        self.assertEqual(result.diagnostics['source_sha256'],
                         source.asset.to_dict()['content_sha256'])
        self.assertEqual(result.diagnostics['sonic_sha256'], sonic.sha256)
        self.assertEqual(result.diagnostics['clock_sha256'], sonic.clock.sha256)
        if result.status == 'converged':
            direct = SamplerPlan.prepare(
                source, sonic, sampler_evaluation(768000),
                frame_count=1536,
            ).render()
            final = convert_numerical_to_delivery(direct.audio, 768000, 48000)
            np.testing.assert_array_equal(result.selected_audio, final.audio)
        else:
            self.assertEqual(result.status, 'inconclusive')
            self.assertIsNone(result.selected_audio)
        np.testing.assert_array_equal(source.pcm, x)

    def test_unaligned_duration_or_budget_rejected_before_render(self):
        source, sonic = setup(np.zeros(95, dtype='<f4'), rate=44100)
        with self.assertRaises(ContractError):
            evaluate_sampler_model_convergence(source, sonic)
        source, sonic = setup()
        with self.assertRaises(ContractError):
            evaluate_sampler_model_convergence(
                source, sonic, budget=ResourceBudget(max_frames=100))

    def test_unsupported_routed_geometry_and_cancellation(self):
        source, sonic = setup()
        routed = SonicSpec(clock=ClockSpec(
            rate=VirtualRate('12000/1'),
            routes=(ModulationRoute(depth=1.),),
        ))
        with self.assertRaises(ContractError):
            evaluate_sampler_model_convergence(source, routed)
        with self.assertRaises(ClockCancelled):
            evaluate_sampler_model_convergence(
                source, sonic, cancelled=lambda: True)
        checks = [0]
        def cancel_after_first_pass():
            checks[0] += 1
            return checks[0] >= 20
        with self.assertRaises(ClockCancelled):
            evaluate_sampler_model_convergence(
                source, sonic, cancelled=cancel_after_first_pass)
        self.assertGreaterEqual(checks[0], 20)

    def test_full_precision_event_ledger_matches_independent_clock_coordinates(self):
        source, sonic = setup(np.linspace(-1, 1, 96, dtype='<f4'))
        result = evaluate_sampler_model_convergence(source, sonic)
        plan = SamplerPlan.prepare(
            source, sonic, sampler_evaluation(192000), frame_count=384)
        h = hashlib.sha256()
        h.update(b'nyq.exact-physical-event-ledger.v1\0')
        for index, event in enumerate(plan.events):
            physical = plan.clock.event_coordinate(index)
            stamp = (f'r:{physical.numerator}/{physical.denominator}'
                     if isinstance(physical, Fraction) else 'd:' + str(physical))
            h.update(f'{event.index}:{event.epoch}:{event.crossing}:{stamp}\n'.encode('ascii'))
        self.assertEqual(result.diagnostics['event_ledger_sha256'], h.hexdigest())
        self.assertEqual(result.diagnostics['event_ledger_method'],
                         'nyq.exact-physical-event-ledger.v1')
        self.assertEqual(result.diagnostics['event_count'], len(plan.events))

    def test_empty_extent_cannot_qualify_audio(self):
        source, sonic = setup(np.zeros(0, dtype='<f4'))
        result = evaluate_sampler_model_convergence(source, sonic)
        self.assertEqual(result.status, 'inconclusive')
        self.assertIsNone(result.selected_audio)
        self.assertEqual(result.diagnostics['event_count'], 0)


if __name__ == '__main__':
    unittest.main()
