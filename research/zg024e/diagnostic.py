"""ZG-024e preregistered starvation/generalisation diagnostic search.

This research layer is deliberately outside zaaggenz_inverse. Search receives only the
accepted FitEvaluator capability; truth and holdout/audit remain orchestration-only.
The frozen authority is docs/inverse/ZG024E_DIAGNOSTIC_PROTOCOL_V1.md.
"""
from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
import hashlib
from pathlib import Path

from zaaggenz_contracts import digest
from zaaggenz_inverse import FitEvaluator, ParameterState
from zaaggenz_inverse.contracts import InverseError, require, sha
from zaaggenz_inverse.laboratory import AuditSelection
from zaaggenz_inverse.recipes import state_from_recipe
from zaaggenz_inverse.results import Candidate, pareto_front
from zaaggenz_inverse.search import estimate_memory_bytes
from zaaggenz_jobs import JobCancelled, JobClass
from zaaggenz_jobs.model import numeric_thread_limit
from research.zg024b.strategies import (
    _candidate_sort_key,
    _halton_state,
    research_implementation_sha256 as zg024b_implementation_sha256,
)

VERSION = "1.0.0"
LOCAL_RADII = (0.25, 0.125, 0.0625, 0.03125)
FAMILY_NAMES = {
    "A": frozenset(("f0_hz", "attack_ms", "decay_ms", "sustain", "transient_click",
                    "noise_decay_ms", "sweep_semitones")),
    "B": frozenset(("harmonic_count", "harmonic_decay", "odd_even_ratio",
                    "harmonic_tilt_db_per_oct", "harmonic_lock_cents", "roughness")),
    "C": frozenset(("drive_db", "input_trim_db", "shaper_mix", "hard_clip_mix",
                    "asymmetry", "wavefold", "preemphasis", "noise_level")),
}
METHOD_SPECS = {
    "zg024e.factorized-24-control.v1": {
        "mode": "factorized", "budget": 24, "allocation": {"A": 10, "B": 7, "C": 7}, "retain": 4,
    },
    "zg024e.factorized-36-balanced.v1": {
        "mode": "factorized", "budget": 36, "allocation": {"A": 12, "B": 12, "C": 12}, "retain": 4,
    },
    "zg024e.factorized-36-a-heavy.v1": {
        "mode": "factorized", "budget": 36, "allocation": {"A": 16, "B": 10, "C": 10}, "retain": 4,
    },
    "zg024e.factorized-36-b-heavy.v1": {
        "mode": "factorized", "budget": 36, "allocation": {"A": 10, "B": 16, "C": 10}, "retain": 4,
    },
    "zg024e.factorized-36-wide-parents.v1": {
        "mode": "factorized", "budget": 36, "allocation": {"A": 12, "B": 12, "C": 12}, "retain": 8,
    },
    "zg024e.coupled-ab-36.v1": {
        "mode": "coupled-ab", "budget": 36, "allocation": {"AB": 24, "C": 12}, "retain": 4,
    },
}
METHODS = tuple(METHOD_SPECS)
CONTROL_METHOD = "zg024e.factorized-24-control.v1"
BALANCED_36_METHOD = "zg024e.factorized-36-balanced.v1"

DESIGN_MANIFEST = {
    "kind": "ZG024eDiagnosticDesignManifest",
    "version": VERSION,
    "protocol": "docs/inverse/ZG024E_DIAGNOSTIC_PROTOCOL_V1.md",
    "families": {key: sorted(value) for key, value in FAMILY_NAMES.items()},
    "methods": METHOD_SPECS,
    "local_radii": list(LOCAL_RADII),
    "seeds": ["53", "307", "4099"],
    "selection": "eligible-final availability, then starvation stops, then fit score, then method id",
    "checkpoint": "verified-prefix-replay-zg024e-v1",
    "portable_policy": {"absolute_tolerance": 1e-7, "relative_tolerance": 1e-5},
    "capability_policy": "FitEvaluator only; truth and holdout/audit unavailable to search and selection",
}


def design_sha256():
    return digest(DESIGN_MANIFEST)


def research_implementation():
    text = Path(__file__).read_text(encoding="utf-8").replace("\r\n", "\n")
    return {
        "kind": "ZG024eDiagnosticResearchImplementation",
        "version": VERSION,
        "strategy_source_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "design_sha256": design_sha256(),
        "zg024b_dependency_sha256": zg024b_implementation_sha256(),
        "policy": "fit-only deterministic causal diagnostic; no truth/holdout feedback",
    }


def research_implementation_sha256():
    return digest(research_implementation())


@dataclass(frozen=True)
class DiagnosticSpec:
    method_id: str
    version: str = VERSION

    def __post_init__(self):
        require(self.method_id in METHODS, "unsupported ZG-024e diagnostic strategy")
        require(self.version == VERSION, "unsupported ZG-024e diagnostic strategy version")

    @property
    def config(self):
        return METHOD_SPECS[self.method_id]

    @property
    def budget(self):
        return self.config["budget"]

    @property
    def allocation(self):
        return dict(self.config["allocation"])

    @property
    def retain(self):
        return self.config["retain"]

    @property
    def mode(self):
        return self.config["mode"]

    def to_dict(self):
        return {
            "kind": "ZG024eDiagnosticSpec", "version": self.version,
            "method_id": self.method_id, "mode": self.mode, "budget": self.budget,
            "allocation": self.allocation, "retained_alternatives": self.retain,
            "design_sha256": design_sha256(),
        }

    @property
    def sha256(self):
        return digest(self.to_dict())


@dataclass(frozen=True)
class DiagnosticCheckpoint:
    run_id: str
    environment_sha256: str
    next_ordinal: int
    evaluation_sha256s: tuple[str, ...]
    parent_checkpoint_sha256: str | None = None

    def __post_init__(self):
        sha(self.run_id, "run_id")
        sha(self.environment_sha256, "environment_sha256")
        require(type(self.next_ordinal) is int and 0 <= self.next_ordinal <= 512,
                "invalid ZG-024e checkpoint ordinal")
        require(self.next_ordinal == len(self.evaluation_sha256s), "ZG-024e checkpoint prefix mismatch")
        for value in self.evaluation_sha256s:
            sha(value, "evaluation_sha256")
        if self.parent_checkpoint_sha256 is not None:
            sha(self.parent_checkpoint_sha256, "parent_checkpoint_sha256")
        object.__setattr__(self, "evaluation_sha256s", tuple(self.evaluation_sha256s))

    def to_dict(self):
        return {
            "kind": "ZG024eDiagnosticCheckpoint", "version": VERSION,
            "run_id": self.run_id, "environment_sha256": self.environment_sha256,
            "next_ordinal": self.next_ordinal,
            "evaluation_sha256s": list(self.evaluation_sha256s),
            "parent_checkpoint_sha256": self.parent_checkpoint_sha256,
            "policy": "verified-prefix-replay-zg024e-v1",
        }

    @property
    def sha256(self):
        return digest(self.to_dict())


class DiagnosticInterrupted(JobCancelled):
    def __init__(self, checkpoint):
        self.checkpoint = checkpoint
        super().__init__("ZG-024e diagnostic search cancelled; latest complete prefix retained")


class DiagnosticResumeDivergence(InverseError):
    def __init__(self, checkpoint, reason, actual=None):
        self.checkpoint, self.reason, self.actual = checkpoint, reason, actual
        super().__init__("ZG-024e resume divergence: " + reason)


@dataclass(frozen=True)
class DiagnosticResult:
    run_id: str
    evaluator_search_id: str
    strategy: DiagnosticSpec
    candidates: tuple[Candidate, ...]
    lineage: tuple[dict, ...]
    promotions: tuple[dict, ...]
    ranked_candidate_ids: tuple[str, ...]
    pareto_candidate_ids: tuple[str, ...]
    final_retained_candidate_ids: tuple[str, ...]
    checkpoint: DiagnosticCheckpoint
    stage_consumption: tuple[tuple[str, int], ...]
    proposal_attempts: int
    stop_reason: str | None = None

    def __post_init__(self):
        sha(self.run_id, "run_id")
        sha(self.evaluator_search_id, "evaluator_search_id")
        require(isinstance(self.strategy, DiagnosticSpec), "DiagnosticSpec required")
        require(len(self.candidates) == len(self.lineage) == self.checkpoint.next_ordinal,
                "ZG-024e result prefix mismatch")
        require(tuple(row["candidate_id"] for row in self.lineage) == tuple(c.id for c in self.candidates),
                "ZG-024e lineage/candidate mismatch")
        expected_stages = set(self.strategy.allocation)
        consumption = dict(self.stage_consumption)
        require(set(consumption) == expected_stages, "invalid ZG-024e stage consumption keys")
        require(sum(consumption.values()) == len(self.candidates), "invalid ZG-024e stage consumption")
        require(len(self.candidates) <= self.strategy.budget, "ZG-024e logical budget exceeded")
        require(self.proposal_attempts >= len(self.candidates), "proposal attempts below evaluations")
        candidate_ids = {candidate.id for candidate in self.candidates}
        require(set(self.final_retained_candidate_ids) <= candidate_ids,
                "ZG-024e retained candidate outside result")

    def to_dict(self):
        return {
            "kind": "ZG024eDiagnosticResult", "version": VERSION,
            "run_id": self.run_id, "evaluator_search_id": self.evaluator_search_id,
            "strategy": self.strategy.to_dict(), "design_manifest": DESIGN_MANIFEST,
            "research_implementation": research_implementation(),
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "lineage": list(self.lineage), "promotions": list(self.promotions),
            "ranked_candidate_ids": list(self.ranked_candidate_ids),
            "pareto_candidate_ids": list(self.pareto_candidate_ids),
            "final_retained_candidate_ids": list(self.final_retained_candidate_ids),
            "checkpoint": self.checkpoint.to_dict(),
            "budget": {
                "declared_evaluations": self.strategy.budget,
                "consumed_evaluations": len(self.candidates),
                "unspent_evaluations": self.strategy.budget - len(self.candidates),
                "stage_consumption": dict(self.stage_consumption),
                "proposal_attempts": self.proposal_attempts,
                "unit": "unique logical candidate evaluations; foundation evaluator verifies cold renders twice",
            },
            "stop_reason": self.stop_reason,
            "selection": "fit-only eligibility/objective/Pareto promotion; truth and holdout absent",
        }

    @property
    def sha256(self):
        return digest(self.to_dict())

    def audit_selection(self, *, all_candidates=False):
        ids = tuple(c.id for c in self.candidates) if all_candidates else self.final_retained_candidate_ids
        require(ids, "no eligible fit-selected ZG-024e alternative available")
        return AuditSelection(self.evaluator_search_id, ids)


def _run_id(evaluator, strategy):
    require(isinstance(evaluator, FitEvaluator), "diagnostic search requires FitEvaluator")
    return digest({
        "domain": "zaaggenz.zg024e-diagnostic-run-v1",
        "evaluator_search_id": evaluator.search_id,
        "strategy": strategy.to_dict(),
        "research_implementation_sha256": research_implementation_sha256(),
        "environment_sha256": evaluator.environment_sha256,
        "declared_budget": evaluator.request.budget.max_evaluations,
    })


def _family_for_axis(path):
    name = path.rsplit("/", 1)[-1]
    found = [family for family, names in FAMILY_NAMES.items() if name in names]
    require(len(found) == 1, "every ZG-024e axis must belong to exactly one frozen family: " + path)
    return found[0]


def _family_axes(request):
    output = {"A": [], "B": [], "C": []}
    for axis in request.domain.axes:
        output[_family_for_axis(axis.path)].append(axis)
    require(all(output[key] for key in ("A", "B", "C")),
            "ZG-024e fixtures require at least one axis in every frozen family")
    return {key: tuple(value) for key, value in output.items()}


def _state(candidate):
    return ParameterState.from_dict(candidate.to_dict()["parameters"])


def _sample_families(request, anchor, families, attempt, label, axes):
    sample = _halton_state(request, attempt, label)
    sampled = dict(sample.values)
    values = dict(anchor.values)
    for family in families:
        for axis in axes[family]:
            values[axis.path] = sampled[axis.path]
    return request.domain.validate_state(ParameterState(tuple(values.items())))


def _coordinate_state(request, anchor, axis, sign, radius):
    values = dict(anchor.values)
    center = values[axis.path]
    value = max(axis.lower, min(axis.upper, center + sign * radius * (axis.upper - axis.lower)))
    if axis.numeric_type == "integer":
        value = max(int(axis.lower), min(int(axis.upper), int(round(value))))
    values[axis.path] = value
    return request.domain.validate_state(ParameterState(tuple(values.items())))


def _output_identity(candidate):
    return digest(candidate.to_dict()["render"]["signals"]["output"]["asset"])


def _promotion(stage, candidates, retain):
    eligible = sorted((candidate for candidate in candidates if candidate.eligible), key=_candidate_sort_key)
    pareto_ids = tuple(pareto_front(candidates))
    pareto_set = set(pareto_ids)
    retained = [candidate for candidate in eligible if candidate.id in pareto_set][:retain]
    retained_ids = {candidate.id for candidate in retained}
    for candidate in eligible:
        if len(retained) >= retain:
            break
        if candidate.id not in retained_ids:
            retained.append(candidate)
            retained_ids.add(candidate.id)
    by_output = {}
    for candidate in eligible:
        by_output.setdefault(_output_identity(candidate), []).append(candidate.id)
    groups = [ids for _, ids in sorted(by_output.items()) if len(ids) > 1]
    return {
        "stage": stage,
        "eligible_candidate_ids": [candidate.id for candidate in eligible],
        "pareto_candidate_ids": list(pareto_ids),
        "retained_candidate_ids": [candidate.id for candidate in retained],
        "exact_output_equivalence_groups": groups,
        "retained_cap": retain,
        "policy": "eligible Pareto-first then fit-order supplement",
    }, tuple(retained)


def _evaluate(evaluator, state, ordinal, replay, checkpoint, check_cancelled):
    candidate = evaluator.evaluate(
        state, ordinal, check_cancelled=check_cancelled, force_recheck=ordinal < replay
    )
    if ordinal < replay and candidate.sha256 != checkpoint.evaluation_sha256s[ordinal]:
        raise DiagnosticResumeDivergence(
            checkpoint, f"completed candidate {ordinal} failed exact replay", candidate.sha256
        )
    return candidate


def _fill_texture(request, axes, parents, c_budget, accept, check_cancelled):
    output = []
    for radius_index, radius in enumerate(LOCAL_RADII):
        if len(output) >= c_budget:
            break
        for parent_rank, parent in enumerate(parents):
            if len(output) >= c_budget:
                break
            for axis in axes["C"]:
                for sign in (-1, 1):
                    if len(output) >= c_budget:
                        break
                    check_cancelled()
                    state = _coordinate_state(request, _state(parent), axis, sign, radius)
                    candidate = accept(
                        state, "C",
                        {"family": "coordinate-refine", "stage_family": "C",
                         "parent_rank": parent_rank, "axis": axis.path, "direction": sign,
                         "radius_index": radius_index, "radius_fraction": radius},
                        (parent.id,),
                    )
                    if candidate is not None:
                        output.append(candidate)
    continuation = 0
    while len(output) < c_budget and continuation < c_budget * 256:
        check_cancelled()
        parent = parents[continuation % len(parents)]
        sample_index = continuation // len(parents)
        state = _sample_families(
            request, _state(parent), ("C",), sample_index,
            f"zg024e-stage-c-parent-{continuation % len(parents)}", axes,
        )
        candidate = accept(
            state, "C",
            {"family": "shifted-halton-continuation", "stage_family": "C",
             "parent_rank": continuation % len(parents), "coverage_attempt": sample_index,
             "reason": "coordinate duplicate/clipping exhaustion"},
            (parent.id,),
        )
        if candidate is not None:
            output.append(candidate)
        continuation += 1
    require(len(output) == c_budget, "ZG-024e Stage C could not consume its unique-state budget")
    return output


def run_diagnostic(evaluator, strategy, *, checkpoint=None, check_cancelled=lambda: None,
                   progress=lambda value: None, on_checkpoint=lambda cp: None):
    require(isinstance(evaluator, FitEvaluator), "run_diagnostic accepts only FitEvaluator")
    require(isinstance(strategy, DiagnosticSpec), "DiagnosticSpec required")
    request = evaluator.request
    require(request.budget.max_evaluations == strategy.budget, "ZG-024e request/spec budget mismatch")
    require(sum(strategy.allocation.values()) == strategy.budget, "ZG-024e allocation/budget mismatch")
    axes = _family_axes(request)
    run_id = _run_id(evaluator, strategy)
    replay = 0
    current = DiagnosticCheckpoint(run_id, evaluator.environment_sha256, 0, ())
    if checkpoint is not None:
        require(isinstance(checkpoint, DiagnosticCheckpoint), "DiagnosticCheckpoint required")
        if checkpoint.run_id != run_id:
            raise DiagnosticResumeDivergence(checkpoint, "method/design/request/implementation changed", run_id)
        if checkpoint.environment_sha256 != evaluator.environment_sha256:
            raise DiagnosticResumeDivergence(
                checkpoint, "numerical environment changed", evaluator.environment_sha256
            )
        require(checkpoint.next_ordinal <= strategy.budget, "checkpoint exceeds ZG-024e budget")
        replay, current = checkpoint.next_ordinal, checkpoint

    candidates, lineage, promotions, seen = [], [], [], set()
    consumption = {key: 0 for key in strategy.allocation}
    attempts = 0
    stop_reason = None

    def accept(state, stage, proposal, parents=()):
        nonlocal attempts, current
        attempts += 1
        if state.sha256 in seen or len(candidates) >= strategy.budget:
            return None
        seen.add(state.sha256)
        ordinal = len(candidates)
        candidate = _evaluate(evaluator, state, ordinal, replay, checkpoint, check_cancelled)
        candidates.append(candidate)
        consumption[stage] += 1
        lineage.append({
            "ordinal": ordinal, "candidate_id": candidate.id, "stage": stage,
            "parent_candidate_ids": list(parents), "proposal": proposal,
            "eligible": candidate.eligible,
        })
        if ordinal >= replay:
            current = DiagnosticCheckpoint(
                run_id, evaluator.environment_sha256, ordinal + 1,
                tuple(candidate.sha256 for candidate in candidates), current.sha256,
            )
            on_checkpoint(current)
        progress((ordinal + 1) / strategy.budget)
        return candidate

    controller = numeric_thread_limit(1)
    try:
        with controller if controller is not None else nullcontext():
            base = state_from_recipe(request.base_recipe, request.domain)
            if strategy.mode == "factorized":
                a_budget = strategy.allocation["A"]
                b_budget = strategy.allocation["B"]
                c_budget = strategy.allocation["C"]
                a_candidates = []
                attempt = 0
                while len(a_candidates) < a_budget and attempt < a_budget * 128:
                    check_cancelled()
                    state = _sample_families(
                        request, base, ("A",), attempt, strategy.method_id + "-stage-a", axes
                    )
                    candidate = accept(
                        state, "A",
                        {"family": "shifted-halton", "stage_family": "A", "coverage_attempt": attempt},
                    )
                    if candidate is not None:
                        a_candidates.append(candidate)
                    attempt += 1
                require(len(a_candidates) == a_budget, "ZG-024e Stage A unique-state budget failure")
                record, a_parents = _promotion("A", a_candidates, strategy.retain)
                promotions.append(record)
                if not a_parents:
                    stop_reason = "stage-A-no-eligible-parent"
                else:
                    b_candidates = []
                    attempt = 0
                    while len(b_candidates) < b_budget and attempt < b_budget * 256:
                        check_cancelled()
                        parent = a_parents[attempt % len(a_parents)]
                        sample_index = attempt // len(a_parents)
                        state = _sample_families(
                            request, _state(parent), ("B",), sample_index,
                            f"{strategy.method_id}-stage-b-parent-{attempt % len(a_parents)}", axes,
                        )
                        candidate = accept(
                            state, "B",
                            {"family": "shifted-halton", "stage_family": "B",
                             "parent_rank": attempt % len(a_parents),
                             "coverage_attempt": sample_index},
                            (parent.id,),
                        )
                        if candidate is not None:
                            b_candidates.append(candidate)
                        attempt += 1
                    require(len(b_candidates) == b_budget, "ZG-024e Stage B unique-state budget failure")
                    record, b_parents = _promotion("B", b_candidates, strategy.retain)
                    promotions.append(record)
                    if not b_parents:
                        stop_reason = "stage-B-no-eligible-parent"
                    else:
                        c_candidates = _fill_texture(
                            request, axes, b_parents, c_budget, accept, check_cancelled
                        )
                        record, final = _promotion("C-final", c_candidates, strategy.retain)
                        promotions.append(record)
                        if not final:
                            stop_reason = "stage-C-no-eligible-final-alternative"
            else:
                ab_budget = strategy.allocation["AB"]
                c_budget = strategy.allocation["C"]
                ab_candidates = []
                attempt = 0
                while len(ab_candidates) < ab_budget and attempt < ab_budget * 128:
                    check_cancelled()
                    state = _sample_families(
                        request, base, ("A", "B"), attempt, strategy.method_id + "-stage-ab", axes
                    )
                    candidate = accept(
                        state, "AB",
                        {"family": "shifted-halton", "stage_family": "AB",
                         "coverage_attempt": attempt, "coupled_families": ["A", "B"]},
                    )
                    if candidate is not None:
                        ab_candidates.append(candidate)
                    attempt += 1
                require(len(ab_candidates) == ab_budget, "ZG-024e Stage AB unique-state budget failure")
                record, ab_parents = _promotion("AB", ab_candidates, strategy.retain)
                promotions.append(record)
                if not ab_parents:
                    stop_reason = "stage-AB-no-eligible-parent"
                else:
                    c_candidates = _fill_texture(
                        request, axes, ab_parents, c_budget, accept, check_cancelled
                    )
                    record, final = _promotion("C-final", c_candidates, strategy.retain)
                    promotions.append(record)
                    if not final:
                        stop_reason = "stage-C-no-eligible-final-alternative"
            check_cancelled()
    except JobCancelled as exc:
        raise DiagnosticInterrupted(current) from exc

    require(len(candidates) >= replay, "resume prefix could not be regenerated")
    eligible = sorted((candidate for candidate in candidates if candidate.eligible), key=_candidate_sort_key)
    final_ids = ()
    if promotions and promotions[-1]["stage"] == "C-final":
        final_ids = tuple(promotions[-1]["retained_candidate_ids"])
    return DiagnosticResult(
        run_id, evaluator.search_id, strategy, tuple(candidates), tuple(lineage),
        tuple(promotions), tuple(candidate.id for candidate in eligible),
        pareto_front(candidates), final_ids, current, tuple(sorted(consumption.items())),
        attempts, stop_reason,
    )


def submit_diagnostic_job(scheduler, evaluator, strategy, *, checkpoint=None,
                          on_checkpoint=lambda cp: None):
    require(isinstance(evaluator, FitEvaluator), "FitEvaluator required")
    require(isinstance(strategy, DiagnosticSpec), "DiagnosticSpec required")

    def execute(ctx):
        ctx.check_cancelled()
        return run_diagnostic(
            evaluator, strategy, checkpoint=checkpoint, check_cancelled=ctx.check_cancelled,
            progress=ctx.progress, on_checkpoint=on_checkpoint,
        )

    return scheduler.submit(
        JobClass.RESEARCH, evaluator.request.source_revision_id, execute,
        estimated_memory_bytes=estimate_memory_bytes(evaluator),
    )
