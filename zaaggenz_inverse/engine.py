"""A deliberately boring deterministic grid, with fit-only capabilities."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from zaaggenz_contracts import Contract, digest, derive_seed, loads
from zaaggenz_dsp.graph import GraphError
from zaaggenz_jobs import JobCancelled
from zaaggenz_project.project import ProjectError
from zaaggenz_jobs.model import atomic_publish_bytes
from .contracts import (SearchRequest, Snapshot, ParameterState, Window, document, fields,
                        require, integer, finite, sha, InverseError)
from .render import AudioBuffer, Rendered, execution_identity
from .objectives import ObjectivePlan, FeatureStore, compare_window, aggregate, AXES
from .validation import GatePolicy, validate_window


class DivergenceError(InverseError):
    """Resume/replay changed: begin an explicitly parented new search instead."""


def _measure_split(rendered, targets, plan, gates, store, check):
    windows = []
    for window, target in targets:
        check()
        candidate = rendered.output.excerpt(window)
        tf = store.measure(target, plan)
        check()
        cf = store.measure(candidate, plan)
        check()
        objective = compare_window(target, candidate, tf, cf, plan)
        validation = validate_window(target, rendered, window, tf, cf, gates)
        windows.append({'window': window.to_dict(), 'objective': objective, 'validation': validation})
    return {'windows': windows, 'aggregate': aggregate(windows, plan)}


@dataclass(frozen=True)
class FitProblem:
    """The search receives this object, NOT an AuditTarget or a fixture witness.

    All target buffers here are copies of fitting excerpts. No target-wide
    analysis, onset alignment, level match or filter is performed before slicing.
    This is an accidental-leakage API boundary, not a hostile-Python sandbox.
    """
    request: SearchRequest
    renderer: object
    fitting_targets: tuple[tuple[Window, AudioBuffer], ...]
    _store: FeatureStore

    def __post_init__(self):
        require(isinstance(self.request, SearchRequest), 'SearchRequest required')
        data = self.request.to_dict()
        require(data['execution'] == execution_identity(), 'execution changed; create a new search with explicit parent lineage')
        require(self._store.execution.to_dict() == data['execution'], 'feature cache execution mismatch')
        require(self.renderer.source.asset.to_dict() == data['source'], 'renderer source identity mismatch')
        require(self.renderer.method == data['renderer'], 'renderer method/configuration mismatch')
        self.renderer.validate_domain(self.request.domain)
        require(tuple(w for w, _ in self.fitting_targets) == self.request.windows.fitting, 'fit excerpt inventory mismatch')
        for window, target in self.fitting_targets:
            require(isinstance(target, AudioBuffer) and len(target.audio) == window.end - window.start, 'fit excerpt length mismatch')
            require(target.rate == data['target']['sample_rate_hz'], 'fit excerpt sample rate mismatch')
        require(any(abs(t.audio).max() > 1e-8 for _, t in self.fitting_targets), 'silent fitting target cannot establish inverse recovery')

    def evaluate(self, state, ordinal, check=lambda: None):
        request = self.request
        request.domain.validate(state)  # Hard bound check BEFORE either renderer call.
        integer(ordinal, 'candidate ordinal', 0, request.budget.evaluations - 1)
        require(state == request.grid.point(ordinal), 'candidate does not match declared grid point')
        cfg = request.to_dict()
        seed = derive_seed(cfg['seed'], 'inverse-render')
        candidate_id = request.candidate_id(state)
        base = dict(id=candidate_id, search_id=request.sha256, grid_index=ordinal,
                    parameters=state.to_dict(), stage=cfg['stage'], seed=seed,
                    parent_candidate_ids=cfg['stage']['parent_candidate_ids'])
        calls = 0
        try:
            check()
            calls += 1
            rendered = self.renderer.render(state, seed, check)
            require(isinstance(rendered, Rendered), 'renderer must return owned pre/post-gain taps')
            output = rendered.output.asset.to_dict()
            for name in ('sample_rate_hz', 'channels', 'frame_count'):
                require(output[name] == cfg['target'][name], 'render/target ' + name + ' mismatch')
            check()
            calls += 1
            repeated = self.renderer.render(state, seed, check)
            require(isinstance(repeated, Rendered), 'repeat renderer result invalid')
            reproducible = rendered.sha256 == repeated.sha256
            plan = ObjectivePlan.from_dict(cfg['objectives'])
            gates = GatePolicy.from_dict(cfg['validation'])
            fit = _measure_split(rendered, self.fitting_targets, plan, gates, self._store, check)
            codes = sorted({code for row in fit['windows'] for code in row['validation']['codes']})
            if not fit['aggregate']['complete']:
                codes.append('unavailable_objective')
            if fit['aggregate']['search_score'] is None:
                codes.append('no_search_score')
            if not reproducible:
                codes.append('divergent_render')
            return Snapshot(document('InverseCandidate', **base, render=rendered.identity(), render_id=rendered.sha256,
                repeat_render_id=repeated.sha256, fit=fit, render_calls=calls,
                validation={'state': 'valid' if not codes else 'divergent' if not reproducible else 'rejected',
                            'eligible': not codes, 'codes': codes,
                            'reproducibility': 'exact-repeat-verified' if reproducible else 'divergent'}, error=None))
        except (JobCancelled, ProjectError):
            raise
        except (InverseError, GraphError, ValueError, FloatingPointError) as exc:
            # Invalid signals and graph configurations consume a candidate attempt.
            # Programming/runtime exceptions outside this set fail the job visibly.
            return Snapshot(document('InverseCandidate', **base, render=None, render_id=None, repeat_render_id=None,
                fit=None, render_calls=calls, validation={'state': 'rejected', 'eligible': False,
                'codes': ['render_or_measurement_invalid'], 'reproducibility': 'non-reproducible-invalid-output'},
                error={'type': type(exc).__name__, 'message': str(exc)[:512]}))


@dataclass(frozen=True)
class AuditTarget:
    request_id: str
    target: AudioBuffer
    held_out: tuple[Window, ...]

    def __post_init__(self):
        sha(self.request_id)
        require(isinstance(self.target, AudioBuffer), 'owned audit target required')


def prepare_problem(request, renderer, target, *, store=None):
    require(isinstance(request, SearchRequest) and isinstance(target, AudioBuffer), 'request and canonical target required')
    require(target.asset.to_dict() == request.to_dict()['target'], 'target identity mismatch')
    store = store or FeatureStore(request.to_dict()['execution'])
    fitting = tuple((w, target.excerpt(w)) for w in request.windows.fitting)
    return FitProblem(request, renderer, fitting, store), AuditTarget(request.sha256, target, request.windows.held_out)


def _ledger_entry(candidate):
    d = candidate.to_dict()
    a = d['fit']['aggregate'] if d['fit'] else None
    return {'index': d['grid_index'], 'candidate_id': d['id'], 'evaluation_sha256': candidate.sha256,
            'render_id': d['render_id'], 'render_calls': d['render_calls'], 'eligible': d['validation']['eligible'],
            'score': a['search_score'] if a else None, 'axes': list(AXES),
            'vector': a['vector'] if a else [None] * len(AXES),
            'applicable': a['applicable'] if a else [False] * len(AXES)}


def _trace_id(request_id, ledger):
    state = digest(document('InverseTraceRoot', search_id=request_id))
    for entry in ledger:
        state = digest(document('InverseTraceStep', previous=state, evaluation=entry))
    return state


@dataclass(frozen=True, init=False)
class Checkpoint(Snapshot):
    """Small prefix ledger, not a serialized optimiser/worker process.

    Resume intentionally replays this prefix and verifies every evaluation hash.
    That reconstructs retention without trusting saved scores or hidden RNG state.
    """
    def __init__(self, request, ledger, status):
        require(isinstance(request, SearchRequest), 'checkpoint request required')
        require(status in ('running', 'paused', 'cancelled', 'completed'), 'invalid checkpoint state')
        require(isinstance(ledger, list) and len(ledger) <= request.budget.evaluations, 'invalid checkpoint prefix')
        for index, entry in enumerate(ledger):
            require(type(entry) is dict and set(entry) == {'index', 'candidate_id', 'evaluation_sha256', 'render_id',
                'render_calls', 'eligible', 'score', 'axes', 'vector', 'applicable'}, 'invalid checkpoint ledger entry')
            require(entry['index'] == index, 'checkpoint must be an ordered contiguous prefix')
            require(entry['candidate_id'] == request.candidate_id(request.grid.point(index)), 'checkpoint candidate identity mismatch')
            sha(entry['evaluation_sha256'])
            if entry['render_id'] is not None:
                sha(entry['render_id'])
            integer(entry['render_calls'], 'render calls', 0, 2)
            require(type(entry['eligible']) is bool and entry['axes'] == list(AXES), 'invalid checkpoint objective metadata')
            require(type(entry['vector']) is list and type(entry['applicable']) is list and len(entry['vector']) == len(AXES) and len(entry['applicable']) == len(AXES), 'checkpoint objective vector shape mismatch')
            require(all(type(v) is bool for v in entry['applicable']), 'checkpoint applicability must be boolean')
            for value in [entry['score'], *entry['vector']]:
                if value is not None:
                    finite(value, 'checkpoint loss', 0., 1e100)
            require(not entry['eligible'] or (entry['score'] is not None and entry['render_id'] is not None and entry['render_calls'] == 2), 'eligible checkpoint entry lacks reproducibility evidence')
        require(status != 'completed' or len(ledger) == request.budget.evaluations, 'incomplete completed checkpoint')
        super().__init__(document('InverseCheckpoint', request=request.to_dict(), search_id=request.sha256,
            next_index=len(ledger), ledger=ledger, trace_sha256=_trace_id(request.sha256, ledger), status=status,
            resume_policy='replay-and-verify-prefix; changed-code-or-numerics-requires-parented-new-search'))

    @classmethod
    def from_dict(cls, data):
        keys = ('request', 'search_id', 'next_index', 'ledger', 'trace_sha256', 'status', 'resume_policy')
        fields(data, keys, 'InverseCheckpoint')
        result = cls(SearchRequest.from_dict(data['request']), data['ledger'], data['status'])
        require(result.to_dict() == data, 'checkpoint metadata/trace hash mismatch')
        return result

    @classmethod
    def load(cls, path):
        return cls.from_dict(loads(Path(path).read_bytes()))

    def save(self, path):
        # Completed-prefix recovery metadata, not a final audio publication.
        atomic_publish_bytes(path, self._json)


def dominates(a, b):
    """Minimise all target-applicable axes. Equal observations remain alternatives."""
    if not a['eligible'] or not b['eligible'] or a['applicable'] != b['applicable']:
        return False
    pairs = [(x, y) for x, y, use in zip(a['vector'], b['vector'], a['applicable']) if use]
    if not pairs or any(x is None or y is None for x, y in pairs):
        return False
    return all(x <= y for x, y in pairs) and any(x < y for x, y in pairs)


def _rank(entry):
    # Ties use grid order, NOT target-dependent candidate hashes. Merely changing
    # sealed holdout samples therefore cannot alter fit-based tie selection.
    return (not entry['eligible'], float('inf') if entry['score'] is None else entry['score'], entry['index'])


@dataclass(frozen=True, init=False)
class SearchResult(Snapshot):
    def __init__(self, request, candidates, ledger, status, resumed_from=None, replayed=0):
        require(status in ('completed', 'paused'), 'only completed/paused results can be frozen')
        checkpoint = Checkpoint(request, ledger, status)
        require(len(candidates) == len(ledger), 'candidate/ledger mismatch')
        frontier = [e for e in ledger if e['eligible'] and not any(dominates(other, e) for other in ledger)]
        frontier_indices = {e['index'] for e in frontier}
        ordered = sorted(frontier, key=_rank) + sorted((e for e in ledger if e['index'] not in frontier_indices), key=_rank)
        kept = ordered[:request.budget.retain]
        best = min((e for e in ledger if e['eligible']), key=_rank, default=None)
        # A zero-weight objective can make the scalar tie winner Pareto-dominated.
        # Do not publish a best ID whose editable record/audit was dropped by a cap.
        if best is not None and best not in kept:
            kept = [best] + kept[:request.budget.retain - 1]
        rows = [candidates[e['index']].to_dict() for e in kept]
        candidate_set_id = digest(document('InverseFrozenCandidateSet', search_id=request.sha256,
            trace_sha256=checkpoint.to_dict()['trace_sha256'], candidate_ids=[r['id'] for r in rows]))
        super().__init__(document('InverseSearchResult', request=request.to_dict(), search_id=request.sha256, status=status,
            evaluations=len(ledger), render_calls=sum(e['render_calls'] for e in ledger),
            ledger=ledger, retained=rows, frontier_candidate_ids=[e['candidate_id'] for e in sorted(frontier, key=_rank)],
            best_candidate_id=None if best is None else best['candidate_id'], candidate_set_sha256=candidate_set_id,
            checkpoint=checkpoint.to_dict(), lineage={'resumed_from_checkpoint_sha256': resumed_from,
                'replayed_evaluations': replayed, 'replay_is_verification_not_new_budget': True},
            retention_policy='non-dominated-first with scalar winner reserved; then valid scalar rank; ordinal ties; explicit retention cap',
            interpretation='editable candidate transformations, never recovered original production chains'))


def run_baseline(problem, *, resume=None, pause_after=None, check_cancelled=lambda: None,
                 progress=lambda _: None, on_checkpoint=lambda _: None, checkpoint_path=None):
    """Canonical enumeration, at most two renders per attempted grid point.

    A resume replays prior attempts separately from the original unique-point
    budget. Cancellation publishes only the last completed prefix and re-raises
    JobCancelled so ZG-004 remains the scheduler authority.
    """
    require(isinstance(problem, FitProblem), 'FitProblem required; never pass an audit target to search')
    request = problem.request
    require(request.to_dict()['execution'] == execution_identity(), 'execution changed since problem construction')
    if pause_after is not None:
        integer(pause_after, 'pause boundary', 0, request.budget.evaluations)
    old = []
    if resume is not None:
        require(isinstance(resume, Checkpoint), 'Checkpoint required')
        d = resume.to_dict()
        require(d['search_id'] == request.sha256 and d['request'] == request.to_dict(), 'checkpoint belongs to a different search; use explicit parent lineage')
        old = d['ledger']
    candidates, ledger = [], []

    def publish(status):
        checkpoint = Checkpoint(request, ledger, status)
        if checkpoint_path is not None:
            checkpoint.save(checkpoint_path)
        on_checkpoint(checkpoint)
        return checkpoint

    try:
        # Replay happens without overwriting an existing checkpoint. A failed
        # replay cannot replace the previous trustworthy completed prefix.
        for index, expected in enumerate(old):
            check_cancelled()
            candidate = problem.evaluate(request.grid.point(index), index, check_cancelled)
            entry = _ledger_entry(candidate)
            if entry != expected:
                raise DivergenceError('checkpoint replay diverged at candidate ' + expected['candidate_id'])
            candidates.append(candidate)
            ledger.append(entry)
        if pause_after is not None:
            require(pause_after >= len(ledger), 'pause boundary precedes replayed prefix')
        limit = request.budget.evaluations if pause_after is None else pause_after
        for index in range(len(ledger), limit):
            check_cancelled()
            candidate = problem.evaluate(request.grid.point(index), index, check_cancelled)
            candidates.append(candidate)
            ledger.append(_ledger_entry(candidate))
            publish('running')
            progress(len(ledger) / request.budget.evaluations)
        status = 'completed' if len(ledger) == request.budget.evaluations else 'paused'
        publish(status)
        return SearchResult(request, candidates, ledger, status, None if resume is None else resume.sha256, len(old))
    except JobCancelled:
        if len(ledger) >= len(old):
            publish('cancelled')
        raise


def audit_result(result, vault, renderer, *, store=None, check_cancelled=lambda: None):
    """Evaluate a FROZEN retained set; never re-rank it or feed holdouts to search."""
    require(isinstance(result, SearchResult) and isinstance(vault, AuditTarget), 'frozen result and separate AuditTarget required')
    data = result.to_dict()
    request = SearchRequest.from_dict(data['request'])
    require(vault.request_id == data['search_id'], 'audit target/search mismatch')
    require(vault.target.asset.to_dict() == request.to_dict()['target'], 'audit target content mismatch')
    require(vault.held_out == request.windows.held_out, 'audit window inventory mismatch')
    require(renderer.method == request.to_dict()['renderer'] and renderer.source.asset.to_dict() == request.to_dict()['source'], 'audit renderer mismatch')
    require(request.to_dict()['execution'] == execution_identity(), 'audit execution changed; label a new lineage rather than reusing this result')
    store = store or FeatureStore(request.to_dict()['execution'])
    require(store.execution.to_dict() == request.to_dict()['execution'], 'audit feature cache execution mismatch')
    plan = ObjectivePlan.from_dict(request.to_dict()['objectives'])
    gates = GatePolicy.from_dict(request.to_dict()['validation'])
    held = tuple((w, vault.target.excerpt(w)) for w in vault.held_out)
    whole = Window('whole-signal', 0, len(vault.target.audio))
    rows = []
    for candidate in data['retained']:
        check_cancelled()
        if candidate['render_id'] is None:
            rows.append({'candidate_id': candidate['id'], 'reproducibility': 'non-reproducible-invalid-output',
                         'held_out': None, 'whole_signal': None})
            continue
        rendered = renderer.render(ParameterState.from_mapping(candidate['parameters']), candidate['seed'], check_cancelled)
        if rendered.sha256 != candidate['render_id']:
            rows.append({'candidate_id': candidate['id'], 'reproducibility': 'divergent',
                         'expected_render_id': candidate['render_id'], 'actual_render_id': rendered.sha256,
                         'held_out': None, 'whole_signal': None})
            continue
        rows.append({'candidate_id': candidate['id'], 'reproducibility': 'exact',
                     'held_out': _measure_split(rendered, held, plan, gates, store, check_cancelled),
                     'whole_signal': _measure_split(rendered, ((whole, vault.target),), plan, gates, store, check_cancelled)})
    return Snapshot(document('InverseAudit', search_id=request.sha256, candidate_set_sha256=data['candidate_set_sha256'],
        frozen_result_sha256=result.sha256, candidates=rows,
        policy='post-freeze evaluation only; same retained order; no selection or re-ranking',
        whole_signal_role='diagnostics-only, not optimisation or independent holdout evidence'))
