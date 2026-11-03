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

    def test_ratio_ladder_frozen_reference_and_exact_absolute_hz(self):
        from zaaggenz_contracts.nyquismic_controls import RatioLadder
        values = ('1/3', '2/5', '3/7', '5/11', '7/13')
        ladder = RatioLadder(reference_hz='48000/1', ratios=values)
        self.assertEqual(RatioLadder.from_json(ladder.to_json()), ladder)
        self.assertEqual(ladder.ratios, values)
        quantizer = ladder.as_quantizer()
        self.assertEqual(quantizer.levels_hz,
                         ('16000/1', '19200/1', '144000/7', '240000/11', '336000/13'))
        self.assertEqual(quantizer.tie, 'lower')
        # The same fractions against another *saved* Hz authority are different
        # musical clocks: a numerical evaluator rate is never an input.
        other = RatioLadder(reference_hz='96000/1', ratios=('1/3', '2/5'))
        self.assertEqual(other.as_quantizer().levels_hz, ('32000/1', '38400/1'))
        self.assertNotEqual(other.sha256, ladder.sha256)
        self.assertEqual(RatioLadder(reference_hz='48000/1', ratios=('2/6',)).ratios,
                         ('1/3',))

    def test_ratio_ladder_lower_ties_and_instantaneous_clock_integration(self):
        from zaaggenz_contracts.nyquismic_controls import (
            RatioLadder, evaluate_instantaneous_rate, nearest_ladder_hz)
        from zaaggenz_contracts.nyquismic import ClockSpec, SonicSpec, VirtualRate
        ladder = RatioLadder(reference_hz='48000/1', ratios=('1/3', '2/5'))
        quantizer = ladder.as_quantizer()
        self.assertEqual(nearest_ladder_hz(Fraction(17600), quantizer.levels_hz),
                         Fraction(16000))
        spec = SonicSpec(clock=ClockSpec(rate=VirtualRate('17600/1'),
                                        quantizer=quantizer))
        sample = evaluate_instantaneous_rate(spec, '9/8')
        self.assertEqual(sample.quantized_hz, '16000/1')
        self.assertEqual(sample.realized_hz, '16000/1')
        # The downstream NYQ-002 audio executor remains deliberately gated.
        with self.assertRaises(ContractError):
            spec.clock.require_geometry()

    def test_ratio_ladder_invalid_values_fail_closed(self):
        from zaaggenz_contracts.nyquismic_controls import RatioLadder
        from zaaggenz_contracts.nyquismic import ContractError
        cases = [
            {'ratios': ()}, {'ratios': ('0/1',)}, {'ratios': ('-1/3',)},
            {'ratios': ('2/5', '1/3')}, {'ratios': ('1/3', '2/6')},
            {'ratios': tuple('1/' + str(i) for i in range(1, 66))},
            {'reference_hz': '0/1'}, {'reference_hz': '1536001/1'},
            {'reference_hz': '1536000/1', 'ratios': ('2/1',)},
            {'ratios': ('1/10000000000',)},
        ]
        for overrides in cases:
            with self.subTest(overrides=str(overrides)[:80]):
                with self.assertRaises(ContractError):
                    RatioLadder(**overrides)
        row = RatioLadder().to_dict()
        for bad in ({**row, 'extra': 3}, {**row, 'ratios': ['1/3', 4]},
                    {**row, 'ratios': ('1/3',)}, {**row, 'version': 'v2'}):
            with self.assertRaises(ContractError):
                RatioLadder.from_dict(bad)


if __name__ == '__main__':
    unittest.main()
