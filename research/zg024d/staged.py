"""Preregistered staged deterministic search for ZG-024d / issue #92.

The runner accepts only the existing fit capability.  It never receives fixture truth,
holdout PCM, or an AuditEvaluator.  Stage A uses shifted low-discrepancy coverage for
root/timing/envelope coordinates; stage B applies shifted low-discrepancy coverage to
spectral coordinates around deterministically retained parents; stage C performs local
coordinate refinement for texture/nonlinear coordinates with an explicitly labelled
Halton fallback when clipping/duplicates would otherwise waste logical budget.

This is research code.  It deliberately does not alter the frozen ZG-024a production-
candidate package or the accepted ZG-024b comparison methods.
"""
from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
import hashlib
import math
from pathlib import Path

from zaaggenz_contracts import derive_seed, digest
from zaaggenz_jobs import JobCancelled
from zaaggenz_jobs.model import numeric_thread_limit
from zaaggenz_inverse import FitEvaluator, ParameterState
from zaaggenz_inverse.contracts import InverseError, require, sha
from zaaggenz_inverse.recipes import engine_identity, state_from_recipe
from zaaggenz_inverse.results import Candidate, pareto_front
from zaaggenz_inverse.laboratory import AuditSelection

VERSION = "1.0.0"
METHOD_ID = "zg024d.staged-halton-coordinate.v1"
MASK64 = (1 << 64) - 1
PRIMES = (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53)
STAGE_IDS = ("stage-a-root-envelope", "stage-b-spectral", "stage-c-texture")


def _canonical(value):
    if isinstance(value, tuple):
        return [_canonical(x) for x in value]
    if isinstance(value, dict):
        return {k: _canonical(v) for k, v in value.items()}
    return value


def research_implementation():
    path = Path(__file__)
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    return {
        "kind": "ZG024dResearchImplementation",
        "version": VERSION,
        "method_id": METHOD_ID,
        "strategy_source_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "foundation_engine_sha256": engine_identity(),
        "numerical_policy": "same-environment exact replay; portable metrics use preregistered tolerances",
    }


def research_implementation_sha256():
    return digest(research_implementation())


@dataclass(frozen=True)
class StageDefinition:
    id: str
    axis_paths: tuple[str, ...]
    evaluations: int
    retain_cap: int
    proposal: str

    def __post_init__(self):
        require(self.id in STAGE_IDS, "unknown staged-search stage")
        require(type(self.axis_paths) is tuple, "axis_paths must be tuple")
        require(len(set(self.axis_paths)) == len(self.axis_paths), "duplicate stage axis")
        require(all(type(x) is str and x.startswith("/") for x in self.axis_paths), "canonical stage axis paths required")
        require(type(self.evaluations) is int and 0 <= self.evaluations <= 256, "invalid stage evaluation budget")
        require(type(self.retain_cap) is int and 1 <= self.retain_cap <= 16, "invalid stage retain cap")
        expected = {
            "stage-a-root-envelope": "shifted-halton-v1",
            "stage-b-spectral": "parented-shifted-halton-v1",
            "stage-c-texture": "parented-coordinate-v1",
        }[self.id]
        require(self.proposal == expected, "stage proposal method does not match frozen protocol")
        require(bool(self.axis_paths) == bool(self.evaluations), "empty stage must have zero budget and vice versa")
        object.__setattr__(self, "axis_paths", tuple(self.axis_paths))

    def to_dict(self):
        return {
            "id": self.id,
            "axis_paths": list(self.axis_paths),
            "evaluations": self.evaluations,
            "retain_cap": self.retain_cap,
            "proposal": self.proposal,
        }


@dataclass(frozen=True)
class StagedPlan:
    stages: tuple[StageDefinition, ...]
    version: str = VERSION

    def __post_init__(self):
        require(self.version == VERSION, "unsupported staged plan version")
        require(type(self.stages) is tuple and len(self.stages) == 3, "exactly three frozen stages required")
        require(tuple(x.id for x in self.stages) == STAGE_IDS, "stages must use frozen A/B/C order")
        axes = [path for stage in self.stages for path in stage.axis_paths]
        require(len(axes) == len(set(axes)), "an axis may belong to only one stage")
        require(1 <= sum(x.evaluations for x in self.stages) <= 256, "invalid total staged budget")
        object.__setattr__(self, "stages", tuple(self.stages))

    def validate_request(self, request):
        declared = tuple(a.path for a in request.domain.axes)
        staged = tuple(sorted(path for stage in self.stages for path in stage.axis_paths))
        require(staged == declared, "staged plan must partition the request domain exactly")
        require(sum(x.evaluations for x in self.stages) == request.budget.max_evaluations,
                "staged plan budget must equal declared logical search budget")
        return self

    def to_dict(self):
        return {
            "kind": "ZG024dStagedPlan",
            "version": self.version,
            "method_id": METHOD_ID,
            "stages": [x.to_dict() for x in self.stages],
            "promotion": "eligible-fit-best plus eligible Pareto diversity, deterministic cap; holdouts absent",
            "selection": "global fit-only eligible ranking across all evaluated candidates",
            "logical_budget": "unique candidate evaluations; duplicates do not consume budget",
        }

    @property
    def sha256(self):
        return digest(self.to_dict())


@dataclass(frozen=True)
class StagedCheckpoint:
    run_id: str
    plan_sha256: str
    environment_sha256: str
    next_ordinal: int
    evaluation_sha256s: tuple[str, ...]
    parent_checkpoint_sha256: str | None = None

    def __post_init__(self):
        sha(self.run_id, "run_id")
        sha(self.plan_sha256, "plan_sha256")
        sha(self.environment_sha256, "environment_sha256")
        require(type(self.next_ordinal) is int and 0 <= self.next_ordinal <= 256, "invalid next_ordinal")
        require(self.next_ordinal == len(self.evaluation_sha256s), "checkpoint prefix length mismatch")
        for value in self.evaluation_sha256s:
            sha(value, "evaluation_sha256")
        if self.parent_checkpoint_sha256 is not None:
            sha(self.parent_checkpoint_sha256, "parent_checkpoint_sha256")
        object.__setattr__(self, "evaluation_sha256s", tuple(self.evaluation_sha256s))

    def to_dict(self):
        return {
            "kind": "ZG024dStagedCheckpoint",
            "version": VERSION,
            "run_id": self.run_id,
            "plan_sha256": self.plan_sha256,
            "environment_sha256": self.environment_sha256,
            "next_ordinal": self.next_ordinal,
            "evaluation_sha256s": list(self.evaluation_sha256s),
            "parent_checkpoint_sha256": self.parent_checkpoint_sha256,
            "policy": "verified-adaptive-prefix-replay-v1",
        }

    @property
    def sha256(self):
        return digest(self.to_dict())


class StagedInterrupted(JobCancelled):
    def __init__(self, checkpoint):
        self.checkpoint = checkpoint
        super().__init__("ZG-024d staged search cancelled; completed verified prefix retained")


class StagedResumeDivergence(InverseError):
    def __init__(self, checkpoint, reason, actual=None):
        self.checkpoint, self.reason, self.actual = checkpoint, reason, actual
        super().__init__("ZG-024d resume divergence: " + reason)

    def to_dict(self):
        return {
            "kind": "ZG024dResumeDivergence",
            "version": VERSION,
            "checkpoint_sha256": self.checkpoint.sha256,
            "reason": self.reason,
            "actual": self.actual,
        }


@dataclass(frozen=True)
class StagedResult:
    run_id: str
    evaluator_search_id: str
    plan: StagedPlan
    candidates: tuple[Candidate, ...]
    lineage: tuple[dict, ...]
    promotions: tuple[dict, ...]
    ranked_candidate_ids: tuple[str, ...]
    pareto_candidate_ids: tuple[str, ...]
    checkpoint: StagedCheckpoint
    declared_budget: int
    proposal_attempts: int

    def __post_init__(self):
        sha(self.run_id, "run_id")
        sha(self.evaluator_search_id, "evaluator_search_id")
        require(isinstance(self.plan, StagedPlan), "StagedPlan required")
        require(len(self.candidates) == len(self.lineage) == self.checkpoint.next_ordinal, "result prefix mismatch")
        require(len(self.candidates) <= self.declared_budget, "logical budget exceeded")
        require(self.proposal_attempts >= len(self.candidates), "proposal attempts below evaluations")
        require(tuple(row["candidate_id"] for row in self.lineage) == tuple(c.id for c in self.candidates),
                "lineage/candidate mismatch")

    def to_dict(self):
        return {
            "kind": "ZG024dStagedResult",
            "version": VERSION,
            "run_id": self.run_id,
            "evaluator_search_id": self.evaluator_search_id,
            "plan": self.plan.to_dict(),
            "research_implementation": research_implementation(),
            "candidates": [c.to_dict() for c in self.candidates],
            "lineage": [_canonical(x) for x in self.lineage],
            "promotions": [_canonical(x) for x in self.promotions],
            "ranked_candidate_ids": list(self.ranked_candidate_ids),
            "pareto_candidate_ids": list(self.pareto_candidate_ids),
            "checkpoint": self.checkpoint.to_dict(),
            "budget": {
                "declared_evaluations": self.declared_budget,
                "consumed_evaluations": len(self.candidates),
                "unspent_evaluations": self.declared_budget - len(self.candidates),
                "proposal_attempts": self.proposal_attempts,
                "unit": "unique logical candidate evaluations; foundation evaluator verifies cold renders twice",
            },
            "selection": "fit-only eligibility/score; truth and holdouts absent from proposal, promotion, ranking and stopping",
        }

    @property
    def sha256(self):
        return digest(self.to_dict())

    def audit_selection(self, *, all_candidates=False):
        ids = tuple(c.id for c in self.candidates) if all_candidates else self.ranked_candidate_ids
        require(ids, "no eligible fitted candidate available")
        return AuditSelection(self.evaluator_search_id, ids)


def _splitmix64(value):
    z = (value + 0x9E3779B97F4A7C15) & MASK64
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK64
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK64
    return (z ^ (z >> 31)) & MASK64


def _unit64(value):
    return ((value >> 11) & ((1 << 53) - 1)) / float(1 << 53)


def _radical_inverse(index, base):
    require(type(index) is int and index >= 1, "Halton index must be >= 1")
    result, factor = 0.0, 1.0 / base
    while index:
        index, digit = divmod(index, base)
        result += digit * factor
        factor /= base
    return result


def _axis_value(axis, unit):
    if axis.numeric_type == "integer":
        count = int(axis.upper - axis.lower) + 1
        return int(axis.lower) + min(count - 1, int(unit * count))
    return axis.lower + unit * (axis.upper - axis.lower)


def _replace_axes(request, base_state, axis_paths, units):
    require(len(axis_paths) == len(units), "staged coordinate count mismatch")
    values = dict(base_state.values)
    by_path = {a.path: a for a in request.domain.axes}
    for path, unit in zip(axis_paths, units):
        require(path in by_path, "staged axis outside request domain")
        require(type(unit) in (int, float) and math.isfinite(unit) and 0.0 <= unit < 1.0,
                "unit coordinate outside [0,1)")
        values[path] = _axis_value(by_path[path], float(unit))
    return request.domain.validate_state(ParameterState(tuple(values.items())))


def _halton_units(request, axis_paths, attempt, label):
    require(len(axis_paths) <= len(PRIMES), "too many staged Halton axes")
    seed = int(derive_seed(request.seed, "zg024d-" + label)) & MASK64
    units = []
    for index, prime in enumerate(PRIMES[:len(axis_paths)]):
        shift = _unit64(_splitmix64(seed ^ ((index + 1) * 0x9E3779B97F4A7C15 & MASK64)))
        units.append((_radical_inverse(attempt + 1, prime) + shift) % 1.0)
    return tuple(units)


def _candidate_sort_key(candidate):
    d = candidate.to_dict()
    values = tuple(value for _, value in ParameterState.from_dict(d["parameters"]).values)
    score = candidate.score if candidate.score is not None and math.isfinite(candidate.score) else math.inf
    return (0 if candidate.eligible else 1, score, values, candidate.id)


def _promote(stage_id, candidates, retain_cap):
    eligible = sorted((c for c in candidates if c.eligible), key=_candidate_sort_key)
    pareto_ids = set(pareto_front(candidates))
    selected = []
    # Fit-best is always first.  Then preserve distinct eligible Pareto alternatives
    # until the frozen cap; remaining slots use deterministic fit order.
    if eligible:
        selected.append(eligible[0])
    for candidate in eligible:
        if len(selected) >= retain_cap:
            break
        if candidate.id in pareto_ids and candidate not in selected:
            selected.append(candidate)
    for candidate in eligible:
        if len(selected) >= retain_cap:
            break
        if candidate not in selected:
            selected.append(candidate)
    return tuple(selected), {
        "stage_id": stage_id,
        "eligible_count": len(eligible),
        "pareto_count": sum(c.id in pareto_ids for c in eligible),
        "retain_cap": retain_cap,
        "retained_candidate_ids": [c.id for c in selected],
        "reason": "fit-best then eligible Pareto diversity then fit order; deterministic cap; holdouts absent",
    }


def _run_id(evaluator, plan):
    require(isinstance(evaluator, FitEvaluator), "staged search requires fit-only FitEvaluator")
    plan.validate_request(evaluator.request)
    return digest({
        "domain": "zaaggenz.zg024d-staged-run-v1",
        "evaluator_search_id": evaluator.search_id,
        "plan": plan.to_dict(),
        "research_implementation_sha256": research_implementation_sha256(),
        "environment_sha256": evaluator.environment_sha256,
        "declared_budget": evaluator.request.budget.max_evaluations,
    })


def run_staged(evaluator, plan, *, checkpoint=None, check_cancelled=lambda: None,
               progress=lambda value: None, on_checkpoint=lambda cp: None):
    """Run the frozen three-stage strategy under the accepted one-thread numerical policy."""
    require(isinstance(evaluator, FitEvaluator), "run_staged accepts only the fit-only capability")
    require(isinstance(plan, StagedPlan), "StagedPlan required")
    plan.validate_request(evaluator.request)
    controller = numeric_thread_limit(1)
    with controller if controller is not None else nullcontext():
        return _run_staged(evaluator, plan, checkpoint=checkpoint, check_cancelled=check_cancelled,
                           progress=progress, on_checkpoint=on_checkpoint)


def _run_staged(evaluator, plan, *, checkpoint, check_cancelled, progress, on_checkpoint):
    request = evaluator.request
    run_id = _run_id(evaluator, plan)
    replay = 0
    current = StagedCheckpoint(run_id, plan.sha256, evaluator.environment_sha256, 0, ())
    if checkpoint is not None:
        require(isinstance(checkpoint, StagedCheckpoint), "StagedCheckpoint required")
        if checkpoint.run_id != run_id or checkpoint.plan_sha256 != plan.sha256:
            raise StagedResumeDivergence(checkpoint, "request/plan/implementation changed", run_id)
        if checkpoint.environment_sha256 != evaluator.environment_sha256:
            raise StagedResumeDivergence(checkpoint, "numerical environment changed", evaluator.environment_sha256)
        require(checkpoint.next_ordinal <= request.budget.max_evaluations, "checkpoint exceeds declared budget")
        replay, current = checkpoint.next_ordinal, checkpoint

    base = state_from_recipe(request.base_recipe, request.domain)
    candidates, lineage, promotions = [], [], []
    seen = set()
    proposal_attempts = 0
    parents = ()

    def evaluate_state(state, stage, proposal, parent_ids=()):
        nonlocal current, proposal_attempts
        proposal_attempts += 1
        if state.sha256 in seen:
            return None
        seen.add(state.sha256)
        ordinal = len(candidates)
        if ordinal >= request.budget.max_evaluations:
            return None
        candidate = evaluator.evaluate(state, ordinal, check_cancelled=check_cancelled,
                                       force_recheck=ordinal < replay)
        if ordinal < replay and candidate.sha256 != checkpoint.evaluation_sha256s[ordinal]:
            raise StagedResumeDivergence(checkpoint, f"completed candidate {ordinal} failed exact replay",
                                         candidate.sha256)
        candidates.append(candidate)
        lineage.append({
            "ordinal": ordinal,
            "candidate_id": candidate.id,
            "stage_id": stage.id,
            "parent_candidate_ids": list(parent_ids),
            "proposal": proposal,
            "promotion_policy": "parents were selected using fit-only evidence before this stage",
        })
        if ordinal >= replay:
            current = StagedCheckpoint(run_id, plan.sha256, evaluator.environment_sha256, ordinal + 1,
                tuple(c.sha256 for c in candidates), current.sha256)
            on_checkpoint(current)
        progress((ordinal + 1) / request.budget.max_evaluations)
        return candidate

    try:
        for stage_index, stage in enumerate(plan.stages):
            if stage.evaluations == 0:
                promotions.append({
                    "stage_id": stage.id, "eligible_count": 0, "pareto_count": 0,
                    "retain_cap": stage.retain_cap,
                    "retained_candidate_ids": [c.id for c in parents],
                    "reason": "stage has no axes/budget; previous parents carried without evaluation",
                })
                continue
            stage_candidates = []
            stage_start = len(candidates)
            max_attempts = max(64, stage.evaluations * 128)
            attempt = 0
            fallback = 0
            while len(stage_candidates) < stage.evaluations and attempt < max_attempts:
                check_cancelled()
                if stage_index == 0 or not parents:
                    parent = None
                    parent_state = base
                    parent_ids = ()
                else:
                    parent = parents[attempt % len(parents)]
                    parent_state = ParameterState.from_dict(parent.to_dict()["parameters"])
                    parent_ids = (parent.id,)

                if stage.id in ("stage-a-root-envelope", "stage-b-spectral"):
                    label = stage.id + ("-base" if parent is None else "-" + parent.id[:16])
                    units = _halton_units(request, stage.axis_paths, attempt, label)
                    state = _replace_axes(request, parent_state, stage.axis_paths, units)
                    proposal = {
                        "family": stage.proposal,
                        "attempt": attempt,
                        "units": list(units),
                    }
                else:
                    by_path = {a.path: a for a in request.domain.axes}
                    local_index = attempt // max(1, len(parents)) if parents else attempt
                    axis_index = (local_index // 2) % len(stage.axis_paths)
                    direction = -1 if local_index % 2 == 0 else 1
                    round_index = local_index // (2 * len(stage.axis_paths))
                    radius_fraction = 0.25 * (0.5 ** round_index)
                    path = stage.axis_paths[axis_index]
                    axis = by_path[path]
                    values = dict(parent_state.values)
                    value = values[path] + direction * radius_fraction * (axis.upper - axis.lower)
                    value = max(axis.lower, min(axis.upper, value))
                    if axis.numeric_type == "integer":
                        value = max(int(axis.lower), min(int(axis.upper), int(round(value))))
                    values[path] = value
                    state = request.domain.validate_state(ParameterState(tuple(values.items())))
                    proposal = {
                        "family": stage.proposal,
                        "attempt": attempt,
                        "axis": path,
                        "direction": direction,
                        "round": round_index,
                        "radius_fraction": radius_fraction,
                    }
                result = evaluate_state(state, stage, proposal, parent_ids)
                attempt += 1
                if result is not None:
                    stage_candidates.append(result)

                # Boundary clipping and integer axes can exhaust local coordinate probes.
                # A labelled stage-local Halton fallback consumes remaining unique budget;
                # it is never presented as coordinate refinement.
                if (stage.id == "stage-c-texture" and attempt >= max(16, stage.evaluations * 4)
                        and len(stage_candidates) < stage.evaluations):
                    while len(stage_candidates) < stage.evaluations and fallback < stage.evaluations * 128:
                        check_cancelled()
                        if parents:
                            parent = parents[fallback % len(parents)]
                            parent_state = ParameterState.from_dict(parent.to_dict()["parameters"])
                            parent_ids = (parent.id,)
                        else:
                            parent_state, parent_ids = base, ()
                        units = _halton_units(request, stage.axis_paths, fallback, stage.id + "-fallback")
                        state = _replace_axes(request, parent_state, stage.axis_paths, units)
                        result = evaluate_state(state, stage, {
                            "family": "stage-c-halton-fallback-v1",
                            "attempt": fallback,
                            "units": list(units),
                            "reason": "coordinate clipping/duplicate budget protection",
                        }, parent_ids)
                        fallback += 1
                        if result is not None:
                            stage_candidates.append(result)
                    break

            require(len(candidates) >= replay or stage_start >= replay,
                    "resume prefix could not be deterministically regenerated")
            parents, row = _promote(stage.id, stage_candidates, stage.retain_cap)
            promotions.append(row)
            # If an entire stage has no eligible result, do not smuggle rejected
            # candidates into an adaptive parent role.  Later stages may restart from
            # the declared base state and the failure remains explicit in evidence.
        check_cancelled()
    except JobCancelled as exc:
        raise StagedInterrupted(current) from exc

    require(len(candidates) >= replay, "resume prefix could not be deterministically regenerated")
    eligible = sorted((c for c in candidates if c.eligible), key=_candidate_sort_key)
    return StagedResult(
        run_id, evaluator.search_id, plan, tuple(candidates), tuple(lineage), tuple(promotions),
        tuple(c.id for c in eligible), pareto_front(candidates), current,
        request.budget.max_evaluations, proposal_attempts,
    )
