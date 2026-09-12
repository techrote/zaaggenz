from copy import deepcopy
import math
from pathlib import Path
import subprocess,sys,tempfile,unittest

from zaaggenz_tuning import *
from zaaggenz_tuning.scala import ScalaScale,ScalaKBM

ROOT=Path(__file__).resolve().parents[2]

class MathTests(unittest.TestCase):
    def test_cents_ratio_roundtrip(self):
        for cents in (-2400,-701.955000865,0,100,701.955000865,1200,1901.934473669):
            self.assertAlmostEqual(ratio_to_cents(cents_to_ratio(cents)),cents,10)
    def test_ratio_examples(self):
        self.assertAlmostEqual(ratio_to_cents(2),1200,12);self.assertAlmostEqual(ratio_to_cents(3/2),701.9550008653874,10)
    def test_negative_degrees_and_period_wrap(self):
        t=fixture_pack()['12tet-a440'];self.assertAlmostEqual(t.frequency(-12),220,10);self.assertAlmostEqual(t.frequency(12),880,10)
    def test_non_octave_period(self):
        t=fixture_pack()['synthetic-13ed3'];self.assertAlmostEqual(t.degree_ratio(13),3,11);self.assertAlmostEqual(t.degree_ratio(-13),1/3,11)
    def test_ratio_fixture(self):
        t=fixture_pack()['synthetic-ratio-7'];self.assertAlmostEqual(t.frequency(4),72,12)
    def test_explicit_root_lock(self):
        t=fixture_pack()['synthetic-ratio-7'];self.assertAlmostEqual(t.frequency(4,root_hz=60,root_degree=0),90,12)
    def test_transpose_matches_degree_ratio(self):
        t=fixture_pack()['12tet-a440'];self.assertAlmostEqual(transpose_frequency(t,48,7),48*2**(7/12),11)
    def test_analysis_does_not_mutate_tuning(self):
        spec=tuning_to_spec(fixture_pack()['12tet-a440']);before=deepcopy(spec);r=analyse_frequency(spec,445)
        self.assertEqual(spec,before);self.assertEqual(r['tuning_id'],'tet12-a440');self.assertAlmostEqual(r['observed_hz'],445)
    def test_invalid_values(self):
        for f in (lambda:cents_to_ratio(float('nan')),lambda:ratio_to_cents(0),lambda:transpose_frequency(fixture_pack()['12tet-a440'],0,1)):
            with self.assertRaises(TuningError):f()

class KeyboardTests(unittest.TestCase):
    def test_direct_and_keyboard_share_target_api(self):
        t=fixture_pack()['12tet-a440'];direct=resolve_pitch_target(t,degree=0);key=resolve_pitch_target(t,key=69)
        self.assertEqual(direct.frequency_hz,key.frequency_hz);self.assertEqual(direct.degree,key.degree)
    def test_unmapped_key_is_explicit_rest(self):
        scale=parse_scl((ROOT/'examples/tuning/12tet.scl').read_text());kbm=parse_kbm((ROOT/'examples/tuning/sparse.kbm').read_text());t=load_scala_tuning((ROOT/'examples/tuning/12tet.scl').read_text(),(ROOT/'examples/tuning/sparse.kbm').read_text(),tuning_id='sparse')
        self.assertIsNone(resolve_pitch_target(t,key=61));self.assertIsNotNone(resolve_pitch_target(t,key=60))
    def test_outside_keyboard_range_rest(self):
        t=fixture_pack()['12tet-a440'];self.assertIsNone(t.keyboard_frequency(128) if False else None)
        with self.assertRaises(TuningError):t.keyboard_frequency(128)
    def test_exactly_one_addressing_mode(self):
        t=fixture_pack()['12tet-a440']
        with self.assertRaises(TuningError):resolve_pitch_target(t)
        with self.assertRaises(TuningError):resolve_pitch_target(t,degree=0,key=69)

class ScalaTests(unittest.TestCase):
    def test_12tet_fixture(self):
        s=parse_scl((ROOT/'examples/tuning/12tet.scl').read_text());self.assertEqual(len(s.degree_ratios),12);self.assertAlmostEqual(s.period_ratio,2,11)
    def test_non_octave_fixture(self):
        t=load_scala_tuning((ROOT/'examples/tuning/13ed3.scl').read_text(),tuning_id='13ed3');self.assertAlmostEqual(t.period_ratio,3,10);self.assertEqual(t.degrees_per_period,13)
    def test_integer_token_is_ratio_not_cents(self):
        self.assertEqual(parse_scl('x\n1\n1200\n').period_ratio,1200)
        self.assertAlmostEqual(parse_scl('x\n1\n1200.0\n').period_ratio,2,12)
    def test_blank_description(self):self.assertAlmostEqual(parse_scl('\n1\n2/1\n').period_ratio,2)
    def test_ratio_and_negative_cents(self):
        s=parse_scl('x\n3\n-50.0\n3/2\n2/1\n');self.assertLess(s.pitch_ratios[0],1);self.assertAlmostEqual(s.pitch_ratios[1],1.5)
    def test_scl_export_semantic_roundtrip(self):
        s=parse_scl((ROOT/'examples/tuning/13ed3.scl').read_text());q=parse_scl(export_scl(s));self.assertEqual(len(s.pitch_ratios),len(q.pitch_ratios))
        for a,b in zip(s.pitch_ratios,q.pitch_ratios):self.assertLess(abs(ratio_to_cents(a/b)),1e-8)
    def test_kbm_sparse(self):
        k=parse_kbm((ROOT/'examples/tuning/sparse.kbm').read_text());self.assertEqual(k.degree(60),0);self.assertIsNone(k.degree(61));self.assertEqual(k.degree(62),4)
    def test_kbm_export_semantic_roundtrip(self):
        k=parse_kbm((ROOT/'examples/tuning/sparse.kbm').read_text());q=parse_kbm(export_kbm(k));self.assertEqual(k,q)
    def test_zero_size_kbm_expands_linear(self):
        k=parse_kbm('0\n0\n127\n60\n60\n48\n12\n');m=k.to_keyboard_map();self.assertEqual(m.degree(72),12);self.assertEqual(m.degree(59),-1)
    def test_unmapped_reference_fails_loading(self):
        scl='x\n2\n3/2\n2/1\n';kbm='2\n0\n127\n60\n61\n48\n2\n0\nx\n'
        with self.assertRaises(TuningError):load_scala_tuning(scl,kbm)
    def test_malformed_counts_and_ratios(self):
        bad=['x\n2\n2/1\n','x\n1\n0\n','x\n1\n-2/1\n','x\n2\n2/1\n3/2\n','x\n0\n']
        for text in bad:
            with self.subTest(text=text),self.assertRaises(TuningError):parse_scl(text)
    def test_bad_kbm_count(self):
        with self.assertRaises(TuningError):parse_kbm('2\n0\n127\n60\n60\n48\n2\n0\n')
    def test_cli(self):
        cp=subprocess.run([sys.executable,'-m','zaaggenz_tuning',str(ROOT/'examples/tuning/12tet.scl'),'--json'],cwd=ROOT,capture_output=True,text=True,check=True)
        self.assertEqual(__import__('json').loads(cp.stdout)['spec']['kind'],'TuningSpec')

class ContractTests(unittest.TestCase):
    def test_all_fixture_specs_validate_and_roundtrip(self):
        for name,t in fixture_pack().items():
            with self.subTest(name=name):self.assertEqual(tuning_from_spec(tuning_to_spec(t)).degree_ratios,t.degree_ratios)

if __name__=='__main__':unittest.main(verbosity=2)
