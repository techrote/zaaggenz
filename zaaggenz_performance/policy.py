from __future__ import annotations

from dataclasses import dataclass
import math

from zaaggenz_analysis import estimate_stft_resources, resolution_specs, STFTSpec
from zaaggenz_components import ComponentTrackerSpec
from zaaggenz_jobs import JobClass, SchedulerLimits
from zaaggenz_jobs.memory import authoritative_memory_reservation

POLICY_ID = "zaaggenz.workload-cost"
POLICY_VERSION = "1.0.0"
MAX_SOURCE_FRAMES = 192000 * 60 * 60  # one hour at the highest accepted sample rate


class PerformanceError(ValueError):
    pass


@dataclass(frozen=True)
class WorkloadEstimate:
    workload: str
    sample_rate_hz: int
    frames: int
    channels: int
    quality: str
    estimated_live_bytes: int
    work_units: int
    numeric_threads: int
    chunk_mode: str
    assumptions: tuple[str, ...]

    def __post_init__(self):
        if type(self.estimated_live_bytes) is not int or self.estimated_live_bytes <= 0:
            raise PerformanceError("estimated_live_bytes must be a positive integer")
        if type(self.work_units) is not int or self.work_units < 0:
            raise PerformanceError("work_units must be a non-negative integer")
        object.__setattr__(self, "assumptions", tuple(self.assumptions))

    def metadata(self):
        return {
            "policy_id": POLICY_ID,
            "version": POLICY_VERSION,
            "workload": self.workload,
            "sample_rate_hz": self.sample_rate_hz,
            "frames": self.frames,
            "channels": self.channels,
            "quality": self.quality,
            "estimated_live_bytes": self.estimated_live_bytes,
            "work_units": self.work_units,
            "numeric_threads": self.numeric_threads,
            "chunk_mode": self.chunk_mode,
            "assumptions": list(self.assumptions),
        }


@dataclass(frozen=True)
class ChunkPolicy:
    workload: str
    mode: str
    exact_chunking_supported: bool
    boundary: str
    reason: str

    def metadata(self):
        return {
            "workload": self.workload,
            "mode": self.mode,
            "exact_chunking_supported": self.exact_chunking_supported,
            "boundary": self.boundary,
            "reason": self.reason,
        }


def _dims(frames, sample_rate_hz, channels):
    if type(frames) is not int or type(frames) is bool or not 0 <= frames <= MAX_SOURCE_FRAMES:
        raise PerformanceError("frames outside bounded long-workload domain")
    if type(sample_rate_hz) is not int or type(sample_rate_hz) is bool or not 8000 <= sample_rate_hz <= 192000:
        raise PerformanceError("sample_rate_hz outside 8000..192000")
    if type(channels) is not int or type(channels) is bool or channels not in (1, 2):
        raise PerformanceError("mono/stereo channels required")
    return frames, sample_rate_hz, channels


def chunk_policy(workload):
    policies = {
        "preview": ChunkPolicy(
            "preview", "whole-phrase", False, "phrase",
            "preview is bounded separately and must not change render quality at arbitrary sample boundaries",
        ),
        "note-render": ChunkPolicy(
            "note-render", "whole-phrase", False, "phrase",
            "source-derived phase-vocoder/glide/tail state is phrase-owned; arbitrary sample chunking is not equivalent",
        ),
        "multiresolution-analysis": ChunkPolicy(
            "multiresolution-analysis", "whole-signal-window-support", False, "analysis-window",
            "STFT padding/support and spectral-flux history cross arbitrary chunk boundaries",
        ),
        "component-tracking": ChunkPolicy(
            "component-tracking", "whole-signal-window-support", False, "analysis-window",
            "track association, fitted phase history and transient analysis cross arbitrary chunk boundaries",
        ),
        "band-processing": ChunkPolicy(
            "band-processing", "whole-signal-zero-phase", False, "filter-support",
            "sosfiltfilt crossovers are offline zero-phase and naive chunk edges change the transfer result",
        ),
        "persistent-layer-render": ChunkPolicy(
            "persistent-layer-render", "explicit-section-state", True, "ZG-029 section boundary",
            "BODY/AUX/SUB oscillator, glide and tail state can continue exactly only through explicit LayerSectionTransition state",
        ),
    }
    try:
        return policies[workload]
    except KeyError as exc:
        raise PerformanceError(f"unknown workload: {workload!r}") from exc


def require_chunk_count(workload, chunk_count):
    if type(chunk_count) is not int or type(chunk_count) is bool or chunk_count < 1:
        raise PerformanceError("chunk_count must be a positive integer")
    policy = chunk_policy(workload)
    if chunk_count > 1 and not policy.exact_chunking_supported:
        raise PerformanceError(
            f"{workload} does not permit arbitrary chunking under {policy.mode}; {policy.reason}"
        )
    return policy


def _note_estimate(frames, sample_rate_hz, channels, quality, preview=False):
    _dims(frames, sample_rate_hz, channels)
    if quality not in ("standard", "high"):
        raise PerformanceError("note render quality must be standard or high")
    fft = 2048 if quality == "standard" else 4096
    # Source f32/f64 views, synthline/exciter/pre-master/mix, pitch-warp temporaries,
    # overlap/phase-vocoder work and one immutable output/artifact copy.
    per_frame = channels * (4 * 6 + 8 * 5)
    fixed = 8 * 1024 * 1024 + fft * channels * 128
    estimate = per_frame * max(1, frames) + fixed
    if preview:
        estimate += frames * channels * 4
    work = max(1, frames) * fft
    return WorkloadEstimate(
        "preview" if preview else "note-render",
        sample_rate_hz, frames, channels, quality, int(estimate), int(work), 1,
        chunk_policy("preview" if preview else "note-render").mode,
        (
            f"phase-vocoder fft={fft}",
            "quality changes only the already-declared melodic FFT tier",
            "no hidden resampling or accelerator assumption",
        ),
    )


def _multiresolution_estimate(frames, sample_rate_hz, channels):
    _dims(frames, sample_rate_hz, channels)
    specs = resolution_specs(sample_rate_hz)
    rows = []
    for name in ("short", "medium", "long"):
        est = estimate_stft_resources(frames, channels, specs[name])
        # FeatureFrame Python/object metadata is bounded here conservatively; STFTs execute sequentially.
        feature_bytes = est.frame_count * 384
        rows.append((name, est, est.estimated_live_bytes + feature_bytes))
    source = max(1, frames) * channels * 8
    peak = source + max(value for _, _, value in rows)
    work = sum(est.fft_point_count for _, est, _ in rows)
    return WorkloadEstimate(
        "multiresolution-analysis", sample_rate_hz, frames, channels, "exact",
        int(peak), int(work), 1, chunk_policy("multiresolution-analysis").mode,
        tuple(
            f"{name}:window={est.window_samples},hop={est.hop_samples},fft={est.fft_samples}"
            for name, est, _ in rows
        ) + ("short/medium/long STFTs execute sequentially",),
    )


def _tracker_window(sample_rate_hz, spec):
    n = int(2 ** round(math.log2(max(32, sample_rate_hz * spec.window_seconds))))
    hop = max(1, n // spec.hop_fraction)
    nfft = n * spec.fft_factor
    return n, hop, nfft


def _component_estimate(frames, sample_rate_hz, channels, tracker_spec):
    _dims(frames, sample_rate_hz, channels)
    if tracker_spec is None:
        tracker_spec = ComponentTrackerSpec()
    if not isinstance(tracker_spec, ComponentTrackerSpec):
        raise PerformanceError("ComponentTrackerSpec required")
    n, hop, nfft = _tracker_window(sample_rate_hz, tracker_spec)
    tracker_stft = estimate_stft_resources(frames, channels, STFTSpec(n, hop, nfft, role="observation"))
    multires = _multiresolution_estimate(frames, sample_rate_hz, channels)
    frame_count = tracker_stft.frame_count
    # Concrete source + sinusoidal/transient/residual + reconstruction + mask,
    # plus bounded candidate/track metadata and the largest analysis stage.
    arrays = max(1, frames) * channels * 8 * 6 + max(1, frames) * 8
    candidates = frame_count * tracker_spec.max_tracks * 320
    peak_analysis = max(tracker_stft.estimated_live_bytes, multires.estimated_live_bytes)
    peak = arrays + candidates + peak_analysis
    work = tracker_stft.fft_point_count + multires.work_units + frame_count * tracker_spec.max_tracks * n
    return WorkloadEstimate(
        "component-tracking", sample_rate_hz, frames, channels, "exact",
        int(peak), int(work), 1, chunk_policy("component-tracking").mode,
        (
            f"tracker window={n},hop={hop},fft={nfft},max_tracks={tracker_spec.max_tracks}",
            "candidate fitting bound includes max_tracks for every tracker frame",
            "source/component arrays remain finite float64/f32-bound evidence",
        ),
    )


def _band_estimate(frames, sample_rate_hz, channels):
    _dims(frames, sample_rate_hz, channels)
    # Source, three cumulative low-passes, four bands, changed/raw/routed delta,
    # output and filter work arrays. Zero effects may use less; admission uses the active bound.
    peak = max(1, frames) * channels * 8 * 14 + 2 * 1024 * 1024
    work = max(1, frames) * channels * 14
    return WorkloadEstimate(
        "band-processing", sample_rate_hz, frames, channels, "exact",
        int(peak), int(work), 1, chunk_policy("band-processing").mode,
        (
            "offline Butterworth sosfiltfilt effect-delta routing",
            "whole-signal zero-phase boundary retained",
            "no quality tier or hidden crossover simplification",
        ),
    )


def _layer_estimate(frames, sample_rate_hz, channels):
    _dims(frames, sample_rate_hz, channels)
    if channels != 1:
        raise PerformanceError("ZG-029 persistent layer runtime is mono in v1")
    # Raw source/source bus, three persistent float64 roles, pre-master/mix,
    # float32 retained stems, frequency/glide working vectors and diagnostics headroom.
    peak = max(1, frames) * (8 * 12 + 4 * 8) + 8 * 1024 * 1024
    work = max(1, frames) * 4
    return WorkloadEstimate(
        "persistent-layer-render", sample_rate_hz, frames, channels, "exact",
        int(peak), int(work), 1, chunk_policy("persistent-layer-render").mode,
        (
            "one source bus plus BODY/AUX/SUB persistent roles",
            "section continuation uses ZG-029 explicit state; no oscillator reset is inferred",
            "no quality reduction or accelerator assumption",
        ),
    )


def estimate_workload(workload, *, frames, sample_rate_hz, channels=1, quality="exact", tracker_spec=None):
    if workload == "preview":
        return _note_estimate(frames, sample_rate_hz, channels, "standard" if quality == "exact" else quality, True)
    if workload == "note-render":
        return _note_estimate(frames, sample_rate_hz, channels, "standard" if quality == "exact" else quality, False)
    if quality != "exact":
        raise PerformanceError(f"{workload} has no quality tier; use quality='exact'")
    if workload == "multiresolution-analysis":
        return _multiresolution_estimate(frames, sample_rate_hz, channels)
    if workload == "component-tracking":
        return _component_estimate(frames, sample_rate_hz, channels, tracker_spec)
    if workload == "band-processing":
        return _band_estimate(frames, sample_rate_hz, channels)
    if workload == "persistent-layer-render":
        return _layer_estimate(frames, sample_rate_hz, channels)
    raise PerformanceError(f"unknown workload: {workload!r}")


def bar_frame_count(bar_count, sample_rate_hz, bpm, beats_per_bar=4):
    if type(bar_count) is not int or type(bar_count) is bool or not 1 <= bar_count <= 4096:
        raise PerformanceError("bar_count must be in 1..4096")
    if type(beats_per_bar) is not int or type(beats_per_bar) is bool or not 1 <= beats_per_bar <= 32:
        raise PerformanceError("beats_per_bar must be in 1..32")
    if type(bpm) not in (int, float) or type(bpm) is bool or not math.isfinite(float(bpm)) or not 20 <= float(bpm) <= 400:
        raise PerformanceError("bpm must be finite in 20..400")
    _dims(0, sample_rate_hz, 1)
    return int(round(bar_count * beats_per_bar * 60.0 * sample_rate_hz / float(bpm)))


def estimate_longform_bars(bar_count, *, sample_rate_hz, bpm, beats_per_bar=4):
    frames = bar_frame_count(bar_count, sample_rate_hz, bpm, beats_per_bar)
    return estimate_workload("persistent-layer-render", frames=frames, sample_rate_hz=sample_rate_hz)


def admission_memory(estimate, *, job_class, limits=SchedulerLimits(), requested_bytes=None):
    if not isinstance(estimate, WorkloadEstimate):
        raise PerformanceError("WorkloadEstimate required")
    if not isinstance(limits, SchedulerLimits):
        raise PerformanceError("SchedulerLimits required")
    try:
        cls = JobClass(job_class)
    except (TypeError, ValueError) as exc:
        raise PerformanceError("valid JobClass required") from exc
    try:
        reserved = authoritative_memory_reservation(estimate.estimated_live_bytes, requested_bytes)
    except Exception as exc:
        raise PerformanceError(str(exc)) from exc
    lane_capacity = (
        limits.max_memory_bytes
        if cls.interactive
        else limits.max_memory_bytes - limits.interactive_memory_reserve_bytes
    )
    hard = min(limits.max_job_memory_bytes, lane_capacity)
    if cls is JobClass.PREVIEW:
        hard = min(hard, limits.max_preview_memory_bytes)
    if reserved > hard:
        raise PerformanceError(
            f"{estimate.workload} requires {reserved} bytes but {cls.name.lower()} admission permits {hard}"
        )
    return reserved


def recommended_section_bars(bar_count, *, sample_rate_hz, bpm, beats_per_bar=4,
                             limits=SchedulerLimits(), retained_output_stems=5):
    if type(retained_output_stems) is not int or not 1 <= retained_output_stems <= 16:
        raise PerformanceError("retained_output_stems must be in 1..16")
    total_frames = bar_frame_count(bar_count, sample_rate_hz, bpm, beats_per_bar)
    retained = total_frames * retained_output_stems * 4
    lane = min(
        limits.max_job_memory_bytes,
        limits.max_memory_bytes - limits.interactive_memory_reserve_bytes,
    )
    best = 0
    for candidate in range(1, bar_count + 1):
        frames = bar_frame_count(candidate, sample_rate_hz, bpm, beats_per_bar)
        working = estimate_workload(
            "persistent-layer-render", frames=frames, sample_rate_hz=sample_rate_hz
        ).estimated_live_bytes
        if working + retained <= lane:
            best = candidate
        else:
            break
    if best < 1:
        raise PerformanceError("retained output plus one section cannot fit the bounded background job")
    return best
