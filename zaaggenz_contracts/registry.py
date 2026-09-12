"""Reviewed data registry, not code discovery or a plugin execution mechanism."""
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


def node_catalogue():
    return {
        'core.identity.v1': {
            'licence': 'LicenseRef-Zaaggenz-Owner-Provided',
            'provenance': 'ZG-002 contract definition; executor belongs to ZG-016',
            'availability': 'contract_only', 'parameters': {}, 'state': 'stateless',
            'bypass': 'identity', 'latency': 0, 'lookahead': 0, 'inputs': (1, 1),
        },
        'core.gain.v1': {
            'licence': 'LicenseRef-Zaaggenz-Owner-Provided',
            'provenance': 'ZG-002 linear-gain contract; not a limiter/master stage',
            'availability': 'contract_only',
            'parameters': {'gain_db': {'type': 'number', 'minimum': -120, 'maximum': 24, 'unit': 'dB', 'default': 0}},
            'state': 'stateless', 'bypass': 'identity', 'latency': 0, 'lookahead': 0, 'inputs': (1, 1),
        },
    }


def node_definition(type_id):
    found = node_catalogue().get(type_id)
    if found is None:
        raise ContractError('unregistered DSP type/version: ' + str(type_id))
    return deepcopy(found)
