"""NYQ-004: different upstream-band PCM drives real controlled virtual-clock PCM.

This is a synthetic graph-snapshot and native-grid proof, not registered
Compose graph-routing, delivery-rate conversion or owner listening evidence.
"""
import hashlib
import unittest

import numpy as np

from zaaggenz_contracts import ContractError
from zaaggenz_contracts.nyquismic import ClockSpec, SonicSpec, VirtualRate
from zaaggenz_contracts.nyquismic_controls import (
    compile_step_clock_events, evaluate_instantaneous_rate,
)
from zaaggenz_contracts.nyquismic_input_envelope import (
    UpstreamGraphEdge, UpstreamGraphSnapshot, UpstreamRmsPolicy,
    compile_upstream_rms_route,
)
from zaaggenz_dsp.nyquismic import FrozenInput
from zaaggenz_dsp.nyquismic_controlled_audio_proof import render_controlled_audio_proof


class UpstreamGraphPcmTests(unittest.TestCase):
    def test_distinct_upstream_band_changes_exact_clock_and_output_pcm(self):
        rate = 8000
        # Different immutable signals: the lowmid control is *not* read from
        # the target air-band output or the current Nyquismic node.
        lowmid = np.concatenate((
            np.full(rate // 2, .125, dtype='<f4'),
            np.full(rate // 2, .5, dtype='<f4'),
        ))
        n = np.arange(rate, dtype=np.int64)
        air_pcm = np.asarray(((n * 37) % 257 - 128) / 1024.0, dtype='<f4')
        self.assertNotEqual(hashlib.sha256(lowmid.tobytes()).hexdigest(),
                            hashlib.sha256(air_pcm.tobytes()).hexdigest())
        graph = UpstreamGraphSnapshot(
            nodes=('band-air-clock', 'band-lowmid-tap', 'band-router'),
            edges=(UpstreamGraphEdge('band-lowmid-tap', 'band-router'),
                   UpstreamGraphEdge('band-router', 'band-air-clock')),
        )
        policy = UpstreamRmsPolicy(
            source_id='band-lowmid-tap',
            source_sha256=hashlib.sha256(lowmid.tobytes()).hexdigest(),
            sample_rate_hz=rate, frames=rate, channel=0,
            window_frames=rate // 8, reference_amplitude='1/1',
        )
        result = compile_upstream_rms_route(
            lowmid, policy, consumer_id='band-air-clock',
            upstream_ids=('band-lowmid-tap', 'band-router'),
            route_id='lowmid-amplitude-to-air-clock', depth=400.0,
            graph_snapshot=graph, expected_graph_sha256=graph.sha256,
        )
        self.assertEqual(result.diagnostics['graph_snapshot_sha256'], graph.sha256)
        self.assertEqual(result.diagnostics['graph_topology'], 'snapshot-dag-verified')
        self.assertEqual(result.diagnostics['windows'], 8)
        self.assertEqual(result.diagnostics['lookahead_s'], '1/8')
        clock = ClockSpec(rate=VirtualRate('360/1'), routes=(result.route,))
        spec = SonicSpec(instance_id='air-controlled', band='air', clock=clock)
        steady = SonicSpec(instance_id='air-controlled', band='air',
                           clock=ClockSpec(rate=VirtualRate('360/1')))
        self.assertEqual(evaluate_instantaneous_rate(spec, '0/1').realized_hz,
                         '410/1')
        self.assertEqual(evaluate_instantaneous_rate(spec, '1/2').realized_hz,
                         '560/1')
        events = compile_step_clock_events(spec, '1/1')
        self.assertGreater(len(events), 400)
        self.assertTrue(all(a.coordinate_s < b.coordinate_s
                            for a, b in zip(events, events[1:])))
        frozen = FrozenInput.from_pcm(air_pcm, rate)
        controlled = render_controlled_audio_proof(frozen, spec)
        base = render_controlled_audio_proof(frozen, steady)
        again = render_controlled_audio_proof(frozen, spec)
        region = render_controlled_audio_proof(frozen, spec,
                                               start_frame=rate//2)
        self.assertNotEqual(controlled.diagnostics['event_ledger_sha256'],
                            base.diagnostics['event_ledger_sha256'])
        self.assertNotEqual(controlled.diagnostics['pcm_sha256'],
                            base.diagnostics['pcm_sha256'])
        self.assertGreater(float(np.max(np.abs(controlled.audio - base.audio))),
                           0.001)
        np.testing.assert_array_equal(controlled.audio, again.audio)
        np.testing.assert_array_equal(controlled.audio[rate//2:], region.audio)
        self.assertFalse(controlled.diagnostics['product_rack_export_qualified'])
        # Missing/stale source and graph identities must fail before a route
        # or audio result can be consumed.
        with self.assertRaises(ContractError):
            compile_upstream_rms_route(
                air_pcm, policy, consumer_id='band-air-clock',
                upstream_ids=('band-lowmid-tap', 'band-router'),
                route_id='lowmid-amplitude-to-air-clock', depth=400.,
                graph_snapshot=graph, expected_graph_sha256=graph.sha256)
        with self.assertRaises(ContractError):
            compile_upstream_rms_route(
                lowmid, policy, consumer_id='band-air-clock',
                upstream_ids=('band-lowmid-tap', 'band-router'),
                route_id='lowmid-amplitude-to-air-clock', depth=400.,
                graph_snapshot=graph, expected_graph_sha256='0'*64)


if __name__ == '__main__':
    unittest.main()
