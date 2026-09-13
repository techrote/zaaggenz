from __future__ import annotations
from copy import deepcopy
import hashlib,io,json,threading,unittest
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError
import numpy as np
from scipy.io import wavfile
import sys
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'app'))
from zaaggenz_melody import render_phrase
from zaaggenz_project import Project
from zaaggenz_textgesture import starter_registry
from zaaggenz_contracts.music import beat_to_sample
from zaaggenz_vocal import *
from zaaggenz_vocal.server import VocalServer

SR=12000
def silence(d):return np.zeros(round(SR*d),np.float32)
def tone(f,d,a=.30):
    t=np.arange(round(SR*d))/SR;return (a*np.sin(2*np.pi*f*t)).astype(np.float32)
def noise(d,a=.20,seed=4):return np.random.default_rng(seed).normal(0,a,round(SR*d)).astype(np.float32)
def fixture():return np.concatenate([silence(.10),tone(120,.32),silence(.08),noise(.25),silence(.08),tone(150,.32),silence(.10)])
def expected_starts():return [round(SR*.10),round(SR*(.10+.32+.08)),round(SR*(.10+.32+.08+.25+.08))]

class AnalysisTests(unittest.TestCase):
    def test_known_voiced_unvoiced_fixture_quantifies_timing_pitch_and_abstention(self):
        a=analyse_vocal(fixture(),SR,origin='generated-fixture');d=a.to_dict();self.assertEqual(len(d['segments']),3)
        starts=[s['start_sample'] for s in d['segments']]
        for got,want in zip(starts,expected_starts()):self.assertLess(abs(got-want),round(.04*SR))
        self.assertEqual([s['voicing'] for s in d['segments']],['voiced','unvoiced','voiced'])
        self.assertLess(abs(d['segments'][0]['pitch_hz']-120),3);self.assertLess(abs(d['segments'][2]['pitch_hz']-150),3)
        self.assertIsNone(d['segments'][1]['pitch_hz']);self.assertLess(d['segments'][1]['pitch_confidence'],.5)
        self.assertGreater(d['segments'][1]['spectral_flatness'],.25);self.assertEqual(d['diagnostics']['shared_feature_method'],'zg-multiresolution-features-v1')
    def test_silence_and_noise_do_not_create_confident_pitch(self):
        a=analyse_vocal(np.zeros(SR//2,np.float32),SR,origin='generated-fixture');self.assertEqual(a.to_dict()['segments'],[])
        b=analyse_vocal(np.r_[silence(.1),noise(.4,.25,9),silence(.1)],SR,origin='generated-fixture')
        self.assertTrue(all(s['pitch_hz'] is None and s['voicing']!='voiced' for s in b.to_dict()['segments']))
    def test_identity_is_float_pcm_content_addressed_and_stereo_supported(self):
        x=fixture();a=analyse_vocal(x,SR,origin='generated-fixture').to_dict();raw=np.asarray(x[:,None],dtype='<f4').tobytes()
        self.assertEqual(a['source']['content_sha256'],hashlib.sha256(raw).hexdigest())
        stereo=np.column_stack((x,x*.5));b=analyse_vocal(stereo,SR,origin='generated-fixture').to_dict();self.assertEqual(b['source']['channels'],2)

class EditCompileTests(unittest.TestCase):
    def setUp(self):self.analysis=analyse_vocal(fixture(),SR,origin='generated-fixture');self.registry=starter_registry();self.edit=make_edit(self.analysis,self.registry)
    def test_grid_alignment_retains_original_sample_and_exact_error(self):
        d=self.edit.to_dict();tm=d['time_map'];segments={s['id']:s for s in d['analysis']['segments']}
        for row in d['segments']:
            self.assertEqual(row['alignment_error_samples'],segments[row['segment_id']]['start_sample']-beat_to_sample(tm,row['aligned_beat']))
            self.assertEqual(row['manual_offset_samples'],0)
        bad=deepcopy(d);bad['segments'][0]['alignment_error_samples']+=1
        with self.assertRaises(VocalCaptureError):VocalEdit(bad)
    def test_unvoiced_abstains_to_rest_until_manual_pitch_is_explicit(self):
        c=compile_edit(self.edit,self.registry);events=c.phrase.to_dict()['events'];self.assertIsNone(events[1]['pitch']);self.assertEqual(c.preview['events'][1]['compiled_as'],'unpitched-rest')
        changed=update_segment(self.edit,'vocal-001',pitch_mode='manual',manual_pitch_hz=135.)
        cc=compile_edit(changed,self.registry);self.assertIsNotNone(cc.phrase.to_dict()['events'][1]['pitch']);self.assertEqual(cc.preview['events'][1]['pitch_mode'],'manual')
        cleared=update_segment(changed,'vocal-001',pitch_mode='unpitched');self.assertIsNone(compile_edit(cleared,self.registry).phrase.to_dict()['events'][1]['pitch'])
    def test_manual_time_pitch_brightness_are_independent_and_original_analysis_is_immutable(self):
        before=self.edit.to_dict()['analysis'];changed=update_segment(self.edit,'vocal-000',manual_offset_samples=37,pitch_mode='manual',manual_pitch_hz=125.,manual_brightness_hz=2200.)
        c=compile_edit(changed,self.registry);row=c.preview['events'][0]
        self.assertEqual(row['manual_offset_samples'],37);self.assertAlmostEqual(row['pitch_hz'],125.);self.assertAlmostEqual(row['brightness_hz'],2200.)
        self.assertEqual(changed.to_dict()['analysis'],before);self.assertNotEqual(row['effective_beat'],self.edit.to_dict()['segments'][0]['aligned_beat'])
    def test_dictionary_mapping_is_project_local_and_changes_semantic_controls_not_capture_identity(self):
        c=compile_edit(self.edit,self.registry);d=self.edit.to_dict();d['dictionary_id']='local-bright';bright=VocalEdit(d)
        cb=compile_edit(bright,self.registry);self.assertEqual(c.preview['source'],cb.preview['source']);self.assertNotEqual(c.automation,cb.automation)
        self.assertNotEqual(c.preview['dictionary_sha256'],cb.preview['dictionary_sha256'])
    def test_discarding_raw_source_leaves_compiled_timeline_and_phrase_usable(self):
        before=compile_edit(self.edit,self.registry);discarded=mark_source_discarded(self.edit);after=compile_edit(discarded,self.registry)
        self.assertEqual(before.phrase.to_dict(),after.phrase.to_dict());self.assertEqual(before.timeline.to_dict(),after.timeline.to_dict());self.assertEqual(after.preview['source_disposition'],'discarded')
    def test_protected_source_is_preserved_and_real_preview_renders(self):
        c=compile_edit(self.edit,self.registry);recipe=make_render_recipe(c);base=Project.from_document(c.timeline.to_dict()['project']).head_recipe.to_dict()
        self.assertEqual(recipe.to_dict()['source'],base['source']);r=render_phrase(recipe);self.assertGreater(np.max(np.abs(r.mix)),0);self.assertEqual(r.diagnostics['clipped_fraction'],0)
    def test_registry_identity_and_invalid_manual_ranges_fail(self):
        bad=deepcopy(self.edit.to_dict());bad['dictionary_registry_sha256']='0'*64
        with self.assertRaises(VocalCaptureError):compile_edit(VocalEdit(bad),self.registry)
        with self.assertRaises(VocalCaptureError):update_segment(self.edit,'vocal-000',manual_offset_samples=SR+1)
        with self.assertRaises(VocalCaptureError):update_segment(self.edit,'vocal-000',pitch_mode='manual',manual_pitch_hz=None)

class StoreTests(unittest.TestCase):
    def test_wav_roundtrip_import_and_discard_are_session_local(self):
        raw=encode_wav_bytes(fixture(),SR);sr,x=decode_wav_bytes(raw);self.assertEqual(sr,SR);self.assertEqual(len(x),len(fixture()))
        store=SessionAudioStore();identifier=store.put(x,sr);self.assertTrue(store.has(identifier));got,gsr,_=store.get(identifier);self.assertEqual(gsr,SR);np.testing.assert_allclose(got[:,0],fixture(),atol=1e-7)
        self.assertTrue(store.discard(identifier));self.assertFalse(store.has(identifier));
        with self.assertRaises(VocalCaptureError):store.get(identifier)
    def test_pcm16_recording_style_wav_is_decoded_safely(self):
        b=io.BytesIO();wavfile.write(b,SR,np.asarray(fixture()*32767,dtype=np.int16));sr,x=decode_wav_bytes(b.getvalue());self.assertEqual(sr,SR);self.assertTrue(np.isfinite(x).all());self.assertLessEqual(np.max(np.abs(x)),1)

class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=VocalServer(0,SR);cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start();cls.url=f'http://127.0.0.1:{cls.server.server_port}'
    @classmethod
    def tearDownClass(cls):cls.server.shutdown();cls.server.server_close();cls.thread.join(2)
    def request(self,path,data=None,content='application/json',token=True,headers=None):
        h={'Content-Type':content,**(headers or {})}
        if token:h['X-Zaaggenz-Token']=self.server.token
        body=None if data is None else (json.dumps(data).encode() if content=='application/json' else data)
        with urlopen(Request(self.url+path,data=body,headers=h),timeout=20) as r:return r.status,r.headers,r.read()
    def upload(self):
        _,_,body=self.request('/api/vocal/upload',encode_wav_bytes(fixture(),SR),'audio/wav',headers={'X-Capture-Origin':'local-import'});return json.loads(body)
    def test_bootstrap_vocal_static_and_normal_compose_coexist_without_microphone(self):
        _,_,raw=self.request('/api/vocal/bootstrap');boot=json.loads(raw);self.assertTrue(boot['microphone_optional']);self.assertIn('not been requested',boot['capture_state'])
        for path,needle in [('/vocal',b'Local vocal gesture'),('/vocal/app.mjs',b'getUserMedia'),('/timeline',b'Phrase timeline')]:
            _,_,body=self.request(path);self.assertIn(needle,body)
    def test_upload_analyse_compile_discard_then_compile_again(self):
        source=self.upload();_,_,raw=self.request('/api/vocal/analyse',{'source_id':source['source_id'],'dictionary_id':'local-soft','grid_beats':'1/4'});analysed=json.loads(raw);self.assertEqual(len(analysed['analysis']['segments']),3)
        _,_,raw=self.request('/api/vocal/compile',{'edit':analysed['edit']});first=json.loads(raw)
        _,_,raw=self.request('/api/vocal/discard',{'source_id':source['source_id'],'edit':analysed['edit']});discard=json.loads(raw);self.assertTrue(discard['discarded'])
        _,_,raw=self.request('/api/vocal/compile',{'edit':discard['edit']});second=json.loads(raw);self.assertEqual(first['timeline'],second['timeline'])
        with self.assertRaises(HTTPError):self.request(f"/api/vocal/source/{source['source_id']}/audio")
    def test_foreign_origin_bad_token_and_non_wav_are_rejected(self):
        with self.assertRaises(HTTPError) as cm:self.request('/api/vocal/bootstrap',headers={'Origin':'https://foreign.invalid'});self.assertEqual(cm.exception.code,403)
        with self.assertRaises(HTTPError) as cm:self.request('/api/vocal/analyse',{'source_id':'capture-'+'0'*16,'dictionary_id':'local-soft','grid_beats':'1/4'},token=False);self.assertEqual(cm.exception.code,403)
        with self.assertRaises(HTTPError):self.request('/api/vocal/upload',b'not a wav','audio/wav')

if __name__=='__main__':unittest.main(verbosity=2)
