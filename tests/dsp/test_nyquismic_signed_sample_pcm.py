"""NYQ-004 signed cross-band audio-rate modulation drives native-grid PCM."""
import hashlib
from fractions import Fraction
import unittest

import numpy as np

from zaaggenz_contracts import ContractError
from zaaggenz_contracts.nyquismic import ClockSpec, SonicSpec, VirtualRate
from zaaggenz_contracts.nyquismic_controls import (
    compile_step_clock_events, evaluate_instantaneous_rate,
)
from zaaggenz_contracts.nyquismic_input_envelope import (
    UpstreamGraphEdge, UpstreamGraphSnapshot, UpstreamRmsPolicy,
    UpstreamSignedSamplePolicy, compile_upstream_signed_sample_route,
)
from zaaggenz_dsp.nyquismic import FrozenInput
from zaaggenz_dsp.nyquismic_controlled_audio_proof import render_controlled_audio_proof


class SignedAudioRatePcmTests(unittest.TestCase):
    def test_bipolar_upstream_pcm_changes_clock_and_target_pcm_without_preorigin_leak(self):
        rate = 8000
        lowmid = np.concatenate((
            np.full(32, .5, dtype='<f4'), np.full(32, -.5, dtype='<f4'),
            np.full(32, .75, dtype='<f4'), np.zeros(32, dtype='<f4'),
        ))
        n = np.arange(256)
        target = np.asarray(((n * 37) % 257 - 128) / 512., dtype='<f4')
        graph = UpstreamGraphSnapshot(
            nodes=('air-clock', 'lowmid'),
            edges=(UpstreamGraphEdge('lowmid', 'air-clock'),))
        p = UpstreamSignedSamplePolicy(source=UpstreamRmsPolicy(
            source_id='lowmid', source_sha256=hashlib.sha256(lowmid.tobytes()).hexdigest(),
            sample_rate_hz=rate, frames=len(lowmid), channel=0,
            window_frames=1, origin_s='1/100', reference_amplitude='1/1',
        ))
        compiled = compile_upstream_signed_sample_route(
            lowmid, p, consumer_id='air-clock', upstream_ids=('lowmid',),
            route_id='signed-bipolar', depth=160.,
            graph_snapshot=graph, expected_graph_sha256=graph.sha256)
        spec = SonicSpec(instance_id='air-controlled',
            clock=ClockSpec(rate=VirtualRate('800/1'), routes=(compiled.route,)))
        static = SonicSpec(instance_id='air-controlled',
            clock=ClockSpec(rate=VirtualRate('800/1')))
        for when, hz in (('0/1', 800), ('1/100', 880),
                         ('7/500', 720), ('9/500', 920),
                         ('13/500', 800)):
            self.assertEqual(Fraction(evaluate_instantaneous_rate(
                spec, when).realized_hz), hz)
        events = compile_step_clock_events(spec, '4/125')
        self.assertTrue(all(a.coordinate_s < b.coordinate_s
                            for a, b in zip(events, events[1:])))
        frozen = FrozenInput.from_pcm(target, rate)
        a = render_controlled_audio_proof(frozen, spec)
        b = render_controlled_audio_proof(frozen, static)
        replay = render_controlled_audio_proof(frozen, spec)
        region = render_controlled_audio_proof(frozen, spec, start_frame=80)
        np.testing.assert_array_equal(a.audio[:80], b.audio[:80])
        self.assertGreater(float(np.max(np.abs(a.audio[80:] - b.audio[80:]))), .01)
        self.assertNotEqual(a.diagnostics['event_ledger_sha256'],
                            b.diagnostics['event_ledger_sha256'])
        self.assertNotEqual(a.diagnostics['pcm_sha256'],
                            b.diagnostics['pcm_sha256'])
        np.testing.assert_array_equal(a.audio, replay.audio)
        np.testing.assert_array_equal(a.audio[80:], region.audio)
        self.assertFalse(a.diagnostics['product_rack_export_qualified'])
        with self.assertRaises(ContractError):
            compile_upstream_signed_sample_route(
                lowmid, p, consumer_id='air-clock', upstream_ids=('lowmid',),
                route_id='signed-bipolar', depth=160., graph_snapshot=graph,
                expected_graph_sha256='0'*64)


if __name__ == '__main__':
    unittest.main()
