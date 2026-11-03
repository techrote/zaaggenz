"""Independent exact-time controlled-step phase/capture regression oracles.

Proves a bounded event geometry subset; not evidence for sampler/rack integration.
"""
from dataclasses import replace
from fractions import Fraction
import unittest

from zaaggenz_contracts import ContractError
from zaaggenz_contracts.nyquismic import (
    ClockSpec, JitterSpec, ModulationRoute, Point, RateQuantizer, Reset,
    ResourceBudget, SonicSpec, UnsupportedNyquismic, VirtualRate,
)
from zaaggenz_contracts.nyquismic_clock import ClockCancelled, ClockPlan
from zaaggenz_contracts.nyquismic_controls import compile_step_clock_events


def sonic(rate='4/1', **clock_kwargs):
    return SonicSpec(clock=ClockSpec(rate=VirtualRate(rate), **clock_kwargs))


class ControlledStepGeometryTests(unittest.TestCase):
    def test_static_captures_equal_accepted_fractional_phase_clock(self):
        request = sonic()
        actual = compile_step_clock_events(request, '1/1')
        baseline = ClockPlan(request.clock, '1/1')
        self.assertEqual(
            [e.coordinate_s for e in actual],
            [baseline.event_coordinate(i) for i in range(baseline.event_count)],
        )
        self.assertEqual([e.crossing for e in actual], [0, 1, 2, 3])
        self.assertEqual([e.index for e in actual], list(range(4)))

    def test_step_route_changes_rate_without_resetting_accumulated_phase(self):
        route = ModulationRoute(id='add', mapping='add_hz', depth=4.,
                                initial='1/2', points=(Point('1/2', '0/1'),))
        request = sonic(routes=(route,))
        events = compile_step_clock_events(request, '1/1')
        self.assertEqual(
            [e.coordinate_s for e in events],
            [Fraction(0), Fraction(1, 6), Fraction(1, 3),
             Fraction(1, 2), Fraction(3, 4)],
        )
        self.assertEqual([e.epoch for e in events], [0] * 5)

    def test_piecewise_base_and_quantized_lower_tie(self):
        request = sonic('100/1', quantizer=RateQuantizer(
            policy='nearest_hz', levels_hz=('90/1', '110/1')))
        events = compile_step_clock_events(request, '1/10')
        self.assertEqual(len(events), 9)
        self.assertEqual([e.coordinate_s for e in events],
                         [Fraction(k, 90) for k in range(9)])
        switched = sonic('4/1', points_hz=(Point('1/2', '6/1'),))
        events = compile_step_clock_events(switched, '1/1')
        # 2 cycles at t=1/2; then 6 Hz, so crossings at 1/2,2/3,5/6.
        self.assertEqual([e.coordinate_s for e in events],
                         [Fraction(0), Fraction(1, 4), Fraction(1, 2),
                          Fraction(2, 3), Fraction(5, 6)])

    def test_explicit_reset_new_epoch_and_half_open_boundary(self):
        request = sonic(resets=(Reset(time_s='1/2', phase_cycles='0/1'),))
        events = compile_step_clock_events(request, '1/1')
        self.assertEqual([e.coordinate_s for e in events],
                         [Fraction(0), Fraction(1, 4), Fraction(1, 2), Fraction(3, 4)])
        self.assertEqual([e.epoch for e in events], [0, 0, 1, 1])
        self.assertEqual([e.crossing for e in events], [0, 1, 0, 1])

    def test_stochastic_cells_linked_and_independent_are_reproducible(self):
        jitter = JitterSpec(model='uniform_frequency_cells_v1', amount=.05,
                            cell_s='1/10', seed='71', stream='test')
        request = replace(sonic('12/1', jitter=jitter),
                          channels=2, instance_id='stable-node')
        a = compile_step_clock_events(request, '1/1', channel=0)
        b = compile_step_clock_events(request, '1/1', channel=1)
        self.assertEqual(a, b)
        self.assertEqual(a, compile_step_clock_events(request, '1/1', channel=0))
        self.assertTrue(all(a[i].coordinate_s < a[i + 1].coordinate_s
                            for i in range(len(a) - 1)))
        independent = replace(request, stereo_link='independent')
        self.assertNotEqual(
            [e.coordinate_s for e in compile_step_clock_events(independent, '1/1', channel=0)],
            [e.coordinate_s for e in compile_step_clock_events(independent, '1/1', channel=1)],
        )

    def test_unimplemented_geometry_rejects_before_publication(self):
        for invalid in (
            sonic(points_hz=(Point('1/2', '6/1'),), interpolation='linear'),
            sonic(routes=(ModulationRoute(
                mapping='log2_ratio', depth=1, initial='1/2'),)),
            sonic(routes=(ModulationRoute(
                depth=1, initial='1/2', points=(Point('1/2', '0/1'),),
                interpolation='linear'),)),
        ):
            with self.subTest(clock=invalid.clock.sha256), self.assertRaises(UnsupportedNyquismic):
                compile_step_clock_events(invalid, '1/1')
        with self.assertRaises(ClockCancelled):
            compile_step_clock_events(sonic(), '1/1', cancelled=lambda: True)
        with self.assertRaises(ContractError):
            compile_step_clock_events(sonic('15/1'), '1/1',
                                      budget=ResourceBudget(max_events=2))
        with self.assertRaises(ContractError):
            compile_step_clock_events(
                sonic(jitter=JitterSpec(model='uniform_frequency_cells_v1',
                                        amount=.05, cell_s='1/1536000')),
                '1/1',
            )


if __name__ == '__main__':
    unittest.main()
