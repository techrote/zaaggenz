from dataclasses import replace
import unittest
from unittest import mock

import numpy as np

from zaaggenz_zaag import ZaagFamilyError, family, render_family_source


class FormantSampleRateContractTests(unittest.TestCase):
    def setUp(self):
        self.base = family('zaag.vowel-sway')

    def recipe(self, start_hz, end_hz, *, motion=None, boost_db=None):
        expert = replace(
            self.base.expert,
            formant_start_hz=float(start_hz),
            formant_end_hz=float(end_hz),
            formant_boost_db=(self.base.expert.formant_boost_db if boost_db is None else float(boost_db)),
        )
        macros = self.base.macros if motion is None else replace(self.base.macros, vowel_motion=float(motion))
        return replace(self.base, expert=expert, macros=macros)

    def test_exact_low_and_high_boundaries_are_realized_without_remap(self):
        for sample_rate_hz in (8000, 12000, 24000, 48000):
            with self.subTest(sample_rate_hz=sample_rate_hz):
                high = 0.45 * sample_rate_hz
                recipe = self.recipe(20.0, high)
                rendered = render_family_source(recipe, sample_rate_hz)
                self.assertEqual(rendered.diagnostics['formant']['policy'], 'fail-closed-exact-v1')
                self.assertTrue(rendered.diagnostics['formant']['active'])
                self.assertEqual(rendered.diagnostics['formant']['supported_band_hz'], [20.0, high])
                self.assertEqual(rendered.diagnostics['formant']['requested_hz'], {'start_hz': 20.0, 'end_hz': high})
                self.assertEqual(rendered.diagnostics['formant']['realized_hz'], {'start_hz': 20.0, 'end_hz': high})

    def test_just_outside_each_boundary_fails_closed(self):
        sample_rate_hz = 8000
        high = 0.45 * sample_rate_hz
        cases = (
            (np.nextafter(20.0, 0.0), 1000.0, 'start_hz'),
            (1000.0, np.nextafter(20.0, 0.0), 'end_hz'),
            (np.nextafter(high, np.inf), 1000.0, 'start_hz'),
            (1000.0, np.nextafter(high, np.inf), 'end_hz'),
        )
        for start_hz, end_hz, label in cases:
            with self.subTest(start_hz=start_hz, end_hz=end_hz):
                with self.assertRaisesRegex(ZaagFamilyError, label):
                    render_family_source(self.recipe(start_hz, end_hz), sample_rate_hz)

    def test_historical_10khz_at_12khz_mismatch_now_rejects_before_source_execution(self):
        recipe = self.recipe(10000.0, 1000.0)
        with mock.patch('uptempo_harmony.synth.synthesize_one', side_effect=AssertionError('source must not execute')):
            with self.assertRaisesRegex(ZaagFamilyError, '5400'):
                render_family_source(recipe, 12000)

    def test_same_recipes_have_explicit_12_24_48khz_admissibility(self):
        cases = (
            (3000.0, {8000: True, 12000: True, 24000: True, 48000: True, 96000: True}),
            (8000.0, {8000: False, 12000: False, 24000: True, 48000: True, 96000: True}),
            (15000.0, {8000: False, 12000: False, 24000: False, 48000: True, 96000: True}),
        )
        for hz, expectations in cases:
            recipe = self.recipe(hz, hz)
            for sample_rate_hz, accepted in expectations.items():
                with self.subTest(hz=hz, sample_rate_hz=sample_rate_hz):
                    if accepted:
                        rendered = render_family_source(recipe, sample_rate_hz)
                        self.assertEqual(rendered.diagnostics['formant']['realized_hz'], {'start_hz': hz, 'end_hz': hz})
                    else:
                        with self.assertRaises(ZaagFamilyError):
                            render_family_source(recipe, sample_rate_hz)

    def test_reverse_sweep_is_valid_when_both_endpoints_are_in_band(self):
        rendered = render_family_source(self.recipe(3600.0, 20.0), 8000)
        self.assertEqual(rendered.diagnostics['formant']['realized_hz'], {'start_hz': 3600.0, 'end_hz': 20.0})

    def test_inert_formant_controls_do_not_create_sample_rate_restrictions(self):
        invalid_at_8k = 23999.0
        by_motion = render_family_source(self.recipe(invalid_at_8k, invalid_at_8k, motion=0.0), 8000)
        self.assertFalse(by_motion.diagnostics['formant']['active'])
        self.assertIsNone(by_motion.diagnostics['formant']['realized_hz'])
        by_gain = render_family_source(self.recipe(invalid_at_8k, invalid_at_8k, boost_db=0.0), 8000)
        self.assertFalse(by_gain.diagnostics['formant']['active'])
        self.assertIsNone(by_gain.diagnostics['formant']['realized_hz'])

    def test_sample_rate_margin_is_not_silently_clamped(self):
        at_margin = render_family_source(self.recipe(5400.0, 5400.0), 12000)
        self.assertEqual(at_margin.diagnostics['formant']['realized_hz']['start_hz'], 5400.0)
        with self.assertRaises(ZaagFamilyError):
            render_family_source(self.recipe(np.nextafter(5400.0, np.inf), 5400.0), 12000)


if __name__ == '__main__':
    unittest.main()
