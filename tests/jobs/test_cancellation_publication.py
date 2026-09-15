from __future__ import annotations

import hashlib
import threading
import time
import unittest

from zaaggenz_jobs import JobClass, JobError, JobScheduler, RenderArtifact, SchedulerLimits


REVISION = 'a' * 64
RECIPE = 'b' * 64
CACHE_KEY = 'c' * 64


def _asset(payload: bytes) -> dict:
    return {
        'kind': 'AudioAssetRef',
        'version': '1.0.0',
        'content_sha256': hashlib.sha256(payload).hexdigest(),
        'identity_domain': 'pcm-f32le-interleaved-v1',
        'sample_rate_hz': 48000,
        'channels': 1,
        'channel_layout': 'mono',
        'frame_count': len(payload) // 4,
        'level_domain': 'source',
        'sample_policy': 'unclamped_float',
    }


def _artifact(payload: bytes = b'1234') -> RenderArtifact:
    return RenderArtifact(
        REVISION,
        RECIPE,
        'preview',
        CACHE_KEY,
        payload,
        _asset(payload),
        {'waveform': [0, 1]},
    )


class CancellationPublicationTests(unittest.TestCase):
    def setUp(self):
        self.scheduler = JobScheduler(
            SchedulerLimits(
                interactive_workers=1,
                background_workers=1,
                max_queued_jobs=16,
                max_background_queued_jobs=8,
                max_history_jobs=128,
                max_memory_bytes=100,
                interactive_memory_reserve_bytes=20,
                max_job_memory_bytes=80,
                max_preview_memory_bytes=20,
                preview_cache_bytes=4096,
                preview_cache_entries=8,
                numeric_threads=1,
            ),
            apply_numeric_limit=False,
        )

    def tearDown(self):
        self.scheduler.shutdown(cancel=True, timeout=2.0)

    def _pause_after_final_check(self, job_id: str):
        checked = threading.Event()
        release_commit = threading.Event()
        token = self.scheduler._records[job_id].token
        original_check = token.check

        def hooked_check():
            # Establish that the semantic final check observed a clear token, then
            # hold the worker in the exact historical race window before it can
            # reacquire the scheduler condition for publication.
            original_check()
            checked.set()
            self.assertTrue(release_commit.wait(2.0), 'test failed to release publication boundary')

        token.check = hooked_check
        return checked, release_commit

    def test_cancel_after_final_check_wins_preview_publication_commit(self):
        executor_started = threading.Event()
        executor_release = threading.Event()

        def executor(_ctx):
            executor_started.set()
            self.assertTrue(executor_release.wait(2.0))
            return _artifact()

        job_id = self.scheduler.submit(
            JobClass.PREVIEW,
            REVISION,
            executor,
            estimated_memory_bytes=1,
            dedupe_key='race-preview',
        )
        self.assertTrue(executor_started.wait(1.0))
        checked, release_commit = self._pause_after_final_check(job_id)
        executor_release.set()
        self.assertTrue(checked.wait(1.0), 'worker never reached the final publication check')

        self.assertTrue(self.scheduler.cancel(job_id))
        mid = self.scheduler.snapshot(job_id)
        self.assertEqual(mid.state, 'cancel_requested')
        self.assertTrue(mid.cancel_requested)

        release_commit.set()
        final = self.scheduler.wait(job_id, 1.0)
        self.assertEqual(final.state, 'cancelled')
        self.assertTrue(final.cancel_requested)
        self.assertEqual(final.progress, 0.0)
        self.assertIsNone(self.scheduler.cached_preview('race-preview'))
        with self.assertRaisesRegex(JobError, 'job has no completed result'):
            self.scheduler.result(job_id)
        self.assertIsNotNone(self.scheduler._records[job_id].finished_at)

    def test_cancel_after_final_check_discards_non_preview_result(self):
        executor_started = threading.Event()
        executor_release = threading.Event()

        def executor(_ctx):
            executor_started.set()
            self.assertTrue(executor_release.wait(2.0))
            return {'should_not_publish': True}

        job_id = self.scheduler.submit(
            JobClass.ANALYSIS,
            REVISION,
            executor,
            estimated_memory_bytes=1,
        )
        self.assertTrue(executor_started.wait(1.0))
        checked, release_commit = self._pause_after_final_check(job_id)
        executor_release.set()
        self.assertTrue(checked.wait(1.0))
        self.assertTrue(self.scheduler.cancel(job_id))
        release_commit.set()

        self.assertEqual(self.scheduler.wait(job_id, 1.0).state, 'cancelled')
        with self.assertRaisesRegex(JobError, 'job has no completed result'):
            self.scheduler.result(job_id)
        self.assertIsNone(self.scheduler._records[job_id].result)

    def test_cancel_immediately_before_final_check_needs_no_executor_check(self):
        executor_started = threading.Event()
        executor_release = threading.Event()

        def executor(_ctx):
            executor_started.set()
            self.assertTrue(executor_release.wait(2.0))
            return _artifact()

        job_id = self.scheduler.submit(
            JobClass.PREVIEW,
            REVISION,
            executor,
            estimated_memory_bytes=1,
            dedupe_key='before-check',
        )
        self.assertTrue(executor_started.wait(1.0))
        self.assertTrue(self.scheduler.cancel(job_id))
        executor_release.set()

        self.assertEqual(self.scheduler.wait(job_id, 1.0).state, 'cancelled')
        self.assertIsNone(self.scheduler.cached_preview('before-check'))
        with self.assertRaises(JobError):
            self.scheduler.result(job_id)

    def test_cancel_after_committed_completion_is_false_and_does_not_revoke(self):
        expected = _artifact()
        job_id = self.scheduler.submit(
            JobClass.PREVIEW,
            REVISION,
            lambda _ctx: expected,
            estimated_memory_bytes=1,
            dedupe_key='committed',
        )
        self.assertEqual(self.scheduler.wait(job_id, 1.0).state, 'completed')
        self.assertIs(self.scheduler.result(job_id), expected)
        self.assertIs(self.scheduler.cached_preview('committed'), expected)

        self.assertFalse(self.scheduler.cancel(job_id))
        self.assertEqual(self.scheduler.snapshot(job_id).state, 'completed')
        self.assertIs(self.scheduler.result(job_id), expected)
        self.assertIs(self.scheduler.cached_preview('committed'), expected)

    def test_shutdown_cancellation_wins_at_publication_boundary(self):
        executor_started = threading.Event()
        executor_release = threading.Event()

        def executor(_ctx):
            executor_started.set()
            self.assertTrue(executor_release.wait(2.0))
            return _artifact()

        job_id = self.scheduler.submit(
            JobClass.PREVIEW,
            REVISION,
            executor,
            estimated_memory_bytes=1,
            dedupe_key='shutdown-race',
        )
        self.assertTrue(executor_started.wait(1.0))
        checked, release_commit = self._pause_after_final_check(job_id)
        executor_release.set()
        self.assertTrue(checked.wait(1.0))

        shutdown_result = []
        shutdown_done = threading.Event()

        def shutdown():
            shutdown_result.append(self.scheduler.shutdown(cancel=True, timeout=1.5))
            shutdown_done.set()

        thread = threading.Thread(target=shutdown)
        thread.start()
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            if self.scheduler.snapshot(job_id).state == 'cancel_requested':
                break
            time.sleep(0.001)
        self.assertEqual(self.scheduler.snapshot(job_id).state, 'cancel_requested')

        release_commit.set()
        self.assertTrue(shutdown_done.wait(1.5))
        thread.join(1.0)
        self.assertEqual(shutdown_result, [True])
        self.assertEqual(self.scheduler.snapshot(job_id).state, 'cancelled')
        self.assertIsNone(self.scheduler.cached_preview('shutdown-race'))
        with self.assertRaises(JobError):
            self.scheduler.result(job_id)

    def test_concurrent_cancel_completion_has_one_atomic_winner(self):
        # Timing is deliberately not used to prescribe the winner here. The
        # invariant is stronger: if cancel() reports that it won before the
        # publication commit, completion must never be observable afterwards.
        for index in range(32):
            started = threading.Event()
            release = threading.Event()

            def executor(_ctx, value=index):
                started.set()
                self.assertTrue(release.wait(2.0))
                return value

            job_id = self.scheduler.submit(
                JobClass.RENDER,
                REVISION,
                executor,
                estimated_memory_bytes=1,
            )
            self.assertTrue(started.wait(1.0))
            cancel_outcome = []
            cancel_thread = threading.Thread(target=lambda: cancel_outcome.append(self.scheduler.cancel(job_id)))
            cancel_thread.start()
            release.set()
            cancel_thread.join(1.0)
            self.assertEqual(len(cancel_outcome), 1)

            final = self.scheduler.wait(job_id, 1.0)
            if cancel_outcome[0]:
                self.assertEqual(final.state, 'cancelled')
                with self.assertRaises(JobError):
                    self.scheduler.result(job_id)
            else:
                self.assertEqual(final.state, 'completed')
                self.assertEqual(self.scheduler.result(job_id), index)


if __name__ == '__main__':
    unittest.main(verbosity=2)
