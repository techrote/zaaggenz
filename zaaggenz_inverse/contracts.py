"""Small inverse-laboratory contracts. Frozen ZG-002 contracts are composed, not widened."""
from __future__ import annotations

from dataclasses import dataclass, fields
import math
import re
from typing import ClassVar

from zaaggenz_contracts import Contract, ContractError, digest, loads
from zaaggenz_contracts.model import seed_value

VERSION = '1.0.0'
MAX_EVALUATIONS = 256
MAX_FRAMES = 262144


class InverseError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise InverseError(message)


def finite(value, name):
    require(type(value) in (int, float) and math.isfinite(value), name + ' must be finite numeric, not bool')
    return float(value)


def integer(value, name, lo=0, hi=2**53-1):
    require(type(value) is int and lo <= value <= hi, f'{name} must be an integer in [{lo}, {hi}]')
    return value


def sha(value, name='identity'):
    require(type(value) is str and re.fullmatch('[0-9a-f]{64}', value), name + ' must be lowercase SHA-256')
    return value


def identifier(value, name='id'):
    require(type(value) is str and re.fullmatch('[a-z][a-z0-9_.-]{0,63}', value), 'invalid ' + name)
    return value


def encode(value):
    if isinstance(value, Contract):
        return value.to_dict()
    if isinstance(value, Model):
        return value.to_dict()
    if isinstance(value, tuple):
        return [encode(x) for x in value]
    if isinstance(value, dict):
        return {k: encode(v) for k, v in value.items()}
    return value


class Model:
    """Pure-data serialization; canonical identities use the accepted zg-c14n-v1 hash."""
    version: ClassVar[str] = VERSION

    def to_dict(self):
        return {'kind': type(self).__name__, 'version': VERSION,
                **{f.name: encode(getattr(self, f.name)) for f in fields(self)}}

    @property
    def sha256(self):
        return digest(self.to_dict())

    @classmethod
    def unpack(cls, data):
        require(type(data) is dict, cls.__name__ + ' must be an object')
        require(set(data) == {'kind', 'version', *(f.name for f in fields(cls))}, 'unknown/missing ' + cls.__name__ + ' fields')
        require(data['kind'] == cls.__name__ and data['version'] == VERSION, 'unsupported ' + cls.__name__ + ' version')
        return {k: v for k, v in data.items() if k not in ('kind', 'version')}


@dataclass(frozen=True)
class ParameterAxis(Model):
    path: str
    lower: float
    upper: float
    unit: str
    numeric_type: str = 'number'

    def __post_init__(self):
        require(type(self.path) is str and re.fullmatch(r'/(?:[a-z_][a-z0-9_]*|0|[1-9][0-9]*)(?:/(?:[a-z_][a-z0-9_]*|0|[1-9][0-9]*))*', self.path), 'canonical numeric recipe pointer required')
        lo, hi = finite(self.lower, 'lower'), finite(self.upper, 'upper')
        require(lo <= hi, 'reversed parameter bounds')
        require(self.numeric_type in ('number', 'integer'), 'unsupported numeric type')
        if self.numeric_type == 'integer':
            require(lo.is_integer() and hi.is_integer(), 'integer bounds must be integral')
        require(type(self.unit) is str and 1 <= len(self.unit) <= 32, 'explicit unit required')
        object.__setattr__(self, 'lower', int(lo) if self.numeric_type == 'integer' else lo)
        object.__setattr__(self, 'upper', int(hi) if self.numeric_type == 'integer' else hi)

    @classmethod
    def from_dict(cls, data):
        return cls(**cls.unpack(data))


@dataclass(frozen=True)
class ParameterState(Model):
    values: tuple[tuple[str, float], ...]

    def __post_init__(self):
        try:
            values = tuple(sorted(tuple(x) for x in self.values))
        except (TypeError, ValueError) as exc:
            raise InverseError('parameter values must be path/value pairs') from exc
        require(1 <= len(values) <= 16 and all(len(x) == 2 for x in values), '1..16 parameter pairs required')
        require(all(type(x[0]) is str for x in values), 'parameter paths must be strings')
        require(len({x[0] for x in values}) == len(values), 'duplicate parameter path')
        for path, value in values:
            finite(value, path)
        object.__setattr__(self, 'values', values)

    @classmethod
    def from_dict(cls, data):
        return cls(**cls.unpack(data))


@dataclass(frozen=True)
class ParameterDomain(Model):
    axes: tuple[ParameterAxis, ...]

    def __post_init__(self):
        require(1 <= len(self.axes) <= 16 and all(isinstance(x, ParameterAxis) for x in self.axes), '1..16 axes required')
        axes = tuple(sorted(self.axes, key=lambda a: a.path))
        require(len({a.path for a in axes}) == len(axes), 'duplicate axis')
        object.__setattr__(self, 'axes', axes)

    def validate_state(self, state):
        require(isinstance(state, ParameterState), 'ParameterState required')
        require([a.path for a in self.axes] == [k for k, _ in state.values], 'state must contain exactly the domain paths')
        for axis, (_, value) in zip(self.axes, state.values):
            finite(value, axis.path)
            require(axis.lower <= value <= axis.upper, 'parameter-bound violation: ' + axis.path)
            if axis.numeric_type == 'integer':
                require(type(value) is int, 'integer parameter required: ' + axis.path)
        return state

    @classmethod
    def from_dict(cls, data):
        d = cls.unpack(data)
        return cls(tuple(ParameterAxis.from_dict(x) for x in d['axes']))


@dataclass(frozen=True)
class Window(Model):
    id: str
    start_sample: int
    end_sample: int

    def __post_init__(self):
        identifier(self.id)
        integer(self.start_sample, 'window start', 0, MAX_FRAMES)
        integer(self.end_sample, 'window end', 1, MAX_FRAMES)
        require(self.end_sample - self.start_sample >= 32, 'window must contain at least 32 samples')

    @property
    def support(self):
        return dict(start_sample=self.start_sample, end_sample=self.end_sample,
                    anchor_sample=(self.start_sample+self.end_sample-1)//2, padding='none')

    @classmethod
    def from_dict(cls, data):
        return cls(**cls.unpack(data))


def check_windows(windows, frame_count):
    require(1 <= len(windows) <= 16 and all(isinstance(w, Window) for w in windows), '1..16 explicit windows required')
    require(len({w.id for w in windows}) == len(windows), 'duplicate window id')
    ordered = sorted(windows, key=lambda w: w.start_sample)
    require(all(w.end_sample <= frame_count for w in windows), 'window outside audio')
    require(all(a.end_sample <= b.start_sample for a, b in zip(ordered, ordered[1:])), 'overlapping windows are prohibited')


@dataclass(frozen=True)
class WindowPlan(Model):
    fit: tuple[Window, ...]
    holdout: tuple[Window, ...]
    frame_count: int

    def __post_init__(self):
        integer(self.frame_count, 'frame_count', 32, MAX_FRAMES)
        object.__setattr__(self, 'fit', tuple(self.fit))
        object.__setattr__(self, 'holdout', tuple(self.holdout))
        check_windows(self.fit, self.frame_count)
        check_windows(self.holdout, self.frame_count)
        check_windows(self.fit + self.holdout, self.frame_count)

    @classmethod
    def from_dict(cls, data):
        d = cls.unpack(data)
        return cls(tuple(Window.from_dict(x) for x in d['fit']), tuple(Window.from_dict(x) for x in d['holdout']), d['frame_count'])


@dataclass(frozen=True)
class SearchStage(Model):
    id: str = 'calibration'
    method_id: str = 'zg.inverse.cyclic-grid.v1'
    parent_search_sha256: str | None = None
    parent_candidate_ids: tuple[str, ...] = ()

    def __post_init__(self):
        identifier(self.id)
        require(self.method_id == 'zg.inverse.cyclic-grid.v1', 'only the transparent grid baseline is implemented in this pass')
        if self.parent_search_sha256 is not None:
            sha(self.parent_search_sha256)
        require(len(self.parent_candidate_ids) <= 256, 'too many parent candidates')
        for value in self.parent_candidate_ids:
            sha(value)
        require(len(set(self.parent_candidate_ids)) == len(self.parent_candidate_ids), 'duplicate parent candidate')
        object.__setattr__(self, 'parent_candidate_ids', tuple(self.parent_candidate_ids))

    @classmethod
    def from_dict(cls, data):
        return cls(**cls.unpack(data))


@dataclass(frozen=True)
class SearchBudget(Model):
    max_evaluations: int = 27
    grid_points_per_axis: int = 3
    render_repeats: int = 2

    def __post_init__(self):
        integer(self.max_evaluations, 'max_evaluations', 1, MAX_EVALUATIONS)
        integer(self.grid_points_per_axis, 'grid_points_per_axis', 2, 9)
        require(type(self.render_repeats) is int and self.render_repeats == 2, 'v1 verifies every uncached render twice')

    @classmethod
    def from_dict(cls, data):
        return cls(**cls.unpack(data))


# All are minimization components. Scales are explicit engineering choices, not perceptual tolerances.
LOSS_UNITS = {'waveform': 'ratio', 'spectrum': 'ratio', 'level': 'dB',
              'periodicity': 'ratio', 'occupancy': 'ratio', 'comb_fit': 'ratio',
              'roughness': 'ratio', 'interaction': 'relative_interaction'}


@dataclass(frozen=True)
class ObjectiveTerm(Model):
    name: str
    scale: float = 1.0
    weight: float = 1.0

    def __post_init__(self):
        require(self.name in LOSS_UNITS, 'unregistered inverse objective')
        require(0 < finite(self.scale, 'scale') <= 10000, 'scale must be positive')
        require(0 <= finite(self.weight, 'weight') <= 100, 'weight outside [0,100]')
        object.__setattr__(self, 'scale', float(self.scale))
        object.__setattr__(self, 'weight', float(self.weight))

    @classmethod
    def from_dict(cls, data):
        return cls(**cls.unpack(data))


@dataclass(frozen=True)
class ObjectivePolicy(Model):
    terms: tuple[ObjectiveTerm, ...] = (ObjectiveTerm('waveform'), ObjectiveTerm('spectrum'), ObjectiveTerm('level', 6.0))
    sonority: bool = False
    # Serialized accepted CombTemplate(s), DescriptorAnalysisSpec, STFTSpec and DissonanceModelSpec
    # live in the method manifest, not an inverse-only replacement for those representations.
    def __post_init__(self):
        require(type(self.sonority) is bool, 'sonority must be bool')
        require(1 <= len(self.terms) <= len(LOSS_UNITS) and all(isinstance(x, ObjectiveTerm) for x in self.terms), 'objective terms required')
        require(len({x.name for x in self.terms}) == len(self.terms), 'duplicate objective term')
        require(any(x.weight > 0 for x in self.terms), 'at least one objective weight must be positive')
        require(self.sonority or not any(x.name in ('comb_fit', 'roughness', 'interaction') for x in self.terms), 'sonority objective requires the accepted sonority descriptor path')
        object.__setattr__(self, 'terms', tuple(sorted(self.terms, key=lambda x: x.name)))

    @classmethod
    def from_dict(cls, data):
        d = cls.unpack(data)
        return cls(tuple(ObjectiveTerm.from_dict(x) for x in d['terms']), d['sonority'])


ALLOWABLE_GATES = ('silence_collapse', 'level_mismatch', 'transient_loss', 'pathological_clipping',
                   'bandwidth_collapse', 'energy_collapse', 'destructive_output_clipping', 'normalisation_suspect')


@dataclass(frozen=True)
class ValidationPolicy(Model):
    min_rms_ratio: float = 0.05
    max_level_delta_db: float = 6.0
    min_transient_ratio: float = 0.4
    max_plateau_excess: float = 0.03
    min_bandwidth_ratio: float = 0.25
    min_band_energy_ratio: float = 0.1
    allowed: tuple[str, ...] = ()

    def __post_init__(self):
        for name in ('min_rms_ratio', 'min_transient_ratio', 'max_plateau_excess', 'min_bandwidth_ratio', 'min_band_energy_ratio'):
            require(0 < finite(getattr(self, name), name) <= 1, name + ' outside (0,1]')
            object.__setattr__(self, name, float(getattr(self, name)))
        require(0 < finite(self.max_level_delta_db, 'max_level_delta_db') <= 36, 'invalid level bound')
        object.__setattr__(self, 'max_level_delta_db', float(self.max_level_delta_db))
        require(len(set(self.allowed)) == len(self.allowed) and all(x in ALLOWABLE_GATES for x in self.allowed), 'invalid allowed diagnostic exception')
        object.__setattr__(self, 'allowed', tuple(sorted(self.allowed)))

    @classmethod
    def from_dict(cls, data):
        return cls(**cls.unpack(data))


@dataclass(frozen=True)
class SearchRequest(Model):
    base_recipe: Contract
    source_revision_id: str
    target_asset: Contract
    domain: ParameterDomain
    fitting_windows: tuple[Window, ...]
    seed: str = '24'
    budget: SearchBudget = SearchBudget()
    stage: SearchStage = SearchStage()
    objective: ObjectivePolicy = ObjectivePolicy()
    validation: ValidationPolicy = ValidationPolicy()

    def __post_init__(self):
        require(isinstance(self.base_recipe, Contract) and self.base_recipe.to_dict()['kind'] == 'RenderRecipe', 'existing RenderRecipe required')
        require(isinstance(self.target_asset, Contract) and self.target_asset.to_dict()['kind'] == 'AudioAssetRef', 'existing AudioAssetRef required')
        sha(self.source_revision_id, 'source_revision_id')
        try:
            seed_value(self.seed)
        except ContractError as exc:
            raise InverseError(str(exc)) from exc
        for value, expected in ((self.domain, ParameterDomain), (self.budget, SearchBudget), (self.stage, SearchStage), (self.objective, ObjectivePolicy), (self.validation, ValidationPolicy)):
            require(isinstance(value, expected), expected.__name__ + ' required')
        asset = self.target_asset.to_dict()
        require(asset['identity_domain'] == 'pcm-f32le-interleaved-v1' and asset['sample_policy'] == 'unclamped_float', 'canonical unclamped PCM target required')
        require(32 <= asset['frame_count'] <= MAX_FRAMES, 'target frame bound exceeded')
        require(asset['sample_rate_hz'] == self.base_recipe.to_dict()['time_map']['sample_rate_hz'], 'source/target sample-rate mismatch')
        require(asset['channels'] == self.base_recipe.to_dict()['channels'], 'source/target channels differ')
        object.__setattr__(self, 'fitting_windows', tuple(self.fitting_windows))
        check_windows(self.fitting_windows, asset['frame_count'])

    @classmethod
    def from_dict(cls, data):
        d = cls.unpack(data)
        return cls(Contract(d['base_recipe']), d['source_revision_id'], Contract(d['target_asset']),
                   ParameterDomain.from_dict(d['domain']), tuple(Window.from_dict(x) for x in d['fitting_windows']),
                   d['seed'], SearchBudget.from_dict(d['budget']), SearchStage.from_dict(d['stage']),
                   ObjectivePolicy.from_dict(d['objective']), ValidationPolicy.from_dict(d['validation']))


@dataclass(frozen=True)
class Checkpoint(Model):
    search_id: str
    environment_sha256: str
    next_ordinal: int
    evaluation_sha256s: tuple[str, ...]
    parent_checkpoint_sha256: str | None = None
    policy: str = 'verified-prefix-replay-v1'

    def __post_init__(self):
        sha(self.search_id)
        sha(self.environment_sha256)
        integer(self.next_ordinal, 'next_ordinal', 0, MAX_EVALUATIONS)
        require(self.next_ordinal == len(self.evaluation_sha256s), 'checkpoint prefix length mismatch')
        for value in self.evaluation_sha256s:
            sha(value)
        object.__setattr__(self, 'evaluation_sha256s', tuple(self.evaluation_sha256s))
        if self.parent_checkpoint_sha256 is not None:
            sha(self.parent_checkpoint_sha256)
        require(self.policy == 'verified-prefix-replay-v1', 'unsupported checkpoint policy')

    @classmethod
    def from_dict(cls, data):
        return cls(**cls.unpack(data))

    @classmethod
    def from_json(cls, text):
        try:
            return cls.from_dict(loads(text))
        except (ContractError, TypeError, KeyError) as exc:
            raise InverseError('invalid checkpoint JSON') from exc
