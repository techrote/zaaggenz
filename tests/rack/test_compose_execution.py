"""Real Compose/service/API audio, immutable revisions and adversarial publication."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import numpy as np
from scipy.io import wavfile

from zaaggenz_contracts import Contract
from zaaggenz_contracts.rack import RackRecipe, empty_rack
from zaaggenz_contracts.music import beat_to_sample
from zaaggenz_dsp.graph import apply_output_policy
from zaaggenz_jobs import JobScheduler, SchedulerLimits, JobError, RenderArtifact
from zaaggenz_melody import render_phrase
from zaaggenz_melody.render import melodic_cache_key
from zaaggenz_project import Project
from zaaggenz_runtime import RuntimeSession, ZaaggenzServer
from zaaggenz_spectral.band_selective import process_band_selective
from zaaggenz_spectral.rack_adapter import execution_request
from zaaggenz_spectral.rack_executor import execute_rack
from zaaggenz_timeline.model import TimelineDocument, default_document, compile_recipe, memory_estimate
from zaaggenz_timeline.service import TimelineService, region_executor
from zaaggenz_web_release import RELEASE_HEADER
from helpers import rack, insert, external
from test_executor import retune880


def document(sr=12000, *, with_rack=True, spectral=None):
    data = default_document(sr).to_dict()
    data.update(end_beat='2/1', next_id=2, notes=[
        {'id':'n0','beat':'0/1','duration_beats':'1/1','degree':0,
         'detune_cents':0.,'gain_db':-6.,'muted':False,'roll_density':4},
        {'id':'n1','beat':'1/1','duration_beats':'1/1','degree':7,
         'detune_cents':0.,'gain_db':-8.,'muted':False,'roll_density':0}])
    if with_rack:
        project = Project.from_document(data['project'])
        project.set_rack(rack(project.head_recipe, spectral=spectral))
        data['project'] = project.to_document()
    return data


def edit_rack(data, mutate):
    data = deepcopy(data); project = Project.from_document(data['project'])
    saved = project.head_recipe.to_dict()['rack']; mutate(saved)
    project.set_rack(RackRecipe(saved)); data['project'] = project.to_document()
    return data


def completed(service, request):
    state = service.scheduler.wait(request['job_id'], 30)
    if state.state != 'completed':raise AssertionError(state)
    return service.artifact(request['job_id'])


class ComposeExecutionTests(unittest.TestCase):
    def test_real_synthline_route_matches_legacy_oracle_and_master_runs_once(self):
        for sr in (12000,48000):
            data = document(sr); project_before = deepcopy(data['project'])
            compiled = compile_recipe(TimelineDocument(data)); captured = []
            def record(source, rate, saved, **kwargs):
                result = execute_rack(source, rate, saved, **kwargs)
                captured.append((source.copy(), result[0].copy()))
                return result
            with patch('zaaggenz_spectral.rack_executor.execute_rack', side_effect=record), \
                 patch('zaaggenz_dsp.graph.apply_output_policy', wraps=apply_output_policy) as master:
                actual = render_phrase(compiled)
            self.assertEqual(master.call_count,1)
            self.assertEqual(len(captured),1)
            expected = process_band_selective(captured[0][0],sr,execution_request(compiled.to_dict()['rack'])).audio
            np.testing.assert_array_equal(captured[0][1],expected)
            np.testing.assert_array_equal(actual.stems['synthline'],expected.astype(np.float32))
            dry = render_phrase(compile_recipe(TimelineDocument(document(sr,with_rack=False))))
            np.testing.assert_array_equal(actual.stems['exciter'],dry.stems['exciter'])
            self.assertGreater(np.max(np.abs(actual.stems['exciter'])),0)
            self.assertFalse(np.array_equal(actual.mix,dry.mix))
            self.assertEqual(data['project'],project_before)
            # Full-mix BODY/AUX/SUB configuration remains in the retained project.
            base = Project.from_document(project_before).head_recipe.to_dict()
            for field in ('arrangement','reversebass','sculpt'):
                self.assertIsNotNone(base[field]);self.assertIsNone(compiled.to_dict()[field])
            self.assertEqual(actual.diagnostics['rack']['placement']['bus'],'SYNTHLINE')

    def test_accepted_production_source_is_unchanged_and_rack_is_post_source(self):
        from zaaggenz_zaag import PRODUCTION_PRESET_IDS
        from zaaggenz_timeline.model import apply_source_preset
        data = apply_source_preset(TimelineDocument(document(48000, with_rack=False)),
                                   PRODUCTION_PRESET_IDS[0]).to_dict()
        dry = render_phrase(compile_recipe(TimelineDocument(data)))
        project = Project.from_document(data['project']); original = project.head_recipe.to_dict()
        project.set_rack(rack(project.head_recipe)); data['project'] = project.to_document()
        captured = []
        def capture(audio, rate, saved, **kwargs):
            captured.append(audio.copy()); return execute_rack(audio, rate, saved, **kwargs)
        with patch('zaaggenz_spectral.rack_executor.execute_rack', side_effect=capture):
            wet = render_phrase(compile_recipe(TimelineDocument(data)))
        np.testing.assert_array_equal(captured[0].astype(np.float32), dry.stems['synthline'])
        expected = process_band_selective(captured[0], 48000,
                         execution_request(project.head_recipe.to_dict()['rack'])).audio
        np.testing.assert_array_equal(wet.stems['synthline'], expected.astype(np.float32))
        np.testing.assert_array_equal(wet.stems['exciter'], dry.stems['exciter'])
        self.assertEqual(project.head_recipe.to_dict()['source'], original['source'])
        self.assertEqual(wet.diagnostics['source_preset_id'], PRODUCTION_PRESET_IDS[0])
        self.assertFalse(np.array_equal(wet.mix, dry.mix))

    def test_longform_keeps_explicit_rejection_instead_of_resetting_rack_per_section(self):
        from zaaggenz_longform.fixtures import small_test_example
        from zaaggenz_longform import render_longform, LongformDocument
        from zaaggenz_longform.model import LongformError
        data = small_test_example(12000).to_dict()
        project = Project.from_document(data['base_project'])
        project.set_rack(rack(project.head_recipe)); data['base_project'] = project.to_document()
        with patch('zaaggenz_longform.render.render_phrase', side_effect=AssertionError('must reject before synthesis')):
            with self.assertRaisesRegex(LongformError, 'whole-context Compose'):
                render_longform(LongformDocument(data))

    def test_source_owned_sculpt_and_graph_execute_after_rack_before_master(self):
        from zaaggenz_contracts.legacy import freeze_legacy
        from uptempo_harmony.multiband import SCULPT_PRESETS, SpectralSculptParams, process_spectral_sculpt
        from zaaggenz_dsp.legacy import graphify_legacy_recipe
        from zaaggenz_dsp.graph import execute_graph
        for graph in (False,True):
            origin=freeze_legacy({'sr':12000},sculpt=SCULPT_PRESETS['gentle_separation'].to_dict())
            if graph:origin=graphify_legacy_recipe(origin)
            project=Project(origin);project.set_rack(rack(origin))
            data=document();data['project']=project.to_document();data['master_gain_db']=-7.
            recipe=compile_recipe(TimelineDocument(data));d=recipe.to_dict();seen=[]
            from zaaggenz_melody.render import _apply_preserved_topology
            def capture(pre, config):
                seen.append(pre.copy());return _apply_preserved_topology(pre,config)
            with patch('zaaggenz_melody.render._apply_preserved_topology',side_effect=capture), \
                 patch('zaaggenz_dsp.graph.apply_output_policy',wraps=apply_output_policy) as master:
                actual=render_phrase(recipe)
            self.assertEqual(master.call_count,1)
            if graph:
                pre=execute_graph(seen[0],12000,d['nodes'],d['output_node'],d['source']['id'],False).output
            else:
                pre=process_spectral_sculpt(seen[0].astype(np.float32),12000,SpectralSculptParams(**d['sculpt']))
            expected=apply_output_policy(pre,d['output'])[0]
            np.testing.assert_array_equal(actual.mix,expected)
            self.assertEqual(d['sculpt'],origin.to_dict()['sculpt'])
            self.assertEqual(d['nodes'],origin.to_dict()['nodes'])

    def test_saved_reopen_rerender_and_service_export_are_same_real_audio(self):
        for sr in (12000,48000):
            data=document(sr,spectral=retune880())
            reopened=TimelineDocument.from_json(json.dumps(data))
            expected=render_phrase(compile_recipe(reopened)).mix
            service=TimelineService(debounce_seconds=0)
            try:
                request=service.submit(reopened.to_dict());artifact=completed(service,request)
                np.testing.assert_array_equal(np.frombuffer(artifact.audio_bytes,dtype='<f4'),expected)
                raw,revision=service.wave(request['job_id']);rate,wave=wavfile.read(io.BytesIO(raw))
                self.assertEqual(rate,sr);self.assertEqual(revision,reopened.revision_id)
                np.testing.assert_array_equal(wave,expected)
                self.assertEqual(hashlib.sha256(wave.astype('<f4').tobytes()).hexdigest(),artifact.asset['content_sha256'])
                self.assertEqual(artifact.scopes['diagnostics']['rack']['meter_context'],'complete-input-context')
            finally:service.close()

    def test_full_context_region_matches_crop_not_fresh_filter_state(self):
        for sr in (12000,48000):
            data=document(sr,spectral=retune880());service=TimelineService(debounce_seconds=0)
            try:
                full=service.submit(data)
                selection={'start_beat':'1/4','end_beat':'5/4'}
                selected=service.submit(data,selection)
                a=completed(service,full);b=completed(service,selected)
                recipe=compile_recipe(TimelineDocument(data));tm=recipe.to_dict()['time_map']
                lo=beat_to_sample(tm,selection['start_beat']);hi=beat_to_sample(tm,selection['end_beat'])
                self.assertEqual(b.audio_bytes,a.audio_bytes[lo*4:hi*4])
                self.assertEqual(full['estimated_memory_bytes'],selected['estimated_memory_bytes'])
                self.assertEqual(b.scopes['diagnostics']['render_policy'],'whole-phrase-then-crop')
                self.assertEqual(b.scopes['diagnostics']['rack']['resource_estimate']['frames'],a.scopes['diagnostics']['rack']['resource_estimate']['frames'])
                # Independent short-context filtering is demonstrably not the policy.
                dry=render_phrase(compile_recipe(TimelineDocument(document(sr,with_rack=False)))).stems['synthline']
                saved=recipe.to_dict()['rack']
                complete=execute_rack(dry,sr,saved)[0][lo:hi]
                restarted=execute_rack(dry[lo:hi],sr,saved)[0]
                self.assertGreater(float(np.max(np.abs(complete-restarted))),1e-6)
            finally:service.close()

    def test_cache_identity_includes_sonic_controls_but_not_rack_labels(self):
        data=document();recipe=compile_recipe(TimelineDocument(data));key=melodic_cache_key(recipe)
        mutations=[lambda r:r.update(bypass=True),lambda r:r.update(wet=.5),
                   lambda r:r['bands'][1].update(wet=.5),lambda r:r['bands'][1].update(confine_delta=True),
                   lambda r:insert(r).update(wet=.5),lambda r:insert(r)['params'].update(ratio=4.),
                   lambda r:r['bands'][1]['inserts'].reverse(),
                   lambda r:r['crossovers']['frequencies_hz'].__setitem__(1,600.)]
        for mutate in mutations:
            other=compile_recipe(TimelineDocument(edit_rack(data,mutate)))
            self.assertNotEqual(melodic_cache_key(other),key)
        renamed=compile_recipe(TimelineDocument(edit_rack(data,lambda r:r['display'].update({'rack':'Renamed'}))))
        self.assertNotEqual(renamed.sha256,recipe.sha256);self.assertEqual(melodic_cache_key(renamed),key)
        changed=deepcopy(data);changed['master_gain_db']=-3.
        self.assertNotEqual(melodic_cache_key(compile_recipe(TimelineDocument(changed))),key)
        self.assertNotEqual(melodic_cache_key(compile_recipe(TimelineDocument(document(48000)))),key)
        with patch('zaaggenz_spectral.rack_executor.implementation_identity',return_value='f'*64):
            self.assertNotEqual(melodic_cache_key(recipe),key)

    def test_unavailable_bypassed_rack_fails_before_source_and_scheduler_work(self):
        data=edit_rack(document(),lambda r:(r.update(bypass=True),r['bands'][1]['inserts'].append(external())))
        service=TimelineService(debounce_seconds=0)
        try:
            before=service.session.snapshot()
            with patch('zaaggenz_melody.render._production_preset_source') as source_renderer, \
                 patch.object(service.scheduler,'submit') as enqueue:
                with self.assertRaisesRegex(ValueError,'VST3'):service.submit(data)
                source_renderer.assert_not_called();enqueue.assert_not_called()
            self.assertEqual(service.session.snapshot(),before)
        finally:service.close()


class RevisionPublicationTests(unittest.TestCase):
    def setUp(self):self.service=TimelineService(debounce_seconds=0)
    def tearDown(self):self.service.close()

    def test_completed_exact_cache_hit_does_not_run_source_or_dsp_again(self):
        data=document();first=self.service.submit(data);a=completed(self.service,first)
        with patch('zaaggenz_melody.render.render_phrase',side_effect=AssertionError('cache hit reran DSP')):
            second=self.service.submit(data);b=completed(self.service,second)
        self.assertNotEqual(first['job_id'],second['job_id'])
        self.assertTrue(self.service.status(second['job_id'])['cache_hit'])
        self.assertEqual(a.metadata(),b.metadata());self.assertEqual(a.audio_bytes,b.audio_bytes)
        # A valid sonic edit cannot reuse the old artifact.
        changed=edit_rack(data,lambda r:insert(r)['params'].update(ratio=4.))
        third=self.service.submit(changed);c=completed(self.service,third)
        self.assertFalse(self.service.status(third['job_id'])['cache_hit'])
        self.assertNotEqual(c.recipe_sha256,a.recipe_sha256)
        self.assertNotEqual(c.audio_bytes,a.audio_bytes)

    def test_identical_pending_requests_adopt_only_the_same_owned_job(self):
        self.service._debounce_seconds=.3
        first=self.service.submit(document());second=self.service.submit(document(),name='Same sound')
        self.assertEqual(first['job_id'],second['job_id']);self.assertTrue(second['adopted'])
        completed(self.service,second)

    def test_rapid_edit_debounce_does_not_launch_obsolete_dsp(self):
        self.service._debounce_seconds=.5
        with patch('zaaggenz_melody.render.render_phrase',wraps=render_phrase) as render:
            jobs=[]
            for i in range(4):
                data=document();data['name']=f'Edit {i}';jobs.append(self.service.submit(data))
            completed(self.service,jobs[-1])
            self.assertEqual(render.call_count,1)
        for job in jobs[:-1]:
            self.assertEqual(self.service.scheduler.wait(job['job_id'],5).state,'cancelled')
            status=self.service.status(job['job_id']);self.assertFalse(status['accepted']);self.assertNotIn('artifact',status)

    def test_stale_completed_audio_and_meters_rejected_but_research_evidence_retained(self):
        data=document();old=self.service.submit(data);artifact=completed(self.service,old)
        changed=deepcopy(data);changed['master_gain_db']=-6.
        self.service.validate(changed)
        status=self.service.status(old['job_id'])
        self.assertEqual(status['state'],'stale');self.assertFalse(status['accepted']);self.assertNotIn('artifact',status)
        with self.assertRaisesRegex(JobError,'stale'):self.service.wave(old['job_id'])
        self.assertEqual(self.service.artifact(old['job_id']).audio_bytes,artifact.audio_bytes)

    def test_aba_edit_cannot_republish_old_job_but_fresh_identical_request_can_use_cache(self):
        data=document();old=self.service.submit(data);a=completed(self.service,old)
        changed=deepcopy(data);changed['name']='Intermediate'
        self.service.validate(changed);self.service.validate(data)
        self.assertEqual(self.service.session.current_revision_id(),old['revision_id'])
        self.assertEqual(self.service.status(old['job_id'])['state'],'stale')
        with self.assertRaisesRegex(JobError,'stale'):self.service.wave(old['job_id'])
        new=self.service.submit(data);b=completed(self.service,new)
        self.assertTrue(self.service.status(new['job_id'])['cache_hit'])
        self.assertEqual(a.audio_bytes,b.audio_bytes)
        self.assertEqual(self.service.scheduler.snapshot(new['job_id']).generation,new['session']['generation'])

    def test_cancel_after_dsp_before_publication_never_inserts_cache(self):
        reached=threading.Event();release=threading.Event()
        def factory(*args):
            real=region_executor(*args)
            def delayed(ctx):
                result=real(ctx);reached.set()
                if not release.wait(10):raise AssertionError('release missing')
                return result
            return delayed
        with patch('zaaggenz_timeline.service.region_executor',side_effect=factory):
            request=self.service.submit(document())
            try:
                self.assertTrue(reached.wait(15));self.service.cancel(request['job_id'])
            finally:release.set()
            self.assertEqual(self.service.scheduler.wait(request['job_id'],10).state,'cancelled')
        with self.assertRaises(JobError):self.service.artifact(request['job_id'])
        key=self.service._jobs[request['job_id']]['request_key']
        self.assertIsNone(self.service.scheduler.cached_preview(key))
        self.assertFalse(self.service.status(request['job_id'])['accepted'])

    def test_cancel_completed_job_revokes_publication_without_destroying_evidence(self):
        request=self.service.submit(document());a=completed(self.service,request)
        self.assertTrue(self.service.cancel(request['job_id']))
        self.assertEqual(self.service.status(request['job_id'])['state'],'cancelled')
        with self.assertRaisesRegex(JobError,'cancelled'):self.service.wave(request['job_id'])
        self.assertEqual(self.service.artifact(request['job_id']).audio_bytes,a.audio_bytes)

    def test_wrong_cache_identity_fails_closed_without_publishing_audio(self):
        request=self.service.submit(document());a=completed(self.service,request)
        bad=RenderArtifact('f'*64,a.recipe_sha256,a.product,a.cache_key,a.audio_bytes,a.asset,a.scopes)
        with patch.object(self.service.scheduler,'cached_render',return_value=bad):
            again=self.service.submit(document());snapshot=self.service.scheduler.wait(again['job_id'],10)
        self.assertEqual(snapshot.state,'failed');self.assertIn('identity mismatch',snapshot.error)
        with self.assertRaises(JobError):self.service.wave(again['job_id'])

    def test_memory_rejection_preserves_last_coherent_document_and_audio(self):
        limits=replace(SchedulerLimits(),max_job_memory_bytes=20*1024**2)
        scheduler=JobScheduler(limits);service=TimelineService(scheduler,debounce_seconds=0)
        try:
            good=document(with_rack=False);good['end_beat']='1/1';good['notes']=good['notes'][:1]
            request=service.submit(good);a=completed(service,request);before=service.session.snapshot()
            bad=document();bad['end_beat']='1/1';bad['notes']=bad['notes'][:1]
            with self.assertRaisesRegex(JobError,'memory'):service.submit(bad,{'start_beat':'0/1','end_beat':'1/4'})
            self.assertEqual(service.session.snapshot(),before)
            self.assertTrue(service.status(request['job_id'])['accepted'])
            self.assertEqual(service.artifact(request['job_id']).audio_bytes,a.audio_bytes)
        finally:service.close();scheduler.shutdown(cancel=True)

    def test_full_queue_rejects_before_mutating_or_cancelling_coherent_revision(self):
        from zaaggenz_jobs import JobClass
        limits = replace(SchedulerLimits(), interactive_workers=1, background_workers=1,
                         max_queued_jobs=1, max_background_queued_jobs=1)
        scheduler = JobScheduler(limits); service = TimelineService(scheduler, debounce_seconds=0)
        entered = threading.Event(); release = threading.Event()
        try:
            data = document(); good = service.submit(data); completed(service, good)
            before = service.session.snapshot()
            def occupied(ctx):
                entered.set()
                if not release.wait(15): raise AssertionError('release missing')
                ctx.check_cancelled(); return None
            scheduler.submit(JobClass.RENDER, 'a'*64, occupied, estimated_memory_bytes=1)
            self.assertTrue(entered.wait(5))
            scheduler.submit(JobClass.RENDER, 'b'*64, occupied, estimated_memory_bytes=1)
            changed = deepcopy(data); changed['master_gain_db'] = -13.
            with self.assertRaisesRegex(JobError, 'queue full'): service.submit(changed)
            self.assertEqual(service.session.snapshot(), before)
            self.assertTrue(service.status(good['job_id'])['accepted'])
        finally:
            release.set(); service.close(); scheduler.shutdown(cancel=True)

    def test_shared_scheduler_other_owner_and_proposal_do_not_replace_compose(self):
        before=self.service.session.snapshot();proposal=document()
        request=self.service.submit(proposal,authoritative=False);completed(self.service,request)
        self.assertEqual(self.service.session.snapshot(),before)
        self.assertTrue(self.service.status(request['job_id'])['accepted'])
        other=TimelineService(self.service.scheduler,debounce_seconds=0)
        try:
            with self.assertRaisesRegex(JobError,'owned'):other.cancel(request['job_id'])
            with self.assertRaisesRegex(JobError,'owned'):other.wave(request['job_id'])
            other.close()
            self.assertTrue(self.service.status(request['job_id'])['accepted'])
        finally:other.close()

    def test_history_owner_records_and_shared_cache_remain_bounded(self):
        data=document(with_rack=False);data['notes']=[];data['end_beat']='1/4'
        for _ in range(70):completed(self.service,self.service.submit(data))
        self.assertLessEqual(len(self.service._jobs),self.service._MAX_OWNED_JOB_IDS)
        self.assertLessEqual(len(self.service.scheduler._records),self.service.scheduler.limits.max_history_jobs)
        cache=self.service.scheduler._cache
        self.assertLessEqual(cache.bytes,cache.max_bytes);self.assertLessEqual(len(cache.data),cache.max_entries)


class RackHTTPAudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=ZaaggenzServer(0,12000)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.base=f'http://127.0.0.1:{cls.server.server_port}'
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join(5)
    def request(self,path,data=None,workspace='timeline'):
        headers={'Content-Type':'application/json','X-Zaaggenz-Token':self.server.token,
                 'Origin':self.base,'Sec-Fetch-Site':'same-origin',
                 RELEASE_HEADER:self.server.web_releases[workspace].release_id}
        request=Request(self.base+path,data=None if data is None else json.dumps(data).encode(),headers=headers)
        with urlopen(request,timeout=30) as response:
            return response.status,dict(response.headers),response.read()

    def test_actual_http_render_audio_save_reload_cache_and_current_meter_identity(self):
        self.assertIs(self.server.timeline.session,self.server.session)
        self.assertIs(self.server.timeline.scheduler,self.server.scheduler)
        for sr in (12000,48000):
            data=document(sr);_,_,raw=self.request('/api/timeline/validate',{'document':data})
            validation=json.loads(raw)
            code,_,raw=self.request('/api/timeline/render',{'document':json.loads(json.dumps(data)), 'region':None,'name':f'Rack {sr}'})
            self.assertEqual(code,202);job=json.loads(raw);completed(self.server.timeline,job)
            _,_,raw=self.request('/api/timeline/jobs/'+job['job_id']);status=json.loads(raw)
            self.assertTrue(status['accepted']);self.assertEqual(status['revision_id'],validation['revision_id'])
            self.assertEqual(status['artifact']['recipe_sha256'],job['recipe_sha256'])
            bands=status['artifact']['scopes']['diagnostics']['rack']['bands']
            self.assertGreater(bands[1]['input']['rms'],0)
            _,headers,raw=self.request('/api/timeline/jobs/'+job['job_id']+'/audio')
            rate,audio=wavfile.read(io.BytesIO(raw));self.assertEqual(rate,sr)
            self.assertEqual(headers['X-Timeline-Revision'],job['revision_id'])
            expected=render_phrase(compile_recipe(TimelineDocument(data))).mix
            np.testing.assert_array_equal(audio,expected)
            _,_,raw=self.request('/api/timeline/render',{'document':data,'region':None,'name':'Cached'})
            cached=json.loads(raw);completed(self.server.timeline,cached)
            self.assertTrue(self.server.timeline.status(cached['job_id'])['cache_hit'])
            changed=deepcopy(data);changed['master_gain_db']=-9.
            self.request('/api/timeline/validate',{'document':changed})
            _,_,raw=self.request('/api/timeline/jobs/'+cached['job_id'])
            self.assertEqual(json.loads(raw)['state'],'stale')
            with self.assertRaises(HTTPError):self.request('/api/timeline/jobs/'+cached['job_id']+'/audio')

    def test_http_full_context_memory_rejection_does_not_publish_or_mutate_session(self):
        data = document(48000, spectral=retune880()); data['end_beat'] = '64/1'
        before = self.server.session.snapshot()
        with patch('zaaggenz_melody.render.render_phrase', side_effect=AssertionError('no DSP before admission')):
            with self.assertRaises(HTTPError) as caught:
                self.request('/api/timeline/render', {'document': data, 'name': 'Too large',
                    'region': {'start_beat': '0/1', 'end_beat': '1/4'}})
        self.assertEqual(caught.exception.code, 400)
        self.assertEqual(self.server.session.snapshot(), before)

    def test_vocal_preview_uses_same_executor_without_changing_runtime_owner(self):
        before=self.server.session.snapshot();data=document()
        _,_,raw=self.request('/api/timeline/render',{'document':data,'region':None,'name':'Proposal'},workspace='vocal')
        job=json.loads(raw);completed(self.server.timeline,job)
        self.assertEqual(self.server.session.snapshot(),before)
        _,_,raw=self.request('/api/timeline/jobs/'+job['job_id']+'/audio')
        rate,audio=wavfile.read(io.BytesIO(raw));self.assertEqual(rate,12000)
        np.testing.assert_array_equal(audio,render_phrase(compile_recipe(TimelineDocument(data))).mix)


if __name__=='__main__':unittest.main(verbosity=2)
