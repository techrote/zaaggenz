import json
import unittest
import numpy as np
from zaaggenz_qc.fixtures import fixture
from zaaggenz_inverse import ObjectivePolicy, ObjectiveTerm, ValidationPolicy
from zaaggenz_inverse.objectives import FeatureMeasurements, measure_losses, validation_measurements, aggregate

SR=12000


def reasons(report):
    return set(report['rejected_reasons'])


class ObjectiveTests(unittest.TestCase):
    def setUp(self):
        self.source=fixture('sine',SR,.15).data.astype(np.float32)
        self.features=FeatureMeasurements(SR,72.)

    def test_identity_preserves_every_component_and_units(self):
        m=measure_losses(self.source,self.source,self.features)
        values={x['name']:x['value'] for x in m['components']}
        for name in ('waveform','spectrum','level','periodicity','occupancy'):self.assertEqual(values[name],0.)
        self.assertIsNone(values['roughness'])
        self.assertEqual({x['name']:x['unit'] for x in m['components']}['level'],'dB')
        self.assertEqual(m['target_features']['asset'],m['candidate_features']['asset'])

    def test_waveform_and_feature_agreement_are_not_equivalent(self):
        m=measure_losses(self.source,-self.source,self.features)
        values={x['name']:x['value'] for x in m['components']}
        self.assertAlmostEqual(values['waveform'],2.,places=12)
        self.assertEqual(values['spectrum'],0.)
        self.assertEqual(values['level'],0.)
        self.assertEqual(values['occupancy'],0.)

    def test_no_implicit_alignment(self):
        m=measure_losses(self.source,np.roll(self.source,5),self.features)
        values={x['name']:x['value'] for x in m['components']}
        self.assertGreater(values['waveform'],.5)

    def test_silence_cannot_win_by_discarding_difficult_content(self):
        v=validation_measurements(self.source,np.zeros_like(self.source),SR)
        self.assertIn('silence_collapse',reasons(v))
        self.assertIn('transient_loss',reasons(v))
        self.assertIn('energy_collapse',reasons(v))

    def test_level_mismatch_and_normalization_exploit_remain_visible(self):
        candidate=self.source*.1
        m=measure_losses(self.source,candidate,self.features)
        values={x['name']:x['value'] for x in m['components']}
        self.assertAlmostEqual(values['waveform'],.9,places=6)
        self.assertAlmostEqual(values['level'],20.,places=5)
        self.assertLess(m['intermediate']['gain_fit_diagnostic_only']['gain_aligned_relative_rms'],1e-6)
        v=validation_measurements(self.source,candidate,SR)
        self.assertTrue({'level_mismatch','normalisation_suspect'} <= reasons(v))

    def test_transient_loss_even_when_largest_attack_survives(self):
        n=2400;t=np.arange(n)/SR
        target=.01*np.sin(2*np.pi*100*t)
        target[400]+=.8;target[1200]+=.65
        candidate=target.copy();candidate[1200]-=.65
        v=validation_measurements(target,candidate,SR)
        self.assertIn('transient_loss',reasons(v))
        self.assertGreaterEqual(len(v['measurements']['transient_anchor_samples'][0]),2)

    def test_pathological_clipping_below_full_scale(self):
        clipped=np.clip(self.source*3,-.45,.45)
        v=validation_measurements(self.source,clipped,SR)
        self.assertIn('pathological_clipping',reasons(v))
        self.assertLess(v['measurements']['candidate']['peak'],1.)

    def test_extreme_soft_saturation_also_flagged(self):
        saturated=.45*np.tanh(self.source*100)
        self.assertIn('pathological_clipping',reasons(validation_measurements(self.source,saturated,SR)))

    def test_destructive_final_clipping_fails_even_with_zero_fit_error(self):
        pre=self.source*3
        candidate=np.clip(pre,-1.,1.).astype(np.float32)
        v=validation_measurements(candidate,candidate,SR,pre_master=pre,master_gain=1.)
        self.assertIn('destructive_output_clipping',reasons(v))
        self.assertNotIn('hidden_level_handling',reasons(v))

    def test_hidden_normalizer_fails_even_when_target_matches(self):
        pre=self.source*.1
        candidate=self.source
        v=validation_measurements(candidate,candidate,SR,pre_master=pre,master_gain=1.)
        self.assertIn('hidden_level_handling',reasons(v))
        self.assertEqual(v['measurements']['final_gain_provenance']['normalisation'],'none')

    def test_declared_gain_is_not_mislabelled_as_hidden_processing(self):
        pre=self.source.astype(np.float64)*.1;candidate=(pre*2.).astype(np.float32)
        v=validation_measurements(candidate,candidate,SR,pre_master=pre,master_gain=2.)
        self.assertEqual(v['state'],'accepted')
        self.assertEqual(v['measurements']['final_gain_provenance']['gain_linear'],2.)

    def test_bandwidth_and_energy_collapse_despite_matched_rms(self):
        t=np.arange(2400)/SR
        lo=.2*np.sin(2*np.pi*100*t);hi=.2*np.sin(2*np.pi*4000*t)
        target=lo+hi;candidate=lo*np.sqrt(2)
        v=validation_measurements(target,candidate,SR)
        self.assertTrue({'bandwidth_collapse','energy_collapse'} <= reasons(v))
        self.assertNotIn('level_mismatch',reasons(v))

    def test_nonfinite_shape_and_invalid_gain_provenance(self):
        for bad in (np.nan,np.inf,-np.inf):
            candidate=self.source.copy();candidate[100]=bad
            v=validation_measurements(self.source,candidate,SR)
            self.assertIn('non_finite',reasons(v));json.dumps(v,allow_nan=False)
        self.assertIn('invalid_shape',reasons(validation_measurements(self.source,self.source[:-1],SR)))
        self.assertIn('invalid_gain_provenance',reasons(validation_measurements(self.source,self.source,SR,pre_master=self.source,master_gain=-1.)))

    def test_target_silence_is_not_a_false_cheating_positive(self):
        a=np.zeros(200,dtype=np.float32)
        v=validation_measurements(a,a,SR)
        self.assertEqual(v['state'],'accepted')
        m=measure_losses(a,a,self.features)
        self.assertTrue(all(x['value'] is None or np.isfinite(x['value']) for x in m['components']))

    def test_requested_unknown_component_abstains_not_zero(self):
        a=np.zeros(200,dtype=np.float32)
        m=measure_losses(a,a,self.features)
        v=aggregate([{'measurements':m}],ObjectivePolicy((ObjectiveTerm('periodicity'),)))
        self.assertFalse(v['comparable']);self.assertIsNone(v['score'])
        self.assertIsNone(v['components']['periodicity'])

    def test_stereo_antiphase_not_discarded_by_downmix(self):
        target=np.column_stack((self.source,-self.source))
        v=validation_measurements(target,target,SR)
        self.assertEqual(v['state'],'accepted')
        self.assertGreater(v['measurements']['target']['rms'],.1)
        candidate=target.copy();candidate[:,1]=0
        v=validation_measurements(target,candidate,SR)
        self.assertIn('transient_loss',reasons(v))
        self.assertEqual(len(v['measurements']['transient_channel_ratios']),2)

    def test_allowed_degeneracy_is_explicit_and_never_erases_findings(self):
        ordinary=validation_measurements(self.source,self.source*.1,SR)
        policy=ValidationPolicy(allowed=tuple(ordinary['rejected_reasons']))
        allowed=validation_measurements(self.source,self.source*.1,SR,policy)
        self.assertEqual(allowed['state'],'accepted-with-exceptions')
        self.assertIn('normalisation_suspect',allowed['allowed_exceptions'])
        self.assertEqual(len(ordinary['findings']),len(allowed['findings']))

    def test_canonical_features_share_pcm_not_float64_accidents(self):
        # Values that round to identical PCM must yield identical features and key.
        a=self.source.astype(np.float64);b=a+1e-14
        a[0]=b[0]=0.
        ma,fa=self.features.measure(a);mb,fb=self.features.measure(b)
        self.assertEqual(fa,fb);np.testing.assert_array_equal(ma,mb)
        with self.assertRaises(ValueError):ma.setflags(write=True)
        changed=self.features.configuration;changed['channels']='bad'
        self.assertNotEqual(self.features.configuration['channels'],'bad')

if __name__=='__main__':unittest.main()
