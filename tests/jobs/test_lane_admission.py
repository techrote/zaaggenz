from __future__ import annotations

import threading
import unittest

from zaaggenz_jobs import JobClass,JobError,JobScheduler,SchedulerLimits

R='a'*64


def limits(**overrides):
    values=dict(interactive_workers=1,background_workers=2,max_queued_jobs=8,max_background_queued_jobs=6,
                max_history_jobs=64,max_memory_bytes=100,interactive_memory_reserve_bytes=40,
                max_job_memory_bytes=80,max_preview_memory_bytes=20,preview_cache_bytes=4096,
                preview_cache_entries=2,numeric_threads=1)
    values.update(overrides)
    return SchedulerLimits(**values)


class LaneAdmissionTests(unittest.TestCase):
    def setUp(self):self.schedulers=[]
    def tearDown(self):
        for scheduler in self.schedulers:scheduler.shutdown(cancel=True,timeout=3)
    def make(self,**overrides):
        scheduler=JobScheduler(limits(**overrides),apply_numeric_limit=False);self.schedulers.append(scheduler);return scheduler

    def test_background_classes_over_permanent_capacity_fail_before_queue_mutation(self):
        scheduler=self.make()
        for job_class in (JobClass.ANALYSIS,JobClass.RESEARCH,JobClass.BATCH):
            with self.subTest(job_class=job_class),self.assertRaisesRegex(JobError,'permanent background lane capacity'):
                scheduler.submit(job_class,R,lambda ctx:1,estimated_memory_bytes=61)
        self.assertEqual(scheduler._records,{})
        self.assertEqual(scheduler._background,[])

    def test_exact_background_capacity_is_feasible(self):
        scheduler=self.make(background_workers=1)
        job=scheduler.submit(JobClass.ANALYSIS,R,lambda ctx:7,estimated_memory_bytes=60)
        self.assertEqual(scheduler.wait(job,2).state,'completed')
        self.assertEqual(scheduler.result(job),7)

    def test_temporarily_blocked_feasible_background_job_remains_queueable(self):
        scheduler=self.make(background_workers=2);release=threading.Event();started=threading.Event()
        self.addCleanup(release.set)
        first=scheduler.submit(JobClass.ANALYSIS,R,lambda ctx:(started.set(),release.wait(3),1)[2],estimated_memory_bytes=40)
        self.assertTrue(started.wait(2))
        second=scheduler.submit(JobClass.RESEARCH,R,lambda ctx:2,estimated_memory_bytes=40)
        self.assertEqual(scheduler.snapshot(second).state,'queued')
        release.set()
        self.assertEqual(scheduler.wait(first,2).state,'completed')
        self.assertEqual(scheduler.wait(second,2).state,'completed')
        self.assertEqual(scheduler.result(second),2)

    def test_interactive_render_can_use_memory_reserved_away_from_background(self):
        scheduler=self.make()
        job=scheduler.submit(JobClass.RENDER,R,lambda ctx:9,estimated_memory_bytes=80)
        self.assertEqual(scheduler.wait(job,2).state,'completed')
        self.assertEqual(scheduler.result(job),9)

    def test_preview_specific_reserve_bound_still_wins(self):
        scheduler=self.make()
        with self.assertRaisesRegex(JobError,'preview exceeds reserved memory bound'):
            scheduler.submit(JobClass.PREVIEW,R,lambda ctx:1,estimated_memory_bytes=21)
        job=scheduler.submit(JobClass.PREVIEW,R,lambda ctx:1,estimated_memory_bytes=20)
        self.assertEqual(scheduler.wait(job,2).state,'completed')

    def test_temporary_queue_backpressure_has_distinct_error(self):
        scheduler=self.make(background_workers=1,max_queued_jobs=1,max_background_queued_jobs=1)
        release=threading.Event();started=threading.Event();self.addCleanup(release.set)
        first=scheduler.submit(JobClass.ANALYSIS,R,lambda ctx:(started.set(),release.wait(3),1)[2],estimated_memory_bytes=60)
        self.assertTrue(started.wait(2))
        queued=scheduler.submit(JobClass.RESEARCH,R,lambda ctx:2,estimated_memory_bytes=1)
        self.assertEqual(scheduler.snapshot(queued).state,'queued')
        with self.assertRaisesRegex(JobError,'scheduler queue full') as caught:
            scheduler.submit(JobClass.BATCH,R,lambda ctx:3,estimated_memory_bytes=1)
        self.assertNotIn('capacity',str(caught.exception))
        release.set()
        self.assertEqual(scheduler.wait(first,2).state,'completed')
        self.assertEqual(scheduler.wait(queued,2).state,'completed')

    def test_feasible_queued_cancellation_is_unchanged(self):
        scheduler=self.make(background_workers=1)
        release=threading.Event();started=threading.Event();executed=threading.Event();self.addCleanup(release.set)
        first=scheduler.submit(JobClass.ANALYSIS,R,lambda ctx:(started.set(),release.wait(3),1)[2],estimated_memory_bytes=60)
        self.assertTrue(started.wait(2))
        queued=scheduler.submit(JobClass.RESEARCH,R,lambda ctx:(executed.set(),2)[1],estimated_memory_bytes=1)
        self.assertTrue(scheduler.cancel(queued))
        self.assertEqual(scheduler.snapshot(queued).state,'cancelled')
        release.set()
        self.assertEqual(scheduler.wait(first,2).state,'completed')
        self.assertFalse(executed.is_set())


if __name__=='__main__':unittest.main(verbosity=2)
