from __future__ import annotations

import platform
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "app"))

from tools import benchmark_zg042 as bench  # noqa: E402


class ProcessMemoryEvidenceTests(unittest.TestCase):
    def test_rss_growth_uses_pre_job_baseline(self):
        evidence = bench._process_rss_evidence(
            source="test-rss",
            baseline_bytes=100,
            sampled_peak_bytes=175,
            final_bytes=140,
            required_for_acceptance=True,
        )
        self.assertTrue(evidence["available"])
        self.assertEqual(evidence["baseline_bytes"], 100)
        self.assertEqual(evidence["sampled_peak_bytes"], 175)
        self.assertEqual(evidence["growth_bytes"], 75)
        self.assertEqual(
            evidence["semantics"],
            "sampled-process-rss-growth-above-pre-job-baseline",
        )

    def test_baseline_above_later_samples_cannot_create_negative_credit(self):
        evidence = bench._process_rss_evidence(
            source="test-rss",
            baseline_bytes=200,
            sampled_peak_bytes=150,
            final_bytes=180,
            required_for_acceptance=True,
        )
        self.assertEqual(evidence["sampled_peak_bytes"], 200)
        self.assertEqual(evidence["growth_bytes"], 0)

    def test_missing_process_metric_is_explicit_and_fails_when_required(self):
        evidence = bench._process_rss_evidence(
            source="test-rss",
            baseline_bytes=None,
            sampled_peak_bytes=None,
            final_bytes=None,
            required_for_acceptance=True,
        )
        self.assertFalse(evidence["available"])
        self.assertIsNone(evidence["growth_bytes"])
        acceptance = bench._memory_acceptance(100, 90, evidence)
        self.assertTrue(acceptance["tracemalloc_within_reservation"])
        self.assertIsNone(acceptance["process_rss_within_reservation"])
        self.assertFalse(acceptance["accepted"])

    def test_baseline_without_any_post_observation_is_unavailable(self):
        evidence = bench._process_rss_evidence(
            source="test-rss",
            baseline_bytes=1000,
            sampled_peak_bytes=None,
            final_bytes=None,
            required_for_acceptance=True,
        )
        self.assertFalse(evidence["available"])
        self.assertEqual(evidence["baseline_bytes"], 1000)
        self.assertEqual(evidence["sampled_peak_bytes"], 1000)
        self.assertIsNone(evidence["growth_bytes"])
        self.assertFalse(bench._memory_acceptance(100, 90, evidence)["accepted"])

    def test_process_metric_exact_boundary_and_one_over(self):
        exact = bench._process_rss_evidence(
            source="test-rss",
            baseline_bytes=1000,
            sampled_peak_bytes=1100,
            final_bytes=1080,
            required_for_acceptance=True,
        )
        acceptance = bench._memory_acceptance(100, 100, exact)
        self.assertTrue(acceptance["tracemalloc_within_reservation"])
        self.assertTrue(acceptance["process_rss_within_reservation"])
        self.assertTrue(acceptance["accepted"])

        over = bench._process_rss_evidence(
            source="test-rss",
            baseline_bytes=1000,
            sampled_peak_bytes=1101,
            final_bytes=1080,
            required_for_acceptance=True,
        )
        acceptance = bench._memory_acceptance(100, 100, over)
        self.assertFalse(acceptance["process_rss_within_reservation"])
        self.assertFalse(acceptance["accepted"])

    def test_tracemalloc_remains_an_independent_acceptance_gate(self):
        evidence = bench._process_rss_evidence(
            source="test-rss",
            baseline_bytes=1000,
            sampled_peak_bytes=1050,
            final_bytes=1040,
            required_for_acceptance=True,
        )
        acceptance = bench._memory_acceptance(100, 101, evidence)
        self.assertFalse(acceptance["tracemalloc_within_reservation"])
        self.assertTrue(acceptance["process_rss_within_reservation"])
        self.assertFalse(acceptance["accepted"])

    def test_unsupported_platform_is_explicit_not_fabricated_zero(self):
        evidence = bench._process_rss_evidence(
            source=None,
            baseline_bytes=None,
            sampled_peak_bytes=None,
            final_bytes=None,
            required_for_acceptance=False,
        )
        acceptance = bench._memory_acceptance(100, 90, evidence)
        self.assertFalse(evidence["available"])
        self.assertIsNone(evidence["growth_bytes"])
        self.assertIsNone(acceptance["process_rss_within_reservation"])
        self.assertFalse(acceptance["process_rss_required_for_acceptance"])
        self.assertTrue(acceptance["accepted"])

    def test_measurement_metadata_separates_python_and_process_memory(self):
        estimate = SimpleNamespace(
            estimated_live_bytes=4096,
            work_units=1,
            quality="exact",
            chunk_mode="test",
        )
        _, row = bench._measure(
            "memory-evidence-test",
            estimate,
            lambda: "ok",
            rss_reader=lambda: 123456,
            rss_source="test-rss",
            rss_required=True,
        )
        self.assertIn("tracemalloc_peak_bytes", row)
        self.assertIn("process_rss", row)
        self.assertEqual(row["process_rss"]["source"], "test-rss")
        self.assertEqual(row["process_rss"]["baseline_bytes"], 123456)
        self.assertEqual(row["process_rss"]["growth_bytes"], 0)

    def test_supported_ci_platform_has_real_process_rss_reader(self):
        if platform.system() not in bench.PROCESS_RSS_REQUIRED_SYSTEMS:
            self.skipTest("process RSS acceptance is required only on Linux/Windows")
        self.assertIsNotNone(bench._process_rss_source())
        value = bench._rss_bytes()
        self.assertIsInstance(value, int)
        self.assertGreater(value, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
