from __future__ import annotations

import threading
import unittest

import numpy as np

from zaaggenz_analysis import STFTSpec, stft
from zaaggenz_contracts.legacy import adapt_parameters, freeze_legacy
from zaaggenz_dsp import multiband_gain
from zaaggenz_harmony import (
    ProgressionResult, SonoritySpec, SonorityTone, VoiceSpec,
    VoicingConstraints, solve_progression,
)
from zaaggenz_jobs import JobClass, JobScheduler, SchedulerLimits
from zaaggenz_layers import LayerGeneratorSpec, LayerRuntimeSpec, render_coordinated_layers
from zaaggenz_melody import make_melodic_recipe, make_phrase_plan, rest_event
from zaaggenz_performance import (
    LayerSection, PerformanceError, render_persistent_sections,
    require_chunk_count, submit_persistent_sections,
)


def _sonority(root, name):
    return SonoritySpec(
        name, root,
        (
            SonorityTone("root", degree_offset=0),
            SonorityTone("third", degree_offset=4),
            SonorityTone("fifth", degree_offset=7),
        ),
    )


def _fixture():
    params = adapt_parameters(
        "synth", {"sr": 8000, "bpm": 240.0, "beats": 1, "f0_hz": 48.0}
    )
    frozen = freeze_legacy(params).to_dict()
    tuning, time_map = frozen["tuning"], frozen["time_map"]

    whole_phrase = make_phrase_plan(
        tuning["id"], [rest_event("rest", "0/1", "1/1")],
        start_beat="0/1", end_beat="1/1", bass_role="moving",
    )
    half_phrase = make_phrase_plan(
        tuning["id"], [rest_event("rest", "0/1", "1/2")],
        start_beat="0/1", end_beat="1/2", bass_role="moving",
    )
    whole_recipe = make_melodic_recipe(
        params, time_map, tuning, whole_phrase,
        quality="standard", tail_mode="truncate",
    )
    half_recipe = make_melodic_recipe(
        params, time_map, tuning, half_phrase,
        quality="standard", tail_mode="truncate",
    )
    voices = VoicingConstraints(
        (
            VoiceSpec("sub", "sub", 20, 60, 34, max_leap_cents=1600, anchor_policy="moving"),
            VoiceSpec("body", "body", 36, 90, 56, max_leap_cents=1800),
            VoiceSpec("aux", "aux", 70, 150, 102, max_leap_cents=1800),
            VoiceSpec("lead", "synthline", 105, 240, 160, max_leap_cents=1800),
        )
    )
    full = solve_progression(
        tuning, [_sonority(0, "a"), _sonority(5, "b")], voices
    )
    first = ProgressionResult(
        full.tuning_id, full.constraint_sha256, (full.frames[0],),
        full.frames[0].costs.voice_leading_cost,
    )
    second = ProgressionResult(
        full.tuning_id, full.constraint_sha256, (full.frames[1],),
        full.frames[1].costs.voice_leading_cost,
    )
    runtime = LayerRuntimeSpec(
        tuple(
            LayerGeneratorSpec(role, "sine", -30.0, 64, 128, 0.125)
            for role in ("body", "aux", "sub")
        )
    )
    sections = (
        LayerSection(half_recipe, first, ("0/1",), "1/4", "perf-first"),
        LayerSection(half_recipe, second, ("0/1",), "1/2", "perf-second"),
    )
    return whole_recipe, full, runtime, sections


class ChunkEquivalenceTests(unittest.TestCase):
    def test_persistent_sections_match_whole_render_through_glide_release_and_phase_state(self):
        recipe, progression, runtime, sections = _fixture()
        whole = render_coordinated_layers(
            recipe, progression, ("0/1", "1/2"), ("1/4", "1/2"), runtime,
            muted_roles=("synthline", "exciter"),
        )
        chunked = render_persistent_sections(sections, runtime)

        np.testing.assert_allclose(chunked.mix, whole.mix, rtol=0, atol=3e-7)
        for name in ("body", "aux", "sub", "pre_master"):
            np.testing.assert_allclose(
                chunked.stems[name], whole.stems[name], rtol=0, atol=3e-7
            )
        self.assertEqual(chunked.state.to_dict(), whole.state.to_dict())

    def test_source_phrase_chunking_is_not_silently_claimed_equivalent(self):
        _, _, runtime, sections = _fixture()
        with self.assertRaises(PerformanceError):
            render_persistent_sections(
                sections, runtime, muted_roles=("body",)
            )

    def test_zero_phase_crossovers_prove_naive_chunking_is_not_equivalent(self):
        sr = 8000
        t = np.arange(4096, dtype=np.float64) / sr
        source = (
            0.5 * np.sin(2 * np.pi * 240 * t)
            + 0.2 * np.sin(2 * np.pi * 1300 * t)
        )
        crossovers = (60.0, 500.0, 1800.0)
        gains = (0.0, -9.0, 3.0, 0.0)
        whole = multiband_gain(source, sr, crossovers, gains)
        halves = np.concatenate(
            [
                multiband_gain(source[:2048], sr, crossovers, gains),
                multiband_gain(source[2048:], sr, crossovers, gains),
            ]
        )
        self.assertGreater(float(np.max(np.abs(whole - halves))), 1e-6)
        with self.assertRaises(PerformanceError):
            require_chunk_count("band-processing", 2)

    def test_long_window_stft_proves_naive_chunks_change_support_cardinality(self):
        sr = 8000
        t = np.arange(4096, dtype=np.float64) / sr
        source = np.sin(2 * np.pi * 330 * t)
        spec = STFTSpec(1024, 256, 1024, role="observation")
        whole = stft(source, sr, spec)
        left = stft(source[:2048], sr, spec)
        right = stft(source[2048:], sr, spec)
        self.assertNotEqual(len(whole.anchors), len(left.anchors) + len(right.anchors))
        with self.assertRaises(PerformanceError):
            require_chunk_count("multiresolution-analysis", 2)

    def test_longform_wrapper_uses_background_lane_and_preview_lane_remains_available(self):
        _, _, runtime, sections = _fixture()
        scheduler = JobScheduler(
            SchedulerLimits(
                interactive_workers=1,
                background_workers=1,
                max_memory_bytes=256 * 1024 * 1024,
                interactive_memory_reserve_bytes=64 * 1024 * 1024,
                max_job_memory_bytes=192 * 1024 * 1024,
            )
        )
        try:
            job = submit_persistent_sections(
                scheduler, "a" * 64, sections * 8, runtime
            )
            self.assertEqual(scheduler.snapshot(job).job_class, "batch")

            # A separate deliberately held background job cannot consume the interactive lane.
            started = threading.Event()
            release = threading.Event()

            def hold(ctx):
                started.set()
                release.wait(2)
                ctx.check_cancelled()
                return "done"

            blocker = scheduler.submit(
                JobClass.BATCH, "b" * 64, hold, estimated_memory_bytes=1
            )
            # The longform job may run first; wait until the held job eventually owns the
            # sole background worker, then prove interactive preview admission/execution.
            scheduler.wait(job, 5)
            started.wait(5)
            preview = scheduler.submit(
                JobClass.PREVIEW, "c" * 64, lambda ctx: "preview",
                estimated_memory_bytes=1024,
            )
            snap = scheduler.wait(preview, 2)
            self.assertEqual(snap.state, "completed")
            self.assertEqual(scheduler.result(preview), "preview")
            release.set()
            scheduler.wait(blocker, 2)
        finally:
            scheduler.shutdown(cancel=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
