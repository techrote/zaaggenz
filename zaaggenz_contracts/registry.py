"""Reviewed data registry. IDs map to bounded implementations; recipes never name modules/code."""
from __future__ import annotations
from copy import deepcopy
from .model import ContractError


def legacy_catalogue():
    from .legacy_spec import FIELDS, SECTION, SOURCE_CLASSES
    result = {}
    for family, rows in FIELDS.items():
        props = {}
        for name, type_, default, lo, hi, unit in rows:
            spec = {'type': type_, 'default': default, 'x-unit': unit}
            if lo is not None:
                spec.update(minimum=lo, maximum=hi)
            props[name] = spec
        if family == 'arrangement':
            props['sections'] = deepcopy(SECTION)
        result[family] = {'version': '1.2.1-earth-ui', 'source_class': SOURCE_CLASSES[family],
            'licence': 'LicenseRef-Owner-Provided-Unspecified',
            'schema': {'type': 'object', 'properties': props, 'required': list(props), 'additionalProperties': False},
            'defaults': {k: deepcopy(s['default']) for k, s in props.items()}}
    return result


def legacy_schema(family):
    entry = legacy_catalogue().get(family)
    if entry is None:
        raise ContractError('unsupported legacy parameter family')
    return deepcopy(entry['schema'])


def _p(type_, default, lo=None, hi=None, unit='unitless', automatable=False):
    d={'type':type_,'default':default,'unit':unit,'x-automatable':bool(automatable)}
    if lo is not None:d.update(minimum=lo,maximum=hi)
    return d


def _oversample(default=2):
    return {'type':'integer','default':default,'enum':[1,2,4],'unit':'ratio','x-automatable':False}


def _legacy_sculpt_parameters():
    out={}
    for name,spec in legacy_catalogue()['sculpt']['schema']['properties'].items():
        x=deepcopy(spec);x['unit']=x.pop('x-unit','unitless');x['x-automatable']=False;out[name]=x
    return out


def node_catalogue():
    return {
        'core.identity.v1': {
            'licence':'LicenseRef-Zaaggenz-Owner-Provided','provenance':'ZG-002 contract; ZG-016 executor',
            'availability':'executable','parameters':{},'state':'stateless','bypass':'identity','latency':0,'lookahead':0,'inputs':(1,1),
        },
        'core.gain.v1': {
            'licence':'LicenseRef-Zaaggenz-Owner-Provided','provenance':'ZG-002 linear gain; ZG-016 executor',
            'availability':'executable','parameters':{'gain_db':_p('number',0,-120,24,'dB',True)},
            'state':'stateless','bypass':'identity','latency':0,'lookahead':0,'inputs':(1,1),
        },
        'core.tanh.v1': {
            'licence':'LicenseRef-Zaaggenz-Owner-Provided','provenance':'ZG-016 bounded waveshaper',
            'availability':'executable','parameters':{'drive_db':_p('number',0,-24,48,'dB',True),'mix':_p('number',1,0,1,'ratio',True)},
            'state':'stateless','bypass':'identity','latency':0,'lookahead':0,'inputs':(1,1),
        },
        'core.hard_clip.v1': {
            'licence':'LicenseRef-Zaaggenz-Owner-Provided','provenance':'ZG-016 bounded hard-clip node',
            'availability':'executable','parameters':{'threshold':_p('number',1,.001,4,'linear_amplitude',True),'mix':_p('number',1,0,1,'ratio',True)},
            'state':'stateless','bypass':'identity','latency':0,'lookahead':0,'inputs':(1,1),
        },
        'core.tanh_aa.v1': {
            'licence':'LicenseRef-Zaaggenz-Owner-Provided','provenance':'ZG-019 opt-in Kaiser/polyphase antialiased tanh',
            'availability':'executable','parameters':{'drive_db':_p('number',0,-24,48,'dB'), 'mix':_p('number',1,0,1,'ratio'), 'oversample':_oversample(2)},
            'state':'stateless','bypass':'identity','latency':0,'lookahead':0,'inputs':(1,1),
        },
        'core.hard_clip_aa.v1': {
            'licence':'LicenseRef-Zaaggenz-Owner-Provided','provenance':'ZG-019 opt-in Kaiser/polyphase antialiased hard clip',
            'availability':'executable','parameters':{'threshold':_p('number',1,.001,4,'linear_amplitude'), 'mix':_p('number',1,0,1,'ratio'), 'oversample':_oversample(2)},
            'state':'stateless','bypass':'identity','latency':0,'lookahead':0,'inputs':(1,1),
        },
        'core.multiband_gain.v1': {
            'licence':'LicenseRef-Zaaggenz-Owner-Provided','provenance':'ZG-016 zero-phase offline effect-delta router',
            'availability':'executable','parameters':{
                'low_xover_hz':_p('number',105,20,20000,'Hz'), 'mid_xover_hz':_p('number',520,20,20000,'Hz'),
                'high_xover_hz':_p('number',3600,20,40000,'Hz'), 'sub_gain_db':_p('number',0,-36,24,'dB'),
                'lowmid_gain_db':_p('number',0,-36,24,'dB'),'highmid_gain_db':_p('number',0,-36,24,'dB'),'air_gain_db':_p('number',0,-36,24,'dB'),
                'confine_delta':_p('boolean',True,unit='boolean')},
            'state':'stateless','bypass':'identity','latency':0,'lookahead':0,'inputs':(1,1),
        },
        'legacy.sculpt.v1': {
            'licence':'LicenseRef-Owner-Provided-Unspecified','provenance':'authenticated v1.2.1 SpectralSculptParams/process_spectral_sculpt adapter',
            'availability':'executable','parameters':_legacy_sculpt_parameters(),
            'state':'stateless','bypass':'identity','latency':0,'lookahead':0,'inputs':(1,1),
        },
    }


def node_definition(type_id):
    found = node_catalogue().get(type_id)
    if found is None:
        raise ContractError('unregistered DSP type/version: ' + str(type_id))
    return deepcopy(found)


def automation_parameter_definition(type_id, parameter):
    """Return the registry entry for an explicitly automatable numeric parameter."""
    definition = node_definition(type_id)
    spec = definition['parameters'].get(parameter)
    if spec is None:
        raise ContractError(f'{type_id}.{parameter} is not a registered DSP parameter')
    if spec.get('type') != 'number' or spec.get('x-automatable') is not True:
        raise ContractError(f'{type_id}.{parameter} is not automatable')
    return spec
