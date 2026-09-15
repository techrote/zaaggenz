from dataclasses import replace
from pathlib import Path
import sys
import unittest
import numpy as np

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'app'))

from zaaggenz_qc import fixture,fixture_names,diagnose,alignment,check_identity,check_required_stems,check_master_gain,QCError
from zaaggenz_qc.checks import check_source_preservation
from zaaggenz_qc.metrics import source_preservation
from uptempo_harmony.synth import PRESETS
from uptempo_harmony.arrangement import make_arrangement_template
from uptempo_harmony.reversebass import REVERSEBASS_PRESETS,synthesize_reversebass_arrangement
from uptempo_harmony.multiband import SCULPT_PRESETS,process_spectral_sculpt
from webapp import apply_master_gain

class FixtureTests(unittest.TestCase):
    def test_catalogue(self):
        for name in fixture_names():
            with self.subTest(name=name):
                f=fixture(name,12000,.25);self.assertEqual(f.frames,3000);self.assertTrue(np.isfinite(f.data).all());self.assertFalse(f.data.flags.writeable)
                d=diagnose(f.data,f.sample_rate_hz);self.assertEqual(d['sample_rate_hz'],12000);self.assertEqual(d['evaluation_mode'],'automated')
    def test_float_headroom_preserved(self):
        d=diagnose(fixture('over_full_scale',48000,.2).data,48000);self.assertGreater(d['peak'],1.49);self.assertGreater(d['abs_ge_1_fraction'],0)
    def test_diagnose_reports_nonfinite_without_certifying_it(self):
        x=np.asarray([0.,np.nan,np.inf,-np.inf]);d=diagnose(x,12000);self.assertEqual(d['finite_fraction'],.25);self.assertTrue(np.isfinite(d['rms']))
    def test_noise_repeatable(self):
        np.testing.assert_array_equal(fixture('bandlimited_noise',12000,.2,7).data,fixture('bandlimited_noise',12000,.2,7).data)
        self.assertFalse(np.array_equal(fixture('bandlimited_noise',12000,.2,7).data,fixture('bandlimited_noise',12000,.2,8).data))
    def test_stereo_antiphase_not_destroyed_by_fixture(self):
        x=fixture('stereo_antiphase',12000,.2).data;self.assertGreater(np.std(x[:,0]),.2);np.testing.assert_allclose(x[:,0],-x[:,1],atol=1e-14)
    def test_impulse_alignment(self):
        x=fixture('impulse',12000,.2).data;y=np.pad(x,(7,0))[:len(x)];a=alignment(x,y,32);self.assertEqual(abs(a['lag_samples']),7);self.assertGreater(a['correlation'],.99)

class IdentityTests(unittest.TestCase):
    def test_exact_identity(self):
        x=fixture('harmonic_comb',12000,.2).data;check_identity(x,x.copy())
    def test_detect_change(self):
        x=fixture('harmonic_comb',12000,.2).data;y=x.copy();y[3]+=1e-8
        with self.assertRaises(QCError):check_identity(x,y)
    def test_transparent_sculpt(self):
        x=fixture('transient_tone',12000,.4).data.astype(np.float32);y=process_spectral_sculpt(x,12000,SCULPT_PRESETS['transparent']);check_identity(x,y)
    def test_master_minus6(self):
        x=fixture('sine',12000,.2).data.astype(np.float32);y,_=apply_master_gain(x,{'master_gain_db':-6});r=check_master_gain(x,y,-6,tolerance=3e-7);self.assertAlmostEqual(r['measured_ratio'],10**(-6/20),6)

class RegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base=replace(PRESETS['locked_bloom'],sr=12000,beats=1);spec=make_arrangement_template('escalate',bpm=200,bars=2,seed=1337)
        _,_,cls.stems=synthesize_reversebass_arrangement(base,spec,REVERSEBASS_PRESETS['layered_reverse'])
    def test_required_stems(self):
        r=check_required_stems(self.stems);self.assertGreater(r['synthline_rms'],.01)
    def test_missing_synthline_is_detected(self):
        bad=dict(self.stems);bad.pop('synthline')
        with self.assertRaises(QCError):check_required_stems(bad)
    def test_flattened_source_is_detected(self):
        x=np.asarray(self.stems['synthline'],float);bad=np.tanh(8*x)
        with self.assertRaises(QCError):check_source_preservation(x,bad,max_gain_aligned_error=.01)
    def test_simple_gain_not_called_flattening(self):
        x=np.asarray(self.stems['synthline'],float);r=check_source_preservation(x,.25*x,max_gain_aligned_error=1e-12);self.assertLess(r['gain_aligned_relative_rms'],1e-12)
    def test_stems_aligned_finite(self):
        r=check_required_stems(self.stems);self.assertGreater(r['shape'][0],0)

class NonFiniteFailClosedTests(unittest.TestCase):
    def finite_control(self):return np.asarray([0.,.25,-.5,.75],dtype=np.float64)
    def variants(self):
        base=self.finite_control()
        for label,value in (('nan',np.nan),('posinf',np.inf),('neginf',-np.inf)):
            x=base.copy();x[1]=value;yield label,x

    def test_identity_rejects_nan_and_infinity_even_when_arrays_match(self):
        for label,x in self.variants():
            with self.subTest(label=label),self.assertRaisesRegex(QCError,'non-finite audio'):check_identity(x,x.copy())

    def test_master_gain_rejects_nonfinite_input_before_ratio_math(self):
        clean=self.finite_control()
        for label,x in self.variants():
            with self.subTest(label=label+'-before'),self.assertRaisesRegex(QCError,'non-finite audio'):check_master_gain(x,clean,0)
            with self.subTest(label=label+'-after'),self.assertRaisesRegex(QCError,'non-finite audio'):check_master_gain(clean,x,0)

    def test_master_gain_rejects_nonfinite_controls_and_derived_overflow(self):
        x=self.finite_control()
        for value in (np.nan,np.inf,-np.inf):
            with self.subTest(gain=value),self.assertRaises(QCError):check_master_gain(x,x,value)
            with self.subTest(tolerance=value),self.assertRaises(QCError):check_master_gain(x,x,0,tolerance=value)
        with self.assertRaisesRegex(QCError,'expected ratio'):
            check_master_gain(x,x,1e308)

    def test_source_preservation_rejects_nonfinite_input(self):
        clean=self.finite_control()
        for label,x in self.variants():
            with self.subTest(label=label+'-reference'),self.assertRaisesRegex(QCError,'non-finite audio'):check_source_preservation(x,clean)
            with self.subTest(label=label+'-candidate'),self.assertRaisesRegex(QCError,'non-finite audio'):check_source_preservation(clean,x)

    def test_required_stems_reject_nonfinite_before_acceptance_metrics(self):
        stems={k:self.finite_control().copy() for k in ('synthline','body','aux','sub','kick','bass','mix')}
        stems['synthline'][0]=np.nan
        with self.assertRaisesRegex(QCError,'non-finite audio'):check_required_stems(stems)

    def test_huge_finite_master_ratio_math_remains_defined_or_fails(self):
        huge=np.asarray([np.finfo(np.float64).max/4,-np.finfo(np.float64).max/4])
        result=check_master_gain(huge,huge,0)
        self.assertTrue(np.isfinite(result['measured_ratio']));self.assertEqual(result['measured_ratio'],1.)

    def test_silence_and_constant_source_preservation_semantics_are_explicit(self):
        z=np.zeros(8);same=np.full(8,.25);scaled=np.full(8,.5)
        rz=check_source_preservation(z,z);self.assertEqual(rz['correlation'],1.);self.assertEqual(rz['gain_aligned_relative_rms'],0.)
        rs=check_source_preservation(same,same);self.assertEqual(rs['correlation'],1.);self.assertEqual(rs['gain_aligned_relative_rms'],0.)
        rg=check_source_preservation(same,scaled);self.assertEqual(rg['correlation'],0.);self.assertEqual(rg['gain_aligned_relative_rms'],0.)
        self.assertTrue(all(np.isfinite(float(v)) for v in rz.values()));self.assertTrue(all(np.isfinite(float(v)) for v in rs.values()));self.assertTrue(all(np.isfinite(float(v)) for v in rg.values()))

    def test_raw_source_metric_can_be_nonfinite_but_certifier_rejects(self):
        # Preserve the distinction between diagnostic arithmetic and acceptance.
        x=self.finite_control();bad=x.copy();bad[0]=np.nan
        raw=source_preservation(x,bad);self.assertTrue(any(not np.isfinite(float(v)) for v in raw.values()))
        with self.assertRaises(QCError):check_source_preservation(x,bad)

if __name__=='__main__':unittest.main(verbosity=2)
