from __future__ import annotations
import json,threading,unittest
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'app'))
from zaaggenz_listening import *
from zaaggenz_listening.service import ListeningService
from zaaggenz_listening.server import ListeningServer
from zaaggenz_timeline import TimelineDocument,default_document
from zaaggenz_timeline.service import TimelineService

def timeline(degree=0,gain=-18,sr=12000):
    d=default_document(sr).to_dict();d['name']=f'Test degree {degree}';d['end_beat']='2/1';d['notes']=[{'id':'n-0','beat':'0/1','duration_beats':'1/1','degree':degree,'detune_cents':0.,'gain_db':gain,'muted':False,'roll_density':0}];d['clips']=[];d['next_id']=1
    return TimelineDocument(d).to_dict()
def render(service,doc):
    j=service.submit(doc,name='fixture');state=service.scheduler.wait(j['job_id'],10);assert state.state=='completed',state;return j['job_id']

class StimulusTests(unittest.TestCase):
    def setUp(self):self.timeline=TimelineService();self.service=ListeningService(self.timeline)
    def tearDown(self):self.timeline.close()
    def test_freeze_is_exact_and_project_edits_do_not_regenerate_or_change_identity(self):
        job=render(self.timeline,timeline(0));a=self.service.freeze_job(job,'A');pcm_before=self.service.audio._raw[a['id']]
        render(self.timeline,timeline(4));self.assertEqual(self.service.audio.stimulus(a['id']).to_dict(),a);self.assertEqual(self.service.audio._raw[a['id']],pcm_before)
        with self.assertRaises(ListeningError):ListeningService(self.timeline).audio.stimulus(a['id'])
    def test_level_match_has_common_rms_headroom_and_stable_audio_hash(self):
        ids=[]
        for degree,gain,name in ((0,-18,'A'),(4,-12,'B')):ids.append(self.service.freeze_job(render(self.timeline,timeline(degree,gain)),name)['id'])
        rows=self.service.match(ids,peak_ceiling_dbfs=-3.);self.assertEqual(len(rows),2);self.assertAlmostEqual(rows[0]['matched_rms_dbfs'],rows[1]['matched_rms_dbfs'],places=5)
        self.assertTrue(all(r['sample_peak_headroom_db']>=2.999 for r in rows));self.assertTrue(all(not r['true_peak_measured'] for r in rows))
        for r in rows:self.assertEqual(r['playback_sha256'],__import__('hashlib').sha256(self.service.audio.playback_pcm(r['playback_sha256'])).hexdigest())
    def test_silence_is_rejected_instead_of_boosted(self):
        d=timeline();d['notes']=[];s=self.service.freeze_job(render(self.timeline,d),'silence');a=self.service.freeze_job(render(self.timeline,timeline(0)),'tone')
        with self.assertRaises(ListeningError):self.service.match([s['id'],a['id']])
    def test_excerpt_identity_and_alignment_are_explicit(self):
        job=render(self.timeline,timeline(0));artifact=self.timeline.scheduler.result(job);n=artifact.asset['frame_count'];s=self.service.freeze_job(job,'excerpt',100,n-100)
        self.assertEqual(s['excerpt'],{'start_frame':100,'end_frame':n-100});self.assertEqual(s['alignment']['excerpt_start_frame'],100)

class TrialTests(unittest.TestCase):
    def setUp(self):
        self.timeline=TimelineService();self.service=ListeningService(self.timeline);ids=[]
        for degree,name in ((0,'A'),(4,'B'),(7,'C')):ids.append(self.service.freeze_job(render(self.timeline,timeline(degree)),name)['id'])
        self.match2=self.service.match(ids[:2]);self.match3=self.service.match(ids)
    def tearDown(self):self.timeline.close()
    def test_randomisation_is_deterministic_and_seed_sensitive(self):
        a=make_trial('A/B','ab',self.match2,seed='42');b=make_trial('A/B','ab',self.match2,seed='42');self.assertEqual(a.to_dict(),b.to_dict())
        orders={tuple(make_trial('A/B','ab',self.match2,seed=str(s)).to_dict()['presentation_order']) for s in range(10)};self.assertGreater(len(orders),1)
    def test_abx_accuracy_is_separate_from_ratings_confidence_effort(self):
        t=make_trial('ABX','abx',self.match2,seed='7',endpoints=('liking','groove'));truth=t.to_dict()['abx_truth'];r=make_result(t,choice=truth,ratings={'liking':63,'groove':44},confidence=72,effort=31,comfortable_level=55,x_replay_count=2)
        d=r.to_dict();self.assertTrue(d['abx_correct']);self.assertNotIn('abx_correct',d['ratings']);self.assertEqual(d['ratings']['liking'],63);self.assertEqual(d['confidence'],72);self.assertEqual(d['effort'],31);self.assertEqual(d['x_replay_count'],2)
    def test_ab_and_multi_keep_accuracy_null_and_task_endpoints_explicit(self):
        a=make_trial('AB','ab',self.match2,endpoints=('sound_quality','liking'));r=make_result(a,choice=a.to_dict()['presentation_order'][0],ratings={'sound_quality':80,'liking':50});self.assertIsNone(r.to_dict()['abx_correct'])
        m=make_trial('multi','multi',self.match3,endpoints=('groove',));self.assertEqual(len(m.to_dict()['presentation_order']),3)
        with self.assertRaises(ListeningError):make_result(m,ratings={'excitement':80})
    def test_time_annotations_replays_missing_and_aborted_are_preserved(self):
        t=make_trial('AB','ab',self.match2);sid=t.to_dict()['presentation_order'][0];counts={x:0 for x in t.to_dict()['presentation_order']};counts[sid]=3
        r=make_result(t,status='aborted',replay_counts=counts,annotations=[{'stimulus_id':sid,'time_seconds':.42,'label':'attack','note':'too sharp'}],effort=85,note='stopped')
        self.assertEqual(r.to_dict()['status'],'aborted');self.assertEqual(r.to_dict()['replay_counts'][sid],3);self.assertIsNone(r.to_dict()['abx_correct']);self.assertEqual(make_result(t,status='missing').to_dict()['status'],'missing')
    def test_bundle_reopen_never_regenerates_missing_audio(self):
        public=self.service.create_trial('AB','ab',self.match2,'5',['liking'],None);tid=public['id'];self.service.submit(tid,{'status':'completed','choice':public['presentation_order'][0],'ratings':{'liking':55},'confidence':60,'effort':20,'comfortable_level':50,'replay_counts':{x:1 for x in public['presentation_order']},'x_replay_count':0,'annotations':[],'note':''})
        bundle=self.service.export_bundle(tid);self.assertEqual(self.service.reopen_bundle(bundle)['results'][0]['ratings']['liking'],55)
        with self.assertRaisesRegex(ListeningError,'regeneration is forbidden'):ListeningService(self.timeline).reopen_bundle(bundle)
    def test_manifest_roundtrip_detects_tampering(self):
        t=make_trial('AB','ab',self.match2,seed='9');self.assertEqual(TrialManifest.from_json(t._json).sha256,t.sha256);d=t.to_dict();d['seed']='10'
        with self.assertRaisesRegex(ListeningError,'trial id'):TrialManifest(d)

class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=ListeningServer(0,12000);cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start();cls.url=f'http://127.0.0.1:{cls.server.server_port}'
    @classmethod
    def tearDownClass(cls):cls.server.shutdown();cls.server.server_close();cls.thread.join(2)
    def request(self,path,data=None,token=True,headers=None):
        h={'Content-Type':'application/json',**(headers or {})};
        if token:h['X-Zaaggenz-Token']=self.server.token
        body=None if data is None else json.dumps(data).encode()
        with urlopen(Request(self.url+path,data=body,headers=h),timeout=20) as r:return r.status,r.headers,r.read()
    def test_bootstrap_listen_and_compose_pages_coexist(self):
        _,_,raw=self.request('/api/listening/bootstrap');b=json.loads(raw);self.assertTrue(b['compose_independent']);self.assertIn('neutral-abx',b['templates'])
        for path,needle in [('/listen',b'Listening'),('/timeline',b'Phrase timeline')]:_,_,body=self.request(path);self.assertIn(needle,body)
    def test_end_to_end_freeze_match_trial_audio_submit_export(self):
        jobs=[]
        for d in (timeline(0),timeline(4)):
            j=self.server.timeline.submit(d,name='listen');self.assertEqual(self.server.timeline.scheduler.wait(j['job_id'],10).state,'completed');jobs.append(j['job_id'])
        stimuli=[]
        for i,j in enumerate(jobs):_,_,raw=self.request('/api/listening/freeze',{'job_id':j,'name':chr(65+i),'start_frame':0,'end_frame':None});stimuli.append(json.loads(raw)['id'])
        _,_,raw=self.request('/api/listening/match',{'stimulus_ids':stimuli,'target_rms_dbfs':None,'peak_ceiling_dbfs':-3.});matched=json.loads(raw)['matched_stimuli']
        _,_,raw=self.request('/api/listening/trial',{'title':'HTTP ABX','design':'abx','matched_stimuli':matched,'seed':'77','endpoints':['liking','groove'],'instruction_template':'neutral-abx'});trial=json.loads(raw)['trial'];self.assertIsNone(trial['abx_truth'])
        psha=matched[0]['playback_sha256'];_,headers,wave=self.request(f'/api/listening/audio/{psha}.wav');self.assertEqual(headers['X-Playback-SHA256'],psha);self.assertTrue(wave.startswith(b'RIFF'))
        counts={x:1 for x in trial['presentation_order']};result={'status':'completed','choice':'A','ratings':{'liking':50,'groove':60},'confidence':70,'effort':30,'comfortable_level':50,'replay_counts':counts,'x_replay_count':2,'annotations':[],'note':''}
        _,_,raw=self.request('/api/listening/submit',{'trial_id':trial['id'],'result':result});self.assertIn('result_sha256',json.loads(raw))
        _,_,raw=self.request('/api/listening/export',{'trial_id':trial['id']});bundle=json.loads(raw);self.assertEqual(bundle['manifest']['id'],trial['id']);self.assertEqual(len(bundle['stimuli']),2);self.assertIn('alignment',bundle['stimuli'][0])
    def test_foreign_origin_and_bad_token_rejected(self):
        with self.assertRaises(HTTPError) as cm:self.request('/api/listening/bootstrap',headers={'Origin':'https://foreign.invalid'});self.assertEqual(cm.exception.code,403)
        with self.assertRaises(HTTPError) as cm:self.request('/api/listening/export',{'trial_id':'0'*64},token=False);self.assertEqual(cm.exception.code,403)

if __name__=='__main__':unittest.main(verbosity=2)
