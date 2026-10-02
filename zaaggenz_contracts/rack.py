"""MBR-001: saved multiband intent, not a DSP engine or a plug-in loader.

Validation is deliberately independent of NumPy, filter allocation and native
code. The old four-stage processor is reached only through rack_adapter.py.
Snapshot hashes retain authoring labels; sonic hashes exclude only explicitly
cosmetic fields. Neither hash asserts PCM equivalence of different settings.
"""
from __future__ import annotations

import base64
import binascii
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import math
import re

from .model import ContractError, check_json, digest, loads
from .multiband import validate_multiband_crossovers

RACK_VERSION = '1.0.0'
RECIPE_VERSION = '1.1.0'
BANDS = ('sub', 'lowmid', 'highmid', 'air')
STAGES = ('spectral', 'gain', 'compression', 'bitcrush')
BUILTINS = tuple('zg.' + stage for stage in STAGES)
EXTERNAL_TYPE = 'external.vst3'
FILTER_METHOD = 'zg.butter4_sosfiltfilt_effect_delta.v1'
MAX_INSERTS_PER_BAND = 16
MAX_RACK_BYTES = 48_000
MAX_PLUGIN_STATE_BYTES = 8_192  # each of component and controller state
MAX_RETUNE_SEGMENTS = 64
MAX_RETUNE_CANDIDATE_TEETH = 32_768
ID_PATTERN = r'[a-z][a-z0-9_.-]{0,63}'
PLACEMENT = {
    'bus': 'SYNTHLINE',
    'after': 'complete-source-derived-note-sum',
    'before': 'existing-sculpt-or-dsp-graph-then-final-master',
    'exciter_policy': 'separate-unprocessed',
}
POLICY = {
    'channels': 'linked-preserve-shape',
    'state': 'reset-render',
    'latency': 'offline-zero-aligned',
    'declared_latency_samples': 0,
    'tail': 'input-length',
    'normalisation': 'none',
    'master_gain_db': 0,
}


class RackError(ContractError):
    """Invalid saved intent; bypass never exempts a field from validation."""


class RackCompatibilityError(RackError):
    """A valid saved rack requires a consumer that is not available here."""


def _require(condition, message):
    if not condition:
        raise RackError(message)


def _exact(value, fields, path):
    _require(type(value) is dict and set(value) == set(fields),
             path + ': missing or unknown fields')


def _id(value, path):
    _require(type(value) is str and re.fullmatch(ID_PATTERN, value) is not None,
             path + ': bounded stable identifier required')


def _sha(value, path):
    _require(type(value) is str and re.fullmatch(r'[0-9a-f]{64}', value) is not None,
             path + ': lowercase SHA-256 required')


def _number(value, low, high, path, *, integer=False, positive=False):
    types = (int,) if integer else (int, float)
    _require(type(value) in types and math.isfinite(value)
             and low <= value <= high and (not positive or value > 0),
             f'{path}: expected {low}..{high}' + (' integer' if integer else ''))


def _bool(value, path):
    _require(type(value) is bool, path + ': boolean required')


def _text(value, path, maximum=128):
    _require(type(value) is str and len(value) <= maximum
             and not any(ord(c) < 32 for c in value), path + ': invalid display label')


def _rows(value, low, high, path):
    _require(type(value) is list and low <= len(value) <= high,
             f'{path}: expected {low}..{high} entries')


def _parameter(low, high, default, unit, *, integer=False, positive=False):
    result = {'type': 'integer' if integer else 'number', 'minimum': low,
              'maximum': high, 'default': default, 'unit': unit}
    if positive:
        result['exclusiveMinimum'] = 0
    return result


# These are authoring contracts for the existing implementations. Adapter tests
# compare their defaults and complete payloads with the original typed specs.
GAIN = {'gain_db': _parameter(-36, 24, 0., 'dB')}
COMPRESSION = {
    'threshold_db': _parameter(-120, 24, -12., 'dBFS'),
    'ratio': _parameter(1, 100, 4., 'ratio'),
    'attack_ms': _parameter(.01, 5000, 8., 'ms'),
    'release_ms': _parameter(.01, 10000, 90., 'ms'),
    'knee_db': _parameter(0, 48, 0., 'dB'),
    'makeup_db': _parameter(-36, 36, 0., 'dB'),
    'wet': _parameter(0, 1, 1., 'ratio'),
    'detector': {'const': 'linked-peak', 'default': 'linked-peak', 'unit': 'policy'},
}
BITCRUSH = {
    'bit_depth': _parameter(2, 24, 8, 'bits', integer=True),
    'hold_samples': _parameter(1, 1024, 1, 'samples', integer=True),
    'full_scale': _parameter(0, 32, 1., 'linear amplitude', positive=True),
    'wet': _parameter(0, 1, 1., 'ratio'),
    'dither': {'const': 'none', 'default': 'none', 'unit': 'policy'},
}
RETUNE = {
    'amount': _parameter(0, 1, 1., 'ratio'),
    'min_confidence': _parameter(0, 1, .55, 'ratio'),
    'min_hz': _parameter(0, 96000, 30., 'Hz', positive=True),
    'max_hz': _parameter(0, 96000, 6000., 'Hz', positive=True),
    'max_displacement_cents': _parameter(0, 1_000_000, 350., 'cents', positive=True),
    'max_correction_slew_cents_per_second': _parameter(0, 1_000_000, 1800., 'cents/s', positive=True),
    'assignment_hysteresis_cents': _parameter(0, 1_000_000, 35., 'cents'),
    'preserve_ambiguous': {'type': 'boolean', 'default': True, 'unit': 'policy'},
}
CHORDNESS = {
    'mode': {'enum': ['off', 'reweight', 'retune', 'hybrid'], 'default': 'off', 'unit': 'mode'},
    'selection_mode': {'enum': ['manual', 'descriptor'], 'default': 'manual', 'unit': 'mode'},
    'max_selected_templates': _parameter(1, 32, 1, 'templates', integer=True),
    'retune_amount': _parameter(0, 1, 1., 'ratio'),
    'reweight_amount': _parameter(0, 1, 1., 'ratio'),
    'min_confidence': _parameter(0, 1, .55, 'ratio'),
    'tolerance_cents': _parameter(1, 600, 35., 'cents'),
    'max_assignment_cents': _parameter(1, 4800, 1200., 'cents'),
    'max_displacement_cents': _parameter(1, 2400, 350., 'cents'),
    'max_correction_slew_cents_per_second': _parameter(1, 20000, 1800., 'cents/s'),
    'max_gain_db': _parameter(0, 36, 6., 'dB'),
    'max_gain_slew_db_per_second': _parameter(.01, 240, 24., 'dB/s'),
    'preserve_ambiguous': {'type': 'boolean', 'default': True, 'unit': 'policy'},
}
COEFFICIENTS = {
    name: _parameter(0, 100, default, 'weight') for name, default in
    [('target_fit', 1.), ('roughness', .25), ('density_penalty', .02),
     ('reassignment_cents', .10), ('gain_motion_db', .05)]
}


def processor_definition(type_id):
    """Return defensive metadata, including truthful execution capability."""
    if type_id == EXTERNAL_TYPE:
        return {'type_id': type_id, 'version': RACK_VERSION, 'executable': False,
                'capability': 'preservation-only; no native loader', 'automation': []}
    tables = {'zg.gain': GAIN, 'zg.compression': COMPRESSION,
              'zg.bitcrush': BITCRUSH, 'zg.spectral': {'retune': RETUNE, 'chordness': CHORDNESS}}
    if type_id not in tables:
        raise RackError('unknown processor type: ' + str(type_id))
    return {'type_id': type_id, 'version': RACK_VERSION,
            'capability': 'existing-band-selective-adapter', 'automation': [],
            'parameters': deepcopy(tables[type_id])}


def _parameters(data, definitions, path):
    _exact(data, definitions, path)
    for name, definition in definitions.items():
        value = data[name]
        at = path + '.' + name
        if 'const' in definition:
            _require(type(value) is type(definition['const']) and value == definition['const'],
                     at + ': unsupported policy')
        elif 'enum' in definition:
            _require(type(value) is str and value in definition['enum'], at + ': unsupported value')
        elif definition['type'] == 'boolean':
            _bool(value, at)
        else:
            _number(value, definition['minimum'], definition['maximum'], at,
                    integer=definition['type'] == 'integer', positive='exclusiveMinimum' in definition)


def _voice(value, path):
    _exact(value, ('degree', 'partial_ratios', 'label'), path)
    _number(value['degree'], -4096, 4096, path + '.degree', integer=True)
    _rows(value['partial_ratios'], 1, 128, path + '.partial_ratios')
    last = 0.
    for ratio in value['partial_ratios']:
        _number(ratio, 0, 1_000_000, path + '.partial_ratio', positive=True)
        _require(ratio > last, path + ': partial ratios must strictly increase')
        last = ratio
    _text(value['label'], path + '.label', 64)
    return len(value['partial_ratios'])


def _retune(data, sample_rate_hz):
    fields = {'kind', 'version', 'tuning_spec', 'voices', 'segments', *RETUNE}
    _exact(data, fields, 'spectral.retune')
    _require(data['kind'] == 'SpectralRetuneRequest' and data['version'] == RACK_VERSION,
             'unknown spectral request kind/version')
    _parameters({key: data[key] for key in RETUNE}, RETUNE, 'spectral.retune')
    _require(data['min_hz'] < data['max_hz'] <= sample_rate_hz / 2,
             'spectral min_hz/max_hz must be ordered and within the saved sample rate')
    _require(data['assignment_hysteresis_cents'] <= data['max_displacement_cents'],
             'spectral hysteresis exceeds displacement')
    _rows(data['voices'], 1, 32, 'spectral.voices')
    count = sum(_voice(voice, 'spectral.voice') for voice in data['voices'])
    _rows(data['segments'], 0, MAX_RETUNE_SEGMENTS, 'spectral.segments')
    last = 0
    for segment in data['segments']:
        _exact(segment, ('start_sample', 'voices', 'label'), 'spectral.segment')
        _number(segment['start_sample'], 1, 192000 * 3600, 'segment.start_sample', integer=True)
        _require(segment['start_sample'] > last, 'segment starts must strictly increase')
        last = segment['start_sample']
        _text(segment['label'], 'segment.label', 64)
        _rows(segment['voices'], 1, 32, 'segment.voices')
        count += sum(_voice(voice, 'segment.voice') for voice in segment['voices'])
    _require(count <= MAX_RETUNE_CANDIDATE_TEETH, 'spectral target lattice exceeds candidate bound')
    # Structural/resource admission precedes tuning validation, just as in the
    # original request. This import is pure contract code, never an audio engine.
    from .validation import validate
    validate(data['tuning_spec'], 'TuningSpec')


def _chordness(data, sample_rate_hz):
    _exact(data, {'kind', 'version', 'templates', 'selected_template_ids', 'coefficients', *CHORDNESS},
           'spectral.chordness')
    _require(data['kind'] == 'ChordnessRequest' and data['version'] == RACK_VERSION,
             'unknown chordness request kind/version')
    _parameters({key: data[key] for key in CHORDNESS}, CHORDNESS, 'spectral.chordness')
    _parameters(data['coefficients'], COEFFICIENTS, 'chordness.coefficients')
    _require(data['max_displacement_cents'] <= data['max_assignment_cents'],
             'chordness displacement exceeds assignment bound')
    _rows(data['templates'], 1, 32, 'chordness.templates')
    ids = set()
    for template in data['templates']:
        _exact(template, ('id', 'teeth_hz', 'tooth_capacity', 'label', 'source'), 'chordness.template')
        _id(template['id'], 'template.id')
        _require(template['id'] not in ids, 'duplicate comb template id')
        ids.add(template['id'])
        _text(template['label'], 'template.label')
        _number(template['tooth_capacity'], 1, 16, 'template.tooth_capacity', integer=True)
        _rows(template['teeth_hz'], 1, 128, 'template.teeth_hz')
        last = 0.
        for tooth in template['teeth_hz']:
            _number(tooth, 0, sample_rate_hz / 2, 'template.teeth_hz', positive=True)
            _require(tooth > last, 'comb teeth must strictly increase')
            last = tooth
        _require(type(template['source']) is dict, 'template.source must be a JSON object')
        _require(len(_json(template['source']).encode('utf-8')) <= 8192, 'template.source exceeds byte bound')
    _require(data['max_selected_templates'] <= len(ids), 'max_selected_templates exceeds inventory')
    selected = data['selected_template_ids']
    _rows(selected, 0, data['max_selected_templates'], 'selected_template_ids')
    _require(all(type(item) is str for item in selected), 'selected template identifiers must be strings')
    _require(len(selected) == len(set(selected)) and set(selected) <= ids, 'invalid selected template ids')
    if data['selection_mode'] == 'manual' and data['mode'] != 'off':
        _require(bool(selected), 'active manual Chordness requires a selection')


def state_blob(payload=b''):
    """Serialize bounded opaque state; this function does not interpret it."""
    _require(type(payload) is bytes and len(payload) <= MAX_PLUGIN_STATE_BYTES,
             'plug-in state exceeds byte bound')
    return {'encoding': 'base64', 'data': base64.b64encode(payload).decode('ascii'),
            'sha256': hashlib.sha256(payload).hexdigest()}


def _state(value, path):
    _exact(value, ('encoding', 'data', 'sha256'), path)
    _require(value['encoding'] == 'base64', path + ': unsupported encoding')
    _sha(value['sha256'], path + '.sha256')
    text = value['data']
    _require(type(text) is str and len(text) <= 4 * ((MAX_PLUGIN_STATE_BYTES + 2) // 3),
             path + ': encoded state exceeds bound')
    try:
        payload = base64.b64decode(text, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise RackError(path + ': invalid base64 state') from exc
    _require(len(payload) <= MAX_PLUGIN_STATE_BYTES, path + ': decoded state exceeds bound')
    _require(base64.b64encode(payload).decode('ascii') == text, path + ': noncanonical base64 state')
    _require(hashlib.sha256(payload).hexdigest() == value['sha256'], path + ': state hash mismatch')


def _external(data):
    _exact(data, ('format', 'platform', 'class_id', 'binary_sha256', 'component_state',
                  'controller_state', 'execution_contract'), 'external descriptor')
    _require(data['format'] == 'VST3' and data['platform'] == 'windows-x64',
             'unsupported external format/platform')
    _require(type(data['class_id']) is str and re.fullmatch(r'[0-9A-F]{32}', data['class_id']) is not None,
             'VST3 class_id must be 32 uppercase hexadecimal digits')
    _sha(data['binary_sha256'], 'external.binary_sha256')
    _require(data['execution_contract'] == 'preservation-only.v1',
             'this contract does not authorize native execution')
    _state(data['component_state'], 'external.component_state')
    _state(data['controller_state'], 'external.controller_state')


def validate_insert(data, sample_rate_hz):
    """Validate all latent settings, even if the insert or containing rack is bypassed."""
    check_json(data)
    _number(sample_rate_hz, 8000, 192000, 'sample_rate_hz', integer=True)
    _exact(data, ('id', 'type_id', 'version', 'bypass', 'wet', 'params', 'automation'), 'insert')
    _id(data['id'], 'insert.id')
    _require(type(data['type_id']) is str and data['type_id'] in (*BUILTINS, EXTERNAL_TYPE),
             'unknown insert processor type')
    _require(data['version'] == RACK_VERSION, 'unknown insert processor version')
    _bool(data['bypass'], 'insert.bypass')
    _number(data['wet'], 0, 1, 'insert.wet')
    _require(type(data['automation']) is list and not data['automation'],
             'rack insert automation is unsupported; no lanes are ignored or made static')
    params = data['params']
    type_id = data['type_id']
    if type_id == EXTERNAL_TYPE:
        _external(params)
    elif type_id == 'zg.gain':
        _parameters(params, GAIN, 'gain')
    elif params is not None:
        if type_id == 'zg.compression':
            _parameters(params, COMPRESSION, 'compression')
        elif type_id == 'zg.bitcrush':
            _parameters(params, BITCRUSH, 'bitcrush')
        else:
            _require(type(params) is dict, 'spectral request must be an object or null')
            if params.get('kind') == 'SpectralRetuneRequest':
                _retune(params, sample_rate_hz)
            elif params.get('kind') == 'ChordnessRequest':
                _chordness(params, sample_rate_hz)
            else:
                raise RackError('unknown spectral request type')


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


def _validate(data):
    check_json(data)
    _require(len(_json(data).encode('utf-8')) <= MAX_RACK_BYTES, 'rack exceeds serialized byte bound')
    _exact(data, ('kind', 'version', 'id', 'source_binding', 'placement', 'sample_rate_hz', 'channels',
                  'crossovers', 'bypass', 'wet', 'bands', 'policy', 'display'), 'rack')
    _require(data['kind'] == 'MultibandRack' and data['version'] == RACK_VERSION,
             'unsupported rack kind/version; explicit migration required')
    _id(data['id'], 'rack.id')
    _exact(data['source_binding'], ('source_sha256', 'origin_recipe_sha256'), 'source_binding')
    for key, value in data['source_binding'].items():
        _sha(value, 'source_binding.' + key)
    _require(data['placement'] == PLACEMENT, 'unsupported rack audio-bus placement')
    # Equality alone would accept 0.0/False for fixed integer policy fields.
    _exact(data['policy'], POLICY, 'rack.policy')
    _require(all(type(data['policy'][k]) is type(v) and data['policy'][k] == v for k, v in POLICY.items()),
             'unsupported rack channel/state/latency/tail/output policy')
    _number(data['sample_rate_hz'], 8000, 192000, 'sample_rate_hz', integer=True)
    _number(data['channels'], 1, 2, 'channels', integer=True)
    _exact(data['crossovers'], ('method', 'frequencies_hz'), 'crossovers')
    _require(data['crossovers']['method'] == FILTER_METHOD, 'unknown crossover method/version')
    frequencies = data['crossovers']['frequencies_hz']
    _rows(frequencies, 3, 3, 'crossovers.frequencies_hz')
    for value in frequencies:
        _number(value, 20, 96000, 'crossovers.frequencies_hz')
    validate_multiband_crossovers(frequencies, data['sample_rate_hz'])
    _bool(data['bypass'], 'rack.bypass')
    _number(data['wet'], 0, 1, 'rack.wet')
    _rows(data['bands'], 4, 4, 'rack.bands')
    ids = {data['id']}
    for index, band in enumerate(data['bands']):
        _exact(band, ('id', 'band', 'bypass', 'wet', 'confine_delta', 'inserts'), 'band')
        _id(band['id'], 'band.id')
        _require(band['id'] not in ids, 'duplicate rack/band/insert id')
        ids.add(band['id'])
        _require(band['band'] == BANDS[index], 'four spectral bands must retain their declared order')
        _bool(band['bypass'], 'band.bypass')
        _bool(band['confine_delta'], 'band.confine_delta')
        _number(band['wet'], 0, 1, 'band.wet')
        _rows(band['inserts'], 0, MAX_INSERTS_PER_BAND, 'band.inserts')
        builtins = set()
        for insert in band['inserts']:
            validate_insert(insert, data['sample_rate_hz'])
            _require(insert['id'] not in ids, 'duplicate rack/band/insert id')
            ids.add(insert['id'])
            if insert['type_id'] in BUILTINS:
                _require(insert['type_id'] not in builtins, 'duplicate built-in stage in a band')
                builtins.add(insert['type_id'])
    _require(type(data['display']) is dict and len(data['display']) <= len(ids), 'invalid display label map')
    for key, label in data['display'].items():
        _require(key in ids, 'display label refers to a missing instance')
        _text(label, 'display.' + key)


@dataclass(frozen=True, init=False)
class RackRecipe:
    """Defensive saved snapshot. No mutable object supplied by a caller is retained."""
    _json: str

    def __init__(self, data):
        _validate(data)
        object.__setattr__(self, '_json', _json(data))

    @classmethod
    def from_json(cls, text):
        _require(isinstance(text, (str, bytes)), 'rack JSON text required')
        _require(len(text) <= MAX_RACK_BYTES, 'rack JSON exceeds byte bound')
        return cls(loads(text))

    def to_dict(self):
        return loads(self._json)

    def to_json(self):
        return self._json

    @property
    def sha256(self):
        return digest(self.to_dict())

    def sonic_state(self):
        data = self.to_dict()
        del data['display']
        for band in data['bands']:
            for insert in band['inserts']:
                params = insert['params']
                if insert['type_id'] != 'zg.spectral' or params is None:
                    continue
                if params['kind'] == 'SpectralRetuneRequest':
                    for voice in params['voices']:
                        del voice['label']
                    for segment in params['segments']:
                        del segment['label']
                        for voice in segment['voices']:
                            del voice['label']
                else:
                    for template in params['templates']:
                        del template['label']
        return data

    @property
    def sonic_sha256(self):
        return digest({'domain': 'zaaggenz.multiband-rack-sonic-v1', 'rack': self.sonic_state()})

    @property
    def has_external(self):
        return any(i['type_id'] == EXTERNAL_TYPE for b in self.to_dict()['bands'] for i in b['inserts'])

    def require_source(self, recipe):
        data = recipe.to_dict() if hasattr(recipe, 'to_dict') else recipe
        own = self.to_dict()
        _require(own['source_binding']['source_sha256'] == digest(data['source']), 'rack source binding mismatch')
        _require(own['sample_rate_hz'] == data['time_map']['sample_rate_hz'], 'rack/recipe sample-rate mismatch')
        _require(own['channels'] == data['channels'], 'rack/recipe channel-count mismatch')

    def move_insert(self, band_id, insert_id, new_index):
        """Reorder the same instance; never replace an ID or reset its parameters."""
        data = self.to_dict()
        band = next((b for b in data['bands'] if b['id'] == band_id), None)
        _require(band is not None, 'unknown band instance')
        _number(new_index, 0, len(band['inserts']) - 1, 'new_index', integer=True)
        old = next((j for j, i in enumerate(band['inserts']) if i['id'] == insert_id), None)
        _require(old is not None, 'unknown insert instance in band')
        band['inserts'].insert(new_index, band['inserts'].pop(old))
        return RackRecipe(data)


def empty_rack(recipe, *, rack_id='rack'):
    """Create opt-in authoring data; this does not change the source recipe."""
    from .model import Contract
    source = recipe if isinstance(recipe, Contract) else Contract(recipe)
    base = without_rack(source)
    data = base.to_dict()
    rack = {
        'kind': 'MultibandRack', 'version': RACK_VERSION, 'id': rack_id,
        'source_binding': {'source_sha256': digest(data['source']), 'origin_recipe_sha256': base.sha256},
        'placement': deepcopy(PLACEMENT), 'sample_rate_hz': data['time_map']['sample_rate_hz'],
        'channels': data['channels'],
        'crossovers': {'method': FILTER_METHOD, 'frequencies_hz': [105., 520., 3600.]},
        'bypass': False, 'wet': 1., 'policy': deepcopy(POLICY), 'display': {},
        'bands': [{'id': 'band.' + name, 'band': name, 'bypass': False, 'wet': 1.,
                   'confine_delta': True, 'inserts': []} for name in BANDS],
    }
    return RackRecipe(rack)


def with_rack(recipe, rack):
    """Explicit v1 -> v1.1 opt-in. All non-rack fields remain unchanged."""
    from .model import Contract
    source = recipe if isinstance(recipe, Contract) else Contract(recipe)
    _require(source.to_dict()['kind'] == 'RenderRecipe', 'RenderRecipe required')
    saved = rack if isinstance(rack, RackRecipe) else RackRecipe(rack)
    saved.require_source(source)
    data = source.to_dict()
    data['version'] = RECIPE_VERSION
    data['rack'] = saved.to_dict()
    return Contract(data)


def without_rack(recipe):
    """Reset processing only, not source, phrase, SCULPT, graph or output policy."""
    from .model import Contract
    source = recipe if isinstance(recipe, Contract) else Contract(recipe)
    data = source.to_dict()
    _require(data['kind'] == 'RenderRecipe', 'RenderRecipe required')
    if 'rack' not in data:
        return source
    del data['rack']
    data['version'] = '1.0.0'
    return Contract(data)


def sonic_recipe_sha256(recipe):
    """Keep the exact historical hash for a recipe without a rack."""
    from .model import Contract
    value = recipe if isinstance(recipe, Contract) else Contract(recipe)
    data = value.to_dict()
    if data['kind'] != 'RenderRecipe' or 'rack' not in data:
        return value.sha256
    data['rack'] = RackRecipe(data['rack']).sonic_state()
    return digest({'domain': 'zaaggenz.render-recipe-sonic-v1', 'recipe': data})


def require_rack_consumer(recipe, *, consumer):
    """Fail closed while a legacy consumer has no MBR-002 execution adapter."""
    data = recipe.to_dict() if hasattr(recipe, 'to_dict') else recipe
    if 'rack' in data:
        # The full saved contract is validated before testing bypass, too.
        saved = RackRecipe(data['rack'])
        saved.require_source(data)
        raise RackCompatibilityError(consumer + ': saved multiband rack requires MBR-002 execution support')
