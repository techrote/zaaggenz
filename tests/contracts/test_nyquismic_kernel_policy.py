"""NYQ-002 capability pairing and exact event-coordinate consumer boundary."""
from dataclasses import replace
from decimal import Decimal, localcontext
from fractions import Fraction
import unittest

from zaaggenz_contracts import ContractError
from zaaggenz_contracts.nyquismic import (
    ClockSpec, VirtualRate, Point, Reset, EvaluationPolicy, SonicSpec,
    SAMPLER_AUDIO_METHOD, SAMPLER_NUMERICAL_FILTER, UnsupportedNyquismic,
)
from zaaggenz_contracts.nyquismic_clock import ClockPlan


class NyquismicKernelPolicy(unittest.TestCase):
    def test_default_remains_unavailable_and_explicit_pair_roundtrips(self):
        policy = EvaluationPolicy()
        self.assertEqual(policy.audio_method, 'unavailable_nyq001')
        self.assertEqual(policy.numerical_filter, 'unavailable_nyq001')
        actual = replace(policy, audio_method=SAMPLER_AUDIO_METHOD,
                         numerical_filter=SAMPLER_NUMERICAL_FILTER)
        self.assertEqual(actual, EvaluationPolicy.from_json(actual.to_json()))
        self.assertNotEqual(actual.sha256, policy.sha256)
        with self.assertRaises(ContractError):
            replace(policy, audio_method=SAMPLER_AUDIO_METHOD)
        with self.assertRaises(ContractError):
            replace(policy, numerical_filter=SAMPLER_NUMERICAL_FILTER)
        # No generic registered/rack dispatcher was smuggled in with the kernel.
        with self.assertRaises(UnsupportedNyquismic):
            SonicSpec().require_audio_execution()

    def test_exact_count_handles_reset_ties_and_excluded_endpoint(self):
        clock = ClockSpec(rate=VirtualRate('4/1'), resets=(Reset('1/2', '1/4'),))
        plan = ClockPlan(clock, '1/1')
        expected = ((Fraction(0), 0, 1), (Fraction(1, 4), 1, 2),
                    (Fraction(1, 2), 2, 2), (Fraction(11, 16), 2, 3),
                    (Fraction(15, 16), 3, 4), (Fraction(1), 4, 4))
        for at, before, through in expected:
            self.assertEqual(plan.capture_count_at(at), before)
            self.assertEqual(plan.capture_count_at(at, inclusive=True), through)
        for invalid in (0.0, '0/1', True):
            with self.assertRaises(ContractError):
                plan.capture_count_at(invalid)
        with self.assertRaises(ContractError):
            plan.capture_count_at(Fraction(1, 2), inclusive=1)
        for invalid in (Fraction(-1), Fraction(2)):
            with self.assertRaises(ContractError):
                plan.capture_count_at(invalid)

    def test_exact_grid_membership_is_not_binary64_timestamp_membership(self):
        plan = ClockPlan(ClockSpec(rate=VirtualRate('3/1')), '1/1')
        self.assertEqual(plan.event_coordinate(1), Fraction(1, 3))
        rounded = Fraction.from_float(plan.events()[1].time_s)
        self.assertLess(rounded, Fraction(1, 3))
        self.assertEqual(plan.capture_count_at(rounded, inclusive=True), 1)
        self.assertEqual(plan.capture_count_at(Fraction(1, 3), inclusive=True), 2)
        # In-memory numerical grid denominators need not be serialized inputs.
        tiny_before = Fraction(1, 3) - Fraction(1, 10**40)
        self.assertEqual(plan.capture_count_at(tiny_before, inclusive=True), 1)

    def test_coordinate_root_precision_and_zero_event_segments(self):
        plan = ClockPlan(ClockSpec(rate=VirtualRate('1/1'), phase_cycles='1/4',
                         points_hz=(Point('1/10', '1/1'), Point('1/5', '1/1'),
                                    Point('3/10', '1/1'))), '1/1')
        self.assertEqual(plan.event_coordinate(0), Fraction(3, 4))
        ramp = ClockPlan(ClockSpec(rate=VirtualRate('4/1'), interpolation='linear',
                         points_hz=(Point('1/1', '12/1'),)), '1/1')
        coordinate = ramp.event_coordinate(1)
        self.assertIs(type(coordinate), Decimal)
        self.assertEqual(float(coordinate), ramp.events()[1].time_s)
        with localcontext() as context:
            context.prec = 6
            context.rounding = 'ROUND_FLOOR'
            self.assertEqual(coordinate, ramp.event_coordinate(1))
        for invalid in (-1, 100, True, 0.0):
            with self.assertRaises(ContractError):
                ramp.event_coordinate(invalid)


if __name__ == '__main__':
    unittest.main()
