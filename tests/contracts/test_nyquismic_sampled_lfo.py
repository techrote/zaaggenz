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
        self.assertEqual(route.initial, '0/1')
        self.assertEqual((route.points[0].time_s, route.points[0].value), ('1/8', '0/1'))
        self.assertEqual(Fraction(route.points[-1].time_s), Fraction(3, 10))
        # The exact peak at 7/24 seconds falls between 1/16-second grid
        # samples, and must now be preserved in the compiled route.
        self.assertEqual(len(route.points), 5)
        self.assertIn(Fraction(7, 24), {Fraction(p.time_s) for p in route.points})
        self.assertEqual(Fraction(route.points[-1].value), source.value_at('3/10'))
        self.assertEqual(len(source.compile_route('1/8', route_id='empty').points), 1)

    def test_delayed_lfo_neutral_pre_origin_and_nonzero_step_refusal(self):
        source = SampledLfoSource(origin_s='1/8', phase_cycles='1/4',
                                  frequency='1/1', grid_s='1/8')
        route = source.compile_route('1/2', route_id='delayed', depth=20.)
        self.assertEqual(route.initial, '0/1')
        self.assertEqual((route.points[0].time_s, route.points[0].value),
                         ('1/8', '0/1'))
        spec = SonicSpec(clock=ClockSpec(rate=VirtualRate('100/1'), routes=(route,)))
        for at, expected in (('0/1', 100), ('1/16', 100),
                             ('1/8', 100), ('1/4', 110)):
            with self.subTest(at=at):
                self.assertEqual(Fraction(evaluate_instantaneous_rate(
                    spec, at).realized_hz), expected)
        self.assertEqual(route.to_json(),
                         source.compile_route('1/2', route_id='delayed', depth=20.).to_json())
        # A uniform linear lane cannot have an exact nonzero step at origin.
        with self.assertRaisesRegex(ContractError, 'zero-level onset'):
            SampledLfoSource(origin_s='1/8', phase_cycles='0/1',
                             grid_s='1/8').compile_route('1/2', route_id='no-leak')
        # Count the explicit onset against the same frozen lane budget.
        with self.assertRaises(ContractError):
            source.compile_route('256/8', route_id='over-budget')

    def test_non_grid_turning_points_are_exact_at_intermediate_times(self):
        source = SampledLfoSource(frequency='3/2', grid_s='1/10')
        route = source.compile_route('1/1', route_id='cusps', depth=20.)
        stamps = {Fraction(p.time_s) for p in route.points}
        self.assertTrue({Fraction(1, 3), Fraction(2, 3), Fraction(1)} <= stamps)
        self.assertEqual(len(stamps), len(route.points))
        spec = SonicSpec(clock=ClockSpec(rate=VirtualRate('100/1'), routes=(route,)))
        for t in (Fraction(1, 20), Fraction(1, 4), Fraction(1, 3),
                  Fraction(7, 20), Fraction(11, 20), Fraction(2, 3),
                  Fraction(3, 4), Fraction(19, 20)):
            with self.subTest(time=str(t)):
                actual = Fraction(evaluate_instantaneous_rate(
                    spec, f'{t.numerator}/{t.denominator}').realized_hz)
                expected = Fraction(100) + 20 * source.value_at(
                    f'{t.numerator}/{t.denominator}')
                self.assertEqual(actual, expected)

    def test_off_grid_tempo_change_is_a_saved_slope_discontinuity(self):
        source = SampledLfoSource(mode='beat_sync', frequency='1/1',
                                  base_bpm='120/1', grid_s='1/8',
                                  tempo_points=(Point('1/3', '60/1'),))
        route = source.compile_route('1/1', route_id='tempo', depth=10.)
        stamps = {Fraction(p.time_s) for p in route.points}
        self.assertTrue({Fraction(1, 4), Fraction(1, 3),
                         Fraction(2, 3)} <= stamps)
        spec = SonicSpec(clock=ClockSpec(rate=VirtualRate('100/1'), routes=(route,)))
        for t in (Fraction(1, 5), Fraction(1, 4), Fraction(7, 24),
                  Fraction(1, 3), Fraction(3, 8), Fraction(1, 2),
                  Fraction(2, 3), Fraction(11, 12)):
            with self.subTest(time=str(t)):
                actual = Fraction(evaluate_instantaneous_rate(
                    spec, f'{t.numerator}/{t.denominator}').realized_hz)
                expected = Fraction(100) + 10 * source.value_at(
                    f'{t.numerator}/{t.denominator}')
                self.assertEqual(actual, expected)
        self.assertEqual(len(route.points), len(stamps))
        self.assertEqual(SampledLfoSource.from_json(source.to_json()), source)

    def test_turning_point_enrichment_respects_total_lane_budget(self):
        # The grid alone fits 256 points, but exact cusps raise the total
        # above that bound and must reject instead of being silently dropped.
        source = SampledLfoSource(frequency='64/1', grid_s='1/260')
        with self.assertRaises(ContractError):
            source.compile_route('63/64', route_id='overfull')

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
        for lfo in (SampledLfoSource(frequency='10/1', grid_s='1/8'),
                    SampledLfoSource(mode='beat_sync', base_bpm='360/1',
                                     grid_s='1/8', frequency='1/1')):
            with self.subTest(underresolved=lfo.mode), self.assertRaises(ContractError):
                lfo.compile_route('1/8', route_id='aliasing')
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
