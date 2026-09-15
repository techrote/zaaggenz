from __future__ import annotations
from copy import deepcopy
import json,sys,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request,urlopen
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'app'))
from zaaggenz_inspector import service as inspector_service_module
from zaaggenz_jobs import JobError
from zaaggenz_runtime import RuntimeSession,ZaaggenzServer
from zaaggenz_timeline import TimelineDocument


def note(degree=0):
    return {'id':'runtime-note','beat':'0/1','duration_beats':'1/2','degree':degree,'detune_cents':0.,'gain_db':-12.,'muted':False,'roll_density':0}


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.server=ZaaggenzServer(0,12000);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.base=f'http://127.0.0.1:{self.server.server_port}'
        self.boot=self.get_json('/api/runtime/bootstrap');self.token=self.boot['token']
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join(3)

    def request(self,path,data=None,*,token=None,trusted=None,headers=None):
        h={**(headers or {})}
        if data is not None:h['Content-Type']='application/json'
        if token is not None:h['X-Zaaggenz-Token']=token
        if trusted is not None:h['X-Zaaggenz-Trusted-Token']=trusted
        body=None if data is None else json.dumps(data).encode()
        with urlopen(Request(self.base+path,data=body,headers=h),timeout=30) as r:return r.status,dict(r.headers),r.read()
    def get_json(self,path):
        _,_,raw=self.request(path);return json.loads(raw)
    def post_json(self,path,payload,*,token=None,trusted=None):
        code,headers,raw=self.request(path,payload,token=self.token if token is None else token,trusted=trusted);return code,headers,json.loads(raw)
    def document(self,degree=0):
        d=deepcopy(self.get_json('/api/timeline/bootstrap')['document']);d['name']=f'Runtime degree {degree}';d['end_beat']='2/1';d['notes']=[note(degree)];d['clips']=[];d['next_id']=1;return d
    def render(self,degree=0):
        d=self.document(degree);code,_,job=self.post_json('/api/timeline/render',{'document':d,'region':{'start_beat':'0/1','end_beat':'1/1'},'name':f'Runtime {degree}'})
        self.assertEqual(code,202);self.assertEqual(self.server.scheduler.wait(job['job_id'],30).state,'completed');return d,job,self.server.timeline.artifact(job['job_id'])

    def test_one_origin_exposes_every_workspace_and_one_public_session(self):
        self.assertIs(self.server.timeline.scheduler,self.server.scheduler);self.assertIs(self.server.inspector.scheduler,self.server.scheduler);self.assertIs(self.server.listening.timeline,self.server.timeline)
        self.assertFalse(self.server.timeline.owns_scheduler);self.assertFalse(self.server.inspector.owns_scheduler);self.assertFalse(hasattr(self.server.vocal,'timeline'))
        self.assertNotEqual(self.server.token,self.server.trusted_token);self.assertNotIn('trusted_token',self.boot);self.assertEqual(self.boot['capabilities']['listening_trusted'],'separate-server-held-capability')
        for path,needle in (('/timeline',b'Phrase timeline'),('/listen',b'Listening'),('/inspector',b'Harmonic-comb'),('/vocal',b'Vocal'),('/',b'zaaggenz-workspaces')):
            code,headers,body=self.request(path);self.assertEqual(code,200);self.assertIn(needle,body);self.assertIn('Content-Security-Policy',headers)
        for path in ('/api/timeline/bootstrap','/api/listening/bootstrap','/api/inspector/bootstrap','/api/vocal/bootstrap'):
            self.assertEqual(self.get_json(path)['token'],self.token)
        with self.assertRaises(HTTPError) as cm:self.request('/api/runtime/bootstrap',headers={'Origin':'https://foreign.invalid'})
        self.assertEqual(cm.exception.code,403)

    def test_exact_compose_artifact_flows_to_listening_and_inspector(self):
        document,job,artifact=self.render(0)
        _,_,stimulus=self.post_json('/api/listening/freeze',{'job_id':job['job_id'],'name':'Exact A','start_frame':0,'end_frame':None})
        self.assertEqual(stimulus['revision_id'],artifact.revision_id);self.assertEqual(stimulus['recipe_sha256'],artifact.recipe_sha256);self.assertEqual(stimulus['cache_key'],artifact.cache_key)
        self.assertEqual(stimulus['source_asset']['content_sha256'],artifact.asset['content_sha256'])
        _,_,bound=self.post_json('/api/inspector/bind',{'job_id':job['job_id']})
        self.assertEqual(bound['source_binding']['revision_id'],artifact.revision_id);self.assertEqual(bound['source_binding']['recipe_sha256'],artifact.recipe_sha256);self.assertEqual(bound['source_binding']['cache_key'],artifact.cache_key);self.assertEqual(bound['source_binding']['content_sha256'],artifact.asset['content_sha256'])
        vocal=self.get_json('/api/vocal/bootstrap');self.assertEqual(vocal['source_session']['timeline_revision_id'],artifact.revision_id);self.assertIn('proposal-only',vocal['application_policy'])
        self.assertEqual(job['session']['timeline_revision_id'],TimelineDocument(document).revision_id)

    def test_compose_edit_while_analysis_outstanding_fails_closed(self):
        document,job,artifact=self.render(0);self.post_json('/api/inspector/bind',{'job_id':job['job_id']})
        release=threading.Event();started=threading.Event();original=inspector_service_module.build_analysis
        def delayed(*args,**kwargs):
            started.set()
            while not release.wait(.01):
                checkpoint=kwargs.get('checkpoint')
                if checkpoint:checkpoint()
            return original(*args,**kwargs)
        with patch.object(inspector_service_module,'build_analysis',delayed):
            _,_,analysis=self.post_json('/api/inspector/analyse',{'controls':{'amount':.4}});self.assertTrue(started.wait(5))
            edited=deepcopy(document);edited['name']='Edited while analysis outstanding';edited['notes'][0]['degree']=4
            _,_,validated=self.post_json('/api/timeline/validate',{'document':edited});self.assertNotEqual(validated['revision_id'],artifact.revision_id)
            state=self.server.inspector.state();self.assertTrue(state['source_stale']);self.assertEqual(state['authoritative_revision_id'],validated['revision_id'])
            release.set();self.assertEqual(self.server.scheduler.wait(analysis['job_id'],30).state,'completed');status=self.server.inspector.status(analysis['job_id'])
        self.assertTrue(status['stale']);self.assertFalse(status['published']);self.assertIsNone(self.server.inspector.state()['snapshot'])
        with self.assertRaisesRegex(Exception,'stale|unknown'):self.server.inspector.apply('0'*64)
        reopened=self.get_json('/api/timeline/bootstrap');self.assertEqual(TimelineDocument(reopened['document']).revision_id,validated['revision_id'])

    def test_shared_scheduler_job_ownership_prevents_cross_workspace_cancel_or_read(self):
        _,render_job,_=self.render(0);self.post_json('/api/inspector/bind',{'job_id':render_job['job_id']})
        release=threading.Event();started=threading.Event();original=inspector_service_module.build_analysis
        def delayed(*args,**kwargs):
            started.set()
            while not release.wait(.01):
                checkpoint=kwargs.get('checkpoint')
                if checkpoint:checkpoint()
            return original(*args,**kwargs)
        with patch.object(inspector_service_module,'build_analysis',delayed):
            _,_,analysis=self.post_json('/api/inspector/analyse',{'controls':{'amount':.2}});self.assertTrue(started.wait(5))
            with self.assertRaises(JobError):self.server.timeline.cancel(analysis['job_id'])
            with self.assertRaises(JobError):self.server.inspector.cancel(render_job['job_id'])
            with self.assertRaises(HTTPError) as cm:self.post_json('/api/timeline/cancel',{'job_id':analysis['job_id']})
            self.assertEqual(cm.exception.code,400)
            with self.assertRaises(HTTPError) as cm:self.post_json('/api/inspector/cancel',{'job_id':render_job['job_id']})
            self.assertEqual(cm.exception.code,400)
            _,_,cancelled=self.post_json('/api/inspector/cancel',{'job_id':analysis['job_id']});self.assertTrue(cancelled['cancelled']);release.set();self.server.scheduler.wait(analysis['job_id'],30)

    def test_participant_capability_stays_blind_inside_unified_runtime(self):
        rows=[]
        for degree,name in ((0,'A'),(4,'B')):
            _,job,_=self.render(degree);_,_,stimulus=self.post_json('/api/listening/freeze',{'job_id':job['job_id'],'name':name,'start_frame':0,'end_frame':None});rows.append(stimulus['id'])
        _,_,matched=self.post_json('/api/listening/match',{'stimulus_ids':rows,'target_rms_dbfs':None,'peak_ceiling_dbfs':-3.});matched=matched['matched_stimuli']
        _,_,created=self.post_json('/api/listening/trial',{'title':'Runtime blind ABX','design':'abx','matched_stimuli':matched,'seed':'17','endpoints':['liking'],'instruction_template':'neutral-abx'});trial=created['trial']
        self.assertIsNone(trial['abx_truth']);self.assertNotIn('seed',trial);trusted_id=self.server.listening._participant_to_trusted[trial['id']];self.assertNotEqual(trial['id'],trusted_id);self.assertNotIn(trusted_id,json.dumps(trial,sort_keys=True))
        _,_,safe=self.post_json('/api/listening/export',{'trial_id':trial['id']});self.assertIsNone(safe['trial']['abx_truth']);self.assertNotIn('seed',safe['trial']);self.assertNotIn(trusted_id,json.dumps(safe,sort_keys=True))
        with self.assertRaises(HTTPError) as cm:self.post_json('/api/listening/trusted-export',{'trial_id':trial['id']})
        self.assertEqual(cm.exception.code,403)
        code,_,raw=self.request('/api/listening/trusted-export',{'trial_id':trial['id']},trusted=self.server.trusted_token);self.assertEqual(code,200);trusted=json.loads(raw);self.assertEqual(trusted['manifest']['id'],trusted_id);self.assertIn(trusted['manifest']['abx_truth'],('A','B'))

    def test_session_serialization_reopens_with_identical_project_and_timeline_identity(self):
        document=self.document(7);_,_,validated=self.post_json('/api/timeline/validate',{'document':document});before=self.server.session.snapshot()
        serialized=json.dumps(self.server.session.document().to_dict(),sort_keys=True);reopened=RuntimeSession(TimelineDocument.from_json(serialized));after=reopened.snapshot()
        self.assertEqual(before['timeline_revision_id'],validated['revision_id']);self.assertEqual(after['timeline_revision_id'],before['timeline_revision_id']);self.assertEqual(after['project_revision_id'],before['project_revision_id']);self.assertEqual(after['project_sha256'],before['project_sha256'])

    def test_runtime_is_the_only_shared_scheduler_shutdown_owner(self):
        server=ZaaggenzServer(0,12000)
        with patch.object(server.scheduler,'shutdown',wraps=server.scheduler.shutdown) as shutdown:
            server.server_close();server.server_close();self.assertEqual(shutdown.call_count,1)

if __name__=='__main__':unittest.main(verbosity=2)
