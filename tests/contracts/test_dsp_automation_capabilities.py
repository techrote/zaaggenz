from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np

from zaaggenz_contracts import ContractError, validate
from zaaggenz_contracts.legacy import envelope
from zaaggenz_contracts.registry import (
    automation_parameter_definition,
    node_catalogue,
    node_definition,
)
from zaaggenz_dsp.graph import GraphError, execute_graph


def node(type_id, automation=()):
    definition = node_definition(type_id)
    return envelope(
        'DSPNodeSpec',
        id='under-test',
        type_id=type_id,
        inputs=['source'],
        channels=1,
        params={name: spec['default'] for name, spec in definition['parameters'].items()},
        state_policy=definition['state'],
        phase_policy='source-derived',
        latency_samples=definition['latency'],
        lookahead_samples=definition['lookahead'],
        bypass=definition['bypass'],
        automation=list(automation),
    )


def lane(parameter, unit, value=0.0, second_value=None):
    if second_value is None:
        second_value = value
    return {
        'parameter': parameter,
        'unit': unit,
        'interpolation': 'linear',
        'points': [
            {'sample': 0, 'value': value},
            {'sample': 3, 'value': second_value},
        ],
    }


class AutomationCapabilityContractTests(unittest.TestCase):
    def test_registry_is_single_capability_source_for_every_parameter(self):
        for type_id, definition in node_catalogue().items():
            for parameter, spec in definition['parameters'].items():
                contract = node(type_id, [lane(parameter, spec['unit'], spec['default'])])
                supported = spec.get('type') == 'number' and spec.get('x-automatable') is True
                with self.subTest(type_id=type_id, parameter=parameter, supported=supported):
                    if supported:
                        self.assertEqual(
                            automation_parameter_definition(type_id, parameter), spec
                        )
                        validate(contract, 'DSPNodeSpec')
                    else:
                        with self.assertRaisesRegex(ContractError, 'not automatable'):
                            automation_parameter_definition(type_id, parameter)
                        with self.assertRaisesRegex(ContractError, 'not automatable'):
                            validate(contract, 'DSPNodeSpec')

    def test_supported_gain_tanh_and_hard_clip_automation_executes(self):
        cases = (
            ('core.gain.v1', 'gain_db', 'dB', -6.0, 0.0),
            ('core.tanh.v1', 'drive_db', 'dB', 0.0, 6.0),
            ('core.tanh.v1', 'mix', 'ratio', 0.0, 1.0),
            ('core.hard_clip.v1', 'threshold', 'linear_amplitude', 1.0, 0.5),
            ('core.hard_clip.v1', 'mix', 'ratio', 0.0, 1.0),
        )
        source = np.linspace(-0.75, 0.75, 8, dtype=np.float32)
        for type_id, parameter, unit, start, end in cases:
            with self.subTest(type_id=type_id, parameter=parameter):
                contract = node(type_id, [lane(parameter, unit, start, end)])
                validate(contract, 'DSPNodeSpec')
                result = execute_graph(source, 48000, [contract], 'under-test').output
                self.assertEqual(result.shape, source.shape)
                self.assertTrue(np.isfinite(result).all())

    def test_nonautomatable_numeric_crossover_fails_before_dsp(self):
        contract = node(
            'core.multiband_gain.v1',
            [lane('low_xover_hz', 'Hz', 105.0, 110.0)],
        )
        with self.assertRaisesRegex(ContractError, 'core.multiband_gain.v1.low_xover_hz is not automatable'):
            validate(contract, 'DSPNodeSpec')
        with patch('zaaggenz_dsp.graph.multiband_gain', side_effect=AssertionError('DSP ran')):
            with self.assertRaisesRegex(GraphError, 'core.multiband_gain.v1.low_xover_hz is not automatable'):
                execute_graph(np.zeros(8, dtype=np.float32), 48000, [contract], 'under-test')

    def test_boolean_integer_and_static_numeric_parameters_all_fail_contract_validation(self):
        cases = (
            ('core.multiband_gain.v1', 'confine_delta', 'boolean', 0.0),
            ('core.tanh_aa.v1', 'oversample', 'ratio', 2.0),
            ('core.tanh_aa.v1', 'drive_db', 'dB', 0.0),
        )
        for type_id, parameter, unit, value in cases:
            with self.subTest(type_id=type_id, parameter=parameter):
                with self.assertRaisesRegex(ContractError, 'not automatable'):
                    validate(node(type_id, [lane(parameter, unit, value)]), 'DSPNodeSpec')

    def test_unknown_duplicate_wrong_unit_bound_and_order_remain_rejected(self):
        cases = []
        cases.append(node('core.gain.v1', [lane('missing', 'dB')]))
        duplicate = lane('gain_db', 'dB')
        cases.append(node('core.gain.v1', [duplicate, dict(duplicate)]))
        cases.append(node('core.gain.v1', [lane('gain_db', 'Hz')]))
        cases.append(node('core.gain.v1', [lane('gain_db', 'dB', -121.0)]))
        reversed_lane = lane('gain_db', 'dB')
        reversed_lane['points'] = [
            {'sample': 3, 'value': 0.0},
            {'sample': 0, 'value': 0.0},
        ]
        cases.append(node('core.gain.v1', [reversed_lane]))
        for index, contract in enumerate(cases):
            with self.subTest(case=index), self.assertRaises(ContractError):
                validate(contract, 'DSPNodeSpec')


if __name__ == '__main__':
    unittest.main(verbosity=2)
