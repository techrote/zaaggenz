from __future__ import annotations
import unittest
import numpy as np
from zaaggenz_components import analyse_components
from zaaggenz_tuning import (DissonanceError,DissonanceModelSpec,IntervalGrid,TimbreSpectrum,dissonance_curve,harmonic_spectrum,
                             interaction_roughness,local_minima,sensitivity_candidates,spectrum_from_partial_bundle)

SR=12000

def tone(f,duration=.7):
    t=np.arange(round(SR*duration),dtype=np.float64)/SR
    return (.5*np.cos(2*np.pi*f*t+.17)).astype(np.float32)

class DissonanceMapTests(unittest.TestCase):
    def test_harmonic_spectrum_has_stable_fifth_region_candidate(self):
        spectrum=harmonic_spectrum('harmonic',220.,partials=8)
        curve,candidates,sensitivity=sensitivity_candidates(spectrum,spectrum,IntervalGrid(450.,750.,2.))
        self.assertEqual(curve.model.amplitude_policy,'l1-per-spectrum');self.assertEqual(sensitivity['scenario_count'],9)
        fifth=[x for x in candidates if abs(x.cents-702.)<=4.]
        self.assertTrue(fifth);self.assertGreaterEqual(fifth[0].stability_fraction,.6)
        self.assertIn('not a scale degree',fifth[0].interpretation)

    def test_stretched_timbre_moves_candidate_instead_of_returning_baked_scale(self):
        harmonic=harmonic_spectrum('harmonic',220.,partials=8,stretch=1.)
        stretched=harmonic_spectrum('stretched',220.,partials=8,stretch=1.01)
        _,hc,_=sensitivity_candidates(harmonic,harmonic,IntervalGrid(680.,730.,2.))
        _,sc,_=sensitivity_candidates(stretched,stretched,IntervalGrid(680.,730.,2.))
        h=min(hc,key=lambda x:abs(x.cents-702.));s=min(sc,key=lambda x:abs(x.cents-710.))
        self.assertLess(abs(h.cents-702.),4.1);self.assertLess(abs(s.cents-710.),4.1);self.assertGreater(s.cents,h.cents+3.)

    def test_global_gain_cannot_reduce_interaction_score(self):
        a=TimbreSpectrum('a',(220.,440.,660.),(1.,.5,.25));loud=TimbreSpectrum('loud',(220.,440.,660.),(100.,50.,25.))
        b=harmonic_spectrum('b',330.,partials=3)
        x=interaction_roughness(a,b,0.);y=interaction_roughness(loud,b,0.)
        self.assertAlmostEqual(x.value,y.value,14);self.assertEqual(DissonanceModelSpec().to_dict()['amplitude']['global_gain_invariant'],True)

    def test_curve_is_reproducible_and_versioned(self):
        s=harmonic_spectrum('s',220.,partials=6);grid=IntervalGrid(0.,1200.,10.)
        a=dissonance_curve(s,s,grid);b=dissonance_curve(s,s,grid)
        self.assertEqual(a.to_dict(),b.to_dict());self.assertEqual(a.to_dict()['method_id'],'zg.timbre_interaction_roughness.v1')
        self.assertTrue(local_minima(a))

    def test_component_window_adapter_preserves_unscaled_amplitudes_and_confidence(self):
        analysis=analyse_components(tone(445.),SR);bundle=analysis.bundle.to_dict();anchor=bundle['tracks'][0]['frames'][0]['support']['anchor_sample']
        spectrum=spectrum_from_partial_bundle(analysis.bundle,anchor,max_components=8)
        self.assertTrue(spectrum.frequencies_hz);self.assertGreater(spectrum.confidence,0.);self.assertLessEqual(spectrum.confidence,1.)
        self.assertEqual(spectrum.source['confidence_policy'],'amplitude-weighted component confidence; amplitudes themselves are not confidence-scaled')

    def test_audible_band_abstains_when_shifted_spectrum_leaves_model_band(self):
        a=TimbreSpectrum('a',(100.,),(1.,));b=TimbreSpectrum('b',(100.,),(1.,))
        model=DissonanceModelSpec(audible_min_hz=20.,audible_max_hz=200.)
        observation=interaction_roughness(a,b,2400.,model)
        self.assertIsNone(observation.value);self.assertEqual(observation.validity,'insufficient-audible-partials')

    def test_mismatched_frequency_amplitude_arrays_are_rejected(self):
        with self.assertRaises(DissonanceError):TimbreSpectrum('bad',(220.,440.),(1.,))
        with self.assertRaises(DissonanceError):TimbreSpectrum('bad',(220.,),(1.,.5))

if __name__=='__main__':unittest.main(verbosity=2)
