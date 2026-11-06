"""Independent NYQ-004 physical-time gate/envelope authoring oracles.

These are saved control-route and standalone event-geometry tests, not claims
of an input-following audio detector or registered Nyquismic audio executor.
"""
from dataclasses import replace
from fractions import Fraction
import unittest

from zaaggenz_contracts import ContractError
from zaaggenz_contracts.nyquismic import (
    ClockSpec, ModulationRoute, SonicSpec, VirtualRate,
)
from zaaggenz_contracts.nyquismic_clock import ClockCancelled, ClockPlan
from zaaggenz_contracts.nyquismic_controls import (
    EnvelopeGate, TriggeredEnvelopeSource, compile_step_clock_events,
    evaluate_instantaneous_rate,
)


def q(value):
    value = Fraction(value)
    return f'{value.numerator}/{value.denominator}'


class TriggeredEnvelopeTests(unittest.TestCase):
    def envelope(self, **kwargs):
        return TriggeredEnvelopeSource(
            attack_s='1/4', decay_s='1/4', sustain='1/2',
            release_s='1/4', gates=(EnvelopeGate('0/1', '3/4'),),
            **kwargs,
        )

    def test_exact_attack_decay_sustain_and_release_without_block_smoothing(self):
        source = self.envelope()
        expected = {
            '0/1': Fraction(0), '1/8': Fraction(1, 2),
            '1/4': Fraction(1), '3/8': Fraction(3, 4),
            '1/2': Fraction(1, 2), '5/8': Fraction(1, 2),
            '3/4': Fraction(1, 2), '7/8': Fraction(1, 4),
            '1/1': Fraction(0),
        }
        for t, level in expected.items():
            with self.subTest(time=t):
                self.assertEqual(source.value_at(t), level)
        route = source.compile_route('1/1', route_id='gate', depth=40.)
        self.assertIsInstance(route, ModulationRoute)
        self.assertEqual(route.interpolation, 'linear')
        self.assertEqual(route.initial, '0/1')
        self.assertEqual([(p.time_s, p.value) for p in route.points],
                         [('1/4', '1/1'), ('1/2', '1/2'),
                          ('3/4', '1/2'), ('1/1', '0/1')])
        spec = SonicSpec(clock=ClockSpec(rate=VirtualRate('100/1'),
                                        routes=(route,)))
        for t, level in expected.items():
            realized = Fraction(evaluate_instantaneous_rate(spec, t).realized_hz)
            self.assertEqual(realized, 100 + 40 * level)
        self.assertEqual(source, TriggeredEnvelopeSource.from_json(source.to_json()))
        self.assertEqual(spec, SonicSpec.from_json(spec.to_json()))
        self.assertNotEqual(source.sha256,
                            replace(source, sustain='3/4').sha256)
        # The NYQ-002 sampler must still refuse routed execution.
        with self.assertRaises(ContractError):
            ClockPlan(spec.clock, '1/1')

    def test_early_note_off_releases_actual_attack_value(self):
        source = TriggeredEnvelopeSource(
            origin_s='1/4', attack_s='1/2', decay_s='1/4',
            sustain='1/3', release_s='1/4',
            gates=(EnvelopeGate('1/4', '3/8'),),
        )
        self.assertEqual(source.value_at('1/4'), Fraction(0))
        self.assertEqual(source.value_at('5/16'), Fraction(1, 8))
        self.assertEqual(source.value_at('3/8'), Fraction(1, 4))
        self.assertEqual(source.value_at('1/2'), Fraction(1, 8))
        self.assertEqual(source.value_at('5/8'), Fraction(0))
        route = source.compile_route('5/8', route_id='early')
        # The saved source starts at 1/4. A standard route begins at
        # absolute time zero: without the explicit zero knot at 1/4 its
        # linear interpolation leaked modulation before the source existed.
        self.assertEqual([p.time_s for p in route.points],
                         ['1/4', '3/8', '5/8'])
        self.assertEqual([p.value for p in route.points],
                         ['0/1', '1/4', '0/1'])
        self.assertEqual(source.value_at('1/2'), Fraction(
            evaluate_instantaneous_rate(
                SonicSpec(clock=ClockSpec(rate=VirtualRate('1/1'),
                                          routes=(replace(route, depth=1.),))),
                '1/2').route_values[0]))

    def test_delayed_origin_never_leaks_pre_onset_control(self):
        source = TriggeredEnvelopeSource(
            origin_s='1/4', attack_s='1/2', decay_s='1/4',
            sustain='1/3', release_s='1/4',
            gates=(EnvelopeGate('1/4', '3/8'),),
        )
        route = source.compile_route('5/8', route_id='delayed', depth=4.)
        spec = SonicSpec(clock=ClockSpec(rate=VirtualRate('100/1'),
                                        routes=(route,)))
        for at, expected in (
                ('0/1', Fraction(100)), ('1/8', Fraction(100)),
                ('1/4', Fraction(100)), ('5/16', Fraction(201, 2)),
                ('3/8', Fraction(101)), ('1/2', Fraction(201, 2)),
                ('5/8', Fraction(100))):
            with self.subTest(at=at):
                self.assertEqual(
                    Fraction(evaluate_instantaneous_rate(spec, at).realized_hz),
                    expected)
        self.assertEqual(route.to_json(),
                         source.compile_route('5/8', route_id='delayed', depth=4.).to_json())

    def test_cancellation_during_or_just_before_point_publication_is_atomic(self):
        source = self.envelope()
        calls = [0]
        def during_first_point():
            calls[0] += 1
            return calls[0] == 2  # after gate discovery, before first point
        with self.assertRaises(ClockCancelled):
            source.compile_route('1/1', route_id='cancel-point',
                                 cancelled=during_first_point)
        self.assertEqual(calls[0], 2)

        # Empty gates also have a final publication checkpoint.
        empty = TriggeredEnvelopeSource()
        calls = [0]
        def after_empty_scan():
            calls[0] += 1
            return calls[0] == 2
        with self.assertRaises(ClockCancelled):
            empty.compile_route('1/1', route_id='empty', cancelled=after_empty_scan)
        self.assertEqual(calls[0], 2)
        self.assertEqual(source.compile_route('1/1', route_id='cancel-point'),
                         source.compile_route('1/1', route_id='cancel-point'))

    def test_multiple_gates_retrigger_only_after_complete_release(self):
        source = TriggeredEnvelopeSource(
            attack_s='1/8', decay_s='1/8', sustain='1/2',
            release_s='1/4',
            gates=(EnvelopeGate('0/1', '1/4'),
                   EnvelopeGate('1/2', '3/4')),
        )
        route = source.compile_route('1/1', route_id='two')
        self.assertEqual(source.value_at('1/2'), Fraction(0))
        self.assertEqual(source.value_at('5/8'), Fraction(1))
        self.assertEqual(source.value_at('7/8'), Fraction(1, 4))
        self.assertEqual(source.value_at('1/1'), Fraction(0))
        self.assertEqual(len(route.points),
                         len({p.time_s for p in route.points}))
        self.assertEqual(
            TriggeredEnvelopeSource.from_json(source.to_json()), source)
        with self.assertRaises(ContractError):
            replace(source, gates=(EnvelopeGate('0/1','1/4'),
                                   EnvelopeGate('3/8','3/4')))

    def test_control_route_affine_hz_phase_has_independent_integral_oracle(self):
        source = self.envelope()
        route = source.compile_route('1/1', route_id='phase', depth=4.)
        spec = SonicSpec(clock=ClockSpec(rate=VirtualRate('4/1'),
                                        routes=(route,)))
        events = compile_step_clock_events(spec, '1/1')
        self.assertGreaterEqual(len(events), 4)
        self.assertEqual(events[0].coordinate_s, Fraction(0))
        self.assertTrue(all(a.coordinate_s < b.coordinate_s
                            for a, b in zip(events, events[1:])))
        breaks = (Fraction(0), Fraction(1,4), Fraction(1,2),
                  Fraction(3,4), Fraction(1))
        def phase(t):
            total = Fraction(0)
            for a, b in zip(breaks, breaks[1:]):
                if t <= a:
                    break
                right = min(t, b)
                # A certified irrational event root can have a rational
                # enclosure denominator well beyond the saved-control bound.
                # The oracle interpolates independently between admitted
                # physical-time knots; it must not reserialize that root as
                # a user-authored control timestamp.
                f0 = 4 + 4 * source.value_at(q(a))
                fb = 4 + 4 * source.value_at(q(b))
                f1 = f0 + (fb - f0) * (right - a) / (b - a)
                total += (f0 + f1) * (right - a) / 2
                if right == t:
                    break
            return total
        for event in events:
            self.assertLessEqual(
                abs(phase(event.coordinate_s) - event.crossing),
                8 * event.coordinate_error_bound_s,
            )
        self.assertEqual(events,
                         compile_step_clock_events(spec, '1/1'))
        self.assertEqual(events[:len(compile_step_clock_events(spec, '1/2'))],
                         compile_step_clock_events(spec, '1/2'))

    def test_invalid_gates_extent_depth_and_snapshot_fail_closed(self):
        for on, off in (('-1/1', '1/2'), ('1/2','1/2'),
                        ('3/4','1/2'), ('0/1','3601/1')):
            with self.subTest(gate=(on, off)), self.assertRaises(ContractError):
                EnvelopeGate(on, off)
        for params in (
            {'attack_s': '0/1'}, {'decay_s': '0/1'},
            {'release_s': '0/1'}, {'sustain': '3/2'},
            {'gates': [EnvelopeGate('0/1','1/2')]},
            {'gates': (EnvelopeGate('0/1','3600/1'),)},
        ):
            with self.subTest(params=params), self.assertRaises(ContractError):
                TriggeredEnvelopeSource(**params)
        source = self.envelope()
        with self.assertRaises(ContractError):
            source.compile_route('7/8', route_id='short')
        with self.assertRaises(ContractError):
            source.compile_route('1/1', route_id='bad', depth=float('nan'))
        with self.assertRaises(ContractError):
            source.compile_route('1/1', route_id='bad', mapping='unsupported')
        with self.assertRaises(ContractError):
            source.value_at('-1/1')
        with self.assertRaises(ContractError):
            TriggeredEnvelopeSource.from_dict(
                {**source.to_dict(), 'unsanctioned_input': 'ignored'})
        self.assertEqual(source.compile_route('1/1',route_id='zero',depth=0.).depth, 0.)

    def test_many_note_gates_reject_oversized_route_and_cancel_atomically(self):
        gates = tuple(EnvelopeGate(q(Fraction(k,32)),
                                   q(Fraction(k,32) + Fraction(1,128)))
                      for k in range(60))
        source = TriggeredEnvelopeSource(
            attack_s='1/1024', decay_s='1/1024',
            release_s='1/128', gates=gates)
        with self.assertRaises(ContractError):
            source.compile_route('2/1', route_id='too-many')
        with self.assertRaises(ClockCancelled):
            source.compile_route('2/1', route_id='cancel', cancelled=lambda: True)
        with self.assertRaises(ContractError):
            source.compile_route('2/1', route_id='bad-callback', cancelled=0)


if __name__ == '__main__':
    unittest.main()
