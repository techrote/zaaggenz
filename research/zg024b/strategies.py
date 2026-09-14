"""ZG-024b deterministic strategy research layered on the frozen ZG-024a laboratory.

This module deliberately lives outside ``zaaggenz_inverse`` so pass-1 implementation
identity and calibration remain byte-for-byte reproducible. Strategies receive only a
FitEvaluator. Fixture truth and AuditEvaluator are not accepted by this API.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from contextlib import nullcontext
import hashlib
import json
import math
from pathlib import Path

from zaaggenz_contracts import derive_seed, digest
from zaaggenz_jobs import JobCancelled, JobClass
from zaaggenz_jobs.model import numeric_thread_limit
from zaaggenz_inverse import FitEvaluator, ParameterState
from zaaggenz_inverse.results import Candidate, pareto_front
from zaaggenz_inverse.search import grid_state, grid_levels, estimate_memory_bytes
from zaaggenz_inverse.contracts import InverseError, require, sha
from zaaggenz_inverse.recipes import state_from_recipe, engine_identity
from zaaggenz_inverse.laboratory import AuditSelection

VERSION = '1.0.0'
MASK64 = (1 << 64) - 1
PRIMES = (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53)
METHODS = (
    'zg024b.grid-prefix.v1',
    'zg024b.uniform-splitmix.v1',
    'zg024b.halton-shifted.v1',
    'zg024b.coordinate-refine.v1',
)


def _canonical(value):
    if isinstance(value, tuple):
        return [_canonical(x) for x in value]
    if isinstance(value, dict):
        return {k: _canonical(v) for k, v in value.items()}
    return value


def research_implementation():
    path = Path(__file__)
    text = path.read_text(encoding='utf-8').replace('\r\n', '\n')
    return {
        'kind': 'ZG024bResearchImplementation',
        'version': VERSION,
        'strategy_source_sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(),
        'foundation_engine_sha256': engine_identity(),
        'numerical_policy': 'same-environment exact candidate replay; portable metrics compared separately',
    }


def research_implementation_sha256():
    return digest(research_implementation())


@dataclass(frozen=True)
class StrategySpec:
    method_id: str
    version: str = VERSION

    def __post_init__(self):
        require(self.method_id in METHODS, 'unsupported ZG-024b strategy')
        require(self.version == VERSION, 'unsupported ZG-024b strategy version')

    def to_dict(self):
        return {'kind': 'ZG024bStrategySpec', 'version': self.version, 'method_id': self.method_id}

    @property
    def sha256(self):
        return digest(self.to_dict())


@dataclass(frozen=True)
class ResearchCheckpoint:
    run_id: str
    environment_sha256: str
    next_ordinal: int
    evaluation_sha256s: tuple[str, ...]
    parent_checkpoint_sha256: str | None = None

    def __post_init__(self):
        sha(self.run_id, 'run_id')
        sha(self.environment_sha256, 'environment_sha256')
        require(type(self.next_ordinal) is int and 0 <= self.next_ordinal <= 256, 'invalid next_ordinal')
        require(self.next_ordinal == len(self.evaluation_sha256s), 'checkpoint prefix length mismatch')
        for value in self.evaluation_sha256s:
            sha(value, 'evaluation_sha256')
        if self.parent_checkpoint_sha256 is not None:
            sha(self.parent_checkpoint_sha256, 'parent_checkpoint_sha256')
        object.__setattr__(self, 'evaluation_sha256s', tuple(self.evaluation_sha256s))

    def to_dict(self):
        return {
            'kind': 'ZG024bResearchCheckpoint', 'version': VERSION,
            'run_id': self.run_id, 'environment_sha256': self.environment_sha256,
            'next_ordinal': self.next_ordinal,
            'evaluation_sha256s': list(self.evaluation_sha256s),
            'parent_checkpoint_sha256': self.parent_checkpoint_sha256,
            'policy': 'verified-prefix-replay-v1',
        }

    @property
    def sha256(self):
        return digest(self.to_dict())


class ResearchInterrupted(JobCancelled):
    def __init__(self, checkpoint):
        self.checkpoint = checkpoint
        super().__init__('ZG-024b strategy cancelled; completed prefix checkpoint retained')


class ResearchResumeDivergence(InverseError):
    def __init__(self, checkpoint, reason, actual=None):
        self.checkpoint, self.reason, self.actual = checkpoint, reason, actual
        super().__init__('ZG-024b resume divergence: ' + reason)

    def to_dict(self):
        return {
            'kind': 'ZG024bResumeDivergence', 'version': VERSION,
            'checkpoint_sha256': self.checkpoint.sha256,
            'reason': self.reason, 'actual': self.actual,
        }


@dataclass(frozen=True)
class StrategyResult:
    run_id: str
    evaluator_search_id: str
    strategy: StrategySpec
    candidates: tuple[Candidate, ...]
    lineage: tuple[dict, ...]
    ranked_candidate_ids: tuple[str, ...]
    pareto_candidate_ids: tuple[str, ...]
    checkpoint: ResearchCheckpoint
    declared_budget: int
    proposal_attempts: int

    def __post_init__(self):
        sha(self.run_id, 'run_id')
        sha(self.evaluator_search_id, 'evaluator_search_id')
        require(isinstance(self.strategy, StrategySpec), 'StrategySpec required')
        require(len(self.candidates) == len(self.lineage) == self.checkpoint.next_ordinal, 'result prefix mismatch')
        require(len(self.candidates) <= self.declared_budget, 'logical budget exceeded')
        require(self.proposal_attempts >= len(self.candidates), 'proposal attempts cannot be below evaluations')
        require(tuple(row['candidate_id'] for row in self.lineage) == tuple(c.id for c in self.candidates), 'lineage/candidate mismatch')

    def to_dict(self):
        return {
            'kind': 'ZG024bStrategyResult', 'version': VERSION,
            'run_id': self.run_id, 'evaluator_search_id': self.evaluator_search_id,
            'strategy': self.strategy.to_dict(),
            'research_implementation': research_implementation(),
            'candidates': [c.to_dict() for c in self.candidates],
            'lineage': [_canonical(x) for x in self.lineage],
            'ranked_candidate_ids': list(self.ranked_candidate_ids),
            'pareto_candidate_ids': list(self.pareto_candidate_ids),
            'checkpoint': self.checkpoint.to_dict(),
            'budget': {
                'declared_evaluations': self.declared_budget,
                'consumed_evaluations': len(self.candidates),
                'unspent_evaluations': self.declared_budget-len(self.candidates),
                'proposal_attempts': self.proposal_attempts,
                'unit': 'unique logical candidate evaluations; foundation evaluator verifies cold renders twice',
            },
            'selection': 'fit-only eligibility, score and deterministic parameter-state tie-break; holdouts absent',
        }

    @property
    def sha256(self):
        return digest(self.to_dict())

    def audit_selection(self, *, all_candidates=False):
        ids = tuple(c.id for c in self.candidates) if all_candidates else self.ranked_candidate_ids
        require(ids, 'no eligible fitted candidate available')
        return AuditSelection(self.evaluator_search_id, ids)


def _splitmix64(value):
    z = (value + 0x9E3779B97F4A7C15) & MASK64
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK64
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK64
    return (z ^ (z >> 31)) & MASK64


def _unit64(value):
    # Top 53 bits -> exact IEEE-754 unit interval value in [0,1).
    return ((value >> 11) & ((1 << 53)-1)) / float(1 << 53)


def _radical_inverse(index, base):
    require(type(index) is int and index >= 1, 'Halton index must be >=1')
    result, factor = 0.0, 1.0/base
    while index:
        index, digit = divmod(index, base)
        result += digit*factor
        factor /= base
    return result


def _state_from_units(request, units):
    require(len(units) == len(request.domain.axes), 'coordinate count mismatch')
    values = []
    for axis, u in zip(request.domain.axes, units):
        require(type(u) in (int, float) and math.isfinite(u) and 0.0 <= u < 1.0, 'unit coordinate outside [0,1)')
        if axis.numeric_type == 'integer':
            count = int(axis.upper-axis.lower)+1
            value = int(axis.lower) + min(count-1, int(u*count))
        else:
            value = axis.lower + float(u)*(axis.upper-axis.lower)
        values.append((axis.path, value))
    return request.domain.validate_state(ParameterState(tuple(values)))


def _uniform_state(request, attempt, label='uniform'):
    seed = int(derive_seed(request.seed, 'zg024b-' + label)) & MASK64
    units = []
    for axis_index in range(len(request.domain.axes)):
        mixed = _splitmix64(seed ^ ((attempt+1)*0xD1342543DE82EF95 & MASK64) ^
                            ((axis_index+1)*0xA24BAED4963EE407 & MASK64))
        units.append(_unit64(mixed))
    return _state_from_units(request, units)


def _halton_state(request, attempt, label='halton'):
    require(len(request.domain.axes) <= len(PRIMES), 'too many axes for declared Halton bases')
    seed = int(derive_seed(request.seed, 'zg024b-' + label)) & MASK64
    units = []
    for axis_index, prime in enumerate(PRIMES[:len(request.domain.axes)]):
        shift = _unit64(_splitmix64(seed ^ ((axis_index+1)*0x9E3779B97F4A7C15 & MASK64)))
        units.append((_radical_inverse(attempt+1, prime) + shift) % 1.0)
    return _state_from_units(request, units)


def _candidate_sort_key(candidate):
    d = candidate.to_dict()
    values = tuple(value for _, value in ParameterState.from_dict(d['parameters']).values)
    score = candidate.score if candidate.score is not None and math.isfinite(candidate.score) else math.inf
    return (0 if candidate.eligible else 1, score, values, candidate.id)


def _research_run_id(evaluator, strategy):
    require(isinstance(evaluator, FitEvaluator), 'strategy research requires fit-only FitEvaluator')
    require(isinstance(strategy, StrategySpec), 'StrategySpec required')
    return digest({
        'domain': 'zaaggenz.zg024b-strategy-run-v1',
        'evaluator_search_id': evaluator.search_id,
        'strategy': strategy.to_dict(),
        'research_implementation_sha256': research_implementation_sha256(),
        'environment_sha256': evaluator.environment_sha256,
        'declared_budget': evaluator.request.budget.max_evaluations,
    })


def _static_proposal(request, strategy, attempt):
    if strategy.method_id == 'zg024b.grid-prefix.v1':
        total = math.prod(len(v) for v in grid_levels(request))
        if attempt >= total:
            return None, {'family': 'grid-prefix', 'attempt': attempt, 'grid_size': total}
        return grid_state(request, attempt), {'family': 'grid-prefix', 'attempt': attempt, 'grid_size': total}
    if strategy.method_id == 'zg024b.uniform-splitmix.v1':
        return _uniform_state(request, attempt), {'family': 'uniform-splitmix', 'attempt': attempt}
    if strategy.method_id == 'zg024b.halton-shifted.v1':
        return _halton_state(request, attempt), {'family': 'halton-shifted', 'attempt': attempt}
    raise InverseError('not a static ZG-024b strategy')


def _coordinate_proposals(request, center_state, radius_fraction, round_index):
    values = dict(center_state.values)
    proposals = []
    for axis_index, axis in enumerate(request.domain.axes):
        center = values[axis.path]
        delta = radius_fraction*(axis.upper-axis.lower)
        for sign in (-1, 1):
            value = max(axis.lower, min(axis.upper, center + sign*delta))
            if axis.numeric_type == 'integer':
                value = int(round(value))
                value = max(int(axis.lower), min(int(axis.upper), value))
            state_values = dict(values)
            state_values[axis.path] = value
            state = request.domain.validate_state(ParameterState(tuple(state_values.items())))
            proposals.append((state, {'family': 'coordinate-refine', 'round': round_index,
                                      'axis': axis.path, 'direction': sign,
                                      'radius_fraction': radius_fraction}))
    return proposals


def _evaluate(evaluator, state, ordinal, replay, checkpoint, check_cancelled):
    candidate = evaluator.evaluate(state, ordinal, check_cancelled=check_cancelled,
                                   force_recheck=ordinal < replay)
    if ordinal < replay and candidate.sha256 != checkpoint.evaluation_sha256s[ordinal]:
        raise ResearchResumeDivergence(checkpoint, f'completed candidate {ordinal} failed exact replay', candidate.sha256)
    return candidate


def _final_result(evaluator, strategy, run_id, candidates, lineage, checkpoint, proposal_attempts):
    eligible = sorted((c for c in candidates if c.eligible), key=_candidate_sort_key)
    return StrategyResult(
        run_id, evaluator.search_id, strategy, tuple(candidates), tuple(lineage),
        tuple(c.id for c in eligible), pareto_front(candidates), checkpoint,
        evaluator.request.budget.max_evaluations, proposal_attempts,
    )


def _run_static(evaluator, strategy, checkpoint, check_cancelled, progress, on_checkpoint):
    request = evaluator.request
    run_id = _research_run_id(evaluator, strategy)
    replay = 0
    current = ResearchCheckpoint(run_id, evaluator.environment_sha256, 0, ())
    if checkpoint is not None:
        if checkpoint.run_id != run_id:
            raise ResearchResumeDivergence(checkpoint, 'strategy/request/implementation changed', run_id)
        if checkpoint.environment_sha256 != evaluator.environment_sha256:
            raise ResearchResumeDivergence(checkpoint, 'numerical environment changed', evaluator.environment_sha256)
        require(checkpoint.next_ordinal <= request.budget.max_evaluations, 'checkpoint exceeds declared budget')
        replay, current = checkpoint.next_ordinal, checkpoint
    candidates, lineage, seen = [], [], set()
    attempt = 0
    max_attempts = max(64, request.budget.max_evaluations*64)
    try:
        while len(candidates) < request.budget.max_evaluations and attempt < max_attempts:
            check_cancelled()
            state, proposal = _static_proposal(request, strategy, attempt)
            attempt += 1
            if state is None:
                break
            if state.sha256 in seen:
                continue
            seen.add(state.sha256)
            ordinal = len(candidates)
            candidate = _evaluate(evaluator, state, ordinal, replay, checkpoint, check_cancelled)
            candidates.append(candidate)
            lineage.append({'ordinal': ordinal, 'candidate_id': candidate.id,
                            'parent_candidate_ids': [], 'proposal': proposal})
            if ordinal >= replay:
                current = ResearchCheckpoint(run_id, evaluator.environment_sha256, ordinal+1,
                    tuple(c.sha256 for c in candidates), current.sha256)
                on_checkpoint(current)
            progress((ordinal+1)/request.budget.max_evaluations)
        check_cancelled()
    except JobCancelled as exc:
        raise ResearchInterrupted(current) from exc
    require(len(candidates) >= replay, 'resume prefix could not be regenerated')
    return _final_result(evaluator, strategy, run_id, candidates, lineage, current, attempt)


def _run_coordinate(evaluator, strategy, checkpoint, check_cancelled, progress, on_checkpoint):
    request = evaluator.request
    run_id = _research_run_id(evaluator, strategy)
    replay = 0
    current = ResearchCheckpoint(run_id, evaluator.environment_sha256, 0, ())
    if checkpoint is not None:
        if checkpoint.run_id != run_id:
            raise ResearchResumeDivergence(checkpoint, 'strategy/request/implementation changed', run_id)
        if checkpoint.environment_sha256 != evaluator.environment_sha256:
            raise ResearchResumeDivergence(checkpoint, 'numerical environment changed', evaluator.environment_sha256)
        replay, current = checkpoint.next_ordinal, checkpoint
    candidates, lineage, seen = [], [], set()
    attempts = 0

    def accept(state, proposal, parents=()):
        nonlocal current, attempts
        attempts += 1
        if state.sha256 in seen or len(candidates) >= request.budget.max_evaluations:
            return None
        seen.add(state.sha256)
        ordinal = len(candidates)
        candidate = _evaluate(evaluator, state, ordinal, replay, checkpoint, check_cancelled)
        candidates.append(candidate)
        lineage.append({'ordinal': ordinal, 'candidate_id': candidate.id,
                        'parent_candidate_ids': list(parents), 'proposal': proposal})
        if ordinal >= replay:
            current = ResearchCheckpoint(run_id, evaluator.environment_sha256, ordinal+1,
                tuple(c.sha256 for c in candidates), current.sha256)
            on_checkpoint(current)
        progress((ordinal+1)/request.budget.max_evaluations)
        return candidate

    try:
        check_cancelled()
        initial = _halton_state(request, 0, 'coordinate-initial')
        center_candidate = accept(initial, {'family': 'coordinate-refine', 'phase': 'initial-halton'})
        require(center_candidate is not None, 'coordinate initial state unexpectedly duplicated')
        round_index, radius = 0, 0.5
        stagnant_rounds = 0
        while len(candidates) < request.budget.max_evaluations and round_index < 64:
            check_cancelled()
            center_state = ParameterState.from_dict(min(candidates, key=_candidate_sort_key).to_dict()['parameters'])
            center_id = min(candidates, key=_candidate_sort_key).id
            before = len(candidates)
            for state, proposal in _coordinate_proposals(request, center_state, radius, round_index):
                if len(candidates) >= request.budget.max_evaluations:
                    break
                accept(state, proposal, (center_id,))
            if len(candidates) == before:
                stagnant_rounds += 1
            else:
                stagnant_rounds = 0
            radius *= 0.5
            round_index += 1
            if stagnant_rounds >= 4:
                # Deterministic global fallback prevents boundary clipping from silently
                # wasting a declared logical budget. It is labeled, not hidden.
                fallback_attempt = 0
                while len(candidates) < request.budget.max_evaluations and fallback_attempt < request.budget.max_evaluations*64:
                    state = _halton_state(request, fallback_attempt, 'coordinate-fallback')
                    accept(state, {'family': 'coordinate-refine', 'phase': 'halton-fallback',
                                   'attempt': fallback_attempt}, (center_id,))
                    fallback_attempt += 1
                break
        check_cancelled()
    except JobCancelled as exc:
        raise ResearchInterrupted(current) from exc
    require(len(candidates) >= replay, 'resume prefix could not be regenerated')
    return _final_result(evaluator, strategy, run_id, candidates, lineage, current, attempts)


def run_strategy(evaluator, strategy, *, checkpoint=None, check_cancelled=lambda: None,
                 progress=lambda value: None, on_checkpoint=lambda cp: None):
    require(isinstance(evaluator, FitEvaluator), 'run_strategy accepts only the fit-only capability')
    require(isinstance(strategy, StrategySpec), 'StrategySpec required')
    controller = numeric_thread_limit(1)
    with controller if controller is not None else nullcontext():
        if strategy.method_id == 'zg024b.coordinate-refine.v1':
            return _run_coordinate(evaluator, strategy, checkpoint, check_cancelled, progress, on_checkpoint)
        return _run_static(evaluator, strategy, checkpoint, check_cancelled, progress, on_checkpoint)


def submit_strategy_job(scheduler, evaluator, strategy, *, checkpoint=None, on_checkpoint=lambda cp: None):
    require(isinstance(evaluator, FitEvaluator), 'FitEvaluator required')
    require(isinstance(strategy, StrategySpec), 'StrategySpec required')
    def execute(ctx):
        ctx.check_cancelled()
        return run_strategy(evaluator, strategy, checkpoint=checkpoint, check_cancelled=ctx.check_cancelled,
                            progress=ctx.progress, on_checkpoint=on_checkpoint)
    return scheduler.submit(JobClass.RESEARCH, evaluator.request.source_revision_id, execute,
                            estimated_memory_bytes=estimate_memory_bytes(evaluator))
