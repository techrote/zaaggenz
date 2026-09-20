"""ZG-042 host-measured workload benchmark.

Numbers describe only the executing host/configuration. The tool never changes product defaults.
"""
from __future__ import annotations

import argparse
import ctypes
import gc
import json
import os
import platform
import sys
import threading
import time
import tracemalloc
from ctypes import wintypes
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
    LayerSection, admission_memory, estimate_longform_bars,
    estimate_persistent_sequence, estimate_workload, recommended_section_bars,
    render_persistent_sections, submit_persistent_sections,
)


PROCESS_RSS_REQUIRED_SYSTEMS = frozenset({"Linux", "Windows"})
RSS_SAMPLE_INTERVAL_SECONDS = 0.01


def _process_rss_source():
    system = platform.system()
    if system == "Linux":
        return "linux-proc-self-statm"
    if system == "Windows":
        return "windows-psapi-working-set"
    return None


def _linux_rss_bytes():
    statm = Path("/proc/self/statm")
    if not statm.is_file():
        return None
    try:
        pages = int(statm.read_text().split()[1])
        return pages * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, IndexError):
        return None


def _windows_rss_bytes():
    if platform.system() != "Windows":
        return None

    class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
            ("PrivateUsage", ctypes.c_size_t),
        ]

    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        get_current_process = kernel32.GetCurrentProcess
        get_current_process.restype = wintypes.HANDLE
        get_process_memory_info = psapi.GetProcessMemoryInfo
        get_process_memory_info.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(PROCESS_MEMORY_COUNTERS_EX),
            wintypes.DWORD,
        ]
        get_process_memory_info.restype = wintypes.BOOL
        counters = PROCESS_MEMORY_COUNTERS_EX()
        counters.cb = ctypes.sizeof(counters)
        if not get_process_memory_info(
            get_current_process(), ctypes.byref(counters), counters.cb
        ):
            return None
        return int(counters.WorkingSetSize)
    except (AttributeError, OSError, ValueError):
        return None


def _rss_bytes():
    system = platform.system()
    if system == "Linux":
        return _linux_rss_bytes()
    if system == "Windows":
        return _windows_rss_bytes()
    return None


def _process_rss_evidence(
    *,
    source,
    baseline_bytes,
    sampled_peak_bytes,
    final_bytes,
    required_for_acceptance,
):
    valid_baseline = (
        isinstance(baseline_bytes, int)
        and not isinstance(baseline_bytes, bool)
        and baseline_bytes >= 0
    )
    post_values = [
        value
        for value in (sampled_peak_bytes, final_bytes)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
    ]
    if not valid_baseline or not post_values:
        visible_values = ([baseline_bytes] if valid_baseline else []) + post_values
        peak = max(visible_values) if visible_values else None
        return {
            "source": source,
            "available": False,
            "required_for_acceptance": bool(required_for_acceptance),
            "baseline_bytes": baseline_bytes if valid_baseline else None,
            "sampled_peak_bytes": peak,
            "final_bytes": (
                final_bytes
                if isinstance(final_bytes, int) and not isinstance(final_bytes, bool)
                else None
            ),
            "growth_bytes": None,
            "sample_interval_seconds": RSS_SAMPLE_INTERVAL_SECONDS,
            "semantics": "sampled-process-rss-growth-above-pre-job-baseline",
        }

    peak = max([baseline_bytes, *post_values])
    growth = max(0, peak - baseline_bytes)
    return {
        "source": source,
        "available": True,
        "required_for_acceptance": bool(required_for_acceptance),
        "baseline_bytes": baseline_bytes,
        "sampled_peak_bytes": peak,
        "final_bytes": final_bytes if isinstance(final_bytes, int) else None,
        "growth_bytes": growth,
        "sample_interval_seconds": RSS_SAMPLE_INTERVAL_SECONDS,
        "semantics": "sampled-process-rss-growth-above-pre-job-baseline",
    }


def _memory_acceptance(reserved_memory_bytes, tracemalloc_peak_bytes, process_rss):
    if type(reserved_memory_bytes) is not int or reserved_memory_bytes <= 0:
        raise ValueError("reserved_memory_bytes must be a positive integer")
    if type(tracemalloc_peak_bytes) is not int or tracemalloc_peak_bytes < 0:
        raise ValueError("tracemalloc_peak_bytes must be a non-negative integer")

    traced_ok = tracemalloc_peak_bytes <= reserved_memory_bytes
    required = bool(process_rss.get("required_for_acceptance"))
    growth = process_rss.get("growth_bytes")
    process_ok = (
        growth <= reserved_memory_bytes
        if isinstance(growth, int) and not isinstance(growth, bool) and growth >= 0
        else None
    )
    accepted = traced_ok and (process_ok is True if required else True)
    return {
        "tracemalloc_within_reservation": traced_ok,
        "process_rss_within_reservation": process_ok,
        "process_rss_required_for_acceptance": required,
        "accepted": accepted,
    }


def _measure(
    name,
    estimate,
    fn,
    *,
    rss_reader=None,
    rss_source=None,
    rss_required=None,
):
    if rss_reader is None:
        rss_reader = _rss_bytes
    if rss_source is None:
        rss_source = _process_rss_source()
    if rss_required is None:
        rss_required = platform.system() in PROCESS_RSS_REQUIRED_SYSTEMS

    # Reduce unreachable Python objects before taking the process baseline, then
    # start the measurement apparatus before the baseline so the sampler/thread
    # itself is not charged to the workload's RSS growth.
    gc.collect()
    peak_rss = [None]
    stop = threading.Event()
    ready = threading.Event()

    def sample():
        ready.set()
        while not stop.wait(RSS_SAMPLE_INTERVAL_SECONDS):
            value = rss_reader()
            if value is not None:
                peak_rss[0] = value if peak_rss[0] is None else max(peak_rss[0], value)

    sampler = threading.Thread(target=sample, daemon=True)
    tracemalloc.start()
    sampler.start()
    if not ready.wait(1):
        raise RuntimeError("RSS sampler did not start")
    before = rss_reader()
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
    after = rss_reader()
    if after is not None:
        peak_rss[0] = after if peak_rss[0] is None else max(peak_rss[0], after)
    process_rss = _process_rss_evidence(
        source=rss_source,
        baseline_bytes=before,
        sampled_peak_bytes=peak_rss[0],
        final_bytes=after,
        required_for_acceptance=rss_required,
    )
    return result, {
        "name": name,
        "elapsed_ms": elapsed,
        "estimated_live_bytes": estimate.estimated_live_bytes,
        "work_units": estimate.work_units,
        "quality": estimate.quality,
        "chunk_mode": estimate.chunk_mode,
        "tracemalloc_peak_bytes": traced_peak,
        "rss_before_bytes": process_rss["baseline_bytes"],
        "rss_after_bytes": process_rss["final_bytes"],
        "rss_sampled_peak_bytes": process_rss["sampled_peak_bytes"],
        "process_rss": process_rss,
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


def _runtime_spec():
    return LayerRuntimeSpec(
        tuple(
            LayerGeneratorSpec(role, "sine", -30.0, 64, 128, 0.125)
            for role in ("body", "aux", "sub")
        )
    )


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
    runtime = _runtime_spec()

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


def _planned_long_sections(sample_rate, bpm, bar_plan):
    params = adapt_parameters(
        "synth", {"sr": sample_rate, "bpm": bpm, "beats": 1, "f0_hz": 48.0}
    )
    frozen = freeze_legacy(params).to_dict()
    tuning, time_map = frozen["tuning"], frozen["time_map"]
    progressions = _harmony(tuning)
    sections = []
    for index, bars in enumerate(bar_plan):
        beats = bars * 4
        phrase = make_phrase_plan(
            tuning["id"],
            [rest_event(f"full-rate-rest-{index}", "0/1", f"{beats}/1")],
            start_beat="0/1", end_beat=f"{beats}/1", bass_role="moving",
        )
        recipe = make_melodic_recipe(
            params, time_map, tuning, phrase, quality="standard", tail_mode="truncate"
        )
        sections.append(
            LayerSection(
                recipe, progressions[index % len(progressions)], ("0/1",),
                f"{beats}/1", f"full-rate-s{index:04d}",
            )
        )
    return _runtime_spec(), tuple(sections)


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


def _bar_plan(total_bars, section_bars):
    plan = []
    remaining = total_bars
    while remaining:
        current = min(section_bars, remaining)
        plan.append(current)
        remaining -= current
    return tuple(plan)


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

    measured, row = _measure(
        "note-render",
        estimate_workload(
            "note-render", frames=note_frames, sample_rate_hz=sr, quality=args.quality
        ),
        lambda: render_phrase(note_recipe),
    )
    del measured
    measurements.append(row)

    measured, row = _measure(
        "multiresolution-analysis",
        estimate_workload("multiresolution-analysis", frames=frames, sample_rate_hz=sr),
        lambda: analyse_multiresolution(source, sr),
    )
    del measured
    measurements.append(row)

    measured, row = _measure(
        "component-tracking",
        estimate_workload("component-tracking", frames=frames, sample_rate_hz=sr),
        lambda: analyse_components(source, sr),
    )
    del measured
    measurements.append(row)

    crossovers = (60.0, min(500.0, sr * 0.12), min(1800.0, sr * 0.40))
    measured, row = _measure(
        "band-processing",
        estimate_workload("band-processing", frames=frames, sample_rate_hz=sr),
        lambda: multiband_gain(source, sr, crossovers, (0.0, -6.0, 3.0, 0.0)),
    )
    del measured
    measurements.append(row)

    _, runtime, section_builder = _long_fixture(sr, args.bpm)
    for bars in (4, 16, 64):
        sections = section_builder(bars)
        estimate = estimate_persistent_sequence(sections)
        measured, row = _measure(
            f"persistent-layer-{bars}-bar",
            estimate,
            lambda sections=sections: render_persistent_sections(sections, runtime),
        )
        del measured
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

    # The advertised product-scale plan is now executed, not merely projected. Acceptance
    # requires its Python traced peak to fit the exact reservation used by scheduler admission.
    default_limits = SchedulerLimits()
    section_bars = recommended_section_bars(
        64, sample_rate_hz=48000, bpm=200.0, limits=default_limits
    )
    plan = _bar_plan(64, section_bars)
    full_runtime, full_sections = _planned_long_sections(48000, 200.0, plan)
    full_estimate = estimate_persistent_sequence(full_sections)
    full_reserved = admission_memory(
        full_estimate, job_class=JobClass.BATCH, limits=default_limits
    )
    full_result, full_measurement = _measure(
        "persistent-layer-64-bar-full-rate-accepted-plan",
        full_estimate,
        lambda: render_persistent_sections(full_sections, full_runtime),
    )
    del full_result
    full_measurement["bars"] = 64
    full_measurement["section_plan_bars"] = list(plan)
    full_measurement["reserved_memory_bytes"] = full_reserved
    acceptance = _memory_acceptance(
        full_reserved,
        full_measurement["tracemalloc_peak_bytes"],
        full_measurement["process_rss"],
    )
    full_measurement.update(acceptance)
    if not acceptance["accepted"]:
        raise RuntimeError(
            "full-rate accepted plan exceeded or could not prove its authoritative "
            "memory reservation: "
            + json.dumps(
                {
                    "reserved_memory_bytes": full_reserved,
                    "tracemalloc_peak_bytes": full_measurement["tracemalloc_peak_bytes"],
                    "process_rss": full_measurement["process_rss"],
                    "acceptance": acceptance,
                },
                sort_keys=True,
            )
        )

    full_rate_evidence = {
        "one_job_64_bar_projection": estimate_longform_bars(
            64, sample_rate_hz=48000, bpm=200.0
        ).metadata(),
        "recommended_section_bars_default_scheduler": section_bars,
        "accepted_section_plan_bars": list(plan),
        "sequence_estimate": full_estimate.metadata(),
        "admission_reserved_bytes": full_reserved,
        "measurement": full_measurement,
    }

    ranked = sorted(measurements, key=lambda item: item["elapsed_ms"], reverse=True)
    report = {
        "kind": "ZG042PerformanceBenchmark",
        "version": "1.2.0",
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
        "full_rate_memory_evidence": full_rate_evidence,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
