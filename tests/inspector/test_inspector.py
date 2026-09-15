from __future__ import annotations
import hashlib,io,json,sys,threading,time,unittest,urllib.error,urllib.request
from pathlib import Path
from unittest.mock import patch
import numpy as np
from scipy.io import wavfile
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'app'))
from zaaggenz_inspector import InspectorError,InspectorServer,InspectorService,build_analysis,fixture_source,validate_controls
from zaaggenz_inspector import service as service_module
from zaaggenz_jobs import JobClass,RenderArtifact
from zaaggenz_timeline import TimelineService,default_document


def make_artifact(audio,*,sample_rate=12000,channels=1,seed='0'):
    values=np.asarray(audio,dtype='<f4').reshape(-1);payload=values.tobytes();frames=len(values)//channels
    revision=hashlib.sha256(('revision-'+seed).encode()).hexdigest();recipe=hashlib.sha256(('recipe-'+seed).encode()).hexdigest();cache=hashlib.sha256(('cache-'+seed).encode()).hexdigest()
    asset=dict(kind='AudioAssetRef',version='1.0.0',content_sha256=hashlib.sha256(payload).hexdigest(),identity_domain='pcm-f32le-interleaved-v1',sample_rate_hz=sample_rate,channels=channels,
               channel_layout='mono' if channels==1 else 'stereo-lr',frame_count=frames,level_domain='source',sample_policy='unclamped_float')
    return RenderArtifact(revision,recipe,'synth',cache,payload,asset,{'test_seed':seed})


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
    def setUp(self):self.service=InspectorService(12000,demo_fixture=True)
    def tearDown(self):self.service.close()

    def test_production_service_starts_unbound_and_fixture_is_explicit(self):
        service=InspectorService(12000)
        try:
            state=service.state();self.assertFalse(state['bound']);self.assertIsNone(state['slots']['A']);self.assertIsNone(state['snapshot'])
            with self.assertRaisesRegex(InspectorError,'bind an immutable render artifact'):service.submit_analysis({})
            with self.assertRaisesRegex(InspectorError,'no inspector source'):service.audio('A')
        finally:service.close()
        self.assertEqual(self.service.state()['source_binding']['kind'],'demo-fixture')

    def test_render_artifact_binding_preserves_pcm_and_provenance_then_analysis(self):
        artifact=make_artifact(fixture_source(12000,variant=2),seed='bind')
        state=self.service.bind_artifact(artifact);asset=artifact.asset
        self.assertTrue(state['bound']);self.assertIsNone(state['slots']['B']);self.assertIsNone(state['snapshot'])
        self.assertEqual(state['slots']['A']['revision_id'],artifact.revision_id);self.assertEqual(state['slots']['A']['audio_sha256'],asset['content_sha256'])
        self.assertEqual(state['source_binding']['recipe_sha256'],artifact.recipe_sha256);self.assertEqual(state['source_binding']['cache_key'],artifact.cache_key)
        self.assertEqual(state['working']['revision_id'],artifact.revision_id)
        wave,revision=self.service.audio('A');sr,audio=wavfile.read(io.BytesIO(wave));self.assertEqual(sr,12000);self.assertEqual(revision,artifact.revision_id)
        self.assertEqual(hashlib.sha256(np.asarray(audio,dtype='<f4').tobytes()).hexdigest(),asset['content_sha256'])
        job=self.service.submit_analysis({'amount':.43})['job_id'];self.service.scheduler.wait(job,20);status=self.service.status(job);self.assertTrue(status['published'])
        analysed=self.service.state();provenance=analysed['snapshot']['expert']['source_binding'];self.assertEqual(provenance,analysed['source_binding'])
        self.assertEqual(analysed['snapshot']['before']['revision_id'],artifact.revision_id);self.assertEqual(analysed['snapshot']['before']['audio_sha256'],asset['content_sha256'])

    def test_actual_timeline_render_binds_without_reconstruction(self):
        timeline=TimelineService();service=InspectorService(12000)
        try:
            document=default_document(12000).to_dict();document['notes']=[{'id':'inspect-me','beat':'0/1','duration_beats':'1/2','degree':0,'detune_cents':0.,'gain_db':0.,'muted':False,'roll_density':0}];document['next_id']=1
            job=timeline.submit(document,{'start_beat':'0/1','end_beat':'1/1'},'Inspector source')['job_id'];timeline.scheduler.wait(job,30);artifact=timeline.scheduler.result(job)
            bound=service.bind_artifact(artifact);self.assertEqual(bound['slots']['A']['audio_sha256'],artifact.asset['content_sha256']);self.assertEqual(bound['slots']['A']['revision_id'],artifact.revision_id)
            wave,_=service.audio('A');_,audio=wavfile.read(io.BytesIO(wave));self.assertEqual(hashlib.sha256(np.asarray(audio,dtype='<f4').tobytes()).hexdigest(),artifact.asset['content_sha256'])
            analysis=service.submit_analysis({'amount':.2})['job_id'];service.scheduler.wait(analysis,30);published=service.status(analysis);self.assertTrue(published['published']);self.assertFalse(published['stale'])
            self.assertEqual(published['state_payload']['snapshot']['expert']['source_binding']['recipe_sha256'],artifact.recipe_sha256)
        finally:service.close();timeline.close()

    def test_binding_rejects_non_mono_nonfinite_and_short_inputs(self):
        stereo=np.repeat(fixture_source(12000,variant=1)[:128],2)
        with self.assertRaisesRegex(InspectorError,'mono'):self.service.bind_artifact(make_artifact(stereo,channels=2,seed='stereo'))
        bad=fixture_source(12000,variant=1)[:128].copy();bad[3]=np.nan
        with self.assertRaisesRegex(InspectorError,'finite'):self.service.bind_artifact(make_artifact(bad,seed='nan'))
        with self.assertRaisesRegex(InspectorError,'at least 64'):self.service.bind_artifact(make_artifact(np.zeros(63,dtype=np.float32),seed='short'))
        accepted=self.service.bind_artifact(make_artifact(np.zeros(64,dtype=np.float32),seed='boundary'));self.assertEqual(accepted['slots']['A']['frame_count'],64)

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

    def test_stale_job_is_rejected_after_artifact_rebind(self):
        release=threading.Event();original=service_module.build_analysis
        def delayed(*args,**kwargs):
            while not release.wait(.01):
                checkpoint=kwargs.get('checkpoint')
                if checkpoint:checkpoint()
            return original(*args,**kwargs)
        with patch.object(service_module,'build_analysis',delayed):
            job=self.service.submit_analysis({'amount':.88})['job_id'];time.sleep(.03);artifact=make_artifact(fixture_source(12000,variant=3),seed='replacement');self.service.bind_artifact(artifact);release.set();self.service.scheduler.wait(job,20);status=self.service.status(job)
        self.assertTrue(status['stale']);self.assertFalse(status['published']);state=self.service.state();self.assertEqual(state['slots']['A']['revision_id'],artifact.revision_id);self.assertIsNone(state['slots']['B']);self.assertIsNone(state['snapshot'])

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
    def publish_artifact(self,artifact):
        jid=self.server.timeline.scheduler.submit(JobClass.RENDER,artifact.revision_id,lambda ctx:artifact,estimated_memory_bytes=8*1024*1024);self.server.timeline.scheduler.wait(jid,10);return jid
    def test_bootstrap_bind_static_audio_and_csrf_gate(self):
        code,raw,_=self.get('/api/inspector/bootstrap');self.assertEqual(code,200);boot=json.loads(raw);self.assertFalse(boot['state']['bound'])
        artifact=make_artifact(fixture_source(12000,variant=4),seed='http');jid=self.publish_artifact(artifact)
        with self.assertRaises(urllib.error.HTTPError) as cm:self.post('/api/inspector/bind',{'job_id':jid})
        self.assertEqual(cm.exception.code,403)
        code,bound=self.post('/api/inspector/bind',{'job_id':jid},boot['token']);self.assertEqual(code,200);self.assertEqual(bound['source_binding']['content_sha256'],artifact.asset['content_sha256'])
        code,page,headers=self.get('/inspector');self.assertEqual(code,200);self.assertIn(b'Harmonic-comb',page);self.assertIn('nosniff',headers['X-Content-Type-Options'])
        code,wave,headers=self.get('/api/inspector/audio/A');self.assertEqual(code,200);self.assertGreater(len(wave),44);self.assertEqual(headers['X-Inspector-Revision'],artifact.revision_id)
        code,result=self.post('/api/inspector/analyse',{'controls':{'amount':.5}},boot['token']);self.assertEqual(code,202);self.assertRegex(result['job_id'],r'^[0-9a-f]{32}$')
    def test_bind_fails_closed_for_unknown_or_nonartifact_job(self):
        _,raw,_=self.get('/api/inspector/bootstrap');token=json.loads(raw)['token']
        with self.assertRaises(urllib.error.HTTPError) as cm:self.post('/api/inspector/bind',{'job_id':'0'*32},token)
        self.assertEqual(cm.exception.code,400)
        revision='a'*64;jid=self.server.timeline.scheduler.submit(JobClass.RENDER,revision,lambda ctx:{'not':'artifact'},estimated_memory_bytes=8*1024*1024);self.server.timeline.scheduler.wait(jid,10)
        with self.assertRaises(urllib.error.HTTPError) as cm:self.post('/api/inspector/bind',{'job_id':jid},token)
        self.assertEqual(cm.exception.code,400)

if __name__=='__main__':unittest.main(verbosity=2)
