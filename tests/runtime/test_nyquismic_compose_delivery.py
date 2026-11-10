"""Real Compose -> controlled packet -> sampler -> 48-kHz WAV regressions.

All fixtures are synthetic, authored, full-phrase TimelineService jobs. The
module under test has no UI, filesystem, registered graph, or default effect.
"""
from copy import deepcopy
from fractions import Fraction
import hashlib
import io
import json
import unittest
from unittest.mock import patch

import numpy as np
from scipy.io import wavfile

from zaaggenz_contracts.nyquismic import (
    ClockSpec, ModulationRoute, Point, ResourceBudget, SonicSpec, VirtualRate,
)
from zaaggenz_contracts.nyquismic_clock_packet import (
    AuthenticatedRouteReceiptV1, compile_controlled_sampler_clock_v1,
)
from zaaggenz_dsp.nyquismic import sampler_evaluation
from zaaggenz_dsp.nyquismic_delivery import convert_numerical_to_delivery
from zaaggenz_jobs import JobError
from zaaggenz_runtime import RuntimeSession
from zaaggenz_runtime.nyquismic_compose import bind_completed_compose
from zaaggenz_runtime.nyquismic_compose_delivery import (
    render_compose_controlled_48k_wav,
)
from zaaggenz_timeline.model import TimelineDocument, default_document
from zaaggenz_timeline.service import TimelineService


def source_document():
    document = default_document(12000).to_dict()
    document['name'] = 'NYQ 48-kHz Compose export source'
    document['end_beat'] = '2/1'
    document['notes'] = [
        {'id': 'n0', 'beat': '0/1', 'duration_beats': '1/1', 'degree': 0,
         'detune_cents': 0., 'gain_db': -12., 'muted': False, 'roll_density': 0}
    ]
    return document


def sonic():
    route = ModulationRoute(
        id='physical-step', mapping='add_hz', depth=4.,
        initial='1/1', points=(Point('1/2', '0/1'),))
    return SonicSpec(clock=ClockSpec(
        rate=VirtualRate('4/1'), routes=(route,)))


def packet_for(binding, spec, *, full_end_s=None):
    if full_end_s is None:
        # Actual full-context owned Compose PCM can include bounded sonic tail;
        # the edited two-beat document span is not the audio asset frame count.
        asset = binding.source.asset.to_dict()
        end = Fraction(asset['frame_count'], asset['sample_rate_hz'])
        full_end_s = f'{end.numerator}/{end.denominator}'
    claims = binding.packet_claims
    route = spec.clock.routes[0]
    receipt = AuthenticatedRouteReceiptV1(
        route_id=route.id, route_sha256=route.sha256,
        source_sha256='2' * 64, source_method='nyq.step-source.v1')
    return compile_controlled_sampler_clock_v1(
        spec, full_end_s=full_end_s,
        input_asset_sha256=claims['input_asset_sha256'],
        source_revision_sha256=claims['source_revision_sha256'],
        graph_revision_sha256=claims['graph_revision_sha256'],
        expected_live_graph_sha256=claims['graph_revision_sha256'],
        upstream_route_receipts=(receipt,), budget=ResourceBudget())


class ComposeControlled48kWavTests(unittest.TestCase):
    def setUp(self):
        self.document = source_document()
        self.service = TimelineService(debounce_seconds=0)
        request = self.service.submit(self.document)
        state = self.service.scheduler.wait(request['job_id'], 45)
        self.assertEqual(state.state, 'completed')
        self.job_id = request['job_id']

    def tearDown(self):
        self.service.close()

    def prepared(self):
        binding = bind_completed_compose(self.service, self.job_id)
        spec = sonic()
        return binding, spec, packet_for(binding, spec)

    def export(self, *, cancelled=None):
        binding, spec, packet = self.prepared()
        result = render_compose_controlled_48k_wav(
            binding, spec, packet, sampler_evaluation(192000),
            cancelled=cancelled)
        return binding, spec, packet, result

    def test_real_compose_packet_sampler_to_decoded_48k_float_wav(self):
        binding, spec, packet, result = self.export()
        self.assertEqual(result.sample_rate_hz, 48000)
        self.assertEqual(result.numerical_rate_hz, 192000)
        expected_frames = binding.source.asset.to_dict()['frame_count'] * 4
        self.assertEqual(result.frames, expected_frames)
        self.assertEqual(result.channels, 1)
        self.assertEqual(result.source_asset_sha256, binding.source.asset.sha256)
        self.assertEqual(result.recipe_sha256, binding.recipe_sha256)
        self.assertEqual(result.packet_sha256, packet.sha256)
        rate, audio = wavfile.read(io.BytesIO(result.wav_bytes))
        self.assertEqual(rate, 48000)
        self.assertEqual(audio.dtype, np.dtype('float32'))
        self.assertEqual(audio.shape, (expected_frames,))
        self.assertGreater(float(np.max(np.abs(audio))), 0.)
        self.assertTrue(np.isfinite(audio).all())
        self.assertEqual(hashlib.sha256(result.wav_bytes).hexdigest(),
                         result.wav_sha256)
        self.assertEqual(hashlib.sha256(
            audio.astype('<f4', copy=False).tobytes()).hexdigest(),
            result.pcm_f32le_sha256)
        # Original-host source/PCM receipt: retain actual values in CI logs
        # rather than asserting against a fabricated cross-host byte identity.
        print('NYQ48K_ORIGINAL_NUMERICS ' + json.dumps({
            'source_asset_sha256': result.source_asset_sha256,
            'source_frames': binding.source.asset.to_dict()['frame_count'],
            'source_rate_hz': binding.source.sample_rate_hz,
            'recipe_sha256': result.recipe_sha256,
            'packet_sha256': result.packet_sha256,
            'sampler_render_sha256': result.sampler_render_sha256,
            'numerical_f64le_sha256': result.numerical_f64le_sha256,
            'converted_f64le_sha256': result.converted_f64le_sha256,
            'pcm_f32le_sha256': result.pcm_f32le_sha256,
            'wav_sha256': result.wav_sha256,
            'wav_frames': result.frames,
            'wav_rate_hz': result.sample_rate_hz,
            'identity_sha256': result.identity_sha256,
        }, sort_keys=True))

    def test_checkpoint_replay_matches_full_numerical_and_final_pcm(self):
        binding, spec, packet, result = self.export()
        handle = binding.prepare(spec, packet, sampler_evaluation(192000))
        full = handle.render()
        split = len(full.audio) // 2
        left = handle.render(0, split)
        right = handle.render(checkpoint=handle.checkpoint(split))
        np.testing.assert_array_equal(
            np.concatenate((left.audio, right.audio)), full.audio)
        expected = convert_numerical_to_delivery(full.audio, 192000, 48000)
        rate, pcm = wavfile.read(io.BytesIO(result.wav_bytes))
        self.assertEqual(rate, 48000)
        np.testing.assert_array_equal(
            pcm, np.asarray(expected.audio, dtype='<f4'))
        self.assertEqual(result.numerical_f64le_sha256,
                         full.diagnostics['pcm_sha256'])
        self.assertEqual(result.converted_f64le_sha256,
                         expected.diagnostics['output_pcm_sha256'])
        self.assertEqual(result.conversion_kernel_sha256,
                         expected.diagnostics['kernel_sha256'])

    def test_saved_cold_reopen_replays_identical_wav(self):
        _, _, _, before = self.export()
        saved = json.dumps(self.service.session.document().to_dict(),
                           sort_keys=True)
        reopened = TimelineService(
            session=RuntimeSession(TimelineDocument.from_json(saved)),
            debounce_seconds=0)
        try:
            request = reopened.submit(json.loads(saved))
            self.assertEqual(reopened.scheduler.wait(
                request['job_id'], 45).state, 'completed')
            other = bind_completed_compose(reopened, request['job_id'])
            spec = sonic()
            replay = render_compose_controlled_48k_wav(
                other, spec, packet_for(other, spec), sampler_evaluation(192000))
            self.assertEqual(before.wav_bytes, replay.wav_bytes)
            self.assertEqual(before.identity_sha256, replay.identity_sha256)
        finally:
            reopened.close()

    def test_edit_during_wav_serialization_refuses_final_publication(self):
        binding, spec, packet = self.prepared()
        edited = deepcopy(self.document)
        edited['name'] = 'modified during WAV write'
        original = wavfile.write
        invoked = [False]

        def write_then_edit(stream, rate, audio):
            original(stream, rate, audio)
            invoked[0] = True
            self.service.accept_document(edited)

        with patch('zaaggenz_runtime.nyquismic_compose_delivery.wavfile.write',
                   side_effect=write_then_edit):
            with self.assertRaises(JobError):
                render_compose_controlled_48k_wav(
                    binding, spec, packet, sampler_evaluation(192000))
        self.assertTrue(invoked[0])

    def test_owned_job_revoked_after_fir_refuses_wav_publication(self):
        binding, spec, packet = self.prepared()
        original = convert_numerical_to_delivery
        invoked = [False]

        def convert_then_revoke(*args, **kwargs):
            converted = original(*args, **kwargs)
            invoked[0] = True
            self.service.cancel(self.job_id)
            return converted

        with patch('zaaggenz_runtime.nyquismic_compose_delivery.convert_numerical_to_delivery',
                   side_effect=convert_then_revoke):
            with self.assertRaises(JobError):
                render_compose_controlled_48k_wav(
                    binding, spec, packet, sampler_evaluation(192000))
        self.assertTrue(invoked[0])

    def test_late_caller_cancellation_during_encoding_refuses_publication(self):
        binding, spec, packet = self.prepared()
        original = wavfile.write
        cancelled = [False]

        def write_then_cancel(stream, rate, audio):
            original(stream, rate, audio)
            cancelled[0] = True

        with patch('zaaggenz_runtime.nyquismic_compose_delivery.wavfile.write',
                   side_effect=write_then_cancel):
            with self.assertRaises(JobError):
                render_compose_controlled_48k_wav(
                    binding, spec, packet, sampler_evaluation(192000),
                    cancelled=lambda: cancelled[0])
        self.assertTrue(cancelled[0])

    def test_shorter_packet_cannot_silently_truncate_full_compose_export(self):
        binding, spec, _ = self.prepared()
        asset = binding.source.asset.to_dict()
        extent = Fraction(asset['frame_count'], asset['sample_rate_hz'])
        short_extent = extent * Fraction(3, 4)
        short = packet_for(binding, spec, full_end_s=(
            f'{short_extent.numerator}/{short_extent.denominator}'))
        with patch('zaaggenz_runtime.nyquismic_compose_delivery.ComposeControlledSource.prepare',
                   side_effect=AssertionError('do not prepare partial packet')):
            with self.assertRaises(JobError):
                render_compose_controlled_48k_wav(
                    binding, spec, short, sampler_evaluation(192000))

    def test_admission_budget_rejects_before_preparation(self):
        binding, spec, packet = self.prepared()
        with patch('zaaggenz_runtime.nyquismic_compose_delivery.ComposeControlledSource.prepare',
                   side_effect=AssertionError('sampler preparation should not be called')):
            with self.assertRaises(JobError):
                render_compose_controlled_48k_wav(
                    binding, spec, packet, sampler_evaluation(192000),
                    budget=ResourceBudget(max_frames=1024))


if __name__ == '__main__':
    unittest.main(verbosity=2)
