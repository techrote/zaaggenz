"""Bindings into existing RenderRecipe/DSP contracts; no inverse-only synthesizer."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import platform
import sys
import numpy as np
import scipy

from zaaggenz_contracts import Contract, digest
from zaaggenz_contracts.legacy import freeze_legacy, thaw_legacy
from zaaggenz_contracts.registry import legacy_schema, node_definition
from zaaggenz_descriptors import pcm_asset
from zaaggenz_dsp.legacy import render_recipe
from zaaggenz_qc.metrics import diagnose
from .contracts import InverseError, ParameterDomain, ParameterState, require, MAX_FRAMES

ROOT = Path(__file__).resolve().parents[1]
NUMERICAL_POLICY = 'same-environment-exact-f32-and-measurements-v1'


def ensure_legacy_engine():
    """Import only the authenticated, separately materialized owner-provided source."""
    path = ROOT / 'app'
    require((path / 'uptempo_harmony' / 'synth.py').is_file(),
            'materialize the authenticated source: python baseline/recovered_source/materialize_v2.py')
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


@lru_cache(maxsize=1)
def _implementation_manifest_json():
    # Normalize text line endings: checkout autocrlf must not change method identity.
    roots = ('zaaggenz_inverse', 'zaaggenz_contracts', 'zaaggenz_project',
             'zaaggenz_jobs', 'zaaggenz_dsp', 'zaaggenz_analysis', 'zaaggenz_components',
             'zaaggenz_descriptors', 'zaaggenz_spectral', 'zaaggenz_tuning', 'zaaggenz_qc',
             'app/uptempo_harmony')
    ensure_legacy_engine()
    hashes = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_text(encoding='utf-8').encode('utf-8')).hexdigest()
              for root in roots for p in sorted((ROOT / root).rglob('*.py'))}
    require(all(any(k.startswith(root + '/') for k in hashes) for root in roots), 'missing method source')
    return json.dumps({'domain': 'zaaggenz.inverse-implementation-v1', 'source_files': hashes,
            'numerical_policy': NUMERICAL_POLICY,
            'legacy_normalisation': 'declared source-internal RMS/noise-std/final-peak; factors not exposed by recovered engine',
            'comparison_normalisation': 'none; no alignment, peak matching or fitted gain in objective'}, sort_keys=True)


def implementation_manifest():
    return json.loads(_implementation_manifest_json())


@lru_cache(maxsize=1)
def engine_identity():
    return digest(implementation_manifest())


@lru_cache(maxsize=1)
def render_engine_identity():
    files = implementation_manifest()['source_files']
    selected = {k: v for k, v in files.items() if k.startswith(('zaaggenz_contracts/', 'zaaggenz_dsp/',
        'app/uptempo_harmony/')) or k == 'zaaggenz_inverse/recipes.py'}
    return digest({'domain': 'zaaggenz.inverse-render-engine-v1', 'source_files': selected,
                   'numerical_policy': NUMERICAL_POLICY})


@lru_cache(maxsize=1)
def feature_engine_identity():
    files = implementation_manifest()['source_files']
    selected = {k: v for k, v in files.items() if k.startswith(('zaaggenz_contracts/', 'zaaggenz_analysis/',
        'zaaggenz_components/', 'zaaggenz_descriptors/', 'zaaggenz_spectral/', 'zaaggenz_tuning/', 'zaaggenz_qc/'))
        or k in ('zaaggenz_inverse/recipes.py', 'zaaggenz_inverse/objectives.py')}
    return digest({'domain': 'zaaggenz.inverse-feature-engine-v1', 'source_files': selected,
                   'numerical_policy': NUMERICAL_POLICY})


def environment_manifest():
    try:
        from threadpoolctl import threadpool_info
        backends = [{k: row.get(k) for k in ('internal_api', 'prefix', 'version', 'threading_layer', 'architecture')}
                    for row in threadpool_info()]
        backends.sort(key=lambda row: json.dumps(row, sort_keys=True))
    except ImportError:
        backends = [{'status': 'threadpoolctl-unavailable'}]
    return {'python': platform.python_version(), 'implementation': platform.python_implementation(),
            'numpy': np.__version__, 'scipy': scipy.__version__, 'numeric_backends': backends, 'system': platform.system(),
            'machine': platform.machine(), 'byteorder': sys.byteorder,
            'numerical_policy': NUMERICAL_POLICY, 'numeric_threads': 1}


def _resolve(data, path):
    current = data
    try:
        parts = path.split('/')[1:]
        for part in parts[:-1]:
            current = current[int(part)] if isinstance(current, list) else current[part]
        key = int(parts[-1]) if isinstance(current, list) else parts[-1]
        current[key]  # Verify existing field; never create unregistered recipe intent.
        return current, key
    except (KeyError, IndexError, ValueError, TypeError) as exc:
        raise InverseError('unknown recipe parameter: ' + path) from exc


def parameter_spec(recipe, path):
    """Resolve units/bounds from ZG-002's actual numeric registry, including automation."""
    d = recipe.to_dict()
    parts = path.split('/')[1:]
    _resolve(d, path)
    if len(parts) == 3 and parts[:2] == ['source', 'params']:
        require(parts[2] not in ('sr', 'bpm', 'beats', 'beat_fill'), 'v1 freezes timeline/length parameters')
        spec = legacy_schema('synth')['properties'][parts[2]].copy()
        spec['unit'] = spec['x-unit']
    elif len(parts) == 4 and parts[0] == 'nodes' and parts[2] == 'params':
        spec = node_definition(d['nodes'][int(parts[1])]['type_id'])['parameters'][parts[3]]
    elif len(parts) == 7 and parts[0] == 'nodes' and parts[2] == 'automation' and parts[4] == 'points' and parts[6] == 'value':
        node = d['nodes'][int(parts[1])]
        lane = node['automation'][int(parts[3])]
        spec = node_definition(node['type_id'])['parameters'][lane['parameter']]
        require(spec['x-automatable'], 'parameter does not support automation')
    elif parts == ['output', 'master_gain_db']:
        # Bounds come from the existing RenderRecipe schema, not a parallel contract.
        from zaaggenz_contracts.schema import schema
        spec = schema('RenderRecipe')['$defs']['RenderRecipe']['properties']['output']['properties']['master_gain_db'].copy()
        spec['unit'] = 'dB'
    else:
        raise InverseError('unsupported inverse numeric binding: ' + path)
    require(spec.get('type') in ('number', 'integer') and 'minimum' in spec and 'maximum' in spec,
            'bounded continuous/integer numeric registry entry required (enum axes are not yet supported)')
    require('enum' not in spec, 'enum axes require a later discrete-domain adapter')
    return spec


def validate_base(recipe, expected_frames=None):
    d = recipe.to_dict()
    require(d['render_mode'] == 'synth' and d['source']['params']['beats'] == 1,
            'v1 laboratory is explicitly bounded to a single editable synth recipe')
    require(d['sculpt'] is None, 'move SCULPT into the accepted explicit graph before inverse evaluation')
    projection = d.copy()
    projection['nodes'] = []
    projection['output_node'] = d['source']['id']
    try:
        thaw_legacy(Contract(projection))
    except Exception as exc:
        raise InverseError('unsupported source projection; musical intent may not be silently dropped') from exc
    p = d['source']['params']
    n = int(round(60.0 / p['bpm'] * p['beat_fill'] * p['sr']))
    require(32 <= n <= MAX_FRAMES, 'render frame limit exceeded')
    if expected_frames is not None:
        require(n == expected_frames, 'source/target frame count differs; declare preprocessing explicitly')
    return n


def validate_domain(recipe, domain):
    require(isinstance(domain, ParameterDomain), 'ParameterDomain required')
    validate_base(recipe)
    for axis in domain.axes:
        spec = parameter_spec(recipe, axis.path)
        require(axis.unit == spec['unit'] and axis.numeric_type == spec['type'], 'registry unit/type mismatch: ' + axis.path)
        require(spec['minimum'] <= axis.lower <= axis.upper <= spec['maximum'], 'domain exceeds registered bounds: ' + axis.path)
    return domain


def apply_state(recipe, domain, state):
    domain.validate_state(state)
    validate_domain(recipe, domain)
    d = recipe.to_dict()
    for path, value in state.values:
        obj, key = _resolve(d, path)
        obj[key] = value
    # Reuse the accepted source projection to update linked f0/tuning and seed fields.
    source = freeze_legacy(d['source']['params'], mode=d['render_mode'], arrangement=d['arrangement'],
        reversebass=d['reversebass'], master_gain_db=d['output']['master_gain_db']).to_dict()
    source['nodes'], source['output_node'] = d['nodes'], d['output_node']
    result = Contract(source)
    validate_base(result)
    return result


def state_from_recipe(recipe, domain):
    d = recipe.to_dict()
    return ParameterState(tuple((axis.path, _resolve(d, axis.path)[0][_resolve(d, axis.path)[1]]) for axis in domain.axes))


def frozen_audio(value, dtype='<f4'):
    """Immutable bytes-backed audio; features always observe the PCM that is hashed."""
    a = np.asarray(value)
    require(a.ndim in (1, 2), 'mono/stereo array required')
    if a.ndim == 2:
        require(a.shape[1] in (1, 2), 'mono/stereo array required')
    require(np.issubdtype(a.dtype, np.number) and not np.iscomplexobj(a), 'real numeric audio required')
    if a.ndim == 2 and a.shape[1] == 1:
        a = a.reshape(-1)  # Same mono PCM identity must have the same evaluation shape.
    shape = a.shape
    return np.frombuffer(np.asarray(a, dtype=dtype, order='C').tobytes(), dtype=dtype).reshape(shape)


def audio_identity(value, sr):
    with np.errstate(over='ignore', invalid='ignore'):
        pcm = np.asarray(value, dtype='<f4')
    if np.isfinite(pcm).all():
        return pcm_asset(pcm, sr)
    # Non-finite or f32-overflow output has no valid AudioAssetRef.
    return {'kind': 'InvalidPCM', 'version': '1.0.0', 'raw_f32_sha256': hashlib.sha256(pcm.tobytes()).hexdigest(),
            'finite_fraction': float(np.mean(np.isfinite(pcm))), 'shape': list(pcm.shape)}


@dataclass(frozen=True)
class RenderTrace:
    recipe: Contract
    source: np.ndarray
    pre_master: np.ndarray
    output: np.ndarray

    def __post_init__(self):
        require(isinstance(self.recipe, Contract), 'existing recipe required')
        object.__setattr__(self, 'source', frozen_audio(self.source))
        object.__setattr__(self, 'pre_master', frozen_audio(self.pre_master, '<f8'))
        object.__setattr__(self, 'output', frozen_audio(self.output))

    @property
    def sample_rate(self):
        return self.recipe.to_dict()['time_map']['sample_rate_hz']

    @property
    def gain(self):
        return 10.0 ** (self.recipe.to_dict()['output']['master_gain_db'] / 20.0)

    @property
    def record(self):
        d = self.recipe.to_dict()
        signals = {'source_post_internal_normalisation': self.source, 'pre_master': self.pre_master,
                   'post_gain_pre_clip': self.pre_master * self.gain, 'output': self.output}
        return {'kind': 'InverseRenderTrace', 'version': '1.0.0', 'recipe_sha256': self.recipe.sha256,
                'signals': {k: {'asset': audio_identity(v, self.sample_rate),
                                'levels': diagnose(v, self.sample_rate) if len(v) and np.isfinite(v).all() and float(np.max(np.abs(v))) <= 1e100 else None}
                            for k, v in signals.items()},
                'pre_master_f64_sha256': hashlib.sha256(self.pre_master.tobytes()).hexdigest(),
                'output_policy': d['output'], 'master_gain_linear': self.gain,
                'graph': d['nodes'], 'graph_order': [n['id'] for n in d['nodes']],
                'source_internal_gain_factors': None,
                'source_internal_normalisation': 'declared legacy RMS/noise-std/final-peak; not observable as separate gain taps',
                'objective_gain_matching': 'none'}

    @property
    def sha256(self):
        return digest(self.record)


def render_trace(recipe):
    ensure_legacy_engine()
    validate_base(recipe)
    rendered = render_recipe(recipe, capture_taps=True)
    return RenderTrace(recipe, rendered.taps['legacy-source-post-internal-nonlinear'],
                       rendered.taps['pre-master'], rendered.audio)
