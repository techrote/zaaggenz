"""Deliberately boring bounded enumeration. No adaptive/learned optimizer in pass 1."""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
from contextlib import nullcontext

from zaaggenz_contracts import derive_seed, digest
from zaaggenz_jobs import JobClass, JobCancelled, atomic_publish_bytes
from zaaggenz_jobs.model import numeric_thread_limit
from .contracts import ParameterState, Checkpoint, InverseError, require
from .laboratory import FitEvaluator, AuditSelection
from .results import Candidate, pareto_front


def grid_levels(request):
    result = []
    points = request.budget.grid_points_per_axis
    for axis in request.domain.axes:
        values = [axis.lower + (axis.upper-axis.lower)*i/(points-1) for i in range(points)]
        values[0], values[-1] = axis.lower, axis.upper  # exactly inclusive declared bounds
        if axis.numeric_type == 'integer':
            values = [int(round(x)) for x in values]
        result.append(tuple(sorted(set(values))))
    return tuple(result)


def grid_state(request, ordinal):
    levels = grid_levels(request)
    total = math.prod(len(v) for v in levels)
    require(type(ordinal) is int and 0 <= ordinal < total, 'grid ordinal outside enumeration')
    # Deliberately independent of target hashes so changes to unobserved holdouts
    # cannot change candidate ordering, including ties on fitting windows.
    offset = int(derive_seed(request.seed, 'inverse-grid-v1')) % total
    index = (offset + ordinal) % total
    indices = []
    for values in reversed(levels):
        indices.append(index % len(values))
        index //= len(values)
    indices.reverse()
    state = ParameterState(tuple((axis.path, values[i]) for axis, values, i in zip(request.domain.axes, levels, indices)))
    return request.domain.validate_state(state)


class ResumeDivergence(InverseError):
    def __init__(self, checkpoint, reason, *, actual=None):
        self.checkpoint, self.reason, self.actual = checkpoint, reason, actual
        super().__init__('resume declared divergent: ' + reason)

    def to_dict(self):
        return {'kind': 'InverseResumeDivergence', 'version': '1.0.0', 'checkpoint_sha256': self.checkpoint.sha256,
                'state': 'divergent', 'reason': self.reason, 'actual': self.actual}


class SearchInterrupted(JobCancelled):
    def __init__(self, checkpoint):
        self.checkpoint = checkpoint
        super().__init__('inverse job cancelled; only completed prefix is checkpointed')


@dataclass(frozen=True)
class SearchResult:
    search_id: str
    candidates: tuple[Candidate, ...]
    ranked_candidate_ids: tuple[str, ...]
    pareto_candidate_ids: tuple[str, ...]
    checkpoint: Checkpoint
    grid_size: int
    declared_budget: int

    def to_dict(self):
        return {'kind': 'InverseSearchResult', 'version': '1.0.0', 'search_id': self.search_id,
                'method': 'zg.inverse.cyclic-grid.v1', 'candidates': [x.to_dict() for x in self.candidates],
                'ranked_candidate_ids': list(self.ranked_candidate_ids), 'pareto_candidate_ids': list(self.pareto_candidate_ids),
                'checkpoint': self.checkpoint.to_dict(),
                'budget': {'declared_evaluations': self.declared_budget, 'consumed_evaluations': len(self.candidates),
                           'grid_size': self.grid_size, 'unspent_evaluations': self.declared_budget-len(self.candidates),
                           'termination': 'grid-exhausted' if len(self.candidates) == self.grid_size else 'budget-exhausted',
                           'unit': 'logical candidate evaluations; cache hits consume one; uncached candidates render twice'},
                'selection': 'fit-only; ordinal breaks ties, never target hash or holdout performance'}

    @property
    def sha256(self):
        return digest(self.to_dict())

    def audit_selection(self, *, all_candidates=False):
        ids = tuple(c.id for c in self.candidates) if all_candidates else self.ranked_candidate_ids
        require(ids, 'no eligible candidates; choose all_candidates=True to audit rejected candidates explicitly')
        return AuditSelection(self.search_id, ids)


def save_checkpoint(checkpoint, path):
    require(isinstance(checkpoint, Checkpoint), 'Checkpoint required')
    # Completion journal: safe to publish a finished prefix even after a cancel request.
    # This is not permission to publish a cancelled render as the current product.
    atomic_publish_bytes(path, (json.dumps(checkpoint.to_dict(), sort_keys=True, allow_nan=False)+'\n').encode('utf-8'))


def load_checkpoint(path):
    data = Path(path).read_bytes()
    require(len(data) <= 65536, 'checkpoint exceeds bound')
    return Checkpoint.from_json(data.decode('utf-8'))


def _run_grid(evaluator, *, checkpoint=None, check_cancelled=lambda: None, progress=lambda value: None,
             on_checkpoint=lambda cp: None):
    require(isinstance(evaluator, FitEvaluator), 'run_grid accepts only the fit-only capability')
    request = evaluator.request
    total = math.prod(len(v) for v in grid_levels(request))
    count = min(total, request.budget.max_evaluations)
    current = Checkpoint(evaluator.search_id, evaluator.environment_sha256, 0, ())
    replay = 0
    if checkpoint is not None:
        require(isinstance(checkpoint, Checkpoint), 'Checkpoint required')
        if checkpoint.search_id != evaluator.search_id:
            raise ResumeDivergence(checkpoint, 'search request/method/target/bounds/budget changed', actual=evaluator.search_id)
        if checkpoint.environment_sha256 != evaluator.environment_sha256:
            raise ResumeDivergence(checkpoint, 'numerical environment changed', actual=evaluator.environment_sha256)
        require(checkpoint.next_ordinal <= count, 'checkpoint exceeds declared budget/grid')
        current, replay = checkpoint, checkpoint.next_ordinal
    candidates = []
    try:
        for ordinal in range(count):
            check_cancelled()
            state = grid_state(request, ordinal)
            candidate = evaluator.evaluate(state, ordinal, check_cancelled=check_cancelled, force_recheck=ordinal < replay)
            if ordinal < replay:
                if candidate.sha256 != checkpoint.evaluation_sha256s[ordinal]:
                    raise ResumeDivergence(checkpoint, f'completed candidate {ordinal} failed exact replay', actual=candidate.sha256)
            candidates.append(candidate)
            if ordinal >= replay:
                current = Checkpoint(evaluator.search_id, evaluator.environment_sha256, ordinal+1,
                    tuple(c.sha256 for c in candidates), parent_checkpoint_sha256=current.sha256)
                on_checkpoint(current)
            progress((ordinal+1)/count)
        check_cancelled()
    except JobCancelled as exc:
        raise SearchInterrupted(current) from exc
    eligible = [c for c in candidates if c.eligible]
    ranked = tuple(c.id for c in sorted(eligible, key=lambda c: (c.score, c.to_dict()['ordinal'])))
    return SearchResult(evaluator.search_id, tuple(candidates), ranked, pareto_front(candidates), current, total, request.budget.max_evaluations)


def run_grid(evaluator, **kwargs):
    """Run synchronously under the accepted single-numerical-thread policy."""
    controller = numeric_thread_limit(1)
    with controller if controller is not None else nullcontext():
        return _run_grid(evaluator, **kwargs)


def estimate_memory_bytes(evaluator):
    request = evaluator.request
    n = request.target_asset.to_dict()['frame_count']
    channels = request.target_asset.to_dict()['channels']
    # Conservative admission estimate includes arrays, both bounded caches, full
    # retained candidate metadata and component temporaries. Oversized jobs fail
    # existing scheduler admission rather than evict interactive reservations.
    renders = evaluator.render_cache.max_entries*n*channels*16
    features = evaluator.features.cache.max_entries*(n//64+5)*channels*257*8
    records = min(request.budget.max_evaluations, math.prod(len(x) for x in grid_levels(request)))*len(request.fitting_windows)*131072
    return int(16*1024*1024 + renders + features + records + n*channels*256)


def submit_search_job(scheduler, evaluator, *, checkpoint=None, checkpoint_path=None, on_checkpoint=lambda cp: None):
    require(isinstance(evaluator, FitEvaluator), 'FitEvaluator required')
    def publish(cp):
        if checkpoint_path is not None:
            save_checkpoint(cp, checkpoint_path)
        on_checkpoint(cp)
    def execute(ctx):
        ctx.check_cancelled()
        return run_grid(evaluator, checkpoint=checkpoint, check_cancelled=ctx.check_cancelled,
                        progress=ctx.progress, on_checkpoint=publish)
    return scheduler.submit(JobClass.RESEARCH, evaluator.request.source_revision_id, execute,
                            estimated_memory_bytes=estimate_memory_bytes(evaluator))
