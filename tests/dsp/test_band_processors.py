from __future__ import annotations
import unittest
import numpy as np
from zaaggenz_dsp import (BitcrushSpec,CompressionSpec,bitcrush,compress,route_band_processors,split_bands)

SR=12000

def tone(f,duration=.6,amp=.5,phase=.11):
    t=np.arange(round(SR*duration),dtype=np.float64)/SR
    return (amp*np.sin(2*np.pi*f*t+phase)).astype(np.float64)

def rms(x):
    a=np.asarray(x,dtype=np.float64);return float(np.sqrt(np.mean(a*a)))

class BandProcessorTests(unittest.TestCase):
    def test_compressor_ratio_one_is_exact_identity_with_zero_makeup(self):
        x=tone(900.);result=compress(x,SR,CompressionSpec(threshold_db=-40.,ratio=1.,attack_ms=1.,release_ms=20.,makeup_db=0.,wet=1.))
        np.testing.assert_array_equal(result.audio,x);self.assertTrue(np.all(result.static_gain_reduction_db==0));self.assertTrue(np.all(result.smoothed_gain_reduction_db==0))

    def test_compressor_zero_wet_is_exact_identity_and_controls_are_separate(self):
        x=tone(900.);result=compress(x,SR,CompressionSpec(threshold_db=-30.,ratio=8.,attack_ms=1.,release_ms=20.,wet=0.))
        np.testing.assert_array_equal(result.audio,x);self.assertEqual(result.detector_db.shape,(len(x),));self.assertTrue(result.diagnostics['control_signal_separate_from_audio'])

    def test_compressor_has_real_threshold_ratio_attack_release_behavior(self):
        x=np.concatenate((tone(500,.2,.03),tone(500,.2,.8),tone(500,.2,.03)))
        spec=CompressionSpec(threshold_db=-18.,ratio=4.,attack_ms=5.,release_ms=80.,wet=1.)
        result=compress(x,SR,spec);gr=result.smoothed_gain_reduction_db;n=len(x)//3
        self.assertGreater(float(np.mean(gr[n:n*2])),1.);self.assertGreater(gr[n+200],gr[n]);self.assertGreater(gr[n*2+20],gr[-1])
        self.assertGreater(rms(x[n:n*2]),rms(result.audio[n:n*2]))

    def test_bitcrush_zero_wet_is_exact_identity(self):
        x=tone(700.);result=bitcrush(x,BitcrushSpec(bit_depth=4,hold_samples=8,wet=0.))
        np.testing.assert_array_equal(result.audio,x);self.assertIn('intentional unfiltered',result.diagnostics['alias_policy'])

    def test_bitcrush_is_deterministic_and_sample_zero_anchored(self):
        x=np.linspace(-.8,.8,40,dtype=np.float64);spec=BitcrushSpec(bit_depth=4,hold_samples=4,wet=1.)
        a=bitcrush(x,spec);b=bitcrush(x,spec);np.testing.assert_array_equal(a.audio,b.audio)
        for start in range(0,len(x),4):self.assertTrue(np.all(a.audio[start:start+4]==a.audio[start]))
        self.assertAlmostEqual(a.quantization_step,2./15.)

    def test_no_band_processors_is_exact_identity(self):
        x=tone(60.)+tone(1000.,amp=.25);y,reports=route_band_processors(x,SR,(105.,520.,3600.),(None,None,None,None))
        np.testing.assert_array_equal(y,x);self.assertTrue(all(not row.selected for row in reports))

    def test_delta_confinement_suppresses_deliberate_low_frequency_spill(self):
        x=tone(1000.,amp=.25);t=np.arange(len(x),dtype=np.float64)/SR;spill=.15*np.sin(2*np.pi*50*t)
        processor=lambda band: np.asarray(band)+spill
        confined,cr=route_band_processors(x,SR,(105.,520.,3600.),(None,None,processor,None),(True,True,True,True))
        raw,rr=route_band_processors(x,SR,(105.,520.,3600.),(None,None,processor,None),(True,True,False,True))
        cdelta=confined-x;rdelta=raw-x
        csub=rms(split_bands(cdelta,SR,(105.,520.,3600.))[0]);rsub=rms(split_bands(rdelta,SR,(105.,520.,3600.))[0])
        self.assertLess(csub,rsub*.2);self.assertGreater(rr[2].leakage_rms_by_band[0],cr[2].leakage_rms_by_band[0]*5.)
        self.assertFalse(rr[2].confine_delta);self.assertTrue(cr[2].confine_delta)

if __name__=='__main__':unittest.main(verbosity=2)
