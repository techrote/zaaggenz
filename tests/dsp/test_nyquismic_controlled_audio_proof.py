"""NYQ-004 controlled native-grid PCM execution, independent physical oracles.

This is a real opt-in PCM proof, not graph/rack, final export, or a public
sampler capability registration. No physical Windows or owner listening claim.
"""
from dataclasses import replace
import unittest

import numpy as np

from zaaggenz_contracts import ContractError
from zaaggenz_contracts.nyquismic import (
    ClockSpec, JitterSpec, ModulationRoute, Point, ResourceBudget, SonicSpec,
    VirtualRate,
)
from zaaggenz_contracts.nyquismic_clock import ClockCancelled
from zaaggenz_dsp.nyquismic import FrozenInput, SamplerPlan, sampler_evaluation
from zaaggenz_dsp.nyquismic_controlled_audio_proof import (
    METHOD, render_controlled_audio_proof,
)


RATE = 48000


def ramp(channels=1):
    x = np.arange(RATE, dtype=np.float32) / RATE
    if channels == 2:
        x = np.column_stack((x, x)).astype('<f4')
    return FrozenInput.from_pcm(x, RATE)


def routed_spec(reconstruction='hold_v1'):
    route = ModulationRoute(
        id='physical-step', mapping='add_hz', depth=4.0, initial='1/1',
        points=(Point('1/2', '0/1'),),
    )
    return SonicSpec(
        clock=ClockSpec(rate=VirtualRate('4/1'), routes=(route,)),
        reconstruction=reconstruction,
    )


class ControlledAudioProofTests(unittest.TestCase):
    def test_true_phase_integral_controls_pcm_not_a_rounded_hold_period(self):
        source = ramp()
        spec = routed_spec()
        result = render_controlled_audio_proof(source, spec)
        self.assertEqual(result.diagnostics['method'], METHOD)
        self.assertEqual(result.diagnostics['event_count_by_channel'], [6])
        self.assertEqual(result.diagnostics['native_evaluation_rate_hz'], RATE)
        self.assertEqual(result.diagnostics['sonic_sha256'], spec.sonic_sha256)
        self.assertEqual(result.diagnostics['clock_sha256'], spec.clock.sha256)
        self.assertFalse(result.diagnostics['product_rack_export_qualified'])
        self.assertFalse(result.audio.flags.writeable)
        # 8 Hz until t=1/2, then 4 Hz without resetting accumulated phase.
        for sample, expected in ((0, 0), (9000, .125), (18000, .375),
                                 (30000, .5), (42000, .75)):
            self.assertAlmostEqual(float(result.audio[sample]), expected, places=6)
        self.assertEqual(result.audio.shape, (RATE,))

    def test_linear_reconstruction_and_full_context_regions(self):
        source, spec = ramp(), routed_spec('linear_time_v1')
        whole = render_controlled_audio_proof(source, spec)
        self.assertAlmostEqual(float(whole.audio[9000]), .1875, places=6)
        self.assertAlmostEqual(float(whole.audio[30000]), .625, places=6)
        pieces = []
        for start, stop in ((0, 7000), (7000, 20000), (20000, 33000),
                            (33000, RATE)):
            piece = render_controlled_audio_proof(
                source, spec, start_frame=start, stop_frame=stop)
            self.assertEqual(piece.diagnostics['event_ledger_sha256'],
                             whole.diagnostics['event_ledger_sha256'])
            pieces.append(piece.audio)
        np.testing.assert_array_equal(np.concatenate(pieces), whole.audio)

    def test_static_hold_matches_accepted_nyq002_sampler_native_grid(self):
        source = ramp()
        spec = SonicSpec(clock=ClockSpec(rate=VirtualRate('4/1')))
        accepted = SamplerPlan.prepare(
            source, spec, sampler_evaluation(RATE)).render().audio
        proof = render_controlled_audio_proof(source, spec).audio
        np.testing.assert_array_equal(proof, accepted)

    def test_linked_independent_jitter_and_stable_label_identity(self):
        jitter = JitterSpec(
            model='uniform_frequency_cells_v1', amount=.1,
            cell_s='1/8', seed='71', stream='proof',
        )
        source = ramp(2)
        spec = SonicSpec(
            channels=2, stereo_link='linked', instance_id='fixed-node',
            clock=ClockSpec(rate=VirtualRate('16/1'), jitter=jitter),
        )
        linked = render_controlled_audio_proof(source, spec)
        np.testing.assert_array_equal(linked.audio[:, 0], linked.audio[:, 1])
        renamed = render_controlled_audio_proof(source, replace(spec, label='Changed UI name'))
        np.testing.assert_array_equal(renamed.audio, linked.audio)
        self.assertEqual(renamed.diagnostics['event_ledger_sha256'],
                         linked.diagnostics['event_ledger_sha256'])
        independent = render_controlled_audio_proof(
            source, replace(spec, stereo_link='independent'))
        self.assertGreater(float(np.max(np.abs(
            independent.audio[:, 0] - independent.audio[:, 1]))), .01)
        self.assertEqual(
            independent.diagnostics['event_ledger_sha256'],
            render_controlled_audio_proof(
                source, replace(spec, stereo_link='independent')
            ).diagnostics['event_ledger_sha256'],
        )

    def test_zero_wet_bypass_silence_and_admission_fail_closed(self):
        source = ramp()
        spec = routed_spec()
        for dry in (replace(spec, wet=0.), replace(spec, bypass=True)):
            result = render_controlled_audio_proof(source, dry)
            np.testing.assert_array_equal(result.audio, source.pcm)
        empty = FrozenInput.from_pcm(np.zeros(0, dtype='<f4'), RATE)
        result = render_controlled_audio_proof(empty, spec)
        self.assertEqual(result.audio.shape, (0,))
        self.assertFalse(result.audio.flags.writeable)
        with self.assertRaises(ContractError):
            render_controlled_audio_proof(source, spec, start_frame=-1)
        with self.assertRaises(ContractError):
            render_controlled_audio_proof(source, spec, stop_frame=RATE+1)
        with self.assertRaises(ContractError):
            render_controlled_audio_proof(
                source, spec, budget=ResourceBudget(max_events=2))
        with self.assertRaises(ContractError):
            render_controlled_audio_proof(
                source, replace(spec, clock=replace(spec.clock, origin_s='1/2')))
        with self.assertRaises(ClockCancelled):
            render_controlled_audio_proof(source, spec, cancelled=lambda: True)


if __name__ == '__main__':
    unittest.main()
