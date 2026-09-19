from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
import math

import numpy as np

from zaaggenz_contracts import Contract, ownership_manifest, section_transition_manifest
from zaaggenz_contracts.model import fraction
from zaaggenz_contracts.music import beat_to_sample
from zaaggenz_harmony import ProgressionResult
from zaaggenz_jobs import JobClass
from zaaggenz_layers import LayerRuntimeSpec, render_coordinated_layers

from .policy import (
    PerformanceError,
    WorkloadEstimate,
    admission_memory,
    estimate_workload,
    persistent_sequence_memory_bound,
)

MAX_PERSISTENT_SECTIONS = 4096


@dataclass(frozen=True)
class LayerSection:
    recipe: object
    progression: ProgressionResult
    frame_beats: tuple
    duration_beats: object
    boundary_id: str
    reset_roles: tuple[str, ...] = ()

    def __post_init__(self):
        if not isinstance(self.progression, ProgressionResult):
            raise PerformanceError("LayerSection progression must be ProgressionResult")
        object.__setattr__(self, "frame_beats", tuple(self.frame_beats))
        object.__setattr__(self, "reset_roles", tuple(self.reset_roles))
        if not self.frame_beats:
            raise PerformanceError("LayerSection requires frame beats")


@dataclass(frozen=True)
class PersistentSequenceResult:
    mix: np.ndarray
    stems: dict
    state: object
    section_diagnostics: tuple

    def __post_init__(self):
        mix = np.asarray(self.mix, dtype=np.float32)
        mix.setflags(write=False)
        object.__setattr__(self, "mix", mix)
        frozen = {}
        for name, value in self.stems.items():
            array = np.asarray(value, dtype=np.float32)
            array.setflags(write=False)
            frozen[name] = array
        object.__setattr__(self, "stems", frozen)
        object.__setattr__(self, "section_diagnostics", tuple(deepcopy(self.section_diagnostics)))


def _snapshot_section(section):
    if not isinstance(section, LayerSection):
        raise PerformanceError("sections must contain LayerSection values")
    recipe_data = (
        section.recipe.to_dict()
        if isinstance(section.recipe, Contract)
        else Contract(section.recipe).to_dict()
    )
    return LayerSection(
        Contract(deepcopy(recipe_data)),
        deepcopy(section.progression),
        tuple(deepcopy(section.frame_beats)),
        deepcopy(section.duration_beats),
        deepcopy(section.boundary_id),
        tuple(deepcopy(section.reset_roles)),
    )


def _snapshot_sections(sections):
    try:
        iterator = iter(sections)
    except TypeError as exc:
        raise PerformanceError("sections must be an iterable of LayerSection values") from exc

    snapshot = []
    for index, section in enumerate(iterator):
        if index >= MAX_PERSISTENT_SECTIONS:
            raise PerformanceError(
                f"persistent sequence exceeds the {MAX_PERSISTENT_SECTIONS}-section bound"
            )
        snapshot.append(_snapshot_section(section))
    if not snapshot:
        raise PerformanceError("at least one LayerSection is required")
    return tuple(snapshot)


def section_frame_count(recipe):
    contract = recipe if isinstance(recipe, Contract) else Contract(recipe)
    data = contract.to_dict()
    phrase = data.get("phrase")
    if phrase is None:
        raise PerformanceError("persistent section requires a PhrasePlan")
    time_map = data["time_map"]
    start = beat_to_sample(time_map, phrase["start_beat"])
    end = beat_to_sample(time_map, phrase["end_beat"])
    if end <= start:
        raise PerformanceError("persistent section has no rendered samples")
    return end - start


def _estimate_persistent_sequence_snapshot(sections):
    total_frames = 0
    peak_frames = 0
    sample_rate = None
    for section in sections:
        contract = section.recipe if isinstance(section.recipe, Contract) else Contract(section.recipe)
        data = contract.to_dict()
        sr = data["time_map"]["sample_rate_hz"]
        if sample_rate is None:
            sample_rate = sr
        elif sr != sample_rate:
            raise PerformanceError("all persistent sections must use one sample rate")
        frames = section_frame_count(contract)
        total_frames += frames
        peak_frames = max(peak_frames, frames)

    estimate = persistent_sequence_memory_bound(
        total_frames,
        peak_frames,
        sample_rate_hz=sample_rate,
        section_count=len(sections),
        retained_output_stems=5,
    )
    return WorkloadEstimate(
        "persistent-layer-render", sample_rate, total_frames, 1, "exact",
        estimate, total_frames * 4, 1, "explicit-section-state",
        (
            "peak one-section working set plus retained sequence mix/BODY/AUX/SUB/pre_master",
            "includes bounded immutable input/diagnostic/orchestration headroom",
            "previous section result is released before the next section render begins",
            "SYNTHLINE/exciter are required muted for exact persistent-section chunking",
            "each continuation is bound by LayerSectionTransition",
        ),
    )


def estimate_persistent_sequence(sections):
    return _estimate_persistent_sequence_snapshot(_snapshot_sections(sections))


def _section_schedule(section):
    contract = section.recipe if isinstance(section.recipe, Contract) else Contract(section.recipe)
    data = contract.to_dict()
    phrase = data.get("phrase")
    if phrase is None:
        raise PerformanceError("persistent section requires a PhrasePlan")
    try:
        starts = tuple(fraction(value) for value in section.frame_beats)
        if isinstance(section.duration_beats, str):
            durations = tuple(fraction(section.duration_beats) for _ in section.progression.frames)
        else:
            durations = tuple(fraction(value) for value in section.duration_beats)
    except Exception as exc:
        raise PerformanceError("section frame beats/durations must be exact rationals") from exc
    if len(starts) != len(section.progression.frames) or len(durations) != len(section.progression.frames):
        raise PerformanceError("section frame schedule counts must match harmony progression")

    p0, p1 = fraction(phrase["start_beat"]), fraction(phrase["end_beat"])
    origin = beat_to_sample(data["time_map"], phrase["start_beat"])
    previous_end = p0
    rows = []
    for frame, start, duration in zip(section.progression.frames, starts, durations):
        if duration <= 0 or start < p0 or start + duration > p1 or start < previous_end:
            raise PerformanceError("section harmony frame is outside or overlaps the phrase span")
        previous_end = start + duration
        end = start + duration
        start_sample = beat_to_sample(
            data["time_map"], f"{start.numerator}/{start.denominator}"
        ) - origin
        end_sample = beat_to_sample(
            data["time_map"], f"{end.numerator}/{end.denominator}"
        ) - origin
        if end_sample <= start_sample:
            raise PerformanceError("section harmony frame rounds to zero samples")
        rows.append((start_sample, end_sample, frame))
    return rows


def _same_frequency(left, right):
    return math.isclose(float(left), float(right), rel_tol=1e-12, abs_tol=1e-9)


def _validate_representable_boundaries(sections, runtime_spec):
    """Reject chunk boundaries whose continuation state is not serializable.

    ZG-029 runtime state intentionally stores phase/last target/tail, but v1 does not
    serialize an in-progress glide trajectory. A repeated target split while that glide
    is still active therefore cannot be represented exactly and must fail before PCM work.
    """
    generators = {generator.role: generator for generator in runtime_spec.generators}
    previous_target = {}

    schedules = [_section_schedule(section) for section in sections]
    per_section_segments = []
    for schedule in schedules:
        segments = {}
        for start, end, frame in schedule:
            for voice in frame.voices:
                if voice.role not in ("body", "aux", "sub"):
                    continue
                segments.setdefault((voice.role, voice.voice_id), []).append(
                    (start, end, float(voice.frequency_hz))
                )
        per_section_segments.append(segments)

    for index, segments in enumerate(per_section_segments):
        if index:
            reset_roles = frozenset(sections[index].reset_roles)
            for key in list(previous_target):
                if key[0] in reset_roles:
                    del previous_target[key]
        last_segment_meta = {}
        for key, voice_segments in segments.items():
            prior = previous_target.get(key)
            generator = generators.get(key[0])
            if generator is None:
                continue
            for segment_index, (start, end, target) in enumerate(voice_segments):
                changed = prior is not None and not _same_frequency(prior, target)
                span = end - start
                if segment_index == len(voice_segments) - 1:
                    last_segment_meta[key] = (prior, target, span, changed, generator.glide_samples)
                prior = target
            previous_target[key] = prior

        if index + 1 >= len(sections):
            continue
        next_section = sections[index + 1]
        reset_roles = frozenset(next_section.reset_roles)
        next_segments = per_section_segments[index + 1]
        for key, (_, target, span, changed, glide_samples) in last_segment_meta.items():
            if key[0] in reset_roles or not changed or glide_samples <= 0 or span >= glide_samples:
                continue
            following = next_segments.get(key)
            if not following:
                continue
            next_target = following[0][2]
            if _same_frequency(target, next_target):
                raise PerformanceError(
                    "persistent section boundary cuts through an unfinished glide that "
                    "ZG-029 runtime state cannot serialize; move the boundary, complete "
                    "the glide, or explicitly reset the role"
                )


def _render_persistent_sections_snapshot(sections, runtime_spec, *,
                                         muted_roles=("synthline", "exciter"),
                                         job_context=None):
    if not isinstance(runtime_spec, LayerRuntimeSpec):
        raise PerformanceError("LayerRuntimeSpec required")
    muted = frozenset(muted_roles)
    if not {"synthline", "exciter"} <= muted:
        raise PerformanceError(
            "exact ZG-042 section chunking is limited to the persistent-layer submix; "
            "SYNTHLINE/exciter must be muted rather than arbitrarily chunked"
        )

    estimate = _estimate_persistent_sequence_snapshot(sections)
    _validate_representable_boundaries(sections, runtime_spec)
    if job_context is not None:
        # This check deliberately precedes retained-output allocation.
        job_context.check_cancelled()

    total_frames = estimate.frames
    names = ("body", "aux", "sub", "pre_master")
    mix = np.empty(total_frames, dtype=np.float32)
    stems = {name: np.empty(total_frames, dtype=np.float32) for name in names}
    diagnostics = []
    state = None
    cursor = 0
    for index, section in enumerate(sections):
        if job_context is not None:
            job_context.check_cancelled()
        contract = section.recipe if isinstance(section.recipe, Contract) else Contract(section.recipe)
        data = contract.to_dict()
        transition = None
        if state is not None:
            ownership = ownership_manifest(
                data["phrase"], phase_policy=data["phase_policy"],
                transform_claims=runtime_spec.transform_claims,
            )
            transition = section_transition_manifest(
                ownership, boundary_id=section.boundary_id, reset_roles=section.reset_roles
            )
        result = render_coordinated_layers(
            contract, section.progression, section.frame_beats, section.duration_beats,
            runtime_spec, state=state, section_transition=transition, muted_roles=tuple(muted),
        )
        section_frames = len(result.mix)
        expected_frames = section_frame_count(contract)
        if section_frames != expected_frames or cursor + section_frames > total_frames:
            raise PerformanceError("section runtime extent disagrees with preflight estimate")
        end = cursor + section_frames
        mix[cursor:end] = result.mix
        for name in names:
            stems[name][cursor:end] = result.stems[name]
        diagnostics.append(deepcopy(result.diagnostics))
        state = result.state
        cursor = end

        # The next render must not overlap with the previous section's full PCM result.
        # Only copied retained products, small diagnostics and continuation state survive.
        del result
        if job_context is not None:
            job_context.check_cancelled()
            job_context.progress((index + 1) / len(sections))

    if cursor != total_frames:
        raise PerformanceError("sequence runtime extent disagrees with preflight estimate")
    return PersistentSequenceResult(
        mix, stems, state, tuple(diagnostics)
    )


def render_persistent_sections(sections, runtime_spec, *,
                               muted_roles=("synthline", "exciter"), job_context=None):
    snapshot = _snapshot_sections(sections)
    runtime_snapshot = deepcopy(runtime_spec)
    return _render_persistent_sections_snapshot(
        snapshot, runtime_snapshot, muted_roles=muted_roles, job_context=job_context
    )


def submit_persistent_sections(scheduler, revision_id, sections, runtime_spec, *,
                               requested_memory_bytes=None, muted_roles=("synthline", "exciter")):
    if not isinstance(runtime_spec, LayerRuntimeSpec):
        raise PerformanceError("LayerRuntimeSpec required")
    # Materialize one bounded deep snapshot before admission. The exact same snapshot is
    # then executed, so caller mutation and one-shot iterators cannot change admitted work.
    snapshot = _snapshot_sections(sections)
    runtime_snapshot = deepcopy(runtime_spec)
    estimate = _estimate_persistent_sequence_snapshot(snapshot)
    _validate_representable_boundaries(snapshot, runtime_snapshot)
    reserved = admission_memory(
        estimate, job_class=JobClass.BATCH, limits=scheduler.limits,
        requested_bytes=requested_memory_bytes,
    )

    def execute(ctx):
        return _render_persistent_sections_snapshot(
            snapshot, runtime_snapshot, muted_roles=muted_roles, job_context=ctx
        )

    return scheduler.submit(
        JobClass.BATCH, revision_id, execute, estimated_memory_bytes=reserved
    )
