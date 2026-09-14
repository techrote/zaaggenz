"""Fit-only capability and separate post-selection audit; no holdouts in search APIs."""
from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
import math
import numpy as np

from zaaggenz_analysis import AnalysisCache
from zaaggenz_contracts import Contract, digest
from zaaggenz_descriptors import pcm_asset
from zaaggenz_project import Project, cache_key
from .contracts import (SearchRequest, Window, WindowPlan, ParameterState, require, VERSION)
from .recipes import (apply_state, frozen_audio, render_trace, validate_base, validate_domain,
                      engine_identity, render_engine_identity, environment_manifest, RenderTrace)
from .objectives import FeatureMeasurements, measure_losses, validation_measurements, aggregate, component
from .results import Candidate, candidate_identity


def request_from_project(project, target, plan, domain, **kwargs):
    require(isinstance(project, Project), 'existing Project required')
    require(isinstance(plan, WindowPlan), 'WindowPlan required')
    sr = project.head_recipe.to_dict()['time_map']['sample_rate_hz']
    return SearchRequest(project.head_recipe, project.head, Contract(pcm_asset(frozen_audio(target), sr)),
                         domain, plan.fit, **kwargs)


def _missing_measurements(reason):
    from .contracts import LOSS_UNITS
    return {'kind': 'InverseWindowMeasurements', 'version': VERSION,
            'components': [component(k, None, reason=reason) for k in LOSS_UNITS],
            'intermediate': {}, 'target_features': None, 'candidate_features': None,
            'feature_pair_sha256': digest({'invalid': reason})}


def _evaluate_windows(trace, windows, target_slices, features, objective, validation, check_cancelled):
    records = []
    for window, target in zip(windows, target_slices):
        check_cancelled()
        start, end = window.start_sample, window.end_sample
        candidate = trace.output[start:end]
        gates = validation_measurements(target, candidate, features.sr, validation,
            pre_master=trace.pre_master[start:end], master_gain=trace.gain,
            clipping=trace.recipe.to_dict()['output']['clipping'])
        if candidate.shape == target.shape and np.isfinite(candidate).all():
            measures = measure_losses(target, candidate, features)
        else:
            measures = _missing_measurements('invalid render shape or non-finite output')
        records.append({'window': window.to_dict(), 'support': window.support,
                        'measurements': measures, 'validation': gates})
        check_cancelled()
    return {'windows': records, 'objectives': aggregate(records, objective)}


class FitEvaluator:
    """Stores only independent copies of fitting excerpts; no original/full target.

    Python capability separation prevents accidental leakage, not a sandbox against
    malicious code introspecting the enclosing orchestration process.
    """
    def __setattr__(self, name, value):
        if name in ('request', '_fit', 'features', 'implementation_sha256', 'environment_sha256',
                    'search_id', 'renderer', 'renderer_id', 'render_engine_sha256') and name in self.__dict__:
            raise AttributeError('search identity is immutable; create a new evaluator')
        object.__setattr__(self, name, value)

    def __init__(self, request, target_slices, *, render_cache=None, feature_cache=None, renderer=render_trace, renderer_id='zg.render-recipe.v1'):
        require(isinstance(request, SearchRequest), 'SearchRequest required')
        self.request = request
        validate_base(request.base_recipe, request.target_asset.to_dict()['frame_count'])
        validate_domain(request.base_recipe, request.domain)
        require(len(target_slices) == len(request.fitting_windows), 'one independent slice per fitting window required')
        self._fit = tuple(frozen_audio(a) for a in target_slices)
        for window, a in zip(request.fitting_windows, self._fit):
            require(len(a) == window.end_sample-window.start_sample and np.isfinite(a).all(), 'invalid fitting excerpt')
        d = request.base_recipe.to_dict()
        self.features = FeatureMeasurements(d['time_map']['sample_rate_hz'], d['tuning']['reference_hz'],
                                           request.objective.sonority, feature_cache)
        from .contracts import identifier
        identifier(renderer_id, 'renderer_id')
        require(renderer is render_trace or renderer_id != 'zg.render-recipe.v1', 'custom renderer requires an explicit distinct method ID')
        self.renderer_id = renderer_id
        self.implementation_sha256 = digest({'engine': engine_identity(), 'renderer_id': renderer_id})
        self.render_engine_sha256 = digest({'engine': render_engine_identity(), 'renderer_id': renderer_id})
        self.environment_sha256 = digest(environment_manifest())
        self.search_id = digest({'domain': 'zaaggenz.inverse-search-v1', 'request': request.to_dict(),
            'implementation_sha256': self.implementation_sha256,
            'feature_method_sha256': self.features.method_sha256,
            # Bind the fit slice bytes too: construction cannot forge a different fitting target.
            'fit_assets': [pcm_asset(a, self.features.sr) for a in self._fit]})
        self.render_cache = render_cache if render_cache is not None else AnalysisCache(8)
        self.renderer = renderer
        self.render_calls = self.render_hits = 0

    def evaluate(self, state, ordinal=0, *, check_cancelled=lambda: None, force_recheck=False):
        check_cancelled()
        recipe = apply_state(self.request.base_recipe, self.request.domain, state)
        # Recipe + implementation + environment, not search budget, permits reuse across strategies.
        key = cache_key(recipe.sha256, digest([self.render_engine_sha256, self.environment_sha256]), 'synth')
        cached = None if force_recheck else self.render_cache.get(key)
        if cached is None:
            first = self.renderer(recipe)
            self.render_calls += 1
            check_cancelled()
            second = self.renderer(recipe)
            self.render_calls += 1
            check_cancelled()
            require(isinstance(first, RenderTrace) and isinstance(second, RenderTrace), 'renderer must supply explicit RenderTrace')
            require(first.recipe.sha256 == second.recipe.sha256 == recipe.sha256, 'renderer returned a different recipe')
            reproducibility = 'repeat-verified' if first.sha256 == second.sha256 else 'divergent'
            if reproducibility == 'repeat-verified':
                self.render_cache.put(key, (first, first.sha256))
        else:
            first, proof = cached
            require(isinstance(first, RenderTrace) and first.recipe.sha256 == recipe.sha256 and proof == first.sha256, 'corrupt verified render cache')
            self.render_hits += 1
            reproducibility = 'repeat-verified'
        if force_recheck:
            self.features.cache.clear()
        fit = _evaluate_windows(first, self.request.fitting_windows, self._fit, self.features,
                                self.request.objective, self.request.validation, check_cancelled)
        states = [w['validation']['state'] for w in fit['windows']]
        validation_state = 'rejected' if 'rejected' in states else ('accepted-with-exceptions' if 'accepted-with-exceptions' in states else 'accepted')
        frame_count = self.request.target_asset.to_dict()['frame_count']
        # Full shape/provenance is structural, not a comparison with target holdout content.
        structural_reasons = []
        if len(first.output) != frame_count or first.output.shape != first.pre_master.shape or first.source.shape != first.output.shape:
            structural_reasons.append('invalid_render_shape')
        if any(not np.isfinite(a).all() for a in (first.source, first.pre_master, first.output)):
            structural_reasons.append('non_finite_render')
        if structural_reasons:
            validation_state = 'rejected'
        data = {'kind': 'InverseCandidate', 'version': VERSION,
                'candidate_id': candidate_identity(self.search_id, state, recipe), 'search_id': self.search_id,
                'ordinal': ordinal, 'parameters': state.to_dict(), 'recipe': recipe.to_dict(),
                'provenance': {'implementation_sha256': self.implementation_sha256,
                    'environment_sha256': self.environment_sha256, 'source_revision_id': self.request.source_revision_id,
                    'base_recipe_sha256': self.request.base_recipe.sha256, 'target_asset_sha256': self.request.target_asset.sha256,
                    'render_sha256': first.sha256, 'feature_sha256': digest([w['measurements']['feature_pair_sha256'] for w in fit['windows']]),
                    'parents': list(self.request.stage.parent_candidate_ids), 'stage': self.request.stage.to_dict(),
                    'render_engine_sha256': self.render_engine_sha256, 'feature_method_sha256': self.features.method_sha256,
                    'render_cache_key': key, 'claim': 'editable compatible recipe, never identification of an original production chain'},
                'reproducibility': reproducibility, 'validation_state': validation_state,
                'eligible': reproducibility == 'repeat-verified' and validation_state != 'rejected' and fit['objectives']['comparable'],
                'structural_rejections': structural_reasons, 'fit': fit, 'render': first.record}
        return Candidate.from_dict(data)


@dataclass(frozen=True)
class AuditSelection:
    """Freeze the fit-selected IDs BEFORE obtaining independent holdout diagnostics."""
    search_id: str
    candidate_ids: tuple[str, ...]

    def __post_init__(self):
        from .contracts import sha
        sha(self.search_id)
        require(1 <= len(self.candidate_ids) <= 256 and len(set(self.candidate_ids)) == len(self.candidate_ids), 'invalid audit selection')
        for value in self.candidate_ids:
            sha(value)
        object.__setattr__(self, 'candidate_ids', tuple(self.candidate_ids))

    def to_dict(self):
        return {'kind': 'InverseAuditSelection', 'version': VERSION, 'search_id': self.search_id, 'candidate_ids': list(self.candidate_ids)}

    @property
    def sha256(self):
        return digest(self.to_dict())


class AuditEvaluator:
    """Separate owner of holdout/whole-target data; never passed to run_grid()."""
    def __init__(self, request, plan, target, search_id):
        self.request, self.plan, self.search_id = request, plan, search_id
        self._target = frozen_audio(target)
        d = request.base_recipe.to_dict()
        self.features = FeatureMeasurements(d['time_map']['sample_rate_hz'], d['tuning']['reference_hz'], request.objective.sonority)

    def evaluate(self, candidate, selection, *, check_cancelled=lambda: None):
        require(isinstance(candidate, Candidate) and isinstance(selection, AuditSelection), 'candidate and frozen AuditSelection required')
        require(candidate.to_dict()['search_id'] == selection.search_id == self.search_id and candidate.id in selection.candidate_ids,
                'audit cannot silently choose a new candidate or search')
        check_cancelled()
        trace = render_trace(candidate.recipe)
        reproduced = trace.sha256 == candidate.to_dict()['provenance']['render_sha256']
        holdout = _evaluate_windows(trace, self.plan.holdout,
            tuple(self._target[w.start_sample:w.end_sample] for w in self.plan.holdout), self.features,
            self.request.objective, self.request.validation, check_cancelled)
        # A rich whole-signal diagnostic may exceed the explicitly bounded sonority excerpt cap.
        # Do not silently truncate or drop sonority: require a smaller target for rich mode.
        whole = _evaluate_windows(trace, (Window('whole-signal', 0, len(self._target)),), (self._target,),
            self.features, self.request.objective, self.request.validation, check_cancelled)
        fit_score, held_score = candidate.score, holdout['objectives']['score']
        gap = None if fit_score is None or held_score is None else held_score-fit_score
        return {'kind': 'InverseAudit', 'version': VERSION, 'candidate_id': candidate.id,
                'selection': selection.to_dict(), 'selection_sha256': selection.sha256,
                'window_plan': self.plan.to_dict(), 'reproducibility': 'repeat-verified' if reproduced else 'divergent',
                'fit_score_frozen': fit_score, 'holdout': holdout, 'whole_signal': whole,
                'generalisation_gap': gap,
                'overfit_warning': gap is not None and fit_score < .05 and gap > .25,
                'overfit_rule': 'exploratory engineering flag: fit score <0.05 and holdout-fit >0.25; not a significance test',
                'selection_policy': 'audit-only; holdout never changes fit ranking, candidate identity or budget'}


def prepare_experiment(request, target, plan, **fit_kwargs):
    require(isinstance(request, SearchRequest) and isinstance(plan, WindowPlan), 'request and plan required')
    target = frozen_audio(target)
    asset = Contract(pcm_asset(target, request.target_asset.to_dict()['sample_rate_hz']))
    require(asset.sha256 == request.target_asset.sha256, 'target samples do not match declared AudioAssetRef')
    require(tuple(request.fitting_windows) == plan.fit and len(target) == plan.frame_count, 'window plan differs from fitting request')
    if request.objective.sonority:
        require(len(target) <= 16384, 'rich v1 audit requires <=16384-sample target; no implicit truncation')
    fit = FitEvaluator(request, tuple(target[w.start_sample:w.end_sample] for w in plan.fit), **fit_kwargs)
    audit = AuditEvaluator(request, plan, target, fit.search_id)
    return fit, audit
