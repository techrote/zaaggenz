from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))

from test_chunking import _fixture
from zaaggenz_jobs import SchedulerLimits
from zaaggenz_performance import PerformanceError, render_persistent_sections, submit_persistent_sections


class _Context:
    def check_cancelled(self):
        return None

    def progress(self, _value):
        return None


class _CaptureScheduler:
    def __init__(self):
        self.limits = SchedulerLimits(
            interactive_workers=1,
            background_workers=1,
            max_memory_bytes=256 * 1024 * 1024,
            interactive_memory_reserve_bytes=64 * 1024 * 1024,
            max_job_memory_bytes=192 * 1024 * 1024,
        )
        self.submissions = []

    def submit(self, job_class, revision_id, execute, *, estimated_memory_bytes):
        self.submissions.append((job_class, revision_id, execute, estimated_memory_bytes))
        return execute


class SubmissionInputSnapshotTests(unittest.TestCase):
    def test_muted_roles_are_snapshotted_before_admission_and_execution(self):
        _, _, runtime, sections = _fixture()
        expected = render_persistent_sections(sections, runtime)
        muted_roles = ["synthline", "exciter"]
        scheduler = _CaptureScheduler()

        execute = submit_persistent_sections(
            scheduler,
            "f" * 64,
            sections,
            runtime,
            muted_roles=muted_roles,
        )
        muted_roles.append("body")

        result = execute(_Context())
        np.testing.assert_array_equal(result.stems["body"], expected.stems["body"])
        self.assertGreater(float(np.max(np.abs(result.stems["body"]))), 0.0)

    def test_muted_role_iterators_are_consumed_once_into_the_admitted_snapshot(self):
        _, _, runtime, sections = _fixture()
        muted_roles = iter(("synthline", "exciter"))
        scheduler = _CaptureScheduler()

        execute = submit_persistent_sections(
            scheduler,
            "e" * 64,
            sections,
            runtime,
            muted_roles=muted_roles,
        )
        self.assertEqual(list(muted_roles), [])
        result = execute(_Context())
        self.assertEqual(len(result.mix), 2000)

    def test_muted_role_snapshot_is_bounded_before_scheduler_submission(self):
        _, _, runtime, sections = _fixture()
        scheduler = _CaptureScheduler()
        with self.assertRaisesRegex(PerformanceError, "16-entry bound"):
            submit_persistent_sections(
                scheduler,
                "d" * 64,
                sections,
                runtime,
                muted_roles=["synthline", "exciter"] + [f"role-{index}" for index in range(15)],
            )
        self.assertEqual(scheduler.submissions, [])


if __name__ == "__main__":
    unittest.main()
