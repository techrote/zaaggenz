from __future__ import annotations

from copy import deepcopy
import math
import unittest

import numpy as np

from zaaggenz_contracts import ContractError, validate
from zaaggenz_contracts.examples import examples
from zaaggenz_contracts.legacy import envelope
from zaaggenz_contracts.multiband import validate_multiband_crossovers
from zaaggenz_contracts.registry import node_definition
from zaaggenz_dsp.band_router import route_band_processors
from zaaggenz_dsp.graph import GraphError, execute_graph
from zaaggenz_dsp.multiband import BandError, multiband_gain, route_effect_deltas, validate_crossovers


def multiband_node(crossovers=(105.0, 520.0, 3600.0)):
    definition = node_definition('core.multiband_gain.v1')
    params = {name: spec['default'] for name, spec in definition['parameters'].items()}
    params.update(
        low_xover_hz=crossovers[0],
        mid_xover_hz=crossovers[1],
        high_xover_hz=crossovers[2],
    )
    return envelope(
        'DSPNodeSpec',
        id='multiband',
        type_id='core.multiband_gain.v1',
        inputs=['source'],
        channels=1,
        params=params,
        state_policy=definition['state'],
        phase_policy='source-derived',
        latency_samples=definition['latency'],
        lookahead_samples=definition['lookahead'],
        bypass=definition['bypass'],
        automation=[],
    )


def recipe_with_multiband(sample_rate_hz, crossovers):
    recipe = deepcopy(examples()['RenderRecipe'])
    recipe['source']['params']['sr'] = sample_rate_hz
    recipe['time_map']['sample_rate_hz'] = sample_rate_hz
    recipe['nodes'] = [multiband_node(crossovers)]
    recipe['output_node'] = 'multiband'
    return recipe


class SharedCrossoverRuleTests(unittest.TestCase):
    def test_standalone_node_enforces_cross_parameter_order(self):
        validate(multiband_node(), 'DSPNodeSpec')
        cases = (
            ((105, 105, 3600), 'mid_xover_hz'),
            ((105, 520, 520), 'high_xover_hz'),
            ((1000, 500, 3600), 'mid_xover_hz'),
            ((105, 4000, 3600), 'high_xover_hz'),
        )
        for crossovers, field in cases:
            with self.subTest(crossovers=crossovers), self.assertRaisesRegex(ContractError, field):
                validate(multiband_node(crossovers), 'DSPNodeSpec')

    def test_semantic_nyquist_boundary_is_exact_at_all_supported_rates(self):
        for sample_rate_hz in (8000, 12000, 48000, 192000):
            limit = 0.49 * sample_rate_hz
            below = math.nextafter(limit, -math.inf)
            above = math.nextafter(limit, math.inf)
            with self.subTest(sample_rate_hz=sample_rate_hz, case='below'):
                self.assertEqual(
                    validate_multiband_crossovers((20, 100, below), sample_rate_hz),
                    (20.0, 100.0, below),
                )
            for high in (limit, above):
                with self.subTest(sample_rate_hz=sample_rate_hz, high=high), self.assertRaisesRegex(
                    ContractError, 'high_xover_hz.*0.49.*sample_rate_hz'
                ):
                    validate_multiband_crossovers((20, 100, high), sample_rate_hz)

    def test_render_recipe_binds_rule_to_actual_recipe_rate(self):
        for sample_rate_hz in (8000, 12000, 48000, 192000):
            high = min(3600.0, math.nextafter(0.49 * sample_rate_hz, -math.inf))
            with self.subTest(sample_rate_hz=sample_rate_hz):
                validate(recipe_with_multiband(sample_rate_hz, (105, 520, high)), 'RenderRecipe')

        for sample_rate_hz in (8000, 12000, 48000):
            limit = 0.49 * sample_rate_hz
            with self.subTest(sample_rate_hz=sample_rate_hz), self.assertRaisesRegex(
                ContractError, 'high_xover_hz.*0.49.*sample_rate_hz'
            ):
                validate(recipe_with_multiband(sample_rate_hz, (105, 520, limit)), 'RenderRecipe')

    def test_registry_defaults_are_unchanged(self):
        parameters = node_definition('core.multiband_gain.v1')['parameters']
        self.assertEqual(
            tuple(parameters[name]['default'] for name in ('low_xover_hz', 'mid_xover_hz', 'high_xover_hz')),
            (105, 520, 3600),
        )


class ConsumerConsistencyTests(unittest.TestCase):
    def test_contract_graph_and_direct_dsp_report_same_rate_failure(self):
        sample_rate_hz = 8000
        crossovers = (105, 520, 0.49 * sample_rate_hz)
        expected = 'high_xover_hz must be < 0.49 * sample_rate_hz'
        node = multiband_node(crossovers)
        validate(node, 'DSPNodeSpec')  # ordering is knowable without a bound sample rate

        with self.assertRaisesRegex(ContractError, expected):
            validate(recipe_with_multiband(sample_rate_hz, crossovers), 'RenderRecipe')

        audio = np.zeros(32, dtype=np.float64)
        with self.assertRaisesRegex(GraphError, expected):
            execute_graph(audio, sample_rate_hz, [node], 'multiband')
        with self.assertRaisesRegex(BandError, expected):
            multiband_gain(audio, sample_rate_hz, crossovers, (0, 0, 0, 0))
        with self.assertRaisesRegex(BandError, expected):
            validate_crossovers(crossovers, sample_rate_hz)

    def test_identity_paths_validate_configuration_before_bypass(self):
        sample_rate_hz = 8000
        bad = (105, 520, 3920)
        audio = np.arange(32, dtype=np.float64)
        with self.assertRaisesRegex(BandError, 'high_xover_hz'):
            route_effect_deltas(audio, sample_rate_hz, bad, [None] * 4)
        with self.assertRaisesRegex(BandError, 'high_xover_hz'):
            route_band_processors(audio, sample_rate_hz, bad, [None] * 4)

    def test_valid_zero_gain_remains_bit_exact_identity(self):
        audio = np.linspace(-0.75, 0.75, 32, dtype=np.float64)
        output = multiband_gain(audio, 48000, (105, 520, 3600), (0, 0, 0, 0))
        np.testing.assert_array_equal(output, audio)


if __name__ == '__main__':
    unittest.main(verbosity=2)
