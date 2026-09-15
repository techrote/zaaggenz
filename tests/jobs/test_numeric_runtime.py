from __future__ import annotations
import os
import threading
import unittest
from unittest import mock

import numpy as np
from zaaggenz_jobs import JobClass,JobError,JobScheduler,SchedulerLimits,runtime_state
import zaaggenz_jobs.numeric_runtime as runtime

_ENV=runtime._ENV_NAMES
R='a'*64


def limits(n=1):
    return SchedulerLimits(interactive_workers=1,background_workers=1,max_queued_jobs=8,
        max_background_queued_jobs=4,max_history_jobs=32,max_memory_bytes=64,
        interactive_memory_reserve_bytes=16,max_job_memory_bytes=48,max_preview_memory_bytes=16,
        preview_cache_bytes=1024,preview_cache_entries=2,numeric_threads=n)


class _Guard:
    def __init__(self,limit):self.limit=limit;self.restores=0
    def restore_original_limits(self):self.restores+=1


class _Factory:
    def __init__(self):self.guards=[]
    def __call__(self,*,limits):
        g=_Guard(limits);self.guards.append(g);return g


class NumericRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.schedulers=[];self.leases=[];self.original={name:os.environ.get(name) for name in _ENV}
        self.assertEqual(runtime_state()['owners'],0,'test entered with leaked process numerical owner')
    def tearDown(self):
        for s in reversed(self.schedulers):s.shutdown(cancel=True,timeout=2)
        for lease in reversed(self.leases):lease.restore_original_limits()
        self.assertEqual(runtime_state()['owners'],0,'test leaked process numerical owner')
        for name,value in self.original.items():
            if value is None:os.environ.pop(name,None)
            else:os.environ[name]=value
    def scheduler(self,n=1):
        s=JobScheduler(limits(n),apply_numeric_limit=True);self.schedulers.append(s);return s

    def test_identical_schedulers_share_one_native_guard_and_restore_in_both_orders(self):
        for reverse in (False,True):
            factory=_Factory()
            with self.subTest(reverse=reverse),mock.patch.object(runtime,'_load_threadpool_limits',return_value=factory):
                a=self.scheduler(1);b=self.scheduler(1)
                self.assertEqual(runtime_state(),{'limit':1,'owners':2,'degraded':False})
                self.assertEqual(len(factory.guards),1)
                first,second=(b,a) if reverse else (a,b)
                self.assertTrue(first.shutdown());self.schedulers.remove(first)
                self.assertEqual(runtime_state()['owners'],1);self.assertEqual(factory.guards[0].restores,0)
                self.assertTrue(second.shutdown());self.schedulers.remove(second)
                self.assertEqual(runtime_state()['owners'],0);self.assertEqual(factory.guards[0].restores,1)

    def test_conflicting_limits_fail_before_second_scheduler_owns_runtime(self):
        factory=_Factory()
        with mock.patch.object(runtime,'_load_threadpool_limits',return_value=factory):
            a=self.scheduler(1)
            with self.assertRaisesRegex(JobError,'already owns limit 1'):
                JobScheduler(limits(2),apply_numeric_limit=True)
            self.assertEqual(runtime_state()['owners'],1);self.assertEqual(len(factory.guards),1)
            self.assertTrue(a.shutdown());self.schedulers.remove(a)

    def test_exact_external_environment_is_restored_only_after_final_owner(self):
        external={'OMP_NUM_THREADS':'7','OPENBLAS_NUM_THREADS':None,'MKL_NUM_THREADS':'3',
                  'NUMEXPR_NUM_THREADS':'5','VECLIB_MAXIMUM_THREADS':None}
        for name,value in external.items():
            if value is None:os.environ.pop(name,None)
            else:os.environ[name]=value
        with mock.patch.object(runtime,'_load_threadpool_limits',return_value=_Factory()):
            a=self.scheduler(1);b=self.scheduler(1)
            self.assertTrue(all(os.environ[name]=='1' for name in _ENV))
            a.shutdown();self.schedulers.remove(a)
            self.assertTrue(all(os.environ[name]=='1' for name in _ENV))
            b.shutdown();self.schedulers.remove(b)
        self.assertEqual({name:os.environ.get(name) for name in _ENV},external)

    def test_missing_threadpoolctl_is_explicit_degraded_shared_runtime(self):
        with mock.patch.object(runtime,'_load_threadpool_limits',return_value=None):
            a=self.scheduler(1);b=self.scheduler(1)
            self.assertEqual(runtime_state(),{'limit':1,'owners':2,'degraded':True})
            a.shutdown();self.schedulers.remove(a);self.assertEqual(runtime_state()['owners'],1)
            b.shutdown();self.schedulers.remove(b);self.assertEqual(runtime_state()['owners'],0)

    def test_worker_failure_and_shutdown_do_not_release_another_scheduler_owner(self):
        with mock.patch.object(runtime,'_load_threadpool_limits',return_value=_Factory()):
            a=self.scheduler(1);b=self.scheduler(1)
            job=a.submit(JobClass.ANALYSIS,R,lambda ctx:(_ for _ in ()).throw(RuntimeError('boom')),estimated_memory_bytes=1)
            self.assertEqual(a.wait(job,1).state,'failed');self.assertEqual(runtime_state()['owners'],2)
            a.shutdown();self.schedulers.remove(a);self.assertEqual(runtime_state()['owners'],1)
            good=b.submit(JobClass.ANALYSIS,R,lambda ctx:7,estimated_memory_bytes=1)
            self.assertEqual(b.wait(good,1).state,'completed');self.assertEqual(b.result(good),7)
            b.shutdown();self.schedulers.remove(b)

    def test_apply_numeric_limit_false_is_explicit_already_owned_runtime_path(self):
        with mock.patch.object(runtime,'_load_threadpool_limits',return_value=_Factory()):
            lease=runtime.numeric_thread_limit(2);self.leases.append(lease)
            s=JobScheduler(limits(1),apply_numeric_limit=False);self.schedulers.append(s)
            self.assertEqual(runtime_state()['limit'],2);self.assertEqual(runtime_state()['owners'],1)
            self.assertTrue(s.shutdown());self.schedulers.remove(s)
            self.assertEqual(runtime_state()['owners'],1)
            lease.restore_original_limits();self.leases.remove(lease)

    def test_real_native_threadpool_observation_and_restoration(self):
        try:
            from threadpoolctl import threadpool_info
        except ImportError:self.skipTest('threadpoolctl absent: degraded path covered separately')
        np.dot(np.ones((8,8)),np.ones((8,8)))
        def observed():
            return {(x.get('user_api'),x.get('internal_api'),x.get('prefix')):x.get('num_threads')
                    for x in threadpool_info() if x.get('num_threads') is not None}
        before=observed();self.assertTrue(before,'no native numerical pool exposed for inspection')
        s=self.scheduler(1);during=observed()
        self.assertTrue(during);self.assertTrue(all(value==1 for value in during.values()),during)
        s.shutdown();self.schedulers.remove(s);after=observed()
        self.assertEqual(after,before)


if __name__=='__main__':unittest.main(verbosity=2)
