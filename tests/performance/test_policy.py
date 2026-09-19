from __future__ import annotations

import math
import unittest

from zaaggenz_jobs import JobClass, SchedulerLimits
from zaaggenz_performance import (
    PerformanceError,
    admission_memory,
    bar_frame_count,
    chunk_policy,
    estimate_longform_bars,
    estimate_workload,
    persistent_sequence_memory_bound,
    recommended_section_bars,
    require_chunk_count,
)


class WorkloadPolicyTests(unittest.TestCase):
    def test_note_quality_cost_is_explicit_and_never_hidden(self):
        standard = estimate_workload(
            "note-render", frames=48000, sample_rate_hz=48000, quality="standard"
        )
        high = estimate_workload(
            "note-render", frames=48000, sample_rate_hz=48000, quality="high"
        )
        self.assertGreater(high.work_units, standard.work_units)
        self.assertGreater(high.estimated_live_bytes, standard.estimated_live_bytes)
        self.assertIn("fft=2048", standard.assumptions[0])
        self.assertIn("fft=4096", high.assumptions[0])
        with self.assertRaises(PerformanceError):
            estimate_workload(
                "band-processing", frames=48000, sample_rate_hz=48000, quality="standard"
            )

    def test_multiresolution_component_band_and_layer_estimates_are_bounded_metadata(self):
        estimates = [
            estimate_workload("multiresolution-analysis", frames=12000, sample_rate_hz=12000),
            estimate_workload("component-tracking", frames=12000, sample_rate_hz=12000),
            estimate_workload("band-processing", frames=12000, sample_rate_hz=12000),
            estimate_workload("persistent-layer-render", frames=12000, sample_rate_hz=12000),
        ]
        for estimate in estimates:
            with self.subTest(workload=estimate.workload):
                meta = estimate.metadata()
                self.assertEqual(meta["policy_id"], "zaaggenz.workload-cost")
                self.assertEqual(meta["version"], "1.1.0")
                self.assertGreater(meta["estimated_live_bytes"], 0)
                self.assertGreater(meta["work_units"], 0)
                self.assertEqual(meta["numeric_threads"], 1)

    def test_preview_reservation_fits_the_reserved_interactive_lane(self):
        limits = SchedulerLimits()
        estimate = estimate_workload(
            "preview", frames=48000, sample_rate_hz=48000, quality="standard"
        )
        reserved = admission_memory(
            estimate, job_class=JobClass.PREVIEW, limits=limits
        )
        self.assertLessEqual(reserved, limits.max_preview_memory_bytes)
        self.assertLessEqual(reserved, limits.interactive_memory_reserve_bytes)

    def test_64_bar_full_rate_plan_uses_authoritative_sequence_bound(self):
        limits = SchedulerLimits()
        full = estimate_longform_bars(
            64, sample_rate_hz=48000, bpm=200.0
        )
        self.assertEqual(
            full.frames, bar_frame_count(64, 48000, 200.0)
        )
        with self.assertRaises(PerformanceError):
            admission_memory(full, job_class=JobClass.BATCH, limits=limits)

        section_bars = recommended_section_bars(
            64, sample_rate_hz=48000, bpm=200.0, limits=limits
        )
        self.assertEqual(section_bars, 20)
        peak_frames = bar_frame_count(section_bars, 48000, 200.0)
        section_count = int(math.ceil(64 / section_bars))
        required = persistent_sequence_memory_bound(
            full.frames,
            peak_frames,
            sample_rate_hz=48000,
            section_count=section_count,
            retained_output_stems=5,
        )
        hard = min(
            limits.max_job_memory_bytes,
            limits.max_memory_bytes - limits.interactive_memory_reserve_bytes,
        )
        self.assertLessEqual(required, hard)

        next_candidate = section_bars + 1
        rejected = persistent_sequence_memory_bound(
            full.frames,
            bar_frame_count(next_candidate, 48000, 200.0),
            sample_rate_hz=48000,
            section_count=int(math.ceil(64 / next_candidate)),
            retained_output_stems=5,
        )
        self.assertGreater(rejected, hard)

    def test_sequence_bound_includes_retained_output_and_orchestration_headroom(self):
        total = bar_frame_count(16, 12000, 240.0)
        peak = bar_frame_count(4, 12000, 240.0)
        bound = persistent_sequence_memory_bound(
            total, peak, sample_rate_hz=12000, section_count=4
        )
        raw_components = (
            estimate_workload(
                "persistent-layer-render", frames=peak, sample_rate_hz=12000
            ).estimated_live_bytes
            + total * 5 * 4
        )
        self.assertGreaterEqual(bound - raw_components, 36 * 1024 * 1024)

    def test_4_16_64_bar_estimates_scale_without_changing_quality(self):
        estimates = [
            estimate_longform_bars(bars, sample_rate_hz=12000, bpm=240.0)
            for bars in (4, 16, 64)
        ]
        self.assertEqual([e.quality for e in estimates], ["exact"] * 3)
        self.assertEqual([e.frames for e in estimates], [48000, 192000, 768000])
        self.assertTrue(
            estimates[0].estimated_live_bytes
            < estimates[1].estimated_live_bytes
            < estimates[2].estimated_live_bytes
        )

    def test_unsafe_arbitrary_chunking_fails_closed(self):
        for workload in (
            "preview",
            "note-render",
            "multiresolution-analysis",
            "component-tracking",
            "band-processing",
        ):
            with self.subTest(workload=workload), self.assertRaises(PerformanceError):
                require_chunk_count(workload, 2)
        policy = require_chunk_count("persistent-layer-render", 64)
        self.assertTrue(policy.exact_chunking_supported)
        self.assertEqual(policy.mode, "explicit-section-state")
        self.assertIn("unserialized", policy.reason)
        self.assertEqual(
            chunk_policy("band-processing").mode, "whole-signal-zero-phase"
        )

    def test_invalid_dimensions_and_underdeclared_memory_fail_before_work(self):
        with self.assertRaises(PerformanceError):
            estimate_workload(
                "persistent-layer-render", frames=-1, sample_rate_hz=12000
            )
        estimate = estimate_workload(
            "band-processing", frames=12000, sample_rate_hz=12000
        )
        with self.assertRaises(PerformanceError):
            admission_memory(
                estimate, job_class=JobClass.BATCH,
                requested_bytes=estimate.estimated_live_bytes - 1,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
