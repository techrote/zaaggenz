"""NYQ-004 sample-rate bipolar upstream control: source and timing proofs."""
import hashlib
from fractions import Fraction
import unittest

import numpy as np

from zaaggenz_contracts import ContractError
from zaaggenz_contracts.nyquismic import ClockSpec, SonicSpec, VirtualRate
from zaaggenz_contracts.nyquismic_clock import ClockCancelled
from zaaggenz_contracts.nyquismic_controls import evaluate_instantaneous_rate
from zaaggenz_contracts.nyquismic_input_envelope import (
    UpstreamGraphEdge, UpstreamGraphSnapshot, UpstreamRmsPolicy,
    UpstreamSignedSamplePolicy, compile_upstream_signed_sample_route,
)


def signed_policy(audio, *, origin='0/1', channel=0, tail='zero_after_source',
                  reference='1/1'):
    raw = np.array(audio, dtype='<f4', order='C', copy=True)
    return UpstreamSignedSamplePolicy(
        source=UpstreamRmsPolicy(
            source_id='lowmid', source_sha256=hashlib.sha256(raw.tobytes()).hexdigest(),
            sample_rate_hz=8000, frames=len(raw), channel=channel,
            window_frames=1, origin_s=origin, reference_amplitude=reference,
        ), tail=tail,
    )


def compile_(audio, policy, **kwargs):
    return compile_upstream_signed_sample_route(
        audio, policy, consumer_id='air-clock', upstream_ids=('lowmid',),
        route_id='sample-signed', **kwargs,
    )


class UpstreamSignedAudioRateTests(unittest.TestCase):
    def test_signed_per_sample_steps_are_physical_time_not_rms(self):
        samples = np.array([-.25, .5, -.75, 0.], dtype='<f4')
        p = signed_policy(samples)
        result = compile_(samples, p, depth=200.)
        self.assertEqual(result.route.initial, '-1/4')
        self.assertEqual([(x.time_s, x.value) for x in result.route.points], [
            ('1/8000', '1/2'), ('1/4000', '-3/4'),
            ('3/8000', '0/1'), ('1/2000', '0/1'),
        ])
        spec = SonicSpec(clock=ClockSpec(
            rate=VirtualRate('1000/1'), routes=(result.route,)))
        for when, expected in (
            ('0/1', 950), ('1/8000', 1100), ('1/4000', 850),
            ('1/2000', 1000),
        ):
            with self.subTest(when=when):
                self.assertEqual(Fraction(evaluate_instantaneous_rate(
                    spec, when).realized_hz), expected)
        self.assertEqual(UpstreamSignedSamplePolicy.from_json(p.to_json()), p)
        self.assertEqual(compile_(samples, p, depth=200.).route.to_json(),
                         result.route.to_json())
        self.assertEqual(result.diagnostics['source_sha256'], p.source.source_sha256)
        self.assertFalse(result.diagnostics['product_graph_registered'])

    def test_delayed_origin_stereo_and_explicit_tail(self):
        samples = np.array([[.0, -.5], [.0, .25], [.0, 0.]], dtype='<f4')
        p = signed_policy(samples, origin='1/100', channel=1)
        result = compile_(samples, p, depth=200.)
        self.assertEqual(result.route.initial, '0/1')
        self.assertEqual([(x.time_s, x.value) for x in result.route.points], [
            ('1/100', '-1/2'), ('81/8000', '1/4'),
            ('41/4000', '0/1'), ('83/8000', '0/1'),
        ])
        spec = SonicSpec(clock=ClockSpec(
            rate=VirtualRate('1000/1'), routes=(result.route,)))
        for t, rate in (('79/8000', 1000), ('1/100', 900),
                        ('81/8000', 1050), ('83/8000', 1000)):
            self.assertEqual(Fraction(evaluate_instantaneous_rate(
                spec, t).realized_hz), rate)
        hold = compile_(samples, signed_policy(
            samples, origin='1/100', channel=1, tail='hold_last'))
        self.assertEqual(len(hold.route.points), 3)
        self.assertEqual(hold.diagnostics['tail'], 'hold_last')

    def test_exact_point_budget_empty_and_strict_failures(self):
        full = np.full(256, .25, dtype='<f4')
        self.assertEqual(len(compile_(full, signed_policy(full)).route.points), 256)
        with self.assertRaisesRegex(ContractError, '256 exact-time points'):
            compile_(full, signed_policy(full, origin='1/10'))
        self.assertEqual(compile_(np.zeros(0, dtype='<f4'),
                         signed_policy(np.zeros(0, dtype='<f4'))).route.initial,
                         '0/1')
        for kwargs in ({'tail': 'surprise'}, {'source': UpstreamRmsPolicy()}):
            with self.assertRaises(ContractError):
                UpstreamSignedSamplePolicy(**kwargs)
        with self.assertRaises(ContractError):
            compile_(full.astype(np.float64), signed_policy(full))
        with self.assertRaises(ContractError):
            compile_(full, signed_policy(full), cancelled=lambda: True)
        with self.assertRaises(ContractError):
            compile_(full * 2, signed_policy(full))
        # A source whose admitted reference amplitude is too low must refuse,
        # not clip/normalize a signed rate control.
        with self.assertRaises(ContractError):
            compile_(full, signed_policy(full, reference='1/10'))
        with self.assertRaises(ClockCancelled):
            compile_(full, signed_policy(full),
                     cancelled=lambda: True)

    def test_bound_graph_snapshot_and_mutating_source(self):
        samples = np.array([.5, -.5, .75, 0], dtype='<f4')
        p = signed_policy(samples)
        graph = UpstreamGraphSnapshot(
            nodes=('air-clock', 'lowmid'),
            edges=(UpstreamGraphEdge('lowmid', 'air-clock'),))
        got = compile_(samples, p, graph_snapshot=graph,
                       expected_graph_sha256=graph.sha256)
        self.assertEqual(got.diagnostics['graph_topology'], 'snapshot-dag-verified')
        before = samples.copy()
        with self.assertRaises(ContractError):
            compile_(samples, p, graph_snapshot=graph,
                     expected_graph_sha256='0'*64)
        with self.assertRaises(ContractError):
            compile_(samples, p, upstream_ids=('air-clock',))
        with self.assertRaises(ContractError):
            compile_(samples + np.float32(.125), p)
        np.testing.assert_array_equal(samples, before)


if __name__ == '__main__':
    unittest.main()
