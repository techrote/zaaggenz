"""Independent research tests. Passing is not production acceptance or listening evidence."""
import csv
import json
import tempfile
import unittest
from pathlib import Path
from fractions import Fraction
import numpy as np
from common import cents, mono, rms
from spectral_probes import stft, istft, integrated_phase, bands, project, crush, affinity, comb, dissonance_curves
from musical_probes import parse_scl, parse_kbm, sample_at, run_clocks, run_phrases
from residual_probe import run as residual_run
from design_simulation import run_job_model


class SignalTests(unittest.TestCase):
    def test_empty_rejected(self):
        with self.assertRaises(ValueError): mono([])
    def test_nan_rejected(self):
        with self.assertRaises(ValueError): mono([np.nan])
    def test_stereo_not_silently_flattened(self):
        with self.assertRaises(ValueError): mono(np.ones((4,2)))
    def test_cents_reject_zero(self):
        with self.assertRaises(ValueError): cents(0)
    def test_cents_octave(self):
        self.assertEqual(cents(2),1200)
    def test_stft_impulse_edges(self):
        for count in (1,17,1003):
            for n in (64,256):
                x=np.zeros(count);x[0]=.2;x[-1]+=.5
                z,w=stft(x,n,n//4);y=istft(z,w,n//4,count)
                np.testing.assert_allclose(x,y,rtol=0,atol=2e-14)
    def test_stft_seeded_noise(self):
        x=np.random.default_rng(8).normal(size=8199)
        z,w=stft(x,1024,256);np.testing.assert_allclose(x,istft(z,w,256,len(x)),atol=2e-14)
    def test_stft_silence(self):
        z,w=stft(np.zeros(777),256,64)
        self.assertEqual(rms(istft(z,w,64,777)),0)
    def test_window_validation(self):
        with self.assertRaises(ValueError): stft(np.ones(30),17,4)
    def test_phase_constant(self):
        f=np.full(500,48.);p=integrated_phase(f,48000,.3)
        self.assertEqual(p[0],.3)
        np.testing.assert_allclose(np.diff(p)*48000/(2*np.pi),48,atol=1e-11)
    def test_phase_glide_derivative(self):
        f=np.linspace(48,55,48000);p=integrated_phase(f,48000)
        np.testing.assert_allclose(np.diff(p)*48000/(2*np.pi),(f[:-1]+f[1:])/2,atol=1e-9)


class BandTests(unittest.TestCase):
    def setUp(self):
        self.sr=48000;t=np.arange(self.sr)/self.sr
        self.x=sum(.1*np.sin(2*np.pi*f*t) for f in (105,520,3600));self.cross=(105,520,3600)
    def test_reconstruction(self):
        np.testing.assert_allclose(sum(bands(self.x,self.sr,self.cross)),self.x,atol=1e-14)
    def test_refilter_counterexample(self):
        b=bands(self.x,self.sr,self.cross)
        y=sum(project(v,self.sr,self.cross,i) for i,v in enumerate(b))
        self.assertGreater(rms(y-self.x)/rms(self.x),.1)
    def test_effect_delta_identity(self):
        y=self.x+sum(project(v-v,self.sr,self.cross,i) for i,v in enumerate(bands(self.x,self.sr,self.cross)))
        np.testing.assert_array_equal(y,self.x)
    def test_crush_silence(self):
        np.testing.assert_array_equal(crush(np.zeros(512)),0)
    def test_crush_zero_symmetry(self):
        x=np.linspace(0,1,51);np.testing.assert_allclose(crush(-x,7,1),-crush(x,7,1))
    def test_crush_bounds(self):
        with self.assertRaises(ValueError): crush(self.x,bits=0)
    def test_bad_crossover(self):
        with self.assertRaises(ValueError): bands(self.x,self.sr,(500,105,3600))


class TuningTests(unittest.TestCase):
    def test_blank_description(self): self.assertEqual(parse_scl('\n1\n2/1').degree(1),2)
    def test_comments_and_labels(self): self.assertEqual(parse_scl('! comment\ndesc\n1\n2/1 octave').degree(1),2)
    def test_integer_means_ratio(self): self.assertEqual(parse_scl('a\n1\n1200').degree(1),1200)
    def test_decimal_means_cents(self): self.assertEqual(parse_scl('a\n1\n1200.0').degree(1),2)
    def test_negative_cents_allowed(self): self.assertLess(parse_scl('a\n2\n-50.0\n2/1').degree(1),1)
    def test_negative_ratio_rejected(self):
        with self.assertRaises(ValueError): parse_scl('a\n1\n-2/1')
    def test_zero_ratio_rejected(self):
        with self.assertRaises(ValueError): parse_scl('a\n1\n0')
    def test_empty_scale_not_playable(self):
        s=parse_scl('a\n0')
        with self.assertRaises(ValueError): s.degree(0)
    def test_count_mismatch(self):
        with self.assertRaises(ValueError): parse_scl('a\n2\n2/1')
    def test_extra_pitch_rejected(self):
        with self.assertRaises(ValueError): parse_scl('a\n1\n2/1\n3/1')
    def test_non_octave_negative(self):
        s=parse_scl('a\n2\n3/2\n3/1');self.assertAlmostEqual(s.degree(-1),.5)
    def test_linear_map(self):
        s=parse_scl('a\n1\n2/1');m=parse_kbm('0\n0\n127\n60\n60\n48\n1')
        self.assertEqual(m.frequency(s,61),96)
    def test_sparse_map(self):
        s=parse_scl('a\n2\n3/2\n2/1');m=parse_kbm('2\n0\n127\n60\n60\n48\n2\n0\nx')
        self.assertIsNone(m.frequency(s,61));self.assertEqual(m.frequency(s,62),96)
    def test_unmapped_reference(self):
        with self.assertRaises(ValueError): parse_kbm('2\n0\n127\n60\n61\n48\n2\n0\nx')
    def test_key_outside_range(self):
        s=parse_scl('a\n1\n2');m=parse_kbm('0\n60\n61\n60\n60\n48\n1')
        self.assertIsNone(m.frequency(s,62))
    def test_negative_formal_octave_allowed(self):
        s=parse_scl('a\n1\n2');m=parse_kbm('1\n0\n127\n60\n60\n48\n-1\n0')
        self.assertEqual(m.frequency(s,61),24)


class ModelTests(unittest.TestCase):
    def test_clock_absolute(self):
        for i in range(500):
            exact=Fraction(i,12)*60*44100/Fraction('199.7')
            self.assertLessEqual(abs(sample_at(Fraction(i,12),199.7,44100)-exact),Fraction(1,2))
    def test_clock_invalid(self):
        with self.assertRaises(ValueError): sample_at(1,0,48000)
    def test_clock_noninteger_sr(self):
        with self.assertRaises(ValueError): sample_at(1,120,48000.5)
    def test_density_monotone(self):
        a=48*np.arange(1,25);self.assertEqual(affinity(a,comb([1])),1)
        self.assertEqual(affinity(a,comb(2**(np.arange(12)/12))),1)
    def test_roughness_cross_not_total(self):
        f=np.array([48.,55.]);a=np.ones(2);x,y=dissonance_curves(f,a,np.array([0.,700.]))
        self.assertTrue(np.all(y>x))
    def test_phase_residual_counterexample(self):
        with tempfile.TemporaryDirectory() as t: rows=residual_run(Path(t))
        r=next(r for r in rows if r['duration_s']==1 and r['frequency_error_hz']==.5 and r['estimated_amplitude']==1)
        self.assertLess(r['identity_error_db'],-250);self.assertGreater(r['transformed_error_db'],0)
    def test_stale_result_model(self):
        with tempfile.TemporaryDirectory() as t:
            run_job_model(Path(t));r=json.loads((Path(t)/'job_policy_model.json').read_text())
        self.assertEqual(r['revision_checked_stale_publications'],0);self.assertEqual(r['naive_stale_publications'],18)
    def test_phrase_role_not_five_meter(self):
        with tempfile.TemporaryDirectory() as t:
            run_phrases(Path(t));r=json.loads((Path(t)/'phrase_design.json').read_text())
        self.assertEqual(r['summary']['stable_fill_location']['empirical_location_entropy_bits'],0)
        self.assertEqual(r['summary']['stable_fill_location']['return_beat'],16)


if __name__=='__main__': unittest.main(verbosity=2)
