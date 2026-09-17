"""ZG-024d complete three-stage deterministic-search research.

The strategy sees only :class:`FitEvaluator`. Fixture truth and AuditEvaluator are
orchestration capabilities and are intentionally absent here.  Protocol v2 is frozen
in docs/inverse/ZG024_STAGED_PROTOCOL_V2.md before confirmation fixtures are added.
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

VERSION = '2.0.0'
RETAIN_ALTERNATIVES = 4
LOCAL_RADII = (0.25, 0.125, 0.0625, 0.03125)
METHOD_ALLOCATIONS = {
    'zg024d.staged-balanced.v2': (8, 8, 8),
    'zg024d.staged-structure.v2': (10, 7, 7),
    'zg024d.staged-texture.v2': (7, 7, 10),
}
METHODS = tuple(METHOD_ALLOCATIONS)

FAMILY_NAMES = {
    'A': frozenset(('f0_hz', 'attack_ms', 'decay_ms', 'sustain', 'transient_click',
                    'noise_decay_ms', 'sweep_semitones')),
    'B': frozenset(('harmonic_count', 'harmonic_decay', 'odd_even_ratio',
                    'harmonic_tilt_db_per_oct', 'harmonic_lock_cents', 'roughness')),
    'C': frozenset(('drive_db', 'input_trim_db', 'shaper_mix', 'hard_clip_mix',
                    'asymmetry', 'wavefold', 'preemphasis', 'noise_level')),
}

DESIGN_MANIFEST = {
    'kind': 'ZG024dDesignManifest',
    'version': VERSION,
    'protocol': 'docs/inverse/ZG024_STAGED_PROTOCOL_V2.md',
    'stages': {
        'A': {'name': 'global-structure', 'proposal': 'family-shifted-halton'},
        'B': {'name': 'spectral-structure', 'proposal': 'parent-round-robin-family-shifted-halton'},
        'C': {'name': 'local-texture', 'proposal': 'parent-round-robin-coordinate-refine',
              'radii': list(LOCAL_RADII), 'continuation': 'family-shifted-halton'},
    },
    'families': {k: sorted(v) for k, v in FAMILY_NAMES.items()},
    'methods': {k: {'A': v[0], 'B': v[1], 'C': v[2]} for k, v in METHOD_ALLOCATIONS.items()},
    'retained_alternatives': RETAIN_ALTERNATIVES,
    'logical_budget': 24,
    'seeds': ['41', '211', '2027'],
    'promotion': 'eligible Pareto-front first, deterministic fit-order, then fit-ranked supplement',
    'checkpoint': 'verified-prefix-replay-v2',
    'portable_policy': {'absolute_tolerance': 1e-7, 'relative_tolerance': 1e-5},
    'capability_policy': 'FitEvaluator only; fixture truth and holdout/audit unavailable to strategy',
}


def design_sha256():
    return digest(DESIGN_MANIFEST)


def research_implementation():
    text = Path(__file__).read_text(encoding='utf-8').replace('\r\n', '\n')
    return {
        'kind': 'ZG024dStagedResearchImplementation',
        'version': VERSION,
        'strategy_source_sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(),
        'design_sha256': design_sha256(),
        'zg024b_dependency_sha256': zg024b_implementation_sha256(),
        'policy': 'fit-only deterministic three-stage search; no truth/holdout feedback',
    }


def research_implementation_sha256():
    return digest(research_implementation())


@dataclass(frozen=True)
class StagedSpec:
    method_id: str
    version: str = VERSION

    def __post_init__(self):
        require(self.method_id in METHODS, 'unsupported ZG-024d staged strategy')
        require(self.version == VERSION, 'unsupported ZG-024d staged strategy version')

    @property
    def allocation(self):
        return METHOD_ALLOCATIONS[self.method_id]

    def to_dict(self):
        a, b, c = self.allocation
        return {'kind': 'ZG024dStagedSpec', 'version': self.version, 'method_id': self.method_id,
                'stage_budget': {'A': a, 'B': b, 'C': c}, 'design_sha256': design_sha256()}

    @property
    def sha256(self):
        return digest(self.to_dict())


@dataclass(frozen=True)
class StagedCheckpoint:
    run_id: str
    environment_sha256: str
    next_ordinal: int
    evaluation_sha256s: tuple[str, ...]
    parent_checkpoint_sha256: str | None = None

    def __post_init__(self):
        sha(self.run_id, 'run_id'); sha(self.environment_sha256, 'environment_sha256')
        require(type(self.next_ordinal) is int and 0 <= self.next_ordinal <= 256,
                'invalid staged checkpoint ordinal')
        require(self.next_ordinal == len(self.evaluation_sha256s), 'staged checkpoint prefix mismatch')
        for value in self.evaluation_sha256s:
            sha(value, 'evaluation_sha256')
        if self.parent_checkpoint_sha256 is not None:
            sha(self.parent_checkpoint_sha256, 'parent_checkpoint_sha256')
        object.__setattr__(self, 'evaluation_sha256s', tuple(self.evaluation_sha256s))

    def to_dict(self):
        return {'kind': 'ZG024dStagedCheckpoint', 'version': VERSION, 'run_id': self.run_id,
                'environment_sha256': self.environment_sha256, 'next_ordinal': self.next_ordinal,
                'evaluation_sha256s': list(self.evaluation_sha256s),
                'parent_checkpoint_sha256': self.parent_checkpoint_sha256,
                'policy': 'verified-prefix-replay-v2'}

    @property
    def sha256(self):
        return digest(self.to_dict())


class StagedInterrupted(JobCancelled):
    def __init__(self, checkpoint):
        self.checkpoint = checkpoint
        super().__init__('ZG-024d staged search cancelled; latest complete prefix retained')


class StagedResumeDivergence(InverseError):
    def __init__(self, checkpoint, reason, actual=None):
        self.checkpoint, self.reason, self.actual = checkpoint, reason, actual
        super().__init__('ZG-024d resume divergence: ' + reason)

    def to_dict(self):
        return {'kind': 'ZG024dResumeDivergence', 'version': VERSION,
                'checkpoint_sha256': self.checkpoint.sha256, 'reason': self.reason,
                'actual': self.actual}


@dataclass(frozen=True)
class StagedResult:
    run_id: str
    evaluator_search_id: str
    strategy: StagedSpec
    candidates: tuple[Candidate, ...]
    lineage: tuple[dict, ...]
    promotions: tuple[dict, ...]
    ranked_candidate_ids: tuple[str, ...]
    pareto_candidate_ids: tuple[str, ...]
    final_retained_candidate_ids: tuple[str, ...]
    checkpoint: StagedCheckpoint
    declared_budget: int
    stage_consumption: tuple[tuple[str, int], ...]
    proposal_attempts: int
    stop_reason: str | None = None

    def __post_init__(self):
        sha(self.run_id, 'run_id'); sha(self.evaluator_search_id, 'evaluator_search_id')
        require(isinstance(self.strategy, StagedSpec), 'StagedSpec required')
        require(len(self.candidates) == len(self.lineage) == self.checkpoint.next_ordinal,
                'staged result prefix mismatch')
        require(tuple(row['candidate_id'] for row in self.lineage) == tuple(c.id for c in self.candidates),
                'lineage/candidate mismatch')
        consumption = dict(self.stage_consumption)
        require(set(consumption) == {'A', 'B', 'C'} and sum(consumption.values()) == len(self.candidates),
                'invalid stage consumption')
        require(len(self.candidates) <= self.declared_budget, 'logical budget exceeded')
        require(self.proposal_attempts >= len(self.candidates), 'proposal attempts below evaluations')
        candidate_ids = {c.id for c in self.candidates}
        require(set(self.final_retained_candidate_ids) <= candidate_ids, 'retained candidate outside result')

    def to_dict(self):
        return {
            'kind': 'ZG024dStagedResult', 'version': VERSION,
            'run_id': self.run_id, 'evaluator_search_id': self.evaluator_search_id,
            'strategy': self.strategy.to_dict(), 'design_manifest': DESIGN_MANIFEST,
            'research_implementation': research_implementation(),
            'candidates': [c.to_dict() for c in self.candidates],
            'lineage': list(self.lineage), 'promotions': list(self.promotions),
            'ranked_candidate_ids': list(self.ranked_candidate_ids),
            'pareto_candidate_ids': list(self.pareto_candidate_ids),
            'final_retained_candidate_ids': list(self.final_retained_candidate_ids),
            'checkpoint': self.checkpoint.to_dict(),
            'budget': {'declared_evaluations': self.declared_budget,
                       'consumed_evaluations': len(self.candidates),
                       'unspent_evaluations': self.declared_budget-len(self.candidates),
                       'stage_consumption': dict(self.stage_consumption),
                       'proposal_attempts': self.proposal_attempts,
                       'unit': 'unique logical candidate evaluations; cold foundation renders verify twice'},
            'stop_reason': self.stop_reason,
            'selection': ('fit-only eligibility/objective/Pareto promotion with deterministic state tie-break; '
                          'holdout and fixture truth absent'),
        }

    @property
    def sha256(self):
        return digest(self.to_dict())

    def audit_selection(self, *, all_candidates=False):
        ids = tuple(c.id for c in self.candidates) if all_candidates else self.final_retained_candidate_ids
        require(ids, 'no eligible fit-selected staged alternative available')
        return AuditSelection(self.evaluator_search_id, ids)


def _run_id(evaluator, strategy):
    require(isinstance(evaluator, FitEvaluator), 'staged search requires FitEvaluator')
    return digest({'domain': 'zaaggenz.zg024d-staged-run-v2',
                   'evaluator_search_id': evaluator.search_id,
                   'strategy': strategy.to_dict(), 'design_sha256': design_sha256(),
                   'research_implementation_sha256': research_implementation_sha256(),
                   'environment_sha256': evaluator.environment_sha256,
                   'declared_budget': evaluator.request.budget.max_evaluations})


def _family_for_axis(path):
    name = path.rsplit('/', 1)[-1]
    found = [family for family, names in FAMILY_NAMES.items() if name in names]
    require(len(found) == 1, 'every staged-search axis must belong to exactly one frozen family: ' + path)
    return found[0]


def _family_axes(request):
    out = {'A': [], 'B': [], 'C': []}
    for axis in request.domain.axes:
        out[_family_for_axis(axis.path)].append(axis)
    require(all(out[key] for key in ('A', 'B', 'C')), 'normal staged search requires at least one axis in every family')
    return {key: tuple(value) for key, value in out.items()}


def _state(candidate):
    return ParameterState.from_dict(candidate.to_dict()['parameters'])


def _family_halton(request, anchor, family, attempt, label, axes):
    sample = _halton_state(request, attempt, label)
    sampled = dict(sample.values); values = dict(anchor.values)
    for axis in axes[family]:
        values[axis.path] = sampled[axis.path]
    return request.domain.validate_state(ParameterState(tuple(values.items())))


def _coordinate_state(request, anchor, axis, sign, radius):
    values = dict(anchor.values); center = values[axis.path]
    value = max(axis.lower, min(axis.upper, center + sign*radius*(axis.upper-axis.lower)))
    if axis.numeric_type == 'integer':
        value = max(int(axis.lower), min(int(axis.upper), int(round(value))))
    values[axis.path] = value
    return request.domain.validate_state(ParameterState(tuple(values.items())))


def _output_identity(candidate):
    asset = candidate.to_dict()['render']['signals']['output']['asset']
    return digest(asset)


def _promotion(stage, candidates):
    eligible = sorted((c for c in candidates if c.eligible), key=_candidate_sort_key)
    pareto_ids = tuple(pareto_front(candidates))
    pareto_set = set(pareto_ids)
    retained = [c for c in eligible if c.id in pareto_set][:RETAIN_ALTERNATIVES]
    retained_ids = {c.id for c in retained}
    for candidate in eligible:
        if len(retained) >= RETAIN_ALTERNATIVES:
            break
        if candidate.id not in retained_ids:
            retained.append(candidate); retained_ids.add(candidate.id)
    by_output = {}
    for candidate in eligible:
        by_output.setdefault(_output_identity(candidate), []).append(candidate.id)
    groups = [ids for _, ids in sorted(by_output.items()) if len(ids) > 1]
    record = {
        'stage': stage, 'eligible_candidate_ids': [c.id for c in eligible],
        'pareto_candidate_ids': list(pareto_ids),
        'retained_candidate_ids': [c.id for c in retained],
        'exact_output_equivalence_groups': groups,
        'identifiability_note': ('exact-output parameter alternatives preserved' if groups else
                                 'no exact-output equivalence observed among eligible stage candidates'),
        'policy': f'eligible Pareto-first then fit-order supplement; cap={RETAIN_ALTERNATIVES}',
    }
    return record, tuple(retained)


def _evaluate(evaluator, state, ordinal, replay, checkpoint, check_cancelled):
    candidate = evaluator.evaluate(state, ordinal, check_cancelled=check_cancelled,
                                   force_recheck=ordinal < replay)
    if ordinal < replay and candidate.sha256 != checkpoint.evaluation_sha256s[ordinal]:
        raise StagedResumeDivergence(checkpoint, f'completed candidate {ordinal} failed exact replay',
                                     candidate.sha256)
    return candidate


def run_staged(evaluator, strategy, *, checkpoint=None, check_cancelled=lambda: None,
               progress=lambda value: None, on_checkpoint=lambda cp: None):
    require(isinstance(evaluator, FitEvaluator), 'run_staged accepts only fit-only FitEvaluator')
    require(isinstance(strategy, StagedSpec), 'StagedSpec required')
    request = evaluator.request
    require(request.budget.max_evaluations == 24, 'ZG-024d v2 benchmark requires exactly 24 logical evaluations')
    require(sum(strategy.allocation) == request.budget.max_evaluations, 'stage allocation/budget mismatch')
    axes = _family_axes(request)
    run_id = _run_id(evaluator, strategy)
    replay = 0
    current = StagedCheckpoint(run_id, evaluator.environment_sha256, 0, ())
    if checkpoint is not None:
        require(isinstance(checkpoint, StagedCheckpoint), 'StagedCheckpoint required')
        if checkpoint.run_id != run_id:
            raise StagedResumeDivergence(checkpoint, 'method/design/request/implementation changed', run_id)
        if checkpoint.environment_sha256 != evaluator.environment_sha256:
            raise StagedResumeDivergence(checkpoint, 'numerical environment changed', evaluator.environment_sha256)
        require(checkpoint.next_ordinal <= request.budget.max_evaluations, 'checkpoint exceeds budget')
        replay, current = checkpoint.next_ordinal, checkpoint

    candidates, lineage, promotions, seen = [], [], [], set()
    consumption = {'A': 0, 'B': 0, 'C': 0}
    attempts = 0
    stop_reason = None

    def accept(state, stage, proposal, parents=()):
        nonlocal attempts, current
        attempts += 1
        if state.sha256 in seen or len(candidates) >= request.budget.max_evaluations:
            return None
        seen.add(state.sha256); ordinal = len(candidates)
        candidate = _evaluate(evaluator, state, ordinal, replay, checkpoint, check_cancelled)
        candidates.append(candidate); consumption[stage] += 1
        lineage.append({'ordinal': ordinal, 'candidate_id': candidate.id, 'stage': stage,
                        'parent_candidate_ids': list(parents), 'proposal': proposal,
                        'eligible': candidate.eligible})
        if ordinal >= replay:
            parent_sha = current.sha256
            current = StagedCheckpoint(run_id, evaluator.environment_sha256, ordinal+1,
                                       tuple(c.sha256 for c in candidates), parent_sha)
            on_checkpoint(current)
        progress((ordinal+1)/request.budget.max_evaluations)
        return candidate

    controller = numeric_thread_limit(1)
    try:
        with controller if controller is not None else nullcontext():
            base = state_from_recipe(request.base_recipe, request.domain)
            a_budget, b_budget, c_budget = strategy.allocation

            # A: broad root/timing/envelope structure from the base state.
            a_candidates = []
            attempt = 0
            while len(a_candidates) < a_budget and attempt < a_budget*128:
                check_cancelled()
                state = _family_halton(request, base, 'A', attempt,
                                       strategy.method_id + '-stage-a', axes)
                candidate = accept(state, 'A', {'family': 'shifted-halton', 'stage_family': 'A',
                                                'coverage_attempt': attempt})
                if candidate is not None:
                    a_candidates.append(candidate)
                attempt += 1
            require(len(a_candidates) == a_budget, 'Stage A could not consume its frozen unique-state budget')
            record, a_parents = _promotion('A', a_candidates); promotions.append(record)
            if not a_parents:
                stop_reason = 'stage-A-no-eligible-parent'
            else:
                # B: parent-round-robin spectral coverage.
                b_candidates = []
                attempt = 0
                while len(b_candidates) < b_budget and attempt < b_budget*256:
                    check_cancelled(); parent = a_parents[attempt % len(a_parents)]
                    sample_index = attempt // len(a_parents)
                    state = _family_halton(request, _state(parent), 'B', sample_index,
                        f'{strategy.method_id}-stage-b-parent-{attempt % len(a_parents)}', axes)
                    candidate = accept(state, 'B', {'family': 'shifted-halton', 'stage_family': 'B',
                        'parent_rank': attempt % len(a_parents), 'coverage_attempt': sample_index}, (parent.id,))
                    if candidate is not None:
                        b_candidates.append(candidate)
                    attempt += 1
                require(len(b_candidates) == b_budget, 'Stage B could not consume its frozen unique-state budget')
                record, b_parents = _promotion('B', b_candidates); promotions.append(record)
                if not b_parents:
                    stop_reason = 'stage-B-no-eligible-parent'
                else:
                    # C: bounded texture/nonlinearity refinement around retained B alternatives.
                    c_candidates = []
                    for radius_index, radius in enumerate(LOCAL_RADII):
                        if len(c_candidates) >= c_budget:
                            break
                        for parent_rank, parent in enumerate(b_parents):
                            if len(c_candidates) >= c_budget:
                                break
                            for axis in axes['C']:
                                for sign in (-1, 1):
                                    if len(c_candidates) >= c_budget:
                                        break
                                    check_cancelled()
                                    state = _coordinate_state(request, _state(parent), axis, sign, radius)
                                    candidate = accept(state, 'C', {'family': 'coordinate-refine',
                                        'stage_family': 'C', 'parent_rank': parent_rank,
                                        'axis': axis.path, 'direction': sign,
                                        'radius_index': radius_index, 'radius_fraction': radius}, (parent.id,))
                                    if candidate is not None:
                                        c_candidates.append(candidate)
                    continuation = 0
                    while len(c_candidates) < c_budget and continuation < c_budget*256:
                        check_cancelled(); parent = b_parents[continuation % len(b_parents)]
                        sample_index = continuation // len(b_parents)
                        state = _family_halton(request, _state(parent), 'C', sample_index,
                            f'{strategy.method_id}-stage-c-continuation-parent-{continuation % len(b_parents)}', axes)
                        candidate = accept(state, 'C', {'family': 'shifted-halton-continuation',
                            'stage_family': 'C', 'reason': 'coordinate duplicate/clipping exhaustion',
                            'parent_rank': continuation % len(b_parents),
                            'coverage_attempt': sample_index}, (parent.id,))
                        if candidate is not None:
                            c_candidates.append(candidate)
                        continuation += 1
                    require(len(c_candidates) == c_budget, 'Stage C could not consume its frozen unique-state budget')
                    record, final_parents = _promotion('C-final', c_candidates); promotions.append(record)
                    if not final_parents:
                        stop_reason = 'stage-C-no-eligible-final-alternative'
            check_cancelled()
    except JobCancelled as exc:
        raise StagedInterrupted(current) from exc

    require(len(candidates) >= replay, 'resume prefix could not be regenerated')
    eligible = sorted((c for c in candidates if c.eligible), key=_candidate_sort_key)
    final_ids = tuple(promotions[-1]['retained_candidate_ids']) if promotions and promotions[-1]['stage'] == 'C-final' else ()
    return StagedResult(run_id, evaluator.search_id, strategy, tuple(candidates), tuple(lineage),
                        tuple(promotions), tuple(c.id for c in eligible), pareto_front(candidates), final_ids,
                        current, request.budget.max_evaluations, tuple(sorted(consumption.items())), attempts,
                        stop_reason)


def submit_staged_job(scheduler, evaluator, strategy, *, checkpoint=None, on_checkpoint=lambda cp: None):
    require(isinstance(evaluator, FitEvaluator), 'FitEvaluator required')
    require(isinstance(strategy, StagedSpec), 'StagedSpec required')
    def execute(ctx):
        ctx.check_cancelled()
        return run_staged(evaluator, strategy, checkpoint=checkpoint,
                          check_cancelled=ctx.check_cancelled, progress=ctx.progress,
                          on_checkpoint=on_checkpoint)
    return scheduler.submit(JobClass.RESEARCH, evaluator.request.source_revision_id, execute,
                            estimated_memory_bytes=estimate_memory_bytes(evaluator))
