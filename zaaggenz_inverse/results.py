"""Immutable, versioned result envelopes with explicit provenance and nullable losses."""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
from zaaggenz_contracts import Contract, digest, loads
from .contracts import (VERSION, LOSS_UNITS, ParameterState, InverseError, require,
                        sha, integer, finite)


def candidate_identity(search_id, state, recipe):
    return digest({'domain': 'zaaggenz.inverse-candidate-v1', 'search_id': search_id,
                   'state': state.to_dict(), 'recipe_sha256': recipe.sha256})


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
            expected = {'kind', 'version', 'candidate_id', 'search_id', 'ordinal', 'parameters', 'recipe',
                        'provenance', 'reproducibility', 'validation_state', 'eligible', 'fit', 'render', 'structural_rejections'}
            require(type(d) is dict and set(d) == expected and d['kind'] == 'InverseCandidate' and d['version'] == VERSION,
                    'invalid candidate envelope/version')
            sha(d['candidate_id']); sha(d['search_id']); integer(d['ordinal'], 'ordinal', 0, 255)
            state, recipe = ParameterState.from_dict(d['parameters']), Contract(d['recipe'])
            from .recipes import _resolve
            for path, value in state.values:
                container, key = _resolve(recipe.to_dict(), path)
                require(container[key] == value, 'candidate state does not match editable recipe')
            require(d['candidate_id'] == candidate_identity(d['search_id'], state, recipe), 'candidate identity does not match recipe/state')
            require(d['reproducibility'] in ('repeat-verified', 'divergent', 'non-reproducible'), 'explicit reproducibility state required')
            require(d['validation_state'] in ('accepted', 'accepted-with-exceptions', 'rejected'), 'candidate validation state required')
            require(type(d['eligible']) is bool, 'eligible must be bool')
            vector = validate_vector(d['fit']['objectives'])
            from .contracts import ObjectivePolicy, ObjectiveTerm
            from .objectives import aggregate
            terms = tuple(ObjectiveTerm(a['name'], a['scale'], a['weight']) for a in vector['pareto_axes'])
            policy = ObjectivePolicy(terms, sonority=any(a.name in ('comb_fit', 'roughness', 'interaction') for a in terms))
            require(digest(vector) == digest(aggregate(d['fit']['windows'], policy)), 'aggregate differs from fitting-window measurements')
            require(d['provenance']['feature_sha256'] == digest([w['measurements']['feature_pair_sha256'] for w in d['fit']['windows']]),
                    'feature identity mismatch')
            for key in ('implementation_sha256', 'environment_sha256', 'source_revision_id', 'base_recipe_sha256',
                        'target_asset_sha256', 'render_sha256', 'feature_sha256'):
                sha(d['provenance'][key], key)
            require(d['provenance']['render_sha256'] == digest(d['render']), 'render identity mismatch')
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
