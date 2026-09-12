import hashlib,json,subprocess,sys,tempfile,unittest
from pathlib import Path
import numpy as np
from zaaggenz_reference import load_registry,load_locators,resolve_assets,descriptor_pcm,compare_planning,validate_annotation
from zaaggenz_reference.annotation import AnnotationError

ROOT=Path(__file__).resolve().parents[2]
REG=ROOT/'references/private_registry_v1.json'

class RegistryTests(unittest.TestCase):
    def test_registered_identities_and_rights(self):
        r=load_registry(REG);self.assertEqual(len(r['assets']),6);self.assertEqual(len({a['sha256'] for a in r['assets']}),6)
        self.assertTrue(all(a['rights']['redistribution']=='not-authorized-in-repository' for a in r['assets']))
    def test_empty_locators_report_missing(self):
        r=load_registry(REG);l=load_locators(ROOT/'references/locator-example.json');rows=resolve_assets(r,l);self.assertTrue(all(x['status']=='missing' for x in rows))
    def test_hash_mismatch_not_substituted(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'x';p.write_bytes(b'wrong')
            reg={'assets':[{'id':'a','sha256':'0'*64,'bytes':5}]};loc={'paths':{'a':str(p)}}
            self.assertEqual(resolve_assets(reg,loc)[0]['status'],'identity-mismatch')
    def test_cli_report_omits_local_paths(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/'r.json';cp=subprocess.run([sys.executable,'-m','zaaggenz_reference','--locators',str(ROOT/'references/locator-example.json'),'--out',str(out)],cwd=ROOT,capture_output=True,text=True)
            self.assertEqual(cp.returncode,2);text=out.read_text();self.assertNotIn('"path"',text);self.assertFalse(json.loads(text)['source_paths_included'])

class DescriptorTests(unittest.TestCase):
    def test_unclamped_stereo(self):
        sr=24000;t=np.arange(sr)/sr;l=1.5*np.sin(2*np.pi*997*t);x=np.column_stack((l,-l));d=descriptor_pcm(x,sr)
        self.assertGreater(d['sample_peak'],1.49);self.assertGreater(d['samples_abs_ge_1_fraction'],0);self.assertLess(d['stereo_correlation'],-.999999)
    def test_self_planning_comparison(self):
        e=load_registry(REG)['assets'][0]['planning'];o={'decoded_duration_s':e['decoded_24k_duration_s'],'sample_peak':e['sample_peak_24k'],'loudness':{'integrated_lufs':e['integrated_lufs'],'true_peak_dbtp':e['true_peak_dbtp']},'energetic_medians':e['energetic_medians']}
        self.assertTrue(compare_planning(o,e)['pass'])
    def test_nonfinite_rejected(self):
        x=np.zeros((24000,2));x[0,0]=np.nan
        with self.assertRaises(ValueError):descriptor_pcm(x,24000)

class AnnotationTests(unittest.TestCase):
    def test_automatic_candidates_validate_as_uncertain(self):
        d=json.loads((ROOT/'references/paired_suggestions_v1.json').read_text());validate_annotation(d,{'activation','zaagtivation'});self.assertTrue(all(r['relation']=='uncertain' and r['confidence']==0 for r in d['relations']))
    def test_ambiguous_meter_and_unrelated_sections_supported(self):
        seg=lambda i,a:{'id':i,'asset_id':a,'start_sample':0,'end_sample':48000,'section_function':'unknown','label':'x','confidence':.5,'source':'manual','meter_candidates':[{'numerator':4,'denominator':4,'pulse_divisor':1,'confidence':.5},{'numerator':4,'denominator':4,'pulse_divisor':2,'confidence':.4}],'correspondence_group':None}
        d={'version':'1.0.0','segments':[seg('a','activation'),seg('b','zaagtivation')],'relations':[{'id':'r','left_segment':'a','right_segment':'b','relation':'unrelated','confidence':.9,'source':'manual'}]};validate_annotation(d,{'activation','zaagtivation'})
    def test_bad_meter_confidence(self):
        d=json.loads((ROOT/'references/paired_suggestions_v1.json').read_text());d['segments'][0]['meter_candidates']=[{'numerator':4,'denominator':4,'pulse_divisor':1,'confidence':.7},{'numerator':3,'denominator':4,'pulse_divisor':1,'confidence':.7}]
        with self.assertRaises(AnnotationError):validate_annotation(d,{'activation','zaagtivation'})

class SafetyTests(unittest.TestCase):
    def test_repository_safety_scanner(self):
        cp=subprocess.run([sys.executable,'tools/check_reference_safety.py'],cwd=ROOT,capture_output=True,text=True);self.assertEqual(cp.returncode,0,cp.stdout+cp.stderr)
    def test_holdout_inventory(self):
        d=json.loads((ROOT/'references/holdout_families_v1.json').read_text());self.assertGreaterEqual(sum(x['role']=='holdout' for x in d['families']),2)

if __name__=='__main__':unittest.main(verbosity=2)
