"""NYQ-004 independent ordered instantaneous control policy/boundary tests."""
from dataclasses import replace
from decimal import Decimal
from fractions import Fraction
import unittest

from zaaggenz_contracts import ContractError
from zaaggenz_contracts.nyquismic import (
    ClockSpec, JitterSpec, ModulationRoute, Point, RateQuantizer,
    SonicSpec, VirtualRate, UnsupportedNyquismic,
)
from zaaggenz_contracts.nyquismic_clock import ClockPlan
from zaaggenz_contracts.nyquismic_controls import (
    METHOD, evaluate_instantaneous_rate, nearest_ladder_hz,
)


def make(**kwargs):
    return SonicSpec(clock=ClockSpec(rate=VirtualRate('100/1'), **kwargs))


class NYQ004ControlTests(unittest.TestCase):
    def test_piecewise_hz_step_and_linear_right_continuity(self):
        step = make(points_hz=(Point('1/2', '200/1'),))
        self.assertEqual(evaluate_instantaneous_rate(step, '1/4').base_hz, '100/1')
        self.assertEqual(evaluate_instantaneous_rate(step, '1/2').base_hz, '200/1')
        linear = make(points_hz=(Point('1/2', '200/1'),), interpolation='linear')
        self.assertEqual(evaluate_instantaneous_rate(linear, '1/4').base_hz, '150/1')
        self.assertEqual(evaluate_instantaneous_rate(linear, '1/2').base_hz, '200/1')

    def test_ordered_additive_and_logarithmic_routes(self):
        add = ModulationRoute(id='add', mapping='add_hz', depth=20., initial='1/2')
        log = ModulationRoute(id='octave', mapping='log2_ratio', depth=1., initial='1/1')
        forward = make(routes=(add, log))
        backward = make(routes=(log, add))
        self.assertAlmostEqual(float(Decimal(evaluate_instantaneous_rate(forward, '0/1').realized_hz)), 220)
        self.assertAlmostEqual(float(Decimal(evaluate_instantaneous_rate(backward, '0/1').realized_hz)), 210)
        self.assertNotEqual(forward.sonic_sha256, backward.sonic_sha256)
        frac = make(routes=(replace(log, initial='1/2'),))
        self.assertAlmostEqual(float(Decimal(evaluate_instantaneous_rate(frac, '0/1').realized_hz)),
                               100 * 2**0.5, places=12)

    def test_nearest_ties_rational_ratios_and_ladder_admission(self):
        q = RateQuantizer(policy='nearest_hz', levels_hz=('90/1', '110/1'))
        spec = make(quantizer=q)
        actual = evaluate_instantaneous_rate(spec, '1/5')
        self.assertEqual(actual.quantized_hz, '90/1')
        self.assertEqual(actual.realized_hz, '90/1')
        for ratio in ('1/3', '2/5', '3/7', '5/11', '7/13'):
            hz = Fraction(ratio) * 48000
            self.assertEqual(nearest_ladder_hz(hz, (f'{hz.numerator}/{hz.denominator}',)), hz)
        for values in ((), ('2/1','1/1'), ('1/1','1/1'), ('0/1',)):
            with self.subTest(values=values), self.assertRaises(ContractError):
                nearest_ladder_hz(Fraction(1), values)

    def test_seeded_jitter_linked_and_independent_physical_cells(self):
        jitter = JitterSpec(model='uniform_frequency_cells_v1', amount=.125,
                            cell_s='1/1000', seed='152', stream='clock')
        linked = replace(make(jitter=jitter), channels=2, instance_id='stable-clock')
        a = evaluate_instantaneous_rate(linked, '1/4000', channel=0)
        b = evaluate_instantaneous_rate(linked, '1/4000', channel=1)
        self.assertEqual(a.jitter_cell_index, 0)
        self.assertEqual(a.realized_hz, b.realized_hz)
        self.assertEqual(a, evaluate_instantaneous_rate(linked, '1/4000'))
        self.assertEqual(evaluate_instantaneous_rate(linked, '1/2000').jitter_cell_index, 0)
        self.assertEqual(evaluate_instantaneous_rate(linked, '1/1000').jitter_cell_index, 1)
        self.assertEqual(a.realized_hz, evaluate_instantaneous_rate(replace(linked, label='view'), '1/4000').realized_hz)
        independent = replace(linked, stereo_link='independent')
        ia = evaluate_instantaneous_rate(independent, '1/4000', channel=0)
        ib = evaluate_instantaneous_rate(independent, '1/4000', channel=1)
        self.assertNotEqual(ia.jitter_value, ib.jitter_value)
        self.assertNotEqual(a.jitter_value, evaluate_instantaneous_rate(
            replace(linked, instance_id='second-clock'), '1/4000').jitter_value)

    def test_invalid_requests_fail_and_clock_geometry_remains_blocked(self):
        spec = make(routes=(ModulationRoute(initial='1/2', depth=4),))
        for value in ('-1/1', '3601/1', '1/0', 'nan', 0.1, True):
            with self.subTest(value=value), self.assertRaises(ContractError):
                evaluate_instantaneous_rate(spec, value)
        with self.assertRaises(ContractError):
            evaluate_instantaneous_rate(spec, '1/2', channel=True)
        future = replace(spec, clock=replace(spec.clock, origin_s='1/2'))
        with self.assertRaises(ContractError):
            evaluate_instantaneous_rate(future, '1/4')
        with self.assertRaises(UnsupportedNyquismic):
            ClockPlan(spec.clock, '1/1')
        self.assertEqual(evaluate_instantaneous_rate(spec, '0/1').method, METHOD)


if __name__ == '__main__':
    unittest.main()
