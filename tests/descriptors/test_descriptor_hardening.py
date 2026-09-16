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
        self.assertEqual(r.feature_bundle['observations'],[])
        self.assertTrue(all(o.support['anchor_sample']==0 for o in r.descriptors.observations))
    def test_supplied_partials_must_match_exact_audio_identity(self):
        x=np.sin(2*np.pi*220*np.arange(SR)/SR).astype(np.float32);r=analyse_descriptors(x,SR)
        with self.assertRaises(DescriptorError):analyse_descriptors(x*.5,SR,partials=r.partials)

    def test_unpadded_anchor_accepts_both_source_boundaries(self):
        asset=pcm_asset(np.zeros(8,dtype=np.float32),SR)
        for anchor in (0,7):
            with self.subTest(anchor=anchor):
                s=dict(start_sample=0,end_sample=8,anchor_sample=anchor,padding='none')
                bundle=DescriptorBundle(asset,(observation('rms',0.,s),))
                projection=feature_projection(bundle);validate(projection,'FeatureBundle')
                self.assertEqual(projection['observations'][0]['support'],s)

    def test_padded_edges_may_extend_outside_source_when_anchor_remains_in_source(self):
        asset=pcm_asset(np.zeros(8,dtype=np.float32),SR)
        cases=(dict(start_sample=-4,end_sample=3,anchor_sample=0,padding='zero'),
               dict(start_sample=6,end_sample=12,anchor_sample=7,padding='reflect'))
        for s in cases:
            with self.subTest(support=s):
                bundle=DescriptorBundle(asset,(observation('rms',0.,s),))
                projection=feature_projection(bundle);validate(projection,'FeatureBundle')
                self.assertEqual(projection['observations'][0]['support'],s)

    def test_padded_out_of_source_anchor_is_rejected_before_projection(self):
        asset=pcm_asset(np.zeros(8,dtype=np.float32),SR)
        cases=(dict(start_sample=-4,end_sample=2,anchor_sample=-1,padding='zero'),
               dict(start_sample=7,end_sample=12,anchor_sample=8,padding='reflect'))
        for s in cases:
            with self.subTest(support=s),self.assertRaisesRegex(DescriptorError,'anchor lies outside source asset'):
                DescriptorBundle(asset,(observation('rms',0.,s),))

    def test_every_projected_metric_role_and_validity_is_featurebundle_valid(self):
        asset=pcm_asset(np.zeros(8,dtype=np.float32),SR);s=dict(start_sample=-2,end_sample=10,anchor_sample=3,padding='zero')
        metrics=('rms','f0_candidate_hz','roughness_pairwise','target_comb_fit')
        for metric in metrics:
            for role in ('measurement','estimate'):
                for validity in ('valid','unknown','abstained'):
                    with self.subTest(metric=metric,role=role,validity=validity):
                        value=.5 if validity=='valid' else None
                        confidence=.75 if role=='estimate' else None
                        bundle=DescriptorBundle(asset,(observation(metric,value,s,role=role,validity=validity,confidence=confidence),))
                        projection=feature_projection(bundle);validate(projection,'FeatureBundle')
                        self.assertEqual(len(projection['observations']),1)
                        row=projection['observations'][0]
                        self.assertEqual(row['support'],s);self.assertEqual(row['validity'],validity);self.assertEqual(row['role'],role)
                        self.assertEqual(row['confidence'],.75 if role=='estimate' and validity=='valid' else None)

    def test_unaffected_bundle_serialization_and_hash_stay_stable(self):
        asset=pcm_asset(np.zeros(4,dtype=np.float32),SR)
        s=dict(start_sample=0,end_sample=4,anchor_sample=1,padding='none')
        bundle=DescriptorBundle(asset,(observation('rms',0.,s),),configuration={'probe':'anchor-stability'})
        self.assertEqual(bundle.sha256,'3096aaf3303d4608e290d246abe65727f653b9f2a02ddd0463fcb4d6c8b9d673')
        self.assertEqual(bundle.to_dict()['observations'][0]['support'],s)

if __name__=='__main__':unittest.main(verbosity=2)
