"""Structural schema for the explicit RenderRecipe 1.1 opt-in extension.

As with DSPNodeSpec, semantic validation is mandatory in addition to JSON
Schema: IDs/references, crossover/rate relationships, state hashes, resource
counts, provenance and unsupported execution capabilities are not mere shapes.
"""
from copy import deepcopy
from .schema import obj, string, num, integer, array, enum, const, nullable, ref, ID, HASH, RATE, CHANNELS
from .rack import (BANDS, RACK_VERSION, FILTER_METHOD, MAX_INSERTS_PER_BAND,
                   MAX_PLUGIN_STATE_BYTES, PLACEMENT, POLICY, GAIN, COMPRESSION,
                   BITCRUSH, RETUNE, CHORDNESS, COEFFICIENTS)


def rack_schema():
    label = string(128)
    voice = obj(degree=integer(-4096, 4096),
                partial_ratios=array({'type': 'number', 'exclusiveMinimum': 0, 'maximum': 1_000_000}, 1, 128),
                label=string(64))
    segment = obj(start_sample=integer(1, 192000 * 3600), voices=array(voice, 1, 32), label=string(64))
    retune = obj(kind=const('SpectralRetuneRequest'), version=const(RACK_VERSION),
                 tuning_spec=ref('TuningSpec'), voices=array(voice, 1, 32),
                 segments=array(segment, 0, 64), **deepcopy(RETUNE))
    template = obj(id=ID, teeth_hz=array({'type': 'number', 'exclusiveMinimum': 0, 'maximum': 96000}, 1, 128),
                   tooth_capacity=integer(1, 16), label=label,
                   source={'type': 'object'})
    chordness = obj(kind=const('ChordnessRequest'), version=const(RACK_VERSION),
                    templates=array(template, 1, 32), selected_template_ids=array(ID, 0, 32, unique=True),
                    coefficients=obj(**deepcopy(COEFFICIENTS)), **deepcopy(CHORDNESS))
    state = obj(encoding=const('base64'),
                data=string(4 * ((MAX_PLUGIN_STATE_BYTES + 2) // 3),
                            pattern=r'^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$'),
                sha256=HASH)
    external = obj(format=const('VST3'), platform=const('windows-x64'),
                   class_id=string(32, pattern=r'^[0-9A-F]{32}$'), binary_sha256=HASH,
                   component_state=state, controller_state=state,
                   execution_contract=const('preservation-only.v1'))
    parameter_shapes = {
        'zg.gain': obj(**deepcopy(GAIN)),
        'zg.compression': nullable(obj(**deepcopy(COMPRESSION))),
        'zg.bitcrush': nullable(obj(**deepcopy(BITCRUSH))),
        'zg.spectral': {'anyOf': [retune, chordness, {'type': 'null'}]},
        'external.vst3': external,
    }
    inserts = {'oneOf': [obj(id=ID, type_id=const(type_id), version=const(RACK_VERSION),
                            bypass={'type': 'boolean'}, wet=num(0, 1), params=params,
                            automation=array({}, 0, 0))
                         for type_id, params in parameter_shapes.items()]}
    band = obj(id=ID, band=enum(*BANDS), bypass={'type': 'boolean'}, wet=num(0, 1),
               confine_delta={'type': 'boolean'}, inserts=array(inserts, 0, MAX_INSERTS_PER_BAND))
    return obj(kind=const('MultibandRack'), version=const(RACK_VERSION), id=ID,
               source_binding=obj(source_sha256=HASH, origin_recipe_sha256=HASH),
               placement=const(deepcopy(PLACEMENT)), sample_rate_hz=RATE, channels=CHANNELS,
               crossovers=obj(method=const(FILTER_METHOD), frequencies_hz=array(num(20, 96000), 3, 3)),
               bypass={'type': 'boolean'}, wet=num(0, 1), bands=array(band, 4, 4),
               policy=const(deepcopy(POLICY)),
               display={'type': 'object', 'maxProperties': 69, 'propertyNames': ID,
                        'additionalProperties': label})
