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

    def test_linear_hz_ramp_has_analytic_integral_and_certified_roots(self):
        # f(t)=3+4t, phase(t)=3t+2t^2. Integer crossing two is
        # exactly t=1/2; the other crossings generally have irrational roots.
        request = sonic('3/1', points_hz=(Point('1/1', '7/1'),),
                        interpolation='linear')
        events = compile_step_clock_events(request, '1/1')
        self.assertEqual([e.crossing for e in events], list(range(5)))
        self.assertEqual(events[2].coordinate_s, Fraction(1, 2))
        self.assertEqual(events[2].coordinate_error_bound_s, Fraction(0))
        self.assertGreater(events[1].coordinate_error_bound_s, 0)
        for event in events:
            t = event.coordinate_s
            self.assertLessEqual(abs(3 * t + 2 * t * t - event.crossing),
                                 7 * event.coordinate_error_bound_s)
            self.assertLessEqual(event.coordinate_error_bound_s, Fraction(1, 10**18))
        self.assertTrue(all(a.coordinate_s < b.coordinate_s
                            for a, b in zip(events, events[1:])))

        # Decreasing slope must select the forward root, not the other
        # quadratic branch: f(t)=7-4t, phase(t)=7t-2t^2.
        falling = sonic('7/1', points_hz=(Point('1/1', '3/1'),),
                        interpolation='linear')
        events = compile_step_clock_events(falling, '1/1')
        self.assertEqual(events[3].coordinate_s, Fraction(1, 2))
        self.assertEqual([e.crossing for e in events], list(range(5)))
        for event in events:
            t = event.coordinate_s
            self.assertLessEqual(abs(7 * t - 2 * t * t - event.crossing),
                                 7 * event.coordinate_error_bound_s)

    def test_linear_route_is_not_block_sampled_and_reset_is_continuous_after_reset(self):
        route = ModulationRoute(id='ramp', mapping='add_hz', depth=4.,
                                initial='0/1', points=(Point('1/1', '1/1'),),
                                interpolation='linear')
        routed = sonic('3/1', routes=(route,))
        equivalent = sonic('3/1', points_hz=(Point('1/1', '7/1'),),
                           interpolation='linear')
        self.assertEqual(
            [e.coordinate_s for e in compile_step_clock_events(routed, '1/1')],
            [e.coordinate_s for e in compile_step_clock_events(equivalent, '1/1')],
        )
        reset = sonic('3/1', points_hz=(Point('1/1', '7/1'),),
                      interpolation='linear',
                      resets=(Reset(time_s='1/2', phase_cycles='0/1'),))
        events = compile_step_clock_events(reset, '1/1')
        self.assertEqual([(e.epoch, e.crossing) for e in events],
                         [(0, 0), (0, 1), (1, 0), (1, 1), (1, 2)])
        self.assertEqual(events[2].coordinate_s, Fraction(1, 2))
        self.assertEqual(events, compile_step_clock_events(reset, '1/1'))

    def test_ramped_jitter_cells_are_reproducible_and_bounded(self):
        jitter = JitterSpec(model='uniform_frequency_cells_v1', amount=.05,
                            cell_s='1/4', seed='199', stream='linear')
        request = sonic('3/1', points_hz=(Point('1/1', '7/1'),),
                        interpolation='linear', jitter=jitter)
        events = compile_step_clock_events(request, '1/1')
        self.assertEqual(events, compile_step_clock_events(request, '1/1'))
        self.assertTrue(all(a.coordinate_s < b.coordinate_s
                            for a, b in zip(events, events[1:])))
        self.assertTrue(all(e.coordinate_error_bound_s <= Fraction(1, 10**18)
                            for e in events))

    def test_linear_hz_quantizer_exact_switch_and_boundary_tie(self):
        # Underlying f(t)=4+4t reaches the 6 Hz ladder midpoint at t=1/2.
        # Actual virtual clock is 4 Hz on the first half and 8 Hz on the
        # second: no smoothed ramp, buffer-rate quantization or phase reset.
        from zaaggenz_contracts.nyquismic_controls import evaluate_instantaneous_rate
        request = sonic('4/1', points_hz=(Point('1/1', '8/1'),),
                        interpolation='linear', quantizer=RateQuantizer(
                            policy='nearest_hz', levels_hz=('4/1', '8/1')))
        self.assertEqual(evaluate_instantaneous_rate(request, '1/2').realized_hz, '4/1')
        expected = [Fraction(0), Fraction(1, 4), Fraction(1, 2),
                    Fraction(5, 8), Fraction(3, 4), Fraction(7, 8)]
        actual = compile_step_clock_events(request, '1/1')
        self.assertEqual([event.coordinate_s for event in actual], expected)
        self.assertTrue(all(event.coordinate_error_bound_s == 0 for event in actual))
        self.assertEqual(compile_step_clock_events(request, '3/4'), actual[:4])

    def test_quantized_affine_route_falling_and_reset_at_exact_switch(self):
        # Unlike an upward tie, an exact downward 6 Hz tie selects the
        # right-hand 4 Hz segment. Reset and ladder switch share a boundary.
        route = ModulationRoute(id='fall', mapping='add_hz', depth=-4.,
                                initial='0/1', points=(Point('1/1', '1/1'),),
                                interpolation='linear')
        quantizer = RateQuantizer(policy='nearest_hz', levels_hz=('4/1', '8/1'))
        request = sonic('8/1', routes=(route,), quantizer=quantizer,
                        resets=(Reset(time_s='1/2', phase_cycles='0/1'),))
        actual = compile_step_clock_events(request, '1/1')
        self.assertEqual([event.coordinate_s for event in actual],
                         [Fraction(0), Fraction(1, 8), Fraction(1, 4),
                          Fraction(3, 8), Fraction(1, 2), Fraction(3, 4)])
        self.assertEqual([event.epoch for event in actual], [0, 0, 0, 0, 1, 1])
        self.assertEqual([event.crossing for event in actual], [0, 1, 2, 3, 0, 1])

    def test_multiple_quantized_ramp_switches_preserve_exact_phase(self):
        request = sonic('4/1', points_hz=(Point('1/1', '10/1'),),
                        interpolation='linear', quantizer=RateQuantizer(
                            policy='nearest_hz', levels_hz=('5/1', '7/1', '9/1')))
        expected = [Fraction(0), Fraction(1, 5), Fraction(8, 21),
                    Fraction(11, 21), Fraction(2, 3),
                    Fraction(7, 9), Fraction(8, 9)]
        actual = compile_step_clock_events(request, '1/1')
        self.assertEqual([event.coordinate_s for event in actual], expected)
        self.assertEqual([event.crossing for event in actual], list(range(7)))
        self.assertEqual(actual, compile_step_clock_events(request, '1/1'))
        with self.assertRaises(ContractError):
            compile_step_clock_events(request, '1/1',
                                      budget=ResourceBudget(max_events=4))

    def test_unimplemented_geometry_rejects_before_publication(self):
        for invalid in (
            sonic(routes=(ModulationRoute(
                mapping='log2_ratio', depth=1, initial='1/2'),)),
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
