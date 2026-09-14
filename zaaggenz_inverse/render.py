"""Canonical PCM boundaries and an adapter to the accepted ZG-016/019 graph."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import platform
import re
from typing import Protocol, Callable

import numpy as np
import scipy
from threadpoolctl import threadpool_info

from zaaggenz_contracts import Contract, digest, loads
from zaaggenz_contracts.recipe_schema import recipes
from zaaggenz_contracts.registry import node_definition
from zaaggenz_contracts.validation import shape
from zaaggenz_descriptors.audio import pcm_asset
from zaaggenz_dsp.graph import execute_graph, apply_output_policy
from .contracts import (Snapshot, ParameterState, ParameterDomain, MAX_FRAMES, document,
                        require, integer, identifier, finite)

OUTPUT_SCHEMA = recipes()['RenderRecipe']['properties']['output']
DEFAULT_OUTPUT = dict(master_gain_db=0., clipping='unbounded_float', normalisation='none',
                      diagnostic_stems='pre_master', mix='post_master')


def execution_identity():
    """Code + numerical stack, not a mutable branch name or the current clock."""
    root = Path(__file__).resolve().parents[1]
    packages = ('zaaggenz_inverse', 'zaaggenz_contracts', 'zaaggenz_analysis', 'zaaggenz_components',
                'zaaggenz_descriptors', 'zaaggenz_spectral', 'zaaggenz_tuning', 'zaaggenz_dsp',
                'zaaggenz_project', 'zaaggenz_qc', 'zaaggenz_jobs')
    files = {str(p.relative_to(root)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest()
             for package in packages for p in sorted((root / package).glob('*.py'))}
    require(all(any(k.startswith(p + '/') for k in files) for p in packages), 'implementation source is unavailable')
    return {'implementation_sha256': digest({'domain': 'zg.inverse.implementation.v1', 'files': files}),
            'numeric': {'policy': 'pcm-f32-input-f64-measurement-same-environment-exact-v1',
                        'python': platform.python_version(), 'numpy': np.__version__, 'scipy': scipy.__version__,
                        'platform': platform.system(), 'machine': platform.machine(),
                        'backend_sha256': digest([{k: row.get(k) for k in ('internal_api', 'user_api', 'version', 'architecture', 'num_threads')}
                                                  for row in threadpool_info()])}}


@dataclass(frozen=True, init=False)
class AudioBuffer:
    """Immutable PCM bytes. Measurements use exactly the samples named by the asset."""
    pcm: bytes
    asset: Contract

    def __init__(self, audio, sample_rate_hz, level_domain='source'):
        a = np.asarray(audio)
        require(a.ndim in (1, 2) and (a.ndim == 1 or a.shape[1] in (1, 2)), 'mono/stereo signal required')
        integer(len(a), 'signal frames', 32, MAX_FRAMES)
        require(np.issubdtype(a.dtype, np.number) and not np.iscomplexobj(a), 'real numeric signal required')
        require(np.isfinite(a).all() and np.max(np.abs(a)) <= 1e6, 'nonfinite or excessive output')
        a = np.asarray(a, dtype='<f4', order='C')
        if a.ndim == 2 and a.shape[1] == 1:
            a = a[:, 0]
        asset = Contract(pcm_asset(a, sample_rate_hz, level_domain))
        object.__setattr__(self, 'pcm', a.tobytes(order='C'))
        object.__setattr__(self, 'asset', asset)

    @property
    def audio(self):
        a = np.frombuffer(self.pcm, dtype='<f4')
        channels = self.asset.to_dict()['channels']
        return a if channels == 1 else a.reshape(-1, channels)

    @property
    def rate(self):
        return self.asset.to_dict()['sample_rate_hz']

    def excerpt(self, window):
        return AudioBuffer(self.audio[window.start:window.end], self.rate, self.asset.to_dict()['level_domain'])


@dataclass(frozen=True)
class Rendered:
    """Both sides of ONE declared output policy; no inferred/hidden gain removal."""
    before_gain: AudioBuffer
    output: AudioBuffer
    policy: Snapshot
    recipe: Snapshot

    def __post_init__(self):
        require(isinstance(self.before_gain, AudioBuffer) and isinstance(self.output, AudioBuffer), 'AudioBuffer taps required')
        require(isinstance(self.policy, Snapshot) and isinstance(self.recipe, Snapshot), 'owned render metadata required')
        shape(self.policy.to_dict(), OUTPUT_SCHEMA)
        require(self.before_gain.audio.shape == self.output.audio.shape and self.before_gain.rate == self.output.rate, 'render tap shape/rate mismatch')

    def identity(self):
        return document('InverseRender', before_gain=self.before_gain.asset.to_dict(),
                        output=self.output.asset.to_dict(), output_policy=self.policy.to_dict(),
                        recipe=self.recipe.to_dict(), pcm_boundary='f32-before-and-after-master')

    @property
    def sha256(self):
        return digest(self.identity())


def finish_render(pre_master, rate, recipe, output_policy=None):
    policy = Snapshot(DEFAULT_OUTPUT if output_policy is None else output_policy)
    shape(policy.to_dict(), OUTPUT_SCHEMA)
    before = AudioBuffer(pre_master, rate, 'pre_master')
    after, _ = apply_output_policy(before.audio, policy.to_dict())
    return Rendered(before, AudioBuffer(after, rate, 'post_master'), policy, Snapshot(recipe))


class Renderer(Protocol):
    source: AudioBuffer

    @property
    def method(self) -> dict: ...

    def validate_domain(self, domain: ParameterDomain) -> None: ...

    def render(self, state: ParameterState, seed: str, checkpoint: Callable[[], None]) -> Rendered: ...


_NODE_BINDING = re.compile(r'^/nodes/([0-9]+)/params/([a-z][a-z0-9_]*)$')
_AUTO_BINDING = re.compile(r'^/nodes/([0-9]+)/automation/([0-9]+)/points/([0-9]+)/value$')


def _parent(data, pointer):
    parts = pointer.lstrip('/').split('/')
    current = data
    for part in parts[:-1]:
        current = current[int(part)] if isinstance(current, list) else current[part]
    key = int(parts[-1]) if isinstance(current, list) else parts[-1]
    return current, key


@dataclass(frozen=True, init=False)
class GraphRenderer:
    """Bind bounded numeric JSON pointers into real, validated DSPNodeSpec records.

    Nonlinear order, anti-alias mode, automation and final output semantics remain
    those of the accepted graph. No inverse-only DSP node representation exists.
    """
    source: AudioBuffer
    _configuration: Snapshot

    def __init__(self, source, nodes, bindings, *, output_node, output_policy=None):
        require(isinstance(source, AudioBuffer), 'canonical source required')
        require(isinstance(nodes, (tuple, list)) and 1 <= len(nodes) <= 8, '1..8 existing DSP nodes required')
        rows = [n.to_dict() if isinstance(n, Contract) else Contract(n).to_dict() for n in nodes]
        require(all(n['kind'] == 'DSPNodeSpec' for n in rows), 'DSPNodeSpec required')
        require(type(bindings) is dict and 1 <= len(bindings) <= 16, 'bounded binding mapping required')
        require(len(set(bindings.values())) == len(bindings), 'two parameters cannot bind the same field')
        policy = dict(DEFAULT_OUTPUT if output_policy is None else output_policy)
        shape(policy, OUTPUT_SCHEMA)
        config = {'nodes': rows, 'output_node': output_node, 'bindings': dict(sorted(bindings.items())),
                  'output_policy': policy, 'source': source.asset.to_dict()}
        for name, pointer in bindings.items():
            identifier(name)
            require(type(pointer) is str and (_NODE_BINDING.fullmatch(pointer) or _AUTO_BINDING.fullmatch(pointer)
                                              or pointer == '/output_policy/master_gain_db'), 'unsupported parameter binding')
            try:
                parent, key = _parent(config, pointer)
                finite(parent[key], name)
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise ValueError('binding does not address an existing numeric field') from exc
        # Validate graph topology without assuming default parameters are musical truth.
        execute_graph(source.audio[:32], source.rate, rows, output_node, capture_taps=False)
        object.__setattr__(self, 'source', source)
        object.__setattr__(self, '_configuration', Snapshot(config))

    @property
    def method(self):
        return {'id': 'zg.inverse.graph-adapter.v1', 'version': '1.0.0',
                'configuration': {'recipe_json': self._configuration.to_json(), 'recipe_sha256': self._configuration.sha256}}

    @classmethod
    def from_method(cls, source, method):
        require(type(method) is dict and method.get('id') == 'zg.inverse.graph-adapter.v1' and method.get('version') == '1.0.0', 'unsupported graph adapter')
        configuration = method.get('configuration', {})
        require(set(configuration) == {'recipe_json', 'recipe_sha256'}, 'invalid graph method configuration')
        recipe = Snapshot(loads(configuration['recipe_json']))
        require(recipe.sha256 == configuration['recipe_sha256'], 'graph recipe hash mismatch')
        c = recipe.to_dict()
        require(set(c) == {'nodes', 'output_node', 'bindings', 'output_policy', 'source'}, 'invalid graph recipe')
        require(c['source'] == source.asset.to_dict(), 'graph recipe source mismatch')
        out = cls(source, c['nodes'], c['bindings'], output_node=c['output_node'], output_policy=c['output_policy'])
        require(out.method == method, 'noncanonical graph method')
        return out

    def _binding_schema(self, pointer):
        c = self._configuration.to_dict()
        if pointer == '/output_policy/master_gain_db':
            return OUTPUT_SCHEMA['properties']['master_gain_db'], 'dB'
        match = _NODE_BINDING.fullmatch(pointer)
        if match:
            index, name = int(match[1]), match[2]
        else:
            match = _AUTO_BINDING.fullmatch(pointer)
            index = int(match[1])
            name = c['nodes'][index]['automation'][int(match[2])]['parameter']
        spec = node_definition(c['nodes'][index]['type_id'])['parameters'][name]
        return spec, spec.get('unit')

    def validate_domain(self, domain):
        require(isinstance(domain, ParameterDomain), 'ParameterDomain required')
        bindings = self._configuration.to_dict()['bindings']
        require(set(bindings) == {b.name for b in domain.bounds}, 'renderer/domain mismatch')
        for bound in domain.bounds:
            spec, unit = self._binding_schema(bindings[bound.name])
            # Endpoint validation enforces the inherited node safety domain too.
            shape(bound.lower, spec)
            shape(bound.upper, spec)
            if unit is not None:
                require(bound.unit == unit, 'binding unit disagrees with DSP registry')
            if spec.get('type') == 'integer':
                require(bound.integral, 'integer DSP binding needs integral domain')

    def render(self, state, seed, checkpoint=lambda: None):
        from zaaggenz_contracts.model import seed_value
        seed_value(seed)  # This stateless graph consumes no random stream.
        c = self._configuration.to_dict()
        require(set(state.to_dict()) == set(c['bindings']), 'missing/unknown graph parameter')
        for name, value in state.values:
            parent, key = _parent(c, c['bindings'][name])
            parent[key] = int(value) if self._binding_schema(c['bindings'][name])[0].get('type') == 'integer' else value
        checkpoint()
        result = execute_graph(self.source.audio, self.source.rate, c['nodes'], c['output_node'], capture_taps=False)
        checkpoint()
        return finish_render(result.output, self.source.rate,
                             {'method': self.method['id'], 'nodes': c['nodes'], 'order': list(result.order),
                              'output_node': c['output_node'], 'source': c['source'], 'seed': seed,
                              'randomness': 'none; declared seed retained for lineage'}, c['output_policy'])
