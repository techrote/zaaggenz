from __future__ import annotations
import math
import unittest
from unittest.mock import patch
from zaaggenz_tuning import (DissonanceError,DissonanceModelSpec,IntervalGrid,TimbreSpectrum,dissonance_curve,harmonic_spectrum,
                             interaction_roughness,local_minima,sensitivity_candidates,spectrum_from_partial_bundle)

class DissonanceMapTests(unittest.TestCase):
    def test_harmonic_spectrum_has_stable_fifth_region_candidate(self):
        spectrum=harmonic_spectrum('harmonic',220.,partials=8)
        curve,candidates,sensitivity=sensitivity_candidates(spectrum,spectrum,IntervalGrid(450.,750.,2.))
        self.assertEqual(curve.model.amplitude_policy,'l1-per-spectrum');self.assertEqual(sensitivity['scenario_count'],9)
        self.assertEqual(sensitivity['grid_point_count'],151);self.assertEqual(sensitivity['scenario_point_evaluations'],1359)
        self.assertEqual(sensitivity['total_point_evaluations'],1510)
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

    def test_interval_grid_exact_and_nondivisor_endpoints_are_included_once(self):
        exact=IntervalGrid(0.,10.,2.);nondivisor=IntervalGrid(0.,10.,4.)
        self.assertEqual(exact.values(),(0.,2.,4.,6.,8.,10.));self.assertEqual(exact.values().count(10.),1)
        self.assertEqual(nondivisor.values(),(0.,4.,8.,10.));self.assertEqual(nondivisor.values().count(10.),1)
        self.assertEqual(exact.point_count,len(exact.values()));self.assertEqual(nondivisor.point_count,len(nondivisor.values()))

    def test_interval_grid_maximum_nondivisor_materialises_exactly_2401_points(self):
        grid=IntervalGrid(0.,2400.,1.0001);values=grid.values()
        self.assertEqual(grid.point_count,2401);self.assertEqual(len(values),2401)
        self.assertEqual(values[0],0.);self.assertEqual(values[-1],2400.);self.assertEqual(values.count(2400.),1)
        self.assertEqual(grid.to_dict()['points'],len(values))

    def test_interval_grid_rejects_preappend_2401_case_that_would_materialise_2402(self):
        step=.999999;preappend=math.floor(2400./step)+1
        self.assertEqual(preappend,2401);self.assertLess((preappend-1)*step,2400.-1e-9)
        self.assertEqual(preappend+1,2402)
        with self.assertRaisesRegex(DissonanceError,'2..2401 points'):IntervalGrid(0.,2400.,step)

    def test_interval_grid_endpoint_tolerance_is_deterministic_across_float_boundary(self):
        within=IntervalGrid(0.,1.,1.-5e-10);outside=IntervalGrid(0.,1.,1.-2e-9)
        self.assertEqual(within.values(),(0.,1.));self.assertEqual(within.point_count,2)
        self.assertEqual(outside.values(),(0.,1.-2e-9,1.));self.assertEqual(outside.point_count,3)
        decimal=IntervalGrid(0.,.3,.1)
        self.assertEqual(decimal.point_count,4);self.assertEqual(decimal.values()[-1],.3);self.assertEqual(decimal.values().count(.3),1)

    def test_interval_grid_serialized_count_always_matches_materialised_count(self):
        grids=(IntervalGrid(),IntervalGrid(0.,10.,2.),IntervalGrid(0.,10.,4.),IntervalGrid(0.,1.,2.),
               IntervalGrid(0.,1.,1.-5e-10),IntervalGrid(0.,2400.,1.0001))
        for grid in grids:
            with self.subTest(grid=grid):self.assertEqual(grid.to_dict()['points'],len(grid.values()))

    def test_curve_revalidates_grid_bound_before_interaction_work(self):
        spectrum=harmonic_spectrum('s',220.,partials=3);grid=IntervalGrid(0.,2400.,1.)
        object.__setattr__(grid,'step_cents',.999999)
        with patch('zaaggenz_tuning.dissonance_curve.interaction_roughness') as roughness:
            with self.assertRaisesRegex(DissonanceError,'2..2401 points'):dissonance_curve(spectrum,spectrum,grid)
            roughness.assert_not_called()

    def test_sensitivity_cost_diagnostics_use_realised_grid_cardinality(self):
        spectrum=harmonic_spectrum('s',220.,partials=3);grid=IntervalGrid(0.,10.,4.)
        curve,_,meta=sensitivity_candidates(spectrum,spectrum,grid,bandwidth_scales=(1.,),amplitude_exponents=(1.,))
        self.assertEqual(len(curve.points),4);self.assertEqual(meta['grid_point_count'],4);self.assertEqual(meta['scenario_count'],1)
        self.assertEqual(meta['scenario_point_evaluations'],4);self.assertEqual(meta['total_point_evaluations'],8)

    def test_component_window_adapter_preserves_unscaled_amplitudes_and_confidence(self):
        bundle={'kind':'PartialTrackBundle','asset':{'sample_rate_hz':12000},'tracks':[
            {'id':'track-a','continuity':'continuous','frames':[{'frequency_hz':445.,'amplitudes':[.5],
             'confidence':.8,'support':{'anchor_sample':128},'action':'transform'}]},
            {'id':'track-b','continuity':'continuous','frames':[{'frequency_hz':668.,'amplitudes':[.25],
             'confidence':.6,'support':{'anchor_sample':130},'action':'transform'}]}]}
        spectrum=spectrum_from_partial_bundle(bundle,128,max_components=8)
        self.assertEqual(spectrum.frequencies_hz,(445.,668.));self.assertEqual(spectrum.amplitudes,(.5,.25))
        self.assertAlmostEqual(spectrum.confidence,(.5*.8+.25*.6)/.75)
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
