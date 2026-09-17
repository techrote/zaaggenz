"""Immutable, versioned result envelopes with explicit provenance and nullable losses."""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
from zaaggenz_contracts import Contract, digest, loads
from .contracts import (VERSION, LOSS_UNITS, ParameterState, SearchRequest, InverseError, require,
                        sha, integer, finite, identifier)


CANDIDATE_VERSION = '2.0.0'
SEARCH_BINDING_VERSION = '1.0.0'
_CLAIM = 'editable compatible recipe, never identification of an original production chain'


def candidate_identity(search_id, state, recipe, search_binding_sha256=None):
    """Return the persisted candidate identity.

    The three-argument form retains the historical v1 identity helper for explicit
    migration/testing only. Current persisted Candidate records are v2 and bind the
    authenticated search/provenance envelope as a fourth identity input.
    """
    if search_binding_sha256 is None:
        return digest({'domain': 'zaaggenz.inverse-candidate-v1', 'search_id': search_id,
                       'state': state.to_dict(), 'recipe_sha256': recipe.sha256})
    sha(search_binding_sha256, 'search_binding_sha256')
    return digest({'domain': 'zaaggenz.inverse-candidate-v2', 'search_id': search_id,
                   'search_binding_sha256': search_binding_sha256,
                   'state': state.to_dict(), 'recipe_sha256': recipe.sha256})


def search_identity(binding):
    """Recompute the accepted v1 search ID from a persisted search binding.

    Environment is deliberately not added to the historical search-ID domain: it
    remains a separate resumability dimension. Candidate v2 binds it through the
    complete search-binding digest instead.
    """
    method = binding['method']
    return digest({'domain': 'zaaggenz.inverse-search-v1', 'request': binding['request'],
                   'implementation_sha256': method['implementation_sha256'],
                   'feature_method_sha256': method['feature_method_sha256'],
                   'fit_assets': binding['fit_assets']})


def validate_search_binding(binding, expected_search_id=None):
    """Validate and cryptographically bind request, method, environment and fit inputs."""
    expected = {'kind', 'version', 'request', 'method', 'environment', 'fit_assets'}
    require(type(binding) is dict and set(binding) == expected and
            binding.get('kind') == 'InverseSearchBinding' and
            binding.get('version') == SEARCH_BINDING_VERSION,
            'invalid inverse search binding/version')
    request = SearchRequest.from_dict(binding['request'])

    method = binding['method']
    method_fields = {'renderer_id', 'engine_sha256', 'render_engine_base_sha256',
                     'implementation_sha256', 'render_engine_sha256', 'feature_method_sha256'}
    require(type(method) is dict and set(method) == method_fields, 'invalid inverse method binding')
    identifier(method['renderer_id'], 'renderer_id')
    for key in ('engine_sha256', 'render_engine_base_sha256', 'implementation_sha256',
                'render_engine_sha256', 'feature_method_sha256'):
        sha(method[key], key)
    require(method['implementation_sha256'] == digest({'engine': method['engine_sha256'],
                                                       'renderer_id': method['renderer_id']}),
            'implementation identity does not match method binding')
    require(method['render_engine_sha256'] == digest({'engine': method['render_engine_base_sha256'],
                                                      'renderer_id': method['renderer_id']}),
            'render-engine identity does not match method binding')

    environment = binding['environment']
    environment_fields = {'python', 'implementation', 'numpy', 'scipy', 'numeric_backends', 'system',
                          'machine', 'byteorder', 'numerical_policy', 'numeric_threads'}
    require(type(environment) is dict and set(environment) == environment_fields,
            'invalid inverse environment manifest')
    require(type(environment['numeric_backends']) is list, 'numeric backend manifest must be a list')
    require(type(environment['numeric_threads']) is int and environment['numeric_threads'] == 1,
            'inverse numerical thread policy mismatch')
    environment_sha256 = digest(environment)

    fit_assets = binding['fit_assets']
    require(type(fit_assets) is list and len(fit_assets) == len(request.fitting_windows),
            'search binding must retain one fitting asset identity per fitting window')
    target = request.target_asset.to_dict()
    for raw, window in zip(fit_assets, request.fitting_windows):
        asset = Contract(raw)
        row = asset.to_dict()
        require(row['kind'] == 'AudioAssetRef' and row['identity_domain'] == 'pcm-f32le-interleaved-v1'
                and row['sample_policy'] == 'unclamped_float', 'canonical fitting AudioAssetRef required')
        require(row['frame_count'] == window.end_sample-window.start_sample,
                'fitting asset length differs from declared fitting window')
        require(row['sample_rate_hz'] == target['sample_rate_hz'] and row['channels'] == target['channels'],
                'fitting asset timing/channel domain differs from target')

    actual_search_id = search_identity(binding)
    if expected_search_id is not None:
        sha(expected_search_id, 'search_id')
        require(actual_search_id == expected_search_id,
                'search identity does not match authenticated request/method/fitting assets')
    return request, actual_search_id, digest(binding), environment_sha256


def validate_vector(vector):
    require(type(vector) is dict and set(vector) == {'kind', 'version', 'components', 'pareto_axes', 'score',
            'comparable', 'window_aggregation', 'score_semantics'} and vector.get('kind') == 'InverseObjectiveVector' and vector.get('version') == VERSION,
            'versioned inverse objective vector required')
    require(set(vector['components']) == set(LOSS_UNITS), 'loss vector must preserve every named component')
    for value in vector['components'].values():
        if value is not None:
            require(finite(value, 'loss') >= 0, 'loss must be nonnegative')
    require(type(vector['comparable']) is bool, 'comparable flag required')
    if vector['score'] is not None:
        require(finite(vector['score'], 'score') >= 0 and vector['comparable'], 'invalid aggregate score')
    else:
        require(not vector['comparable'], 'comparable score cannot be null')
    names = []
    for axis in vector['pareto_axes']:
        require(set(axis) == {'name', 'value', 'scale', 'weight', 'scaled_value', 'unit', 'direction'}, 'invalid objective axis fields')
        name = axis['name']
        require(name in LOSS_UNITS and axis['unit'] == LOSS_UNITS[name] and axis['direction'] == 'minimize', 'invalid Pareto axis')
        require(axis['value'] == vector['components'][name], 'Pareto value differs from retained component')
        require(finite(axis['scale'], 'scale') > 0 and finite(axis['weight'], 'weight') >= 0, 'invalid Pareto scaling')
        scaled = None if axis['value'] is None else axis['value']/axis['scale']
        require(axis['scaled_value'] == scaled, 'forged Pareto scaling')
        names.append(name)
    require(len(names) == len(set(names)) and names, 'duplicate/empty Pareto axes')
    active = [a for a in vector['pareto_axes'] if a['weight'] > 0]
    require(active, 'at least one active objective is required')
    comparable = all(a['value'] is not None for a in active)
    expected = math.sqrt(sum(a['weight']*a['scaled_value']**2 for a in active)/sum(a['weight'] for a in active)) if comparable else None
    require(vector['comparable'] == comparable and vector['score'] == expected, 'score does not match retained components')
    return vector


@dataclass(frozen=True)
class Candidate:
    """JSON-backed immutable record; accessors return copies, not mutable shared state."""
    _json: str

    def __post_init__(self):
        try:
            d = loads(self._json)
            if type(d) is dict and d.get('kind') == 'InverseCandidate' and d.get('version') == VERSION:
                raise InverseError('legacy InverseCandidate 1.0.0 lacks authenticated search provenance; replay/regenerate it under Candidate 2.0.0')
            expected = {'kind', 'version', 'candidate_id', 'search_id', 'ordinal', 'parameters', 'recipe',
                        'provenance', 'reproducibility', 'validation_state', 'eligible', 'fit', 'render', 'structural_rejections'}
            require(type(d) is dict and set(d) == expected and d['kind'] == 'InverseCandidate' and d['version'] == CANDIDATE_VERSION,
                    'invalid candidate envelope/version')
            sha(d['candidate_id']); sha(d['search_id']); integer(d['ordinal'], 'ordinal', 0, 255)
            state, recipe = ParameterState.from_dict(d['parameters']), Contract(d['recipe'])
            from .recipes import _resolve
            for path, value in state.values:
                container, key = _resolve(recipe.to_dict(), path)
                require(container[key] == value, 'candidate state does not match editable recipe')

            provenance = d['provenance']
            provenance_fields = {'implementation_sha256', 'environment_sha256', 'source_revision_id',
                'base_recipe_sha256', 'target_asset_sha256', 'render_sha256', 'feature_sha256', 'parents', 'stage',
                'render_engine_sha256', 'feature_method_sha256', 'render_cache_key', 'claim',
                'search_binding', 'search_binding_sha256'}
            require(type(provenance) is dict and set(provenance) == provenance_fields,
                    'invalid candidate provenance envelope')
            request, search_id, binding_sha256, environment_sha256 = validate_search_binding(
                provenance['search_binding'], d['search_id'])
            sha(provenance['search_binding_sha256'], 'search_binding_sha256')
            require(provenance['search_binding_sha256'] == binding_sha256,
                    'search binding identity mismatch')
            require(d['candidate_id'] == candidate_identity(search_id, state, recipe, binding_sha256),
                    'candidate identity does not match recipe/state/search provenance')

            method = provenance['search_binding']['method']
            expected_provenance = {
                'implementation_sha256': method['implementation_sha256'],
                'environment_sha256': environment_sha256,
                'source_revision_id': request.source_revision_id,
                'base_recipe_sha256': request.base_recipe.sha256,
                'target_asset_sha256': request.target_asset.sha256,
                'render_engine_sha256': method['render_engine_sha256'],
                'feature_method_sha256': method['feature_method_sha256'],
            }
            for key, expected_value in expected_provenance.items():
                sha(provenance[key], key)
                require(provenance[key] == expected_value, key + ' differs from authenticated search binding')
            require(provenance['stage'] == request.stage.to_dict(),
                    'candidate stage differs from authenticated search request')
            require(provenance['parents'] == list(request.stage.parent_candidate_ids),
                    'candidate parents differ from authenticated search request')
            require(provenance['claim'] == _CLAIM, 'candidate provenance claim changed')
            sha(provenance['render_cache_key'], 'render_cache_key')

            require(d['reproducibility'] in ('repeat-verified', 'divergent', 'non-reproducible'), 'explicit reproducibility state required')
            require(d['validation_state'] in ('accepted', 'accepted-with-exceptions', 'rejected'), 'candidate validation state required')
            require(type(d['eligible']) is bool, 'eligible must be bool')
            vector = validate_vector(d['fit']['objectives'])
            from .contracts import ObjectivePolicy, ObjectiveTerm
            from .objectives import aggregate
            terms = tuple(ObjectiveTerm(a['name'], a['scale'], a['weight']) for a in vector['pareto_axes'])
            policy = ObjectivePolicy(terms, sonority=any(a.name in ('comb_fit', 'roughness', 'interaction') for a in terms))
            require(digest(vector) == digest(aggregate(d['fit']['windows'], policy)), 'aggregate differs from fitting-window measurements')
            require(provenance['feature_sha256'] == digest([w['measurements']['feature_pair_sha256'] for w in d['fit']['windows']]),
                    'feature identity mismatch')
            for key in ('render_sha256', 'feature_sha256'):
                sha(provenance[key], key)
            require(provenance['render_sha256'] == digest(d['render']), 'render identity mismatch')
            require(d['render']['recipe_sha256'] == recipe.sha256, 'render references another recipe')
            if d['eligible']:
                require(not d['structural_rejections'] and d['reproducibility'] == 'repeat-verified' and d['validation_state'] != 'rejected'
                        and d['fit']['objectives']['comparable'], 'invalid/divergent candidate cannot be eligible')
            if any(w['validation']['state'] == 'rejected' for w in d['fit']['windows']):
                require(not d['eligible'] and d['validation_state'] == 'rejected', 'rejected window cannot become a successful candidate')
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, InverseError):
                raise
            raise InverseError('malformed candidate record') from exc

    @classmethod
    def from_dict(cls, data):
        return cls(json.dumps(data, sort_keys=True, allow_nan=False, separators=(',', ':')))

    def to_dict(self):
        return loads(self._json)

    @property
    def sha256(self):
        return digest(self.to_dict())

    @property
    def id(self):
        return self.to_dict()['candidate_id']

    @property
    def recipe(self):
        return Contract(self.to_dict()['recipe'])

    @property
    def eligible(self):
        return self.to_dict()['eligible']

    @property
    def score(self):
        return self.to_dict()['fit']['objectives']['score']


def pareto_front(candidates):
    """Keep all equivalent alternatives. Unknown values never dominate known values."""
    eligible = [c for c in candidates if c.eligible]
    vectors = []
    names = None
    for candidate in eligible:
        vector = candidate.to_dict()['fit']['objectives']
        validate_vector(vector)
        axes = vector['pareto_axes']  # Includes explicitly requested zero-weight diagnostic axes.
        this_names = tuple((a['name'], a['scale'], a['unit']) for a in axes)
        if names is None:
            names = this_names
        require(this_names == names, 'Pareto candidates must share objective definitions/scales')
        values = tuple(a['scaled_value'] for a in axes)
        vectors.append(values)
    out = []
    for i, candidate in enumerate(eligible):
        a = vectors[i]
        if any(v is None for v in a):
            continue  # Not comparable on the declared Pareto axes; remains in full result archive.
        dominated = any(j != i and all(v is not None for v in b) and
                        all(x <= y for x, y in zip(b, a)) and any(x < y for x, y in zip(b, a))
                        for j, b in enumerate(vectors))
        if not dominated:
            out.append(candidate.id)
    return tuple(out)
