from __future__ import annotations
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
import hashlib
import io
import json
from pathlib import Path
import sys
import threading
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import numpy as np
from scipy.io import wavfile
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'app'))
from zaaggenz_contracts import Contract
from zaaggenz_contracts.music import beat_to_sample
from zaaggenz_jobs import JobError
from zaaggenz_jobs.model import JobContext, CancellationToken
from zaaggenz_project import Project
from zaaggenz_melody import render_phrase
from zaaggenz_timeline.model import *
from zaaggenz_timeline.service import TimelineService, region_executor
from zaaggenz_timeline.server import TimelineServer


def note(identifier='n-0', **kwargs):
    return {'id': identifier, 'beat': '0/1', 'duration_beats': '1/2', 'degree': 0,
            'detune_cents': 0., 'gain_db': -18., 'muted': False, 'roll_density': 0, **kwargs}


def fixture(sr=12000):
    d = default_document(sr).to_dict()
    d.update(end_beat='4/1', next_id=3, notes=[note(), note('n-1', beat='1/1', degree=4, roll_density=8),
                                           note('n-2', beat='3/1', degree=None)])
    return d


class TimelineModelTests(unittest.TestCase):
    def test_immutable_save_roundtrip_and_full_legacy_layers(self):
        d = fixture(); before = deepcopy(d['project'])
        doc = TimelineDocument(d)
        d['notes'][0]['degree'] = 7
        recovered = TimelineDocument.from_json(json.dumps(doc.to_dict()))
        self.assertEqual(doc.revision_id, recovered.revision_id)
        self.assertEqual(recovered.to_dict()['project'], before)
        base = Project.from_document(before).head_recipe.to_dict()
        for key in ('arrangement', 'reversebass', 'sculpt'):
            self.assertIsNotNone(base[key])
        self.assertEqual(recovered.to_dict()['notes'][0]['degree'], 0)

    def test_recipe_compilation_never_mutates_protected_source(self):
        doc = TimelineDocument(fixture())
        base = Project.from_document(doc.to_dict()['project']).head_recipe.to_dict()
        compiled = compile_recipe(doc).to_dict()
        self.assertEqual(compiled['source'], base['source'])
        self.assertEqual(compiled['phase_policy'], 'source-derived')
        self.assertEqual(compiled['render_mode'], 'synth')
        self.assertIsNone(compiled['reversebass'])
        self.assertEqual(doc.to_dict()['layer_ownership'], OWNERSHIP)

    def test_every_authoring_change_affects_revision_identity(self):
        base = fixture(); identity = TimelineDocument(base).revision_id
        for change in (lambda d: d['notes'][0].update(muted=True), lambda d: d.update(name='Renamed'),
                       lambda d: d.update(master_gain_db=-3.), lambda d: d['notes'][0].update(beat='1/4')):
            d = deepcopy(base); change(d)
            self.assertNotEqual(TimelineDocument(d).revision_id, identity)

    def test_validation_rejects_extra_fields_bad_versions_and_ownership(self):
        for patch in ({'extra': 1}, {'version': '2.0.0'}, {'layer_ownership': {}}, {'next_id': True}, {'master_gain_db': float('nan')}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                TimelineDocument({**fixture(), **patch})

    def test_note_boundary_invalid_rational_and_duplicates(self):
        for patch in ({'beat': '-1/1'}, {'duration_beats': '0/1'}, {'duration_beats': '2/4'},
                      {'beat': '4/1'}, {'degree': True}, {'gain_db': float('inf')}, {'id': '../bad'},
                      {'muted': 1}, {'roll_density': 17}, {'id': 'a'*60}):
            d=fixture();d['notes'][0].update(patch)
            with self.subTest(patch=patch), self.assertRaises(ValueError): TimelineDocument(d)
        d=fixture();d['notes'].append(d['notes'][0])
        with self.assertRaisesRegex(ValueError, 'duplicate'): TimelineDocument(d)

    def test_object_and_roll_retrigger_limits_fail_before_allocation(self):
        d=fixture();d['notes']=[note(f'n-{i}') for i in range(257)]
        with self.assertRaises(ValueError): TimelineDocument(d)
        d=fixture();d['end_beat']='16/1';d['notes']=[note(duration_beats='16/1',roll_density=16)]
        with self.assertRaisesRegex(ValueError, '64 retriggers'): TimelineDocument(d)

    def test_max_id_roll_is_valid_contract(self):
        d=fixture();d['notes']=[note('a'*59,roll_density=4)]
        self.assertIsInstance(compile_recipe(TimelineDocument(d)), Contract)

    def test_muted_and_rest_do_not_generate_pitch_or_rolls(self):
        d=fixture();d['notes'][0].update(muted=True,roll_density=8)
        recipe=compile_recipe(TimelineDocument(d))
        events=recipe.to_dict()['phrase']['events']
        self.assertIsNone(events[0]['pitch']);self.assertIsNone(events[-1]['pitch'])
        self.assertEqual(len(recipe.to_dict()['phrase']['gestures']),1)

    def test_empty_phrase_renders_silence_with_explicit_extent(self):
        d=fixture();d['notes']=[]
        result=render_phrase(compile_recipe(TimelineDocument(d)))
        self.assertEqual(len(result.mix),14400)
        self.assertEqual(np.max(np.abs(result.mix)),0)

    def test_render_pitch_range_and_timing_are_not_silently_clamped(self):
        d=fixture();d['notes'][0]['degree']=70
        with self.assertRaisesRegex(ValueError,'target outside'): compile_recipe(TimelineDocument(d))

    def test_clip_bounds_duplicates_and_serialization(self):
        d=fixture();d['clips']=[{'id':'c-0','name':'Opening','start_beat':'0/1','end_beat':'1/1'}]
        self.assertEqual(TimelineDocument(d).to_dict()['clips'],d['clips'])
        for key,val in [('end_beat','5/1'),('start_beat','2/1')]:
            bad=deepcopy(d);bad['clips'][0][key]=val
            with self.assertRaises(ValueError):TimelineDocument(bad)
        d['clips'].append(d['clips'][0])
        with self.assertRaises(ValueError):TimelineDocument(d)

    def test_memory_admission_uses_whole_phrase(self):
        d=fixture(48000);d['end_beat']='256/1'
        with self.assertRaisesRegex(ValueError,'60-second'): memory_estimate(compile_recipe(TimelineDocument(d)))

    def test_reopened_recipe_audio_is_bit_identical_and_rolls_present(self):
        doc=TimelineDocument(fixture())
        a=render_phrase(compile_recipe(doc));b=render_phrase(compile_recipe(TimelineDocument.from_json(doc._json)))
        np.testing.assert_array_equal(a.mix,b.mix)
        self.assertEqual(a.diagnostics['roll_retriggers'],3)
        self.assertGreater(np.max(np.abs(a.stems['synthline'])),0)
        self.assertGreater(np.max(np.abs(a.stems['exciter'])),0)

    def test_no_layer_ownership_drop_in_save_when_notes_change(self):
        d=fixture();before=deepcopy(d['project']);d['notes'][0].update(degree=7)
        doc=TimelineDocument(d);compile_recipe(doc)
        self.assertEqual(doc.to_dict()['project'],before)


class ServiceTests(unittest.TestCase):
    def setUp(self): self.service=TimelineService()
    def tearDown(self): self.service.close()

    def test_real_async_full_and_region_are_sample_exact(self):
        data=fixture();full=self.service.submit(data,name='full')
        selected=self.service.submit(data,{'start_beat':'1/4','end_beat':'3/2'},'selection')
        for item in (full,selected):self.assertEqual(self.service.scheduler.wait(item['job_id'],10).state,'completed')
        a=self.service.scheduler.result(full['job_id']);b=self.service.scheduler.result(selected['job_id'])
        tm=compile_recipe(TimelineDocument(data)).to_dict()['time_map']
        lo=beat_to_sample(tm,'1/4');hi=beat_to_sample(tm,'3/2')
        self.assertEqual(b.audio_bytes,a.audio_bytes[lo*4:hi*4])
        self.assertEqual(b.scopes['offset_sample'],lo)
        self.assertLess(b.scopes['events'][0]['onset_sample'],0)
        self.assertEqual(b.revision_id,TimelineDocument(data).revision_id)
        self.assertNotEqual(a.cache_key,b.cache_key)

    def test_wave_bytes_match_declared_pcm_and_revision(self):
        submitted=self.service.submit(fixture())
        self.service.scheduler.wait(submitted['job_id'],10)
        wave,revision=self.service.wave(submitted['job_id'])
        sr,x=wavfile.read(io.BytesIO(wave));artifact=self.service.scheduler.result(submitted['job_id'])
        self.assertEqual(sr,12000);self.assertEqual(revision,submitted['revision_id'])
        self.assertEqual(hashlib.sha256(x.astype('<f4').tobytes()).hexdigest(),artifact.asset['content_sha256'])

    def test_unknown_audio_cancel_and_job_fail_clearly(self):
        with self.assertRaises(JobError):self.service.wave('0'*32)
        with self.assertRaises(JobError):self.service.status('0'*32)

    def test_invalid_region_name_and_time_limit_rejected_before_enqueue(self):
        for region in ({'start_beat':'-1/1','end_beat':'1/1'},{'start_beat':'1/1','end_beat':'1/1'}, {'start_beat':'0/1','end_beat':'5/1'}):
            with self.assertRaises(ValueError): self.service.submit(fixture(),region)
        with self.assertRaises(ValueError):self.service.submit(fixture(),name='')
        data=fixture();data['end_beat']='256/1'
        with self.assertRaises(ValueError):self.service.submit(data,{'start_beat':'0/1','end_beat':'1/1'})

    def test_cancelled_executor_does_not_publish_artifact(self):
        data=fixture();doc=TimelineDocument(data);token=CancellationToken();token.cancel()
        executor=region_executor(compile_recipe(doc),doc.revision_id,{'start_beat':'0/1','end_beat':'1/1'})
        with self.assertRaises(JobError):executor(JobContext('test',token,lambda x:None))


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=TimelineServer(0,12000);cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.url=f'http://127.0.0.1:{cls.server.server_port}'
    @classmethod
    def tearDownClass(cls):cls.server.shutdown();cls.server.server_close();cls.thread.join(2)

    def request(self,path,data=None,headers=None):
        h={'Content-Type':'application/json','X-Zaaggenz-Token':self.server.token,**(headers or {})}
        with urlopen(Request(self.url+path,data=None if data is None else json.dumps(data).encode(),headers=h),timeout=10) as response:
            return response.status,response.read()

    def test_bootstrap_and_actual_editor_and_legacy_pages(self):
        _,raw=self.request('/api/timeline/bootstrap');boot=json.loads(raw)
        self.assertEqual(boot['token'],self.server.token)
        for path,needle in [('/timeline',b'Notes, rolls'),('/',b'Open note / clip timeline'),('/timeline/app.mjs',b'RenderTransport')]:
            _,body=self.request(path);self.assertIn(needle,body)

    def test_cross_origin_and_dns_rebinding_hosts_rejected(self):
        for headers in ({'Origin':'https://foreign.invalid'},{'Host':'foreign.invalid'}):
            with self.assertRaises(HTTPError) as error:self.request('/api/timeline/bootstrap',headers=headers)
            self.assertEqual(error.exception.code,403)

    def test_mutation_requires_session_token(self):
        with self.assertRaises(HTTPError) as error:self.request('/api/timeline/validate',{'document':fixture()},headers={'X-Zaaggenz-Token':'bad'})
        self.assertEqual(error.exception.code,403)

    def test_bad_routes_and_payloads_do_not_expose_paths(self):
        for path in ('/timeline/../../etc/passwd','/api/timeline/unknown'):
            with self.assertRaises(HTTPError):self.request(path)
        with self.assertRaises(HTTPError):self.request('/api/timeline/render',{'path':'/tmp/whatever'})

    def test_validate_and_submit_returns_immutable_job_identity(self):
        _,body=self.request('/api/timeline/validate',{'document':fixture()});v=json.loads(body)
        code,body=self.request('/api/timeline/render',{'document':fixture(),'region':None,'name':'HTTP render'})
        self.assertEqual(code,202);job=json.loads(body)
        self.assertEqual(job['revision_id'],v['revision_id'])
        self.server.timeline.scheduler.wait(job['job_id'],10)
        _,body=self.request('/api/timeline/jobs/'+job['job_id']);self.assertEqual(json.loads(body)['state'],'completed')
        _,wave=self.request('/api/timeline/jobs/'+job['job_id']+'/audio');self.assertTrue(wave.startswith(b'RIFF'))


if __name__=='__main__': unittest.main(verbosity=2)
