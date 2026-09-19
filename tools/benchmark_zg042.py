"""ZG-042 host-measured workload benchmark.

Numbers describe only the executing host/configuration. The tool never changes product defaults.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import threading
import time
import tracemalloc
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "app")]

from zaaggenz_analysis import analyse_multiresolution
from zaaggenz_components import analyse_components
from zaaggenz_contracts.legacy import adapt_parameters, freeze_legacy
from zaaggenz_dsp import multiband_gain
from zaaggenz_harmony import (
    ProgressionResult, SonoritySpec, SonorityTone, VoiceSpec,
    VoicingConstraints, solve_progression,
)
from zaaggenz_jobs import JobClass, JobScheduler, SchedulerLimits, runtime_state
from zaaggenz_layers import LayerGeneratorSpec, LayerRuntimeSpec
from zaaggenz_melody import (
    make_melodic_recipe, make_phrase_plan, note_event, render_phrase, rest_event,
)
from zaaggenz_performance import (
    LayerSection, estimate_longform_bars, estimate_workload,
    recommended_section_bars, render_persistent_sections, submit_persistent_sections,
)


def _rss_bytes():
    # Linux gives a cheap process RSS sample. Other platforms still report
    # tracemalloc and the authoritative workload estimate.
    statm = Path("/proc/self/statm")
    if statm.is_file():
        try:
            pages = int(statm.read_text().split()[1])
            return pages * os.sysconf("SC_PAGE_SIZE")
        except (OSError, ValueError, IndexError):
            return None
    return None


def _measure(name, estimate, fn):
    before = _rss_bytes()
    peak_rss = [before or 0]
    stop = threading.Event()

    def sample():
        while not stop.wait(0.01):
            value = _rss_bytes()
            if value is not None:
                peak_rss[0] = max(peak_rss[0], value)

    sampler = threading.Thread(target=sample, daemon=True)
    tracemalloc.start()
    sampler.start()
    start_threads = threading.active_count()
    t0 = time.perf_counter()
    try:
        result = fn()
    finally:
        elapsed = (time.perf_counter() - t0) * 1000.0
        stop.set()
        sampler.join(1)
        _, traced_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    after = _rss_bytes()
    if after is not None:
        peak_rss[0] = max(peak_rss[0], after)
    return result, {
        "name": name,
        "elapsed_ms": elapsed,
        "estimated_live_bytes": estimate.estimated_live_bytes,
        "work_units": estimate.work_units,
        "quality": estimate.quality,
        "chunk_mode": estimate.chunk_mode,
        "tracemalloc_peak_bytes": traced_peak,
        "rss_before_bytes": before,
        "rss_after_bytes": after,
        "rss_sampled_peak_bytes": peak_rss[0] or None,
        "python_threads_start": start_threads,
        "python_threads_end": threading.active_count(),
    }


def _sonority(root, name):
    return SonoritySpec(
        name, root,
        (
            SonorityTone("root", degree_offset=0),
            SonorityTone("third", degree_offset=4),
            SonorityTone("fifth", degree_offset=7),
        ),
    )


def _harmony(tuning):
    voices = VoicingConstraints(
        (
            VoiceSpec("sub", "sub", 20, 60, 34, max_leap_cents=1600, anchor_policy="moving"),
            VoiceSpec("body", "body", 36, 90, 56, max_leap_cents=1800),
            VoiceSpec("aux", "aux", 70, 150, 102, max_leap_cents=1800),
            VoiceSpec("lead", "synthline", 105, 240, 160, max_leap_cents=1800),
        )
    )
    full = solve_progression(tuning, [_sonority(0, "home"), _sonority(5, "away")], voices)
    rows = []
    for frame in full.frames:
        rows.append(
            ProgressionResult(
                full.tuning_id, full.constraint_sha256, (frame,),
                frame.costs.voice_leading_cost,
            )
        )
    return tuple(rows)


def _long_fixture(sample_rate, bpm, bars_per_section=4):
    params = adapt_parameters(
        "synth", {"sr": sample_rate, "bpm": bpm, "beats": 1, "f0_hz": 48.0}
    )
    frozen = freeze_legacy(params).to_dict()
    tuning, time_map = frozen["tuning"], frozen["time_map"]
    beats = bars_per_section * 4
    phrase = make_phrase_plan(
        tuning["id"], [rest_event("bench-rest", "0/1", f"{beats}/1")],
        start_beat="0/1", end_beat=f"{beats}/1", bass_role="moving",
    )
    recipe = make_melodic_recipe(
        params, time_map, tuning, phrase, quality="standard", tail_mode="truncate"
    )
    progressions = _harmony(tuning)
    runtime = LayerRuntimeSpec(
        tuple(
            LayerGeneratorSpec(role, "sine", -30.0, 64, 128, 0.125)
            for role in ("body", "aux", "sub")
        )
    )

    def sections(bar_count):
        if bar_count % bars_per_section:
            raise ValueError("benchmark bar counts must be divisible by bars_per_section")
        count = bar_count // bars_per_section
        return tuple(
            LayerSection(
                recipe, progressions[index % len(progressions)], ("0/1",),
                f"{beats}/1", f"bench-s{index:04d}",
            )
            for index in range(count)
        )

    return recipe, runtime, sections


def _note_fixture(sample_rate, bpm, quality):
    params = adapt_parameters(
        "synth", {"sr": sample_rate, "bpm": bpm, "beats": 1, "f0_hz": 48.0}
    )
    frozen = freeze_legacy(params).to_dict()
    tuning, time_map = frozen["tuning"], frozen["time_map"]
    phrase = make_phrase_plan(
        tuning["id"],
        [note_event("bench-note", "0/1", "1/1", tuning["id"], 5, gain_db=-18.0)],
        start_beat="0/1", end_beat="1/1", bass_role="none",
    )
    return make_melodic_recipe(
        params, time_map, tuning, phrase, quality=quality, tail_mode="truncate"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--sample-rate", type=int, default=8000)
    parser.add_argument("--bpm", type=float, default=240.0)
    parser.add_argument("--analysis-seconds", type=float, default=0.5)
    parser.add_argument("--quality", choices=("standard", "high"), default="standard")
    args = parser.parse_args()

    if not 0.1 <= args.analysis_seconds <= 10:
        parser.error("--analysis-seconds must be in 0.1..10")

    sr = args.sample_rate
    frames = int(round(sr * args.analysis_seconds))
    t = np.arange(frames, dtype=np.float64) / sr
    source = (
        0.45 * np.sin(2 * np.pi * 110.0 * t)
        + 0.16 * np.sin(2 * np.pi * 330.0 * t)
        + 0.08 * np.sin(2 * np.pi * 990.0 * t)
    ).astype(np.float32)

    note_recipe = _note_fixture(sr, args.bpm, args.quality)
    note_frames = int(round(sr * 60.0 / args.bpm))
    measurements = []

    _, row = _measure(
        "note-render",
        estimate_workload(
            "note-render", frames=note_frames, sample_rate_hz=sr, quality=args.quality
        ),
        lambda: render_phrase(note_recipe),
    )
    measurements.append(row)

    _, row = _measure(
        "multiresolution-analysis",
        estimate_workload("multiresolution-analysis", frames=frames, sample_rate_hz=sr),
        lambda: analyse_multiresolution(source, sr),
    )
    measurements.append(row)

    _, row = _measure(
        "component-tracking",
        estimate_workload("component-tracking", frames=frames, sample_rate_hz=sr),
        lambda: analyse_components(source, sr),
    )
    measurements.append(row)

    crossovers = (60.0, min(500.0, sr * 0.12), min(1800.0, sr * 0.40))
    _, row = _measure(
        "band-processing",
        estimate_workload("band-processing", frames=frames, sample_rate_hz=sr),
        lambda: multiband_gain(source, sr, crossovers, (0.0, -6.0, 3.0, 0.0)),
    )
    measurements.append(row)

    _, runtime, section_builder = _long_fixture(sr, args.bpm)
    for bars in (4, 16, 64):
        sections = section_builder(bars)
        estimate = estimate_longform_bars(
            bars, sample_rate_hz=sr, bpm=args.bpm
        )
        _, row = _measure(
            f"persistent-layer-{bars}-bar",
            estimate,
            lambda sections=sections: render_persistent_sections(sections, runtime),
        )
        row["bars"] = bars
        row["sections"] = len(sections)
        measurements.append(row)

    # Mechanical preview responsiveness check under a real long-form BATCH workload.
    scheduler = JobScheduler(SchedulerLimits())
    try:
        background_sections = section_builder(64)
        background = submit_persistent_sections(
            scheduler, "a" * 64, background_sections, runtime
        )
        preview_estimate = estimate_workload(
            "preview", frames=note_frames, sample_rate_hz=sr, quality=args.quality
        )
        t0 = time.perf_counter()
        preview = scheduler.submit(
            JobClass.PREVIEW, "b" * 64,
            lambda ctx: render_phrase(note_recipe),
            estimated_memory_bytes=preview_estimate.estimated_live_bytes,
        )
        preview_state = scheduler.wait(preview, 30)
        preview_ms = (time.perf_counter() - t0) * 1000.0
        background_at_preview = scheduler.snapshot(background).state
        if preview_state.state != "completed":
            raise RuntimeError(f"preview under BATCH load did not complete: {preview_state.state}")
        scheduler.cancel(background)
        scheduler.wait(background, 30)
    finally:
        scheduler.shutdown(cancel=True)

    full_rate_projection = {
        "64_bar_48khz_200bpm": estimate_longform_bars(
            64, sample_rate_hz=48000, bpm=200.0
        ).metadata(),
        "recommended_section_bars_default_scheduler": recommended_section_bars(
            64, sample_rate_hz=48000, bpm=200.0
        ),
    }

    ranked = sorted(measurements, key=lambda item: item["elapsed_ms"], reverse=True)
    report = {
        "kind": "ZG042PerformanceBenchmark",
        "version": "1.0.0",
        "scope": "host-measured; not a universal realtime guarantee",
        "configuration": {
            "sample_rate_hz": sr,
            "bpm": args.bpm,
            "analysis_seconds": args.analysis_seconds,
            "note_quality": args.quality,
            "long_render_quality": "exact/no hidden reduction",
        },
        "host": {
            "platform": platform.platform(),
            "python": sys.version,
            "cpu_count": os.cpu_count(),
            "numeric_runtime": runtime_state(),
            "thread_env": {
                name: os.environ.get(name)
                for name in (
                    "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                    "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS",
                )
            },
        },
        "measurements": measurements,
        "dominant_measured_costs": [item["name"] for item in ranked[:3]],
        "preview_under_background": {
            "elapsed_ms": preview_ms,
            "preview_state": preview_state.state,
            "background_state_at_preview_completion": background_at_preview,
            "lane_contract": "long-form=BATCH/background; preview=PREVIEW/interactive",
        },
        "full_rate_planning_projection": full_rate_projection,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
