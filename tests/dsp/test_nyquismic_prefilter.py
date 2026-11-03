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


if __name__ == '__main__':
    unittest.main()
