"""NYQ-004 true spectral input features control exact physical clock and PCM."""
from dataclasses import replace
from fractions import Fraction
from hashlib import sha256
import unittest

import numpy as np

from zaaggenz_contracts import ContractError
from zaaggenz_contracts.nyquismic import ClockSpec, SonicSpec, VirtualRate
from zaaggenz_contracts.nyquismic_clock import ClockCancelled
from zaaggenz_contracts.nyquismic_controls import (
    compile_step_clock_events, evaluate_instantaneous_rate,
)
from zaaggenz_contracts.nyquismic_input_envelope import (
    UpstreamGraphEdge, UpstreamGraphSnapshot, UpstreamRmsPolicy,
)
from zaaggenz_contracts.nyquismic_spectral_feature import (
    METHOD, UpstreamCentroidPolicy, compile_upstream_centroid_route,
)
from zaaggenz_dsp.nyquismic import FrozenInput
from zaaggenz_dsp.nyquismic_controlled_audio_proof import render_controlled_audio_proof


RATE = 8000
WIDTH = 256
GRAPH = UpstreamGraphSnapshot(
    nodes=('air-clock', 'lowmid'),
    edges=(UpstreamGraphEdge('lowmid', 'air-clock'),),
)


def tones():
    t = np.arange(WIDTH, dtype=np.float64) / RATE
    return np.concatenate((
        (.5 * np.sin(2 * np.pi * 500 * t)).astype('<f4'),
        (.5 * np.sin(2 * np.pi * 1500 * t)).astype('<f4'),
    ))


def policy(samples, **kwargs):
    source = UpstreamRmsPolicy(
        source_id='lowmid', source_sha256=sha256(samples.tobytes()).hexdigest(),
        sample_rate_hz=RATE, frames=len(samples), channel=kwargs.pop('channel', 0),
        window_frames=WIDTH, origin_s=kwargs.pop('origin_s', '0/1'),
    )
    return UpstreamCentroidPolicy(source=source, floor_hz='0/1',
                                  ceiling_hz='2000/1', **kwargs)


def compile_(samples, p=None, **kwargs):
    options = {
        'consumer_id': 'air-clock', 'upstream_ids': ('lowmid',),
        'route_id': 'lowmid-centroid', 'depth': 400.0,
        'graph_snapshot': GRAPH, 'expected_graph_sha256': GRAPH.sha256,
    }
    options.update(kwargs)
    return compile_upstream_centroid_route(samples, p or policy(samples), **options)


class CentroidSourceTests(unittest.TestCase):
    def test_real_tonal_pcm_controls_physical_clock_and_native_pcm(self):
        input_pcm = tones()
        p = policy(input_pcm)
        result = compile_(input_pcm, p)
        self.assertEqual(result.diagnostics['method'], METHOD)
        self.assertEqual(result.diagnostics['window_frames'], WIDTH)
        self.assertEqual(result.diagnostics['lookahead_s'], '4/125')
        self.assertEqual(result.diagnostics['graph_snapshot_sha256'], GRAPH.sha256)
        self.assertEqual(result.diagnostics['low_confidence_windows'], [])
        self.assertEqual(len(result.route.points), 2)
        self.assertEqual(result.route.points[-1].time_s, '8/125')
        self.assertEqual(result.route.points[-1].value, '0/1')
        levels = [Fraction(result.route.initial),
                  Fraction(result.route.points[0].value)]
        self.assertAlmostEqual(float(levels[0]), .25, delta=.025)
        self.assertAlmostEqual(float(levels[1]), .75, delta=.025)
        self.assertEqual(UpstreamCentroidPolicy.from_json(p.to_json()), p)
        self.assertEqual(result.route.to_json(), compile_(input_pcm, p).route.to_json())
        spec = SonicSpec(instance_id='air-clock', clock=ClockSpec(
            rate=VirtualRate('800/1'), routes=(result.route,)))
        static = SonicSpec(instance_id='air-clock', clock=ClockSpec(
            rate=VirtualRate('800/1')))
        for instant, expected in (('0/1', 900), ('4/125', 1100),
                                  ('8/125', 800)):
            self.assertAlmostEqual(float(Fraction(
                evaluate_instantaneous_rate(spec, instant).realized_hz)),
                expected, delta=12)
        events = compile_step_clock_events(spec, '8/125')
        self.assertTrue(all(a.coordinate_s < b.coordinate_s
                            for a, b in zip(events, events[1:])))
        frames = np.arange(len(input_pcm), dtype=np.int64)
        target = np.asarray(((frames * 37) % 257 - 128) / 512., dtype='<f4')
        frozen = FrozenInput.from_pcm(target, RATE)
        actual = render_controlled_audio_proof(frozen, spec)
        baseline = render_controlled_audio_proof(frozen, static)
        replay = render_controlled_audio_proof(frozen, spec)
        region = render_controlled_audio_proof(
            frozen, spec, start_frame=WIDTH)
        self.assertNotEqual(actual.diagnostics['event_ledger_sha256'],
                            baseline.diagnostics['event_ledger_sha256'])
        self.assertGreater(float(np.max(np.abs(
            actual.audio - baseline.audio))), .001)
        np.testing.assert_array_equal(actual.audio, replay.audio)
        np.testing.assert_array_equal(actual.audio[WIDTH:], region.audio)
        self.assertFalse(actual.diagnostics['product_rack_export_qualified'])

    def test_silence_dc_confidence_and_explicit_fallback(self):
        input_pcm = np.concatenate((
            np.full(WIDTH, .5, dtype='<f4'), tones()[:WIDTH],
        ))
        with self.assertRaisesRegex(ContractError, 'low-confidence'):
            compile_(input_pcm)
        chosen = policy(input_pcm, low_confidence='neutral_zero')
        result = compile_(input_pcm, chosen)
        self.assertEqual(result.route.initial, '0/1')
        self.assertEqual(result.diagnostics['low_confidence_windows'], [0])
        self.assertGreater(Fraction(result.route.points[0].value), 0)
        self.assertEqual(result.diagnostics['dc_policy'],
                         'subtract-window-mean-before-Hann')
        self.assertEqual(result.route.to_json(),
                         compile_(input_pcm, chosen).route.to_json())
        with self.assertRaises(ContractError):
            compile_(np.zeros(0, dtype='<f4'))

    def test_delayed_source_stereo_and_source_provenance(self):
        mono = tones()
        stereo = np.column_stack((np.zeros_like(mono), mono)).astype('<f4')
        p = policy(stereo, channel=1, origin_s='1/10')
        result = compile_(stereo, p)
        self.assertEqual(result.route.initial, '0/1')
        self.assertEqual(result.route.points[0].time_s, '1/10')
        self.assertEqual(len(result.route.points), 3)
        self.assertEqual(result.route.to_json(), compile_(stereo, p).route.to_json())
        with self.assertRaises(ContractError):
            compile_(stereo, policy(stereo, channel=0))
        with self.assertRaises(ContractError):
            compile_(mono, p)
        with self.assertRaises(ContractError):
            compile_(mono, policy(mono),
                     expected_graph_sha256='0'*64)

    def test_budgets_stale_topology_and_cancel_fail_closed(self):
        src = tones()
        with self.assertRaises(ContractError):
            compile_(src[:-1])
        with self.assertRaises(ContractError):
            compile_(src + np.float32(.01), policy(src))
        with self.assertRaises(ContractError):
            UpstreamCentroidPolicy(source=policy(src).source,
                                   minimum_ac_rms='2/1')
        with self.assertRaises(ContractError):
            UpstreamCentroidPolicy(source=policy(src).source,
                                   ceiling_hz='9000/1')
        with self.assertRaises(ContractError):
            UpstreamCentroidPolicy(source=policy(src).source,
                                   low_confidence='silent_clamp')
        with self.assertRaises(ContractError):
            compile_upstream_centroid_route(
                src, policy(src), consumer_id='lowmid',
                upstream_ids=('air-clock',), route_id='invalid',
                graph_snapshot=GRAPH, expected_graph_sha256=GRAPH.sha256)
        with self.assertRaises(ContractError):
            compile_upstream_centroid_route(
                src, policy(src), consumer_id='air-clock',
                upstream_ids=('lowmid',), route_id='invalid',
                graph_snapshot=None, expected_graph_sha256=None)
        with self.assertRaises(ClockCancelled):
            compile_(src, cancelled=lambda: True)
        too_many = np.tile(src[:WIDTH], 257)
        with self.assertRaises(ContractError):
            compile_(too_many, policy(too_many))


if __name__ == '__main__':
    unittest.main()
