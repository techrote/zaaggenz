"""NYQ-004 immutable upstream PCM envelope adapter regression tests."""
import hashlib
import unittest
from fractions import Fraction

import numpy as np

from zaaggenz_contracts import ContractError
from zaaggenz_contracts.nyquismic import SonicSpec, ClockSpec, VirtualRate
from zaaggenz_contracts.nyquismic_clock import ClockCancelled
from zaaggenz_contracts.nyquismic_controls import evaluate_instantaneous_rate
from zaaggenz_contracts.nyquismic_input_envelope import (
    UpstreamRmsPolicy, compile_upstream_rms_route,
)


def make(signal, *, window=4, channel=0, reference='1/1', **kwargs):
    raw = np.ascontiguousarray(signal, dtype='<f4')
    return UpstreamRmsPolicy(
        source_id='band_a',
        source_sha256=hashlib.sha256(raw.tobytes()).hexdigest(),
        frames=signal.shape[0], sample_rate_hz=8000,
        channel=channel, window_frames=window,
        reference_amplitude=reference, **kwargs,
    )


def compile_(signal, policy=None, **kwargs):
    return compile_upstream_rms_route(
        signal, policy or make(signal), consumer_id='band_b',
        upstream_ids=('band_a',), route_id='rms', **kwargs,
    )


class InputEnvelopeTests(unittest.TestCase):
    def test_exact_window_levels_right_continuity_provenance_and_rate(self):
        audio = np.array([0, 0, 0, 0, .5, -.5, .5, -.5,
                          .25, -.25, .25, -.25], dtype='<f4')
        policy = make(audio)
        result = compile_(audio, policy, depth=200.)
        self.assertEqual(result.route.initial, '0/1')
        self.assertEqual(tuple(p.value for p in result.route.points),
                         ('1/2', '1/4'))
        self.assertEqual(tuple(p.time_s for p in result.route.points),
                         ('1/2000', '1/1000'))
        self.assertEqual(result.diagnostics['lookahead_s'], '1/2000')
        self.assertEqual(UpstreamRmsPolicy.from_json(policy.to_json()), policy)
        self.assertEqual(result.diagnostics['source_sha256'], policy.source_sha256)
        clock = ClockSpec(rate=VirtualRate(value='1000/1'),
                          routes=(result.route,))
        spec = SonicSpec(clock=clock)
        self.assertEqual(evaluate_instantaneous_rate(spec, '0/1').realized_hz, '1000/1')
        self.assertEqual(evaluate_instantaneous_rate(spec, '1/2000').realized_hz, '1100/1')
        self.assertEqual(evaluate_instantaneous_rate(spec, '1/1000').realized_hz, '1050/1')
        self.assertEqual(result.route.to_json(),
                         compile_(audio, policy, depth=200.).route.to_json())

    def test_stereo_channel_selection_and_partial_terminal_window(self):
        stereo = np.array([[0., .5], [0., -.5], [.25, .25],
                           [-.25, -.25], [.5, 0]], dtype='<f4')
        p = make(stereo, window=2, channel=1)
        result = compile_(stereo, p)
        self.assertEqual(result.route.initial, '1/2')
        self.assertEqual(tuple(x.value for x in result.route.points),
                         ('1/4', '0/1'))
        self.assertEqual(result.diagnostics['windows'], 3)
        self.assertNotEqual(result.route.initial,
                            compile_(stereo, make(stereo, window=2, channel=0)).route.initial)

    def test_silent_and_empty_inputs_have_neutral_control(self):
        for audio in (np.zeros(0, dtype='<f4'), np.zeros((5, 2), dtype='<f4')):
            p = make(audio, channel=0)
            result = compile_(audio, p)
            self.assertEqual(result.route.initial, '0/1')
            self.assertTrue(all(x.value == '0/1' for x in result.route.points))

    def test_source_hash_reference_and_upstream_gate_reject_invalid(self):
        audio = np.array([0., .25, .5, .75], dtype='<f4')
        policy = make(audio)
        cases = [
            (audio.copy(), policy, 'band_a', ('band_a',)),
            (audio.copy(), policy, 'band_b', ('band_b',)),
            (audio.copy(), policy, 'band_b', ('band_a', 'band_a')),
            (audio.copy(), policy, 'band_b', ()),
            (audio.astype('<f8'), policy, 'band_b', ('band_a',)),
            (np.array([0., .25, .6, .75], dtype='<f4'), policy, 'band_b', ('band_a',)),
            (np.full(4, float('nan'), dtype='<f4'), make(np.zeros(4, dtype='<f4')),
             'band_b', ('band_a',)),
        ]
        for source, p, consumer, ancestors in cases:
            with self.subTest(consumer=consumer, ancestors=ancestors), self.assertRaises(ContractError):
                compile_upstream_rms_route(
                    source, p, consumer_id=consumer, upstream_ids=ancestors,
                    route_id='rms')
        with self.assertRaises(ContractError):
            compile_(audio, make(audio, reference='1/10'))
        with self.assertRaises(ContractError):
            UpstreamRmsPolicy(source_id='Invalid', source_sha256=policy.source_sha256)
        with self.assertRaises(ContractError):
            UpstreamRmsPolicy.from_dict({**policy.to_dict(), 'other': 'x'})

    def test_windows_bound_and_cancellation_preserve_atomicity(self):
        signal = np.zeros(257, dtype='<f4')
        with self.assertRaises(ContractError):
            compile_(signal, make(signal, window=1))
        signal = np.ones(20, dtype='<f4') * .25
        checks = [0]
        def cancel_after_one_window():
            checks[0] += 1
            return checks[0] >= 3
        with self.assertRaises(ClockCancelled):
            compile_(signal, make(signal, window=4), cancelled=cancel_after_one_window)
        self.assertTrue(checks[0] >= 3)
        with self.assertRaises(ClockCancelled):
            compile_(signal, make(signal), cancelled=lambda: True)


if __name__ == '__main__':
    unittest.main()
