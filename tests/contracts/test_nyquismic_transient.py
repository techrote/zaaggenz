"""NYQ-004 immutable upstream positive RMS-rise transient controls."""
import hashlib
from fractions import Fraction
import unittest

import numpy as np

from zaaggenz_contracts import ContractError
from zaaggenz_contracts.nyquismic import ClockSpec, SonicSpec, VirtualRate
from zaaggenz_contracts.nyquismic_clock import ClockCancelled
from zaaggenz_contracts.nyquismic_controls import evaluate_instantaneous_rate
from zaaggenz_contracts.nyquismic_input_envelope import UpstreamRmsPolicy
from zaaggenz_contracts.nyquismic_transient import (
    METHOD, UpstreamTransientPolicy, compile_upstream_transient_route,
)


def policy(audio, **kwargs):
    raw = np.ascontiguousarray(audio, dtype='<f4')
    source = UpstreamRmsPolicy(
        source_id='body', source_sha256=hashlib.sha256(raw.tobytes()).hexdigest(),
        frames=len(audio), sample_rate_hz=8000, channel=kwargs.pop('channel', 0),
        window_frames=kwargs.pop('window_frames', 4),
        origin_s=kwargs.pop('origin_s', '0/1'),
    )
    return UpstreamTransientPolicy(source=source, **kwargs)


def compile_(audio, chosen=None, **kwargs):
    return compile_upstream_transient_route(
        audio, chosen or policy(audio), consumer_id='sculpt',
        upstream_ids=('body',), route_id='onset', **kwargs,
    )


class UpstreamTransientTests(unittest.TestCase):
    def test_exact_onset_rises_threshold_time_and_clock_inspection(self):
        samples = np.array([
            0, 0, 0, 0,
            .5, -.5, .5, -.5,
            .25, -.25, .25, -.25,
            .75, -.75, .75, -.75,
        ], dtype='<f4')
        saved = policy(samples, minimum_rise='1/10')
        result = compile_(samples, saved, depth=200.)
        self.assertEqual(result.route.initial, '0/1')
        self.assertEqual(tuple(p.time_s for p in result.route.points),
                         ('1/2000', '1/1000', '3/2000'))
        self.assertEqual(tuple(p.value for p in result.route.points),
                         ('2/5', '0/1', '2/5'))
        self.assertEqual(result.diagnostics['method'], METHOD)
        self.assertEqual(result.diagnostics['lookahead_s'], '1/2000')
        self.assertEqual(result.diagnostics['policy_sha256'], saved.sha256)
        self.assertEqual(UpstreamTransientPolicy.from_json(saved.to_json()), saved)
        self.assertEqual(result.route.to_json(),
                         compile_(samples, saved, depth=200.).route.to_json())
        clock = SonicSpec(clock=ClockSpec(
            rate=VirtualRate('1000/1'), routes=(result.route,),
        ))
        self.assertEqual(evaluate_instantaneous_rate(clock, '1/2000').realized_hz,
                         '1080/1')
        self.assertEqual(evaluate_instantaneous_rate(clock, '1/1000').realized_hz,
                         '1000/1')

    def test_non_coprime_rms_differences_fit_frozen_rational_contract(self):
        # Real f32 RMS windows can quantize to unrelated <=1e6
        # denominators; their exact difference may require ~1e12. Preserve
        # the physical rise while serializing to the frozen point budget.
        samples = np.array([.111111, -.111111, .112345, -.112345], dtype='<f4')
        result = compile_(samples, policy(samples, window_frames=2), depth=120.)
        a, b = float(abs(samples[0])), float(abs(samples[2]))
        exact_rise = (Fraction.from_float(b).limit_denominator(1_000_000)
                      - Fraction.from_float(a).limit_denominator(1_000_000))
        self.assertGreater(exact_rise.denominator, 1_000_000_000)
        expected = exact_rise.limit_denominator(1_000_000)
        self.assertEqual(Fraction(result.route.points[0].value), expected)
        self.assertGreater(expected, 0)
        self.assertLessEqual(expected.denominator, 1_000_000)
        self.assertEqual(result.diagnostics['rise_quantization_denominator'], 1_000_000)
        self.assertEqual(result.route.to_json(),
                         compile_(samples, policy(samples, window_frames=2),
                                  depth=120.).route.to_json())

    def test_first_window_is_rise_from_silence_and_no_hidden_level_hold(self):
        samples = np.array([.25, -.25, .25, -.25,
                            .25, -.25, .25, -.25,
                            0, 0, 0, 0], dtype='<f4')
        result = compile_(samples)
        self.assertEqual(result.route.initial, '1/4')
        self.assertEqual(tuple(p.value for p in result.route.points),
                         ('0/1', '0/1'))

    def test_stereo_empty_and_silent_source(self):
        stereo = np.array([[0., .5], [0., -.5],
                           [.25, .75], [-.25, -.75]], dtype='<f4')
        result = compile_(stereo, policy(stereo, channel=1, window_frames=2))
        self.assertEqual((result.route.initial, result.route.points[0].value),
                         ('1/2', '1/4'))
        for audio in (np.zeros(0, dtype='<f4'), np.zeros(8, dtype='<f4')):
            result = compile_(audio)
            self.assertEqual(result.route.initial, '0/1')
            self.assertTrue(all(p.value == '0/1' for p in result.route.points))

    def test_source_hash_topology_origin_and_policy_fail_closed(self):
        samples = np.array([0., .5, 0., -.5], dtype='<f4')
        p = policy(samples)
        self.assertEqual(policy(samples, origin_s='1/8').source.origin_s, '1/8')
        self.assertEqual(
            UpstreamTransientPolicy(source=p.source, minimum_rise='1/1').minimum_rise,
            '1/1')
        with self.assertRaises(ContractError):
            UpstreamTransientPolicy(source=p.source, minimum_rise='-1/10')
        with self.assertRaises(ContractError):
            UpstreamTransientPolicy.from_dict({**p.to_dict(), 'unknown': 1})
        with self.assertRaises(ContractError):
            compile_(samples + .1, p)
        with self.assertRaises(ContractError):
            compile_upstream_transient_route(
                samples, p, consumer_id='body', upstream_ids=('body',),
                route_id='onset')

    def test_delayed_upstream_transients_neutral_before_origin_and_bounded(self):
        samples = np.array([.5, -.5, .5, -.5,
                            .75, -.75, .75, -.75,
                            .25, -.25, .25, -.25], dtype='<f4')
        chosen = policy(samples, origin_s='1/10', minimum_rise='1/10')
        result = compile_(samples, chosen, depth=200.)
        self.assertEqual(result.route.initial, '0/1')
        self.assertEqual(tuple((p.time_s, p.value) for p in result.route.points),
                         (('1/10', '2/5'), ('201/2000', '3/20'),
                          ('101/1000', '0/1')))
        self.assertEqual(result.diagnostics['source_sha256'], chosen.source.source_sha256)
        self.assertEqual(UpstreamTransientPolicy.from_json(chosen.to_json()), chosen)
        self.assertEqual(result.route.to_json(),
                         compile_(samples, chosen, depth=200.).route.to_json())
        clock = SonicSpec(clock=ClockSpec(
            rate=VirtualRate('1000/1'), routes=(result.route,)))
        for when, hz in (('0/1', '1000/1'), ('199/2000', '1000/1'),
                         ('1/10', '1080/1'), ('201/2000', '1030/1'),
                         ('101/1000', '1000/1')):
            with self.subTest(when=when):
                self.assertEqual(evaluate_instantaneous_rate(clock, when).realized_hz,
                                 hz)
        # Delayed first-window onset consumes a saved Point, not a hidden
        # unbounded extra event. The underlying RMS budget is still binding.
        near_limit = np.full(256, .25, dtype='<f4')
        self.assertEqual(len(compile_(near_limit, policy(
            near_limit, window_frames=1, origin_s='1/10')).route.points), 256)
        too_long = np.full(257, .25, dtype='<f4')
        with self.assertRaises(ContractError):
            compile_(too_long, policy(too_long, window_frames=1, origin_s='1/10'))
        empty = np.zeros(0, dtype='<f4')
        self.assertEqual(compile_(empty, policy(empty, origin_s='1/10')).route.initial,
                         '0/1')

    def test_bound_cancellation_and_source_immutability(self):
        samples = np.ones(258, dtype='<f4') * .25
        with self.assertRaises(ContractError):
            compile_(samples, policy(samples, window_frames=1))
        samples = np.ones(20, dtype='<f4') * .25
        original = samples.copy()
        counts = [0]
        def cancel_late():
            counts[0] += 1
            return counts[0] >= 3
        with self.assertRaises(ClockCancelled):
            compile_(samples, cancelled=cancel_late)
        np.testing.assert_array_equal(samples, original)
        with self.assertRaises(ClockCancelled):
            compile_(samples, cancelled=lambda: True)


if __name__ == '__main__':
    unittest.main()
