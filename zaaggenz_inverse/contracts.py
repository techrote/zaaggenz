"""ZG-024a v1 contracts; the shared contract enum is deliberately not widened.

AudioAssetRef, JSON canonicalisation, seeds, sample supports and method schemas
are inherited from ZG-002. Inverse-specific objects compose those conventions.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
import re
from typing import Mapping

from zaaggenz_contracts import Contract, ContractError, digest, loads
from zaaggenz_contracts.model import check_json, seed_value
from zaaggenz_contracts.schema import METHOD, SUPPORT
from zaaggenz_contracts.validation import shape

VERSION = '1.0.0'
METHOD_ID = 'zg.inverse.lexicographic-grid.v1'
MAX_FRAMES = 65536
MAX_EVALUATIONS = 512
ID = re.compile(r'^[a-z][a-z0-9_.-]{0,63}$')
HEX = re.compile(r'^[0-9a-f]{64}$')


class InverseError(ContractError):
    """Invalid or incompatible input; inverse contracts never silently coerce it."""


def require(condition, message):
    if not condition:
        raise InverseError(message)


def finite(value, name, lo=-1e9, hi=1e9):
    require(type(value) in (int, float) and math.isfinite(value), name + ' must be finite numeric')
    require(lo <= value <= hi, name + ' outside bounds')
    return float(value)


def integer(value, name, lo=0, hi=MAX_FRAMES):
    require(type(value) is int and lo <= value <= hi, name + ' must be a bounded integer')
    return value


def identifier(value):
    require(type(value) is str and ID.fullmatch(value), 'invalid identifier')
    return value


def sha(value):
    require(type(value) is str and HEX.fullmatch(value), 'invalid SHA-256')
    return value


def fields(data, expected, kind):
    require(type(data) is dict and set(data) == set(expected) | {'kind', 'version'}, kind + ' missing/unknown fields')
    require(data['kind'] == kind and data['version'] == VERSION, 'unsupported ' + kind + ' version')


def document(kind, **values):
    return dict(kind=kind, version=VERSION, **values)


@dataclass(frozen=True, init=False)
class Snapshot:
    """Defensive bounded JSON ownership, using ZG-002 loading/hash conventions."""
    _json: bytes

    def __init__(self, value):
        check_json(value)
        object.__setattr__(self, '_json', json.dumps(value, allow_nan=False, ensure_ascii=False,
                                                  sort_keys=True, separators=(',', ':')).encode('utf-8'))

    def to_dict(self):
        return loads(self._json)

    def to_json(self):
        return self._json.decode('utf-8')

    @property
    def sha256(self):
        return digest(self.to_dict())


@dataclass(frozen=True)
class ParameterBound:
    name: str
    unit: str
    lower: float
    upper: float
    integral: bool = False

    def __post_init__(self):
        identifier(self.name)
        require(type(self.unit) is str and 1 <= len(self.unit) <= 32, 'parameter unit required')
        lo, hi = finite(self.lower, 'lower'), finite(self.upper, 'upper')
        require(lo <= hi, 'reversed bounds')
        require(type(self.integral) is bool, 'integral must be bool')
        require(not self.integral or (lo.is_integer() and hi.is_integer()), 'integer bounds required')
        object.__setattr__(self, 'lower', lo)
        object.__setattr__(self, 'upper', hi)

    def validate(self, value):
        v = finite(value, self.name, self.lower, self.upper)
        require(not self.integral or v.is_integer(), self.name + ' must be integral')
        return int(v) if self.integral else v

    def to_dict(self):
        return document('InverseParameterBound', name=self.name, unit=self.unit,
                        lower=self.lower, upper=self.upper, integral=self.integral)

    @classmethod
    def from_dict(cls, data):
        fields(data, ('name', 'unit', 'lower', 'upper', 'integral'), 'InverseParameterBound')
        return cls(**{k: data[k] for k in ('name', 'unit', 'lower', 'upper', 'integral')})


@dataclass(frozen=True)
class ParameterState:
    values: tuple[tuple[str, float], ...]

    def __post_init__(self):
        require(isinstance(self.values, (tuple, list)) and 1 <= len(self.values) <= 16, '1..16 parameters required')
        rows = tuple(sorted((identifier(k), finite(v, k)) for k, v in self.values))
        require(len({k for k, _ in rows}) == len(rows), 'duplicate parameter')
        object.__setattr__(self, 'values', rows)

    @classmethod
    def from_mapping(cls, values: Mapping):
        require(isinstance(values, Mapping), 'parameter mapping required')
        return cls(tuple(values.items()))

    def to_dict(self):
        return dict(self.values)

    @property
    def sha256(self):
        return digest(document('InverseParameterState', values=self.to_dict()))


@dataclass(frozen=True)
class ParameterDomain:
    bounds: tuple[ParameterBound, ...]

    def __post_init__(self):
        require(isinstance(self.bounds, (tuple, list)) and 1 <= len(self.bounds) <= 16, '1..16 bounds required')
        require(all(isinstance(b, ParameterBound) for b in self.bounds), 'ParameterBound required')
        bounds = tuple(sorted(self.bounds, key=lambda x: x.name))
        require(len({b.name for b in bounds}) == len(bounds), 'duplicate bound')
        object.__setattr__(self, 'bounds', bounds)

    def validate(self, state):
        require(isinstance(state, ParameterState), 'ParameterState required')
        values = state.to_dict()
        require(set(values) == {b.name for b in self.bounds}, 'missing/unknown parameter')
        for bound in self.bounds:
            bound.validate(values[bound.name])
        return state

    def to_dict(self):
        return document('InverseParameterDomain', bounds=[b.to_dict() for b in self.bounds])

    @classmethod
    def from_dict(cls, data):
        fields(data, ('bounds',), 'InverseParameterDomain')
        return cls(tuple(ParameterBound.from_dict(b) for b in data['bounds']))


@dataclass(frozen=True)
class Grid:
    """Explicit levels, ascending axes/values. No objective-dependent ordering."""
    axes: tuple[tuple[str, tuple[float, ...]], ...]

    def __post_init__(self):
        require(isinstance(self.axes, (tuple, list)) and 1 <= len(self.axes) <= 16, 'bounded axes required')
        axes = []
        for name, levels in self.axes:
            identifier(name)
            require(isinstance(levels, (tuple, list)) and 1 <= len(levels) <= 128, '1..128 levels per axis required')
            values = tuple(sorted(finite(v, name) for v in levels))
            require(len(set(values)) == len(values), 'duplicate grid level')
            axes.append((name, values))
        axes = tuple(sorted(axes))
        require(len({k for k, _ in axes}) == len(axes), 'duplicate grid axis')
        object.__setattr__(self, 'axes', axes)
        require(self.size <= 1_000_000, 'grid exceeds one million points')

    @property
    def size(self):
        return math.prod(len(v) for _, v in self.axes)

    def point(self, index):
        integer(index, 'grid index', 0, self.size - 1)
        values = []
        for name, levels in reversed(self.axes):
            index, offset = divmod(index, len(levels))
            values.append((name, levels[offset]))
        return ParameterState(tuple(values))

    def validate(self, domain):
        require(isinstance(domain, ParameterDomain), 'ParameterDomain required')
        require([k for k, _ in self.axes] == [b.name for b in domain.bounds], 'grid/domain mismatch')
        for bound, (_, values) in zip(domain.bounds, self.axes):
            for value in values:
                bound.validate(value)

    def to_dict(self):
        return document('InverseGrid', axes={k: list(v) for k, v in self.axes}, order='lexicographic-ascending')

    @classmethod
    def from_dict(cls, data):
        fields(data, ('axes', 'order'), 'InverseGrid')
        require(data['order'] == 'lexicographic-ascending', 'unsupported grid order')
        require(type(data['axes']) is dict, 'grid axes mapping required')
        return cls(tuple((k, tuple(v)) for k, v in data['axes'].items()))


@dataclass(frozen=True)
class Window:
    id: str
    start: int
    end: int

    def __post_init__(self):
        identifier(self.id)
        integer(self.start, 'window start')
        integer(self.end, 'window end', 1)
        require(self.end - self.start >= 32, 'windows require at least 32 samples')
        shape(self.support, SUPPORT)

    @property
    def support(self):
        return dict(start_sample=self.start, end_sample=self.end,
                    anchor_sample=(self.start + self.end - 1) // 2, padding='none')

    def to_dict(self):
        return document('InverseWindow', id=self.id, support=self.support)

    @classmethod
    def from_dict(cls, data):
        fields(data, ('id', 'support'), 'InverseWindow')
        shape(data['support'], SUPPORT)
        out = cls(data['id'], data['support']['start_sample'], data['support']['end_sample'])
        require(out.support == data['support'], 'noncanonical inverse window support')
        return out


@dataclass(frozen=True)
class WindowPlan:
    fitting: tuple[Window, ...]
    held_out: tuple[Window, ...]

    def __post_init__(self):
        for name in ('fitting', 'held_out'):
            require(isinstance(getattr(self, name), (tuple, list)), 'window list required')
            windows = tuple(getattr(self, name))
            require(1 <= len(windows) <= 4 and all(isinstance(w, Window) for w in windows), '1..4 windows per split required')
            object.__setattr__(self, name, tuple(sorted(windows, key=lambda w: (w.start, w.end, w.id))))
        all_windows = sorted(self.fitting + self.held_out, key=lambda w: w.start)
        require(len({w.id for w in all_windows}) == len(all_windows), 'duplicate window id')
        require(all(a.end <= b.start for a, b in zip(all_windows, all_windows[1:])), 'fit/holdout or within-split overlap')

    def validate_frames(self, frames):
        integer(frames, 'frames', 32)
        require(all(w.end <= frames for w in self.fitting + self.held_out), 'window outside signal')

    def to_dict(self):
        return document('InverseWindowPlan', fitting=[w.to_dict() for w in self.fitting],
                        held_out=[w.to_dict() for w in self.held_out], aggregation='equal-window-mean-v1')

    @classmethod
    def from_dict(cls, data):
        fields(data, ('fitting', 'held_out', 'aggregation'), 'InverseWindowPlan')
        require(data['aggregation'] == 'equal-window-mean-v1', 'unsupported window aggregation')
        return cls(tuple(Window.from_dict(w) for w in data['fitting']),
                   tuple(Window.from_dict(w) for w in data['held_out']))


@dataclass(frozen=True)
class Budget:
    evaluations: int
    retain: int

    def __post_init__(self):
        integer(self.evaluations, 'evaluation budget', 1, MAX_EVALUATIONS)
        integer(self.retain, 'retention budget', 1, min(16, self.evaluations))

    def to_dict(self):
        return document('InverseBudget', evaluations=self.evaluations, retain=self.retain,
                        accounting='one-grid-point-attempt; at-most-two-renders; cache-hits-count')

    @classmethod
    def from_dict(cls, data):
        fields(data, ('evaluations', 'retain', 'accounting'), 'InverseBudget')
        out = cls(data['evaluations'], data['retain'])
        require(out.to_dict() == data, 'unsupported budget accounting')
        return out


@dataclass(frozen=True)
class Stage:
    id: str = 'calibration'
    parent_search_id: str | None = None
    parent_candidate_ids: tuple[str, ...] = ()

    def __post_init__(self):
        identifier(self.id)
        if self.parent_search_id is not None:
            sha(self.parent_search_id)
        parents = tuple(self.parent_candidate_ids)
        require(len(parents) <= 128 and len(set(parents)) == len(parents), 'invalid parent candidates')
        for parent in parents:
            sha(parent)
        require(not parents or self.parent_search_id is not None, 'candidate parents require parent search')
        object.__setattr__(self, 'parent_candidate_ids', parents)

    def to_dict(self):
        return document('InverseStage', id=self.id, parent_search_id=self.parent_search_id,
                        parent_candidate_ids=list(self.parent_candidate_ids))

    @classmethod
    def from_dict(cls, data):
        fields(data, ('id', 'parent_search_id', 'parent_candidate_ids'), 'InverseStage')
        return cls(data['id'], data['parent_search_id'], tuple(data['parent_candidate_ids']))


@dataclass(frozen=True, init=False)
class SearchRequest(Snapshot):
    """Immutable composition of bounded search policy; no target audio or truth."""
    def __init__(self, *, source, target, renderer, domain, grid, windows, budget, seed,
                 objectives, validation, execution, stage=Stage(), source_revision_id=None):
        for asset in (source, target):
            require(isinstance(asset, Contract) and asset.to_dict()['kind'] == 'AudioAssetRef', 'AudioAssetRef Contract required')
            require(asset.to_dict()['identity_domain'] == 'pcm-f32le-interleaved-v1', 'inverse requires decoded canonical PCM')
            integer(asset.to_dict()['frame_count'], 'frames', 32)
        require(isinstance(domain, ParameterDomain) and isinstance(grid, Grid), 'domain/grid required')
        require(isinstance(windows, WindowPlan) and isinstance(budget, Budget) and isinstance(stage, Stage), 'window/budget/stage contract required')
        require(source.to_dict()['sample_rate_hz'] == target.to_dict()['sample_rate_hz'], 'source/target rate mismatch; explicitly resample before search')
        require(source.to_dict()['channels'] == target.to_dict()['channels'], 'source/target channel mismatch')
        grid.validate(domain)
        require(budget.evaluations <= grid.size, 'budget exceeds explicit grid')
        require(budget.retain <= budget.evaluations, 'retention exceeds evaluations')
        windows.validate_frames(target.to_dict()['frame_count'])
        shape(renderer, METHOD)
        seed_value(seed)
        if source_revision_id is not None:
            sha(source_revision_id)
        # These schemas live beside their executable measurement implementations.
        from .objectives import ObjectivePlan
        from .validation import GatePolicy
        ObjectivePlan.from_dict(objectives)
        GatePolicy.from_dict(validation)
        require(type(execution) is dict and set(execution) == {'implementation_sha256', 'numeric'}, 'execution identity required')
        sha(execution['implementation_sha256'])
        numeric = execution['numeric']
        require(type(numeric) is dict and set(numeric) == {'policy', 'python', 'numpy', 'scipy', 'platform', 'machine', 'backend_sha256'}, 'numeric identity required')
        sha(numeric['backend_sha256'])
        require(numeric['policy'] == 'pcm-f32-input-f64-measurement-same-environment-exact-v1', 'unsupported numeric policy')
        require(all(type(v) is str and 1 <= len(v) <= 256 for v in numeric.values()), 'invalid numeric identity')
        super().__init__(document('InverseSearchRequest', source=source.to_dict(), target=target.to_dict(),
            source_revision_id=source_revision_id, renderer=renderer, domain=domain.to_dict(), grid=grid.to_dict(),
            windows=windows.to_dict(), budget=budget.to_dict(), seed=seed, stage=stage.to_dict(),
            method={'id': METHOD_ID, 'version': VERSION, 'configuration': {'order': 'lexicographic-ascending'}},
            objectives=objectives, validation=validation, execution=execution))

    @classmethod
    def from_dict(cls, data):
        keys = ('source', 'target', 'source_revision_id', 'renderer', 'domain', 'grid', 'windows', 'budget',
                'seed', 'stage', 'method', 'objectives', 'validation', 'execution')
        fields(data, keys, 'InverseSearchRequest')
        require(data['method'] == {'id': METHOD_ID, 'version': VERSION, 'configuration': {'order': 'lexicographic-ascending'}}, 'unsupported search method')
        return cls(source=Contract(data['source']), target=Contract(data['target']), renderer=data['renderer'],
                   domain=ParameterDomain.from_dict(data['domain']), grid=Grid.from_dict(data['grid']),
                   windows=WindowPlan.from_dict(data['windows']), budget=Budget.from_dict(data['budget']), seed=data['seed'],
                   stage=Stage.from_dict(data['stage']), source_revision_id=data['source_revision_id'],
                   objectives=data['objectives'], validation=data['validation'], execution=data['execution'])

    @classmethod
    def from_json(cls, text):
        return cls.from_dict(loads(text))

    @property
    def domain(self):
        return ParameterDomain.from_dict(self.to_dict()['domain'])

    @property
    def grid(self):
        return Grid.from_dict(self.to_dict()['grid'])

    @property
    def windows(self):
        return WindowPlan.from_dict(self.to_dict()['windows'])

    @property
    def budget(self):
        return Budget.from_dict(self.to_dict()['budget'])

    def candidate_id(self, state):
        self.domain.validate(state)
        return digest(document('InverseCandidateIdentity', search_id=self.sha256, parameters=state.to_dict()))
