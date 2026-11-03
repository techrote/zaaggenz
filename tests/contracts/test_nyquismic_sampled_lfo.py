"""NYQ-004 bounded free-Hz and beat-sync triangle LFO authoring tests."""
from dataclasses import replace
from fractions import Fraction
import unittest

from zaaggenz_contracts import ContractError
from zaaggenz_contracts.nyquismic import ClockSpec, Point, SonicSpec, VirtualRate
from zaaggenz_contracts.nyquismic_controls import (
    SampledLfoSource, evaluate_instantaneous_rate,
)


class SampledLfoTests(unittest.TestCase):
    def test_exact_phase_free_hz_and_frozen_route_evaluation(self):
        source = SampledLfoSource(frequency='1/1', grid_s='1/8')
        self.assertEqual(source.value_at('0/1'), -1)
        self.assertEqual(source.value_at('1/4'), 0)
        self.assertEqual(source.value_at('1/2'), 1)
        self.assertEqual(source.value_at('3/4'), 0)
        self.assertEqual(source.value_at('1/1'), -1)
        route = source.compile_route('1/1', route_id='triangle', depth=20.0)
        self.assertEqual(route.interpolation, 'linear')
        self.assertEqual(len(route.points), 8)
        self.assertEqual(route.initial, '-1/1')
        self.assertEqual(route.points[3].value, '1/1')
        spec = SonicSpec(clock=ClockSpec(rate=VirtualRate('100/1'), routes=(route,)))
        self.assertEqual(Fraction(evaluate_instantaneous_rate(spec, '0/1').realized_hz), 80)
        self.assertEqual(Fraction(evaluate_instantaneous_rate(spec, '1/4').realized_hz), 100)
        self.assertEqual(Fraction(evaluate_instantaneous_rate(spec, '1/2').realized_hz), 120)
        self.assertEqual(Fraction(evaluate_instantaneous_rate(spec, '3/4').realized_hz), 100)
        self.assertNotEqual(spec.sonic_sha256,
                            replace(spec, clock=ClockSpec(rate=VirtualRate('100/1'))).sonic_sha256)
        with self.assertRaises(ContractError):
            spec.clock.require_geometry()  # audio adapter remains unavailable

    def test_beat_sync_tempo_change_preserves_integrated_phase(self):
        source = SampledLfoSource(mode='beat_sync', frequency='1/1',
                    base_bpm='120/1', grid_s='1/8',
                    tempo_points=(Point('1/2', '60/1'),))
        self.assertEqual(source.value_at('0/1'), -1)
        self.assertEqual(source.value_at('1/4'), 1)
        self.assertEqual(source.value_at('1/2'), -1)
        self.assertEqual(source.value_at('3/4'), 0)
        self.assertEqual(source.value_at('1/1'), 1)
        route = source.compile_route('1/1', route_id='beats', depth=10.)
        self.assertEqual(route.points[5].value, '0/1')
        self.assertEqual(SampledLfoSource.from_json(source.to_json()), source)
        self.assertNotEqual(source.sha256,
                            replace(source, tempo_points=(Point('1/2', '90/1'),)).sha256)
        self.assertEqual(source.value_at('3/4'), source.value_at('3/4'))

    def test_noninteger_cycles_and_partial_endpoint_have_exact_grid(self):
        source = SampledLfoSource(frequency='3/2', origin_s='1/8',
                                  phase_cycles='1/4', grid_s='1/16')
        route = source.compile_route('3/10', route_id='partial', depth=3.)
        self.assertEqual(route.initial, source.value_at('1/8').numerator.__str__() + '/' + str(source.value_at('1/8').denominator))
        self.assertEqual(Fraction(route.points[-1].time_s), Fraction(3, 10))
        self.assertEqual(len(route.points), 3)
        self.assertEqual(Fraction(route.points[-1].value), source.value_at('3/10'))
        self.assertEqual(len(source.compile_route('1/8', route_id='empty').points), 0)

    def test_invalid_time_tempo_numerics_and_budget_fail_closed(self):
        bad_specs = (
            {'mode': 'unimplemented'}, {'frequency': '0/1'},
            {'frequency': '65/1'}, {'phase_cycles': '1/1'},
            {'grid_s': '0/1'}, {'base_bpm': '10/1'},
            {'tempo_points': (Point('1/4','120/1'),)},
            {'mode': 'beat_sync', 'tempo_points': (Point('0/1','120/1'),)},
            {'mode': 'beat_sync', 'tempo_points': (Point('1/2','400/1'),)},
        )
        for kwargs in bad_specs:
            with self.subTest(kwargs=kwargs), self.assertRaises(ContractError):
                SampledLfoSource(**kwargs)
        source = SampledLfoSource()
        with self.assertRaises(ContractError):
            source.compile_route('1/1', route_id='oversized')
        with self.assertRaises(ContractError):
            source.compile_route('1/1', route_id='invalid', depth=float('nan'))
        with self.assertRaises(ContractError):
            source.compile_route('1/1', route_id='invalid', mapping='unsupported')
        with self.assertRaises(ContractError):
            source.value_at('-1/1')
        with self.assertRaises(ContractError):
            source.compile_route('3601/1', route_id='unbounded')


if __name__ == '__main__':
    unittest.main()
