from dataclasses import replace
from pathlib import Path
import tempfile
import threading
import unittest

from zaaggenz_jobs import JobScheduler, JobClass, JobError
from zaaggenz_jobs.model import CancellationToken
from zaaggenz_inverse import *
from zaaggenz_inverse.fixtures import synthetic_fixture
from zaaggenz_inverse.recipes import render_trace, RenderTrace


class ResumeAndJobTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.fixture=synthetic_fixture('holdout-step')

    def partial(self, fit, path=None):
        token=CancellationToken();records=[]
        def checkpoint(cp):
            records.append(cp)
            if path is not None:save_checkpoint(cp,path)
            if cp.next_ordinal==2:token.cancel()
        with self.assertRaises(SearchInterrupted) as caught:
            run_grid(fit,check_cancelled=token.check,on_checkpoint=checkpoint)
        self.assertEqual(caught.exception.checkpoint.sha256,records[-1].sha256)
        self.assertEqual(records[-1].next_ordinal,2)
        return records[-1]

    def test_atomic_checkpoint_roundtrip_and_resume_matches_uninterrupted(self):
        f=self.fixture
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'checkpoint.json';fit,_=f.experiment();cp=self.partial(fit,path)
            self.assertEqual(load_checkpoint(path).sha256,cp.sha256)
            replay,_=f.experiment();full,_=f.experiment()
            a,b=run_grid(replay,checkpoint=load_checkpoint(path)),run_grid(full)
            self.assertEqual(a.to_dict(),b.to_dict())
            self.assertEqual(replay.render_calls,6,'checkpoint replay is physical work, not budget-free cached proof')
            self.assertEqual(a.to_dict()['budget']['consumed_evaluations'],3)
            self.assertFalse(list(Path(td).glob('*.tmp')))

    def test_replay_does_not_trust_a_warm_render_cache(self):
        fit,_=self.fixture.experiment();cp=self.partial(fit)
        before=fit.render_calls
        result=run_grid(fit,checkpoint=cp)
        self.assertEqual(fit.render_calls-before,6)
        self.assertEqual(len(result.candidates),3)

    def test_request_and_environment_changes_are_explicit_divergence(self):
        fit,_=self.fixture.experiment();cp=self.partial(fit)
        changed=replace(self.fixture,seed='7').experiment()[0]
        with self.assertRaises(ResumeDivergence) as caught:run_grid(changed,checkpoint=cp)
        self.assertEqual(caught.exception.to_dict()['state'],'divergent')
        with self.assertRaises(ResumeDivergence):run_grid(fit,checkpoint=replace(cp,environment_sha256='0'*64))

    def test_changed_completed_result_fails_replay_even_with_same_method_id(self):
        state={'gain':1.}
        def renderer(recipe):
            trace=render_trace(recipe);gain=state['gain']
            return RenderTrace(recipe,trace.source,trace.pre_master*gain,trace.output*gain)
        fit,_=self.fixture.experiment(renderer=renderer,renderer_id='declared-replay-probe.v1')
        cp=self.partial(fit)
        state['gain']=.5
        replay,_=self.fixture.experiment(renderer=renderer,renderer_id='declared-replay-probe.v1')
        with self.assertRaises(ResumeDivergence) as caught:run_grid(replay,checkpoint=cp)
        self.assertIn('failed exact replay',caught.exception.reason)

    def test_tampered_prefix_is_detected(self):
        fit,_=self.fixture.experiment();cp=self.partial(fit)
        tampered=replace(cp,evaluation_sha256s=('0'*64,cp.evaluation_sha256s[1]))
        with self.assertRaises(ResumeDivergence):run_grid(fit,checkpoint=tampered)

    def test_cancel_before_first_candidate_has_empty_valid_checkpoint(self):
        token=CancellationToken();token.cancel();fit,_=self.fixture.experiment()
        with self.assertRaises(SearchInterrupted) as caught:run_grid(fit,check_cancelled=token.check)
        self.assertEqual(caught.exception.checkpoint.next_ordinal,0)
        self.assertEqual(fit.render_calls,0)

    def test_bounds_fail_before_any_render_or_budget_consumption(self):
        fit,_=self.fixture.experiment()
        with self.assertRaises(InverseError):fit.evaluate(ParameterState((('/nodes/0/automation/0/points/1/value',99.),)))
        self.assertEqual(fit.render_calls,0)

    def test_scheduler_research_class_revision_progress_and_output(self):
        scheduler=JobScheduler()
        try:
            fit,_=self.fixture.experiment()
            with tempfile.TemporaryDirectory() as td:
                path=Path(td)/'last.json'
                jid=submit_search_job(scheduler,fit,checkpoint_path=path)
                snapshot=scheduler.wait(jid,30)
                self.assertEqual(snapshot.state,'completed',snapshot.error)
                self.assertEqual(snapshot.job_class,'research')
                self.assertEqual(snapshot.revision_id,fit.request.source_revision_id)
                self.assertEqual(snapshot.progress,1.)
                result=scheduler.result(jid)
                self.assertEqual(load_checkpoint(path).sha256,result.checkpoint.sha256)
        finally:scheduler.shutdown(cancel=True,timeout=5)

    def test_research_does_not_starve_preview_lane(self):
        started=threading.Event();release=threading.Event();scheduler=JobScheduler()
        def renderer(recipe):
            started.set();release.wait(10)
            return render_trace(recipe)
        try:
            fit,_=self.fixture.experiment(renderer=renderer,renderer_id='blocked-research-probe.v1')
            research=submit_search_job(scheduler,fit)
            self.assertTrue(started.wait(5))
            preview=scheduler.submit(JobClass.PREVIEW,fit.request.source_revision_id,lambda ctx:'preview-responsive',estimated_memory_bytes=1024)
            self.assertEqual(scheduler.wait(preview,3).state,'completed')
            self.assertEqual(scheduler.result(preview),'preview-responsive')
            self.assertEqual(scheduler.snapshot(research).state,'running')
            scheduler.cancel(research);release.set()
            self.assertEqual(scheduler.wait(research,10).state,'cancelled')
        finally:release.set();scheduler.shutdown(cancel=True,timeout=5)

    def test_scheduler_cancellation_keeps_completed_checkpoint_not_partial_result(self):
        scheduler=JobScheduler();started=threading.Event();release=threading.Event()
        try:
            fit,_=self.fixture.experiment()
            with tempfile.TemporaryDirectory() as td:
                path=Path(td)/'last.json'
                def checkpoint(cp):
                    if cp.next_ordinal==1:started.set();release.wait(10)
                jid=submit_search_job(scheduler,fit,checkpoint_path=path,on_checkpoint=checkpoint)
                self.assertTrue(started.wait(5));scheduler.cancel(jid);release.set()
                self.assertEqual(scheduler.wait(jid,10).state,'cancelled')
                self.assertEqual(load_checkpoint(path).next_ordinal,1)
                with self.assertRaises(JobError):scheduler.result(jid)
        finally:release.set();scheduler.shutdown(cancel=True,timeout=5)

if __name__=='__main__':unittest.main()
