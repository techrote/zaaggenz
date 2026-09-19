from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
import numpy as np

from zaaggenz_contracts import Contract, ownership_manifest, section_transition_manifest
from zaaggenz_contracts.music import beat_to_sample
from zaaggenz_harmony import ProgressionResult
from zaaggenz_jobs import JobClass
from zaaggenz_layers import LayerRuntimeSpec, render_coordinated_layers

from .policy import PerformanceError, WorkloadEstimate, admission_memory, estimate_workload


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


def estimate_persistent_sequence(sections):
    sections = tuple(sections)
    if not sections:
        raise PerformanceError("at least one LayerSection is required")
    total_frames = 0
    peak_working = 0
    sample_rate = None
    for section in sections:
        if not isinstance(section, LayerSection):
            raise PerformanceError("sections must contain LayerSection values")
        contract = section.recipe if isinstance(section.recipe, Contract) else Contract(section.recipe)
        data = contract.to_dict()
        sr = data["time_map"]["sample_rate_hz"]
        if sample_rate is None:
            sample_rate = sr
        elif sr != sample_rate:
            raise PerformanceError("all persistent sections must use one sample rate")
        frames = section_frame_count(contract)
        total_frames += frames
        peak_working = max(
            peak_working,
            estimate_workload(
                "persistent-layer-render", frames=frames, sample_rate_hz=sr
            ).estimated_live_bytes,
        )
    # Sequence result retains mix + BODY/AUX/SUB/pre_master. Raw source evidence is
    # intentionally excluded because this helper requires source roles muted.
    retained = total_frames * 5 * 4
    estimate = peak_working + retained
    return WorkloadEstimate(
        "persistent-layer-render", sample_rate, total_frames, 1, "exact",
        estimate, total_frames * 4, 1, "explicit-section-state",
        (
            "peak one-section working set plus retained sequence mix/BODY/AUX/SUB/pre_master",
            "SYNTHLINE/exciter are required muted for exact persistent-section chunking",
            "each continuation is bound by LayerSectionTransition",
        ),
    )


def render_persistent_sections(sections, runtime_spec, *,
                               muted_roles=("synthline", "exciter"), job_context=None):
    sections = tuple(sections)
    if not sections:
        raise PerformanceError("at least one LayerSection is required")
    if not isinstance(runtime_spec, LayerRuntimeSpec):
        raise PerformanceError("LayerRuntimeSpec required")
    muted = frozenset(muted_roles)
    if not {"synthline", "exciter"} <= muted:
        raise PerformanceError(
            "exact ZG-042 section chunking is limited to the persistent-layer submix; "
            "SYNTHLINE/exciter must be muted rather than arbitrarily chunked"
        )

    state = None
    results = []
    for index, section in enumerate(sections):
        if not isinstance(section, LayerSection):
            raise PerformanceError("sections must contain LayerSection values")
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
        state = result.state
        results.append(result)
        if job_context is not None:
            job_context.progress((index + 1) / len(sections))

    names = ("body", "aux", "sub", "pre_master")
    stems = {
        name: np.concatenate([np.asarray(result.stems[name], dtype=np.float32) for result in results])
        for name in names
    }
    mix = np.concatenate([np.asarray(result.mix, dtype=np.float32) for result in results])
    return PersistentSequenceResult(
        mix, stems, state, tuple(result.diagnostics for result in results)
    )


def submit_persistent_sections(scheduler, revision_id, sections, runtime_spec, *,
                               requested_memory_bytes=None, muted_roles=("synthline", "exciter")):
    estimate = estimate_persistent_sequence(sections)
    reserved = admission_memory(
        estimate, job_class=JobClass.BATCH, limits=scheduler.limits,
        requested_bytes=requested_memory_bytes,
    )

    def execute(ctx):
        return render_persistent_sections(
            sections, runtime_spec, muted_roles=muted_roles, job_context=ctx
        )

    return scheduler.submit(
        JobClass.BATCH, revision_id, execute, estimated_memory_bytes=reserved
    )
