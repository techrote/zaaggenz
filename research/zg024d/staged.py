"""ZG-024d preregistered deterministic staged-search research.

This pass is deliberately layered outside :mod:`zaaggenz_inverse` and the frozen
ZG-024b baseline implementation.  The runner accepts only a ``FitEvaluator``;
fixture truth and holdout/audit samples are not capabilities of this module.
"""
from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
import hashlib
from pathlib import Path

from zaaggenz_contracts import digest
from zaaggenz_inverse import FitEvaluator, ParameterState
from zaaggenz_inverse.contracts import require, sha
from zaaggenz_inverse.laboratory import AuditSelection
from zaaggenz_inverse.results import Candidate, pareto_front
from zaaggenz_inverse.search import estimate_memory_bytes
from zaaggenz_jobs import JobClass
from zaaggenz_jobs.model import numeric_thread_limit
from research.zg024b.strategies import (
    _candidate_sort_key,
    _coordinate_proposals,
    _halton_state,
    research_implementation_sha256 as zg024b_implementation_sha256,
)

VERSION = '1.0.0'
METHODS = (
    'zg024d.staged-h33.v1',
    'zg024d.staged-h50.v1',
    'zg024d.staged-h67.v1',
)
_GLOBAL_FRACTIONS = {
    'zg024d.staged-h33.v1': (1, 3),
    'zg024d.staged-h50.v1': (1, 2),
    'zg024d.staged-h67.v1': (2, 3),
}
_LOCAL_RADII = (0.25, 0.125, 0.0625, 0.03125, 0.015625, 0.0078125)


def research_implementation():
    text = Path(__file__).read_text(encoding='utf-8').replace('\r\n', '\n')
    return {
        'kind': 'ZG024dStagedResearchImplementation',
        'version': VERSION,
        'strategy_source_sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(),
        'zg024b_dependency_sha256': zg024b_implementation_sha256(),
        'policy': 'fit-only deterministic staged search; no target truth or holdout feedback',
    }


def research_implementation_sha256():
    return digest(research_implementation())


@dataclass(frozen=True)
class StagedSpec:
    method_id: str
    version: str = VERSION

    def __post_init__(self):
        require(self.method_id in METHODS, 'unsupported ZG-024d staged strategy')
        require(self.version == VERSION, 'unsupported ZG-024d strategy version')

    @property
    def global_fraction(self):
        return _GLOBAL_FRACTIONS[self.method_id]

    def to_dict(self):
        n, d = self.global_fraction
        return {
            'kind': 'ZG024dStagedSpec',
            'version': self.version,
            'method_id': self.method_id,
            'global_fraction': {'numerator': n, 'denominator': d},
            'local_radii': list(_LOCAL_RADII),
            'allocation': 'floor(global_fraction * logical budget), minimum one; remainder local refinement',
        }

    @property
    def sha256(self):
        return digest(self.to_dict())


@dataclass(frozen=True)
class StagedResult:
    run_id: str
    evaluator_search_id: str
    strategy: StagedSpec
    candidates: tuple[Candidate, ...]
    lineage: tuple[dict, ...]
    ranked_candidate_ids: tuple[str, ...]
    pareto_candidate_ids: tuple[str, ...]
    declared_budget: int
    global_evaluations: int
    local_evaluations: int
    proposal_attempts: int

    def __post_init__(self):
        sha(self.run_id, 'run_id')
        sha(self.evaluator_search_id, 'evaluator_search_id')
        require(isinstance(self.strategy, StagedSpec), 'StagedSpec required')
        require(len(self.candidates) == len(self.lineage), 'candidate/lineage length mismatch')
        require(len(self.candidates) == self.global_evaluations + self.local_evaluations,
                'stage accounting mismatch')
        require(len(self.candidates) <= self.declared_budget, 'logical budget exceeded')
        require(self.proposal_attempts >= len(self.candidates), 'invalid proposal attempt accounting')
        require(tuple(row['candidate_id'] for row in self.lineage) == tuple(c.id for c in self.candidates),
                'lineage/candidate mismatch')

    def to_dict(self):
        return {
            'kind': 'ZG024dStagedResult',
            'version': VERSION,
            'run_id': self.run_id,
            'evaluator_search_id': self.evaluator_search_id,
            'strategy': self.strategy.to_dict(),
            'research_implementation': research_implementation(),
            'candidates': [candidate.to_dict() for candidate in self.candidates],
            'lineage': list(self.lineage),
            'ranked_candidate_ids': list(self.ranked_candidate_ids),
            'pareto_candidate_ids': list(self.pareto_candidate_ids),
            'budget': {
                'declared_evaluations': self.declared_budget,
                'consumed_evaluations': len(self.candidates),
                'global_evaluations': self.global_evaluations,
                'local_evaluations': self.local_evaluations,
                'proposal_attempts': self.proposal_attempts,
                'unit': 'unique logical candidate evaluations; FitEvaluator retains cold-render verification semantics',
            },
            'selection': 'fit-only eligibility/score with deterministic parameter-state tie-break; holdouts absent',
        }

    @property
    def sha256(self):
        return digest(self.to_dict())

    def audit_selection(self, *, all_candidates=False):
        ids = tuple(c.id for c in self.candidates) if all_candidates else self.ranked_candidate_ids
        require(ids, 'no eligible fitted candidate available')
        return AuditSelection(self.evaluator_search_id, ids)


def _run_id(evaluator, strategy):
    return digest({
        'domain': 'zaaggenz.zg024d-staged-run-v1',
        'evaluator_search_id': evaluator.search_id,
        'strategy': strategy.to_dict(),
        'research_implementation_sha256': research_implementation_sha256(),
        'environment_sha256': evaluator.environment_sha256,
        'declared_budget': evaluator.request.budget.max_evaluations,
    })


def _global_count(budget, strategy):
    numerator, denominator = strategy.global_fraction
    return min(budget, max(1, (budget * numerator) // denominator))


def run_staged(evaluator, strategy, *, check_cancelled=lambda: None, progress=lambda value: None):
    """Run a preregistered global-coverage -> broad-local -> fine-local search.

    The global phase is a shifted Halton prefix.  Local rounds recenter only from
    accumulated fitting evidence and halve their radius after each coordinate sweep.
    Duplicate/clipped proposals never consume logical budget; a visibly-labelled
    Halton continuation fills any remainder rather than silently wasting budget.
    """
    require(isinstance(evaluator, FitEvaluator), 'run_staged accepts only fit-only FitEvaluator')
    require(isinstance(strategy, StagedSpec), 'StagedSpec required')
    request = evaluator.request
    budget = request.budget.max_evaluations
    global_target = _global_count(budget, strategy)
    run_id = _run_id(evaluator, strategy)
    candidates = []
    lineage = []
    seen = set()
    attempts = 0
    global_evaluations = 0

    def accept(state, proposal, parents=()):
        nonlocal attempts, global_evaluations
        attempts += 1
        if len(candidates) >= budget or state.sha256 in seen:
            return None
        seen.add(state.sha256)
        ordinal = len(candidates)
        candidate = evaluator.evaluate(state, ordinal, check_cancelled=check_cancelled)
        candidates.append(candidate)
        if proposal['stage'] == 'global':
            global_evaluations += 1
        lineage.append({
            'ordinal': ordinal,
            'candidate_id': candidate.id,
            'parent_candidate_ids': list(parents),
            'proposal': proposal,
        })
        progress((ordinal + 1) / budget)
        return candidate

    controller = numeric_thread_limit(1)
    with controller if controller is not None else nullcontext():
        # Stage 1: deterministic low-discrepancy global coverage.
        attempt = 0
        max_attempts = max(64, budget * 64)
        while len(candidates) < global_target and attempt < max_attempts:
            check_cancelled()
            state = _halton_state(request, attempt, 'zg024d-' + strategy.method_id)
            accept(state, {'stage': 'global', 'family': 'halton-shifted', 'attempt': attempt})
            attempt += 1
        require(len(candidates) == global_target, 'global stage could not fill its declared logical allocation')

        # Stages 2/3: broad then fine coordinate refinement around fit-best only.
        for round_index, radius in enumerate(_LOCAL_RADII):
            if len(candidates) >= budget:
                break
            check_cancelled()
            center = min(candidates, key=_candidate_sort_key)
            center_state = ParameterState.from_dict(center.to_dict()['parameters'])
            stage = 'broad-local' if round_index == 0 else 'fine-local'
            for state, base_proposal in _coordinate_proposals(request, center_state, radius, round_index):
                if len(candidates) >= budget:
                    break
                proposal = dict(base_proposal)
                proposal.update({'stage': stage, 'center_candidate_id': center.id})
                accept(state, proposal, (center.id,))

        # Integer axes / clipping can exhaust local unique states. Keep the declared
        # evaluation budget comparable with an explicit global-continuation fallback.
        fallback_attempt = attempt
        while len(candidates) < budget and fallback_attempt < max_attempts:
            check_cancelled()
            state = _halton_state(request, fallback_attempt, 'zg024d-' + strategy.method_id)
            accept(state, {
                'stage': 'fallback-global',
                'family': 'halton-shifted',
                'attempt': fallback_attempt,
                'reason': 'local unique-state exhaustion',
            })
            fallback_attempt += 1

    require(len(candidates) == budget, 'staged strategy could not consume exact logical budget')
    eligible = sorted((candidate for candidate in candidates if candidate.eligible), key=_candidate_sort_key)
    return StagedResult(
        run_id=run_id,
        evaluator_search_id=evaluator.search_id,
        strategy=strategy,
        candidates=tuple(candidates),
        lineage=tuple(lineage),
        ranked_candidate_ids=tuple(candidate.id for candidate in eligible),
        pareto_candidate_ids=pareto_front(candidates),
        declared_budget=budget,
        global_evaluations=global_evaluations,
        local_evaluations=len(candidates) - global_evaluations,
        proposal_attempts=attempts,
    )


def submit_staged_job(scheduler, evaluator, strategy):
    require(isinstance(evaluator, FitEvaluator), 'FitEvaluator required')
    require(isinstance(strategy, StagedSpec), 'StagedSpec required')

    def execute(ctx):
        ctx.check_cancelled()
        return run_staged(evaluator, strategy, check_cancelled=ctx.check_cancelled, progress=ctx.progress)

    return scheduler.submit(
        JobClass.RESEARCH,
        evaluator.request.source_revision_id,
        execute,
        estimated_memory_bytes=estimate_memory_bytes(evaluator),
    )
