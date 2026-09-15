from __future__ import annotations
import hashlib,tempfile,threading,time,unittest
from pathlib import Path
from zaaggenz_contracts import digest
from zaaggenz_jobs import *
from zaaggenz_jobs.model import CancellationToken

R='a'*64;Q='b'*64;K='c'*64

def asset(payload,frames=1):
    return dict(kind='AudioAssetRef',version='1.0.0',content_sha256=hashlib.sha256(payload).hexdigest(),
                identity_domain='pcm-f32le-interleaved-v1',sample_rate_hz=48000,channels=1,
                channel_layout='mono',frame_count=frames,level_domain='source',sample_policy='unclamped_float')
def artifact(revision=R,payload=b'1234',recipe=Q,cache_key=K,product='preview'):
    return RenderArtifact(revision,recipe,product,cache_key,payload,asset(payload,len(payload)//4),{'waveform':[0,1],'timecode_s':0.0})
def preview_dedupe(revision=R,recipe=Q,cache_key=K):
    return digest({'domain':'zaaggenz.preview-request-v1','revision_id':revision,
                   'recipe_sha256':recipe,'cache_key':cache_key})

class SchedulerTests(unittest.TestCase):
    def tearDown(self):
        if hasattr(self,'s'):self.s.shutdown(cancel=True,timeout=2)
    def make(self,**kw):
        base=dict(interactive_workers=1,background_workers=2,max_queued_jobs=8,max_background_queued_jobs=6,
                  max_history_jobs=64,max_memory_bytes=100,interactive_memory_reserve_bytes=20,
                  max_job_memory_bytes=80,max_preview_memory_bytes=20,preview_cache_bytes=4096,
                  preview_cache_entries=2,numeric_threads=1);base.update(kw)
        self.s=JobScheduler(SchedulerLimits(**base),apply_numeric_limit=False);return self.s
    def test_background_cannot_starve_preview(self):
        s=self.make();release=threading.Event();started=[threading.Event(),threading.Event()]
        def bg(i):
            def run(ctx):started[i].set();release.wait(2);ctx.check_cancelled();return i
            return run
        b=[s.submit(JobClass.ANALYSIS,R,bg(i),estimated_memory_bytes=40) for i in range(2)]
        self.assertTrue(all(e.wait(1) for e in started))
        p=s.submit(JobClass.PREVIEW,R,lambda ctx:artifact(),estimated_memory_bytes=20)
        self.assertEqual(s.wait(p,1).state,'completed','preview must complete while analysis lane remains occupied')
        self.assertTrue(any(s.snapshot(x).state=='running' for x in b));release.set()
    def test_background_memory_preserves_interactive_reserve(self):
        s=self.make(background_workers=1);release=threading.Event();started=threading.Event()
        s.submit(JobClass.ANALYSIS,R,lambda ctx:(started.set(),release.wait(2))[1],estimated_memory_bytes=80)
        self.assertTrue(started.wait(1));p=s.submit(JobClass.PREVIEW,R,lambda ctx:artifact(),estimated_memory_bytes=20)
        self.assertEqual(s.wait(p,1).state,'completed');release.set()
    def test_active_preview_deduplicates_and_completion_caches(self):
        s=self.make();go=threading.Event()
        def run(ctx):go.wait(1);return artifact()
        a=s.submit(JobClass.PREVIEW,R,run,estimated_memory_bytes=10,dedupe_key='same')
        b=s.submit(JobClass.PREVIEW,R,run,estimated_memory_bytes=10,dedupe_key='same');self.assertEqual(a,b)
        go.set();self.assertEqual(s.wait(a,1).state,'completed');self.assertIsInstance(s.cached_preview('same'),RenderArtifact)
    def test_cancel_requested_preview_is_not_deduplicated(self):
        s=self.make();go=threading.Event();started=threading.Event()
        def old(ctx):started.set();go.wait(1);ctx.check_cancelled();return artifact()
        a=s.submit(JobClass.PREVIEW,R,old,estimated_memory_bytes=1,dedupe_key='same');self.assertTrue(started.wait(1))
        self.assertTrue(s.cancel(a));self.assertEqual(s.snapshot(a).state,'cancel_requested')
        b=s.submit(JobClass.PREVIEW,R,lambda ctx:artifact(),estimated_memory_bytes=1,dedupe_key='same')
        self.assertNotEqual(a,b);go.set();self.assertEqual(s.wait(a,1).state,'cancelled');self.assertEqual(s.wait(b,1).state,'completed')
    def test_cache_is_bounded(self):
        s=self.make(preview_cache_entries=1,preview_cache_bytes=4096)
        for key,payload in [('a',b'aaaa'),('b',b'bbbb')]:
            j=s.submit(JobClass.PREVIEW,R,lambda ctx,p=payload:artifact(payload=p),estimated_memory_bytes=1,dedupe_key=key);s.wait(j,1)
        self.assertIsNone(s.cached_preview('a'));self.assertIsNotNone(s.cached_preview('b'))
    def test_history_bound_skips_old_running_record(self):
        s=self.make(max_history_jobs=16);release=threading.Event();started=threading.Event()
        old=s.submit(JobClass.ANALYSIS,R,lambda ctx:(started.set(),release.wait(3),ctx.check_cancelled())[2],estimated_memory_bytes=1)
        self.assertTrue(started.wait(1))
        for i in range(30):
            payload=int(i).to_bytes(4,'little')
            j=s.submit(JobClass.PREVIEW,R,lambda ctx,p=payload:artifact(payload=p),estimated_memory_bytes=1)
            self.assertEqual(s.wait(j,1).state,'completed')
            self.assertLessEqual(len(s._records),16)
        self.assertEqual(s.snapshot(old).state,'running');release.set()
    def test_history_bound_must_cover_queue_and_workers(self):
        with self.assertRaises(JobError):
            SchedulerLimits(interactive_workers=1,background_workers=2,max_queued_jobs=16,max_background_queued_jobs=8,max_history_jobs=16)
    def test_queued_and_running_cancellation(self):
        s=self.make(background_workers=1);release=threading.Event();started=threading.Event()
        first=s.submit(JobClass.ANALYSIS,R,lambda ctx:(started.set(),release.wait(2),ctx.check_cancelled())[2],estimated_memory_bytes=10);started.wait(1)
        queued=s.submit(JobClass.ANALYSIS,R,lambda ctx:1,estimated_memory_bytes=10);self.assertTrue(s.cancel(queued));self.assertEqual(s.wait(queued,1).state,'cancelled')
        self.assertTrue(s.cancel(first));release.set();self.assertEqual(s.wait(first,1).state,'cancelled')
    def test_cooperative_cancel_and_app_close(self):
        s=self.make();started=threading.Event()
        def run(ctx):
            started.set()
            while True:ctx.check_cancelled();time.sleep(.005)
        j=s.submit(JobClass.RENDER,R,run,estimated_memory_bytes=10);started.wait(1)
        self.assertTrue(s.shutdown(cancel=True,timeout=1));self.assertEqual(s.snapshot(j).state,'cancelled')
    def test_failure_does_not_poison_worker(self):
        s=self.make(background_workers=1)
        bad=s.submit(JobClass.ANALYSIS,R,lambda ctx:(_ for _ in ()).throw(RuntimeError('boom')),estimated_memory_bytes=1)
        self.assertEqual(s.wait(bad,1).state,'failed');good=s.submit(JobClass.ANALYSIS,R,lambda ctx:7,estimated_memory_bytes=1)
        self.assertEqual(s.wait(good,1).state,'completed');self.assertEqual(s.result(good),7)
    def test_progress_is_monotonic_and_bounded(self):
        s=self.make()
        def backwards(ctx):ctx.progress(.7);ctx.progress(.6)
        j=s.submit(JobClass.RENDER,R,backwards,estimated_memory_bytes=1);self.assertEqual(s.wait(j,1).state,'failed')
    def test_preview_must_fit_reserved_memory(self):
        s=self.make()
        with self.assertRaises(JobError):s.submit(JobClass.PREVIEW,R,lambda c:None,estimated_memory_bytes=21)
    def test_backpressure(self):
        s=self.make(max_queued_jobs=1,max_background_queued_jobs=1,background_workers=1);release=threading.Event();started=threading.Event()
        s.submit(JobClass.ANALYSIS,R,lambda c:(started.set(),release.wait(2))[1],estimated_memory_bytes=1);started.wait(1)
        s.submit(JobClass.ANALYSIS,R,lambda c:1,estimated_memory_bytes=1)
        with self.assertRaises(JobError):s.submit(JobClass.ANALYSIS,R,lambda c:2,estimated_memory_bytes=1)
        release.set()

class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.s=JobScheduler(SchedulerLimits(interactive_workers=1,background_workers=1,max_queued_jobs=8,
            max_background_queued_jobs=4,max_history_jobs=64,max_memory_bytes=100,interactive_memory_reserve_bytes=20,
            max_job_memory_bytes=80,max_preview_memory_bytes=20,preview_cache_bytes=8192,preview_cache_entries=4,numeric_threads=1),apply_numeric_limit=False)
        self.c=RenderCoordinator(self.s)
    def tearDown(self):self.c.close()
    def test_replace_race_suppresses_stale_result(self):
        slow=threading.Event()
        t1=self.c.request_preview('preview',R,Q,K,lambda ctx:(slow.wait(1),artifact(R))[1],estimated_memory_bytes=10)
        r2='d'*64;q2='e'*64;k2='f'*64
        t2=self.c.request_preview('preview',r2,q2,k2,lambda ctx:artifact(r2,recipe=q2,cache_key=k2),estimated_memory_bytes=10)
        slow.set();self.assertEqual(self.c.poll(t1)['state'],'stale')
        end=time.time()+1
        while time.time()<end:
            result=self.c.poll(t2)
            if result['state']=='completed':break
            time.sleep(.005)
        self.assertTrue(result['accepted']);self.assertEqual(result['revision_id'],r2);self.assertEqual(result['artifact']['scopes']['waveform'],[0,1])
    def test_identical_replace_reuses_active_job_with_new_generation(self):
        go=threading.Event();calls=[]
        def render(ctx):calls.append(ctx.job_id);go.wait(1);return artifact()
        t1=self.c.request_preview('p',R,Q,K,render,estimated_memory_bytes=1)
        t2=self.c.request_preview('p',R,Q,K,render,estimated_memory_bytes=1)
        self.assertEqual(t1.job_id,t2.job_id);self.assertEqual(t2.generation,t1.generation+1);self.assertEqual(self.c.poll(t1)['state'],'stale')
        self.assertEqual(t2.identity,(R,Q,K,'preview'))
        go.set();end=time.time()+1
        while time.time()<end:
            result=self.c.poll(t2)
            if result['state']=='completed':break
            time.sleep(.005)
        self.assertTrue(result['accepted']);self.assertEqual(len(calls),1)
    def test_stop_invalidates_late_result(self):
        go=threading.Event();t=self.c.request_preview('p',R,Q,K,lambda ctx:(go.wait(1),artifact())[1],estimated_memory_bytes=1)
        self.c.stop('p');go.set();self.assertEqual(self.c.poll(t)['state'],'stale')
    def test_completed_preview_cache_has_new_generation(self):
        t=self.c.request_preview('p',R,Q,K,lambda ctx:artifact(),estimated_memory_bytes=1)
        while self.c.poll(t)['state']!='completed':time.sleep(.005)
        t2=self.c.request_preview('p',R,Q,K,lambda ctx:(_ for _ in ()).throw(AssertionError('cache miss')),estimated_memory_bytes=1)
        self.assertTrue(t2.cache_hit);result=self.c.poll(t2);self.assertTrue(result['accepted']);self.assertEqual(result['generation'],t.generation+1)
        t3=self.c.request_preview('p',R,Q,K,lambda ctx:(_ for _ in ()).throw(AssertionError('repeat cache miss')),estimated_memory_bytes=1)
        self.assertTrue(t3.cache_hit);self.assertTrue(self.c.poll(t3)['accepted']);self.assertEqual(t3.identity,(R,Q,K,'preview'))
    def test_fresh_identity_mismatches_fail_closed_without_cache_poison(self):
        cases=(
            ('revision_id',artifact('d'*64)),
            ('recipe_sha256',artifact(recipe='d'*64)),
            ('cache_key',artifact(cache_key='d'*64)),
            ('product',artifact(product='analysis')),
        )
        for i,(field,bad) in enumerate(cases):
            with self.subTest(field=field):
                t=self.c.request_preview(f'p{i}',R,Q,K,lambda ctx,value=bad:value,estimated_memory_bytes=1)
                self.assertEqual(self.s.wait(t.job_id,1).state,'failed')
                with self.assertRaisesRegex(JobError,rf'preview identity mismatch: {field}'):
                    self.c.poll(t)
                self.assertIsNone(self.s.cached_preview(t.dedupe_key),'rejected result must not poison preview cache')
    def test_correct_fresh_identity_is_accepted_and_ticket_is_complete(self):
        t=self.c.request_preview('p',R,Q,K,lambda ctx:artifact(),estimated_memory_bytes=1)
        self.assertEqual((t.revision_id,t.recipe_sha256,t.cache_key,t.product),(R,Q,K,'preview'))
        self.assertEqual(self.s.wait(t.job_id,1).state,'completed')
        result=self.c.poll(t);self.assertTrue(result['accepted']);self.assertEqual(result['artifact']['recipe_sha256'],Q);self.assertEqual(result['artifact']['cache_key'],K);self.assertEqual(result['artifact']['product'],'preview')
    def test_cache_hit_uses_same_complete_identity_check(self):
        bad_recipe='d'*64;dedupe=preview_dedupe()
        j=self.s.submit(JobClass.PREVIEW,R,lambda ctx:artifact(recipe=bad_recipe),estimated_memory_bytes=1,dedupe_key=dedupe)
        self.assertEqual(self.s.wait(j,1).state,'completed');self.assertIsNotNone(self.s.cached_preview(dedupe))
        with self.assertRaisesRegex(JobError,'preview identity mismatch: recipe_sha256'):
            self.c.request_preview('p',R,Q,K,lambda ctx:artifact(),estimated_memory_bytes=1)
        self.assertNotIn('p',self.c._channels,'mismatched cache entry must not become accepted channel state')
    def test_non_render_executor_result_fails_closed_and_is_not_cached(self):
        t=self.c.request_preview('p',R,Q,K,lambda ctx:b'not-an-artifact',estimated_memory_bytes=1)
        self.assertEqual(self.s.wait(t.job_id,1).state,'failed')
        with self.assertRaisesRegex(JobError,'preview executor returned non-render artifact'):self.c.poll(t)
        self.assertIsNone(self.s.cached_preview(t.dedupe_key))

class AtomicTests(unittest.TestCase):
    def test_cancelled_publish_does_not_replace_existing(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'a.bin';p.write_bytes(b'old');token=CancellationToken();token.cancel()
            with self.assertRaises(JobCancelled):atomic_publish_bytes(p,b'new',token)
            self.assertEqual(p.read_bytes(),b'old');self.assertFalse(list(Path(td).glob('*.tmp')))
    def test_successful_publish_replaces_atomically(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'a.bin';p.write_bytes(b'old');atomic_publish_bytes(p,b'new');self.assertEqual(p.read_bytes(),b'new')
    def test_artifact_identity(self):self.assertEqual(artifact().asset['content_sha256'],hashlib.sha256(b'1234').hexdigest())
    def test_artifact_rejects_mismatched_bytes(self):
        a=asset(b'xxxx')
        with self.assertRaises(JobError):RenderArtifact(R,Q,'preview',K,b'yyyy',a,{})
    def test_pcm_byte_length_matches_declared_frames(self):
        payload=b'abcd';a=asset(payload,frames=2)
        with self.assertRaises(JobError):RenderArtifact(R,Q,'preview',K,payload,a,{})

if __name__=='__main__':unittest.main(verbosity=2)
