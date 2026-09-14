from __future__ import annotations
import io,json,sys,threading,time,unittest,urllib.error,urllib.request
from pathlib import Path
from unittest.mock import patch
import numpy as np
from scipy.io import wavfile
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'app'))
from zaaggenz_inspector import InspectorError,InspectorServer,InspectorService,build_analysis,fixture_source,validate_controls
from zaaggenz_inspector import service as service_module

class InspectorModelTests(unittest.TestCase):
    def test_real_fixture_exposes_combs_motion_remainder_and_compatibility(self):
        result=build_analysis(fixture_source(12000),12000,{'amount':.72,'root_hz':220.,'sonority':'fifth','anchor':'source'},revision_seed='test')
        snap=result['snapshot'].to_dict()
        self.assertEqual(snap['method']['id'],'zg.harmonic_comb_inspector.v1');self.assertEqual(len(snap['target_combs']),2)
        self.assertTrue(snap['components']);self.assertTrue(snap['remainder']);self.assertGreater(len(snap['compatibility']),20)
        self.assertTrue(any(x['requested_hz'] is not None for x in snap['components']))
        self.assertTrue(all({'requested_hz','estimated_hz','realised_hz','classification','confidence'}<=set(x) for x in snap['components']))
        self.assertEqual(snap['diagnostics']['normalization'],'none');self.assertIn('multi-comb-chordness:hybrid',snap['stage_order'])

    def test_controls_are_bounded_and_named(self):
        self.assertEqual(validate_controls({'sonority':'fourth'})['sonority'],'fourth')
        with self.assertRaises(InspectorError):validate_controls({'amount':2})
        with self.assertRaises(InspectorError):validate_controls({'mystery':1})

class InspectorServiceTests(unittest.TestCase):
    def setUp(self):self.service=InspectorService(12000)
    def tearDown(self):self.service.close()

    def test_analysis_does_not_auto_apply_and_apply_undo_are_explicit(self):
        initial=self.service.state();before=initial['working']['revision_id']
        job=self.service.submit_analysis({'amount':.9,'root_hz':225.,'sonority':'fourth','anchor':'source'})['job_id']
        self.service.scheduler.wait(job,20);status=self.service.status(job);self.assertTrue(status['published']);self.assertFalse(status['stale'])
        after_analysis=self.service.state();self.assertEqual(after_analysis['working']['revision_id'],before);self.assertNotEqual(after_analysis['slots']['B']['revision_id'],before)
        sid=after_analysis['snapshot']['snapshot_id'];self.service.freeze(sid);applied=self.service.apply(sid);self.assertEqual(applied['working']['revision_id'],after_analysis['slots']['B']['revision_id']);self.assertEqual(applied['undo_depth'],1)
        undone=self.service.undo();self.assertEqual(undone['working']['revision_id'],before);self.assertEqual(undone['undo_depth'],0)

    def test_frozen_snapshot_survives_later_analysis(self):
        first=self.service.state()['snapshot']['snapshot_id'];self.service.freeze(first)
        job=self.service.submit_analysis({'amount':.35,'root_hz':210.,'sonority':'major-third','anchor':'upper'})['job_id'];self.service.scheduler.wait(job,20);self.service.status(job)
        state=self.service.state();self.assertEqual(state['frozen_snapshot_id'],first);self.assertNotEqual(state['snapshot']['snapshot_id'],first)

    def test_stale_job_is_rejected_after_source_rebind(self):
        release=threading.Event();original=service_module.build_analysis
        def delayed(*args,**kwargs):
            while not release.wait(.01):
                checkpoint=kwargs.get('checkpoint')
                if checkpoint:checkpoint()
            return original(*args,**kwargs)
        with patch.object(service_module,'build_analysis',delayed):
            prior_b=self.service.state()['slots']['B']['revision_id'];job=self.service.submit_analysis({'amount':.88})['job_id'];time.sleep(.03);new_a=self.service.replace_source_for_test(3);release.set();self.service.scheduler.wait(job,20);status=self.service.status(job)
        self.assertTrue(status['stale']);self.assertFalse(status['published']);state=self.service.state();self.assertEqual(state['slots']['A']['revision_id'],new_a.revision_id);self.assertEqual(state['slots']['B']['revision_id'],prior_b);self.assertTrue(state['snapshot_stale'])

    def test_compensated_audio_is_peak_safe_and_revision_bound(self):
        wave,revision=self.service.audio('B',compensated=True);sr,audio=wavfile.read(io.BytesIO(wave));self.assertEqual(sr,12000);self.assertEqual(revision,self.service.state()['slots']['B']['revision_id']);self.assertLessEqual(float(np.max(np.abs(audio),initial=0)),.981)

class InspectorHTTPTests(unittest.TestCase):
    def setUp(self):
        self.server=InspectorServer(0,12000);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.base=f'http://127.0.0.1:{self.server.server_port}'
    def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join(3)
    def get(self,path):
        with urllib.request.urlopen(self.base+path,timeout=10) as r:return r.status,r.read(),dict(r.headers)
    def post(self,path,payload,token=None):
        req=urllib.request.Request(self.base+path,data=json.dumps(payload).encode(),method='POST',headers={'Content-Type':'application/json',**({'X-Zaaggenz-Token':token} if token else {})})
        with urllib.request.urlopen(req,timeout=10) as r:return r.status,json.loads(r.read())
    def test_bootstrap_static_audio_and_csrf_gate(self):
        code,raw,_=self.get('/api/inspector/bootstrap');self.assertEqual(code,200);boot=json.loads(raw);self.assertEqual(boot['state']['slots']['A']['slot'],'A')
        code,page,headers=self.get('/inspector');self.assertEqual(code,200);self.assertIn(b'Harmonic-comb',page);self.assertIn('nosniff',headers['X-Content-Type-Options'])
        code,wave,headers=self.get('/api/inspector/audio/A');self.assertEqual(code,200);self.assertGreater(len(wave),44);self.assertTrue(headers['X-Inspector-Revision'])
        with self.assertRaises(urllib.error.HTTPError) as cm:self.post('/api/inspector/undo',{})
        self.assertEqual(cm.exception.code,403)
        code,result=self.post('/api/inspector/analyse',{'controls':{'amount':.5}},boot['token']);self.assertEqual(code,202);self.assertRegex(result['job_id'],r'^[0-9a-f]{32}$')

if __name__=='__main__':unittest.main(verbosity=2)
