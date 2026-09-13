from __future__ import annotations
import unittest
import numpy as np
from zaaggenz_contracts import validate
from zaaggenz_descriptors import *

SR=12000

class DescriptorHardeningTests(unittest.TestCase):
    def test_octave_ambiguity_discounts_f0_confidence_and_names_selection(self):
        t=np.arange(2*SR)/SR;x=np.sin(2*np.pi*220*t);rows={o.metric:o for o in periodicity_observations(x,SR)}
        f0=rows['f0_candidate_hz'];period=rows['periodicity_peak']
        self.assertAlmostEqual(f0.details['selected_hz'],f0.value,12)
        self.assertTrue(f0.details['octave_ambiguous'])
        self.assertLess(f0.confidence,period.confidence)
        self.assertTrue(any(row.get('selected') for row in f0.details['alternatives']))
    def test_target_generator_is_materialised_once_and_recorded(self):
        t=np.arange(SR)/SR;x=np.sin(2*np.pi*220*t).astype(np.float32)
        targets=(v for v in (220.,440.,660.));r=analyse_descriptors(x,SR,target_hz=targets)
        self.assertEqual(r.descriptors.configuration['target_comb_hz'],[220.,440.,660.])
        self.assertEqual(r.descriptors.get('target_comb_density')[0].value,3.)
    def test_analysis_f0_max_must_remain_below_nyquist(self):
        with self.assertRaises(DescriptorError):analyse_descriptors(np.zeros(4096),8000,spec=DescriptorAnalysisSpec(max_f0_hz=5000.))
    def test_empty_excerpt_keeps_explicit_padded_support_and_frozen_projection(self):
        r=analyse_descriptors(np.zeros(0,dtype=np.float32),SR);validate(r.feature_bundle,'FeatureBundle')
        self.assertEqual(r.descriptors.asset['frame_count'],0)
        self.assertTrue(all(o.support['padding']=='zero' for o in r.descriptors.observations))
    def test_supplied_partials_must_match_exact_audio_identity(self):
        x=np.sin(2*np.pi*220*np.arange(SR)/SR).astype(np.float32);r=analyse_descriptors(x,SR)
        with self.assertRaises(DescriptorError):analyse_descriptors(x*.5,SR,partials=r.partials)

if __name__=='__main__':unittest.main(verbosity=2)
