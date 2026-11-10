"""Original Compose -> NYQ controlled clock -> numerically converted float WAV.

This is an opt-in post-master proof, not a registered rack/export workflow.
"""
from copy import deepcopy
from hashlib import sha256
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
from zaaggenz_jobs import JobError
from zaaggenz_runtime import RuntimeSession
from zaaggenz_runtime.nyquismic_compose import bind_completed_compose
from zaaggenz_runtime.nyquismic_delivery import (
    _convert_48k, export_compose_controlled_wav48,
)
from zaaggenz_timeline.model import TimelineDocument, default_document
from zaaggenz_timeline.service import TimelineService


def _document():
    source = default_document(12000).to_dict()
    source['name'] = 'NYQ 48k export source'
    source['end_beat'] = '2/1'
    source['notes'] = [
        {'id': 'n0', 'beat': '0/1', 'duration_beats': '1/1',
         'degree': 0, 'detune_cents': 0., 'gain_db': -12.,
         'muted': False, 'roll_density': 0}
    ]
    return source


def _handle(service, job_id, evaluation_rate_hz=192000):
    binding = bind_completed_compose(service, job_id)
    route = ModulationRoute(id='physical-step', mapping='add_hz', depth=4.,
                            initial='1/1', points=(Point('1/2', '0/1'),))
    sonic = SonicSpec(clock=ClockSpec(rate=VirtualRate('4/1'), routes=(route,)))
    claims = binding.packet_claims
    receipt = AuthenticatedRouteReceiptV1(
        route_id=route.id, route_sha256=route.sha256,
        source_sha256='2'*64, source_method='nyq.step-source.v1')
    packet = compile_controlled_sampler_clock_v1(
        sonic, full_end_s='1/1',
        input_asset_sha256=claims['input_asset_sha256'],
        source_revision_sha256=claims['source_revision_sha256'],
        graph_revision_sha256=claims['graph_revision_sha256'],
        expected_live_graph_sha256=claims['graph_revision_sha256'],
        upstream_route_receipts=(receipt,), budget=ResourceBudget())
    return binding.prepare(sonic, packet, sampler_evaluation(evaluation_rate_hz))


class FloatWavConversionTests(unittest.TestCase):
    def test_48k_rejects_accidental_high_frequency_fold_but_keeps_low_tone(self):
        rate = 192000
        t = np.arange(rate, dtype=np.float64) / rate
        signal = .25 * np.sin(2*np.pi*6000*t) + .65 * np.sin(2*np.pi*40000*t)
        converted, taps_sha = _convert_48k(signal, rate, 1)
        self.assertEqual(len(converted), 48000)
        self.assertEqual(len(taps_sha), 64)
        middle = converted[500:-500].astype(np.float64)
        axis = np.arange(500, 47500, dtype=np.float64) / 48000
        def amplitude(freq):
            return float(2 * abs(np.vdot(middle, np.exp(2j*np.pi*freq*axis))) / len(middle))
        self.assertAlmostEqual(amplitude(6000), .25, delta=.001)
        # 40 kHz would fold to 8 kHz if we simply picked every fourth frame.
        self.assertLess(amplitude(8000), .001)

    def test_finite_overunity_float_and_stereo_remain_unclipped(self):
        stereo = np.full((32000, 2), [1.25, -1.25], dtype=np.float64)
        out, _ = _convert_48k(stereo, 192000, 2)
        self.assertEqual(out.shape, (8000, 2))
        self.assertAlmostEqual(float(out[4000, 0]), 1.25, delta=1e-5)
        self.assertAlmostEqual(float(out[4000, 1]), -1.25, delta=1e-5)
        with self.assertRaises(JobError):
            _convert_48k(np.array([np.nan]), 192000, 1)
        with self.assertRaises(JobError):
            _convert_48k(np.array([0.], dtype=np.float64), 44100, 1)
        with self.assertRaises(JobError):
            _convert_48k(np.zeros((20, 2)), 192000, 1)

    def test_partial_last_evaluation_frame_uses_fixed_48k_grid(self):
        out, _ = _convert_48k(np.zeros(192003, dtype=np.float64), 192000, 1)
        self.assertEqual(len(out), 48001)


class RealComposeWavTests(unittest.TestCase):
    def setUp(self):
        self.document = _document()
        self.service = TimelineService(debounce_seconds=0)
        job = self.service.submit(self.document)
        self.assertEqual(self.service.scheduler.wait(job['job_id'], 45).state,
                         'completed')
        self.job_id = job['job_id']

    def tearDown(self):
        self.service.close()

    def test_actual_compose_controlled_pcm_exports_decodable_float_wav(self):
        handle = _handle(self.service, self.job_id)
        product = export_compose_controlled_wav48(handle)
        rate, pcm = wavfile.read(io.BytesIO(product.wave_bytes))
        self.assertEqual(rate, 48000)
        self.assertEqual(pcm.dtype, np.dtype('float32'))
        self.assertEqual(pcm.shape, (48000,))
        self.assertTrue(np.isfinite(pcm).all())
        self.assertEqual(product.channels, 1)
        self.assertEqual(product.frame_count, len(pcm))
        self.assertEqual(product.source_recipe_sha256,
                         handle.source_binding.recipe_sha256)
        self.assertEqual(product.source_asset_sha256,
                         handle.source_binding.source.asset.sha256)
        self.assertEqual(product.controlled_render_sha256, handle.render_sha256)
        self.assertEqual(product.wav_sha256, sha256(product.wave_bytes).hexdigest())
        self.assertEqual(product.delivery_pcm_sha256, sha256(pcm.astype('<f4').tobytes()).hexdigest())
        self.assertEqual(product.receipt()['delivery_rate_hz'], 48000)
        self.assertNotIn('wave_bytes', product.receipt())
        self.assertFalse(handle.render(0, 100).diagnostics['delivery_conversion_performed'])

    def test_saved_source_cold_reopen_yields_same_wav_and_receipts(self):
        before = export_compose_controlled_wav48(_handle(self.service, self.job_id))
        saved = json.dumps(self.service.session.document().to_dict(), sort_keys=True)
        reopened = TimelineService(
            session=RuntimeSession(TimelineDocument.from_json(saved)),
            debounce_seconds=0)
        try:
            job = reopened.submit(json.loads(saved))
            self.assertEqual(reopened.scheduler.wait(job['job_id'], 45).state,
                             'completed')
            after = export_compose_controlled_wav48(_handle(reopened, job['job_id']))
            self.assertEqual(before.wave_bytes, after.wave_bytes)
            self.assertEqual(before.receipt(), after.receipt())
        finally:
            reopened.close()

    def test_revision_edit_during_wav_write_refuses_publication(self):
        handle = _handle(self.service, self.job_id)
        changed = deepcopy(self.document)
        changed['name'] = 'Revoked while encoding 48k WAV'
        original_write = wavfile.write
        def write_then_edit(buf, rate, data):
            original_write(buf, rate, data)
            self.service.accept_document(changed)
        with patch('zaaggenz_runtime.nyquismic_delivery.wavfile.write',
                   side_effect=write_then_edit):
            with self.assertRaises(JobError):
                export_compose_controlled_wav48(handle)

    def test_caller_cancelled_at_wav_handoff_refuses(self):
        handle = _handle(self.service, self.job_id)
        original_write = wavfile.write
        cancelled = [False]
        def write_then_cancel(buf, rate, data):
            original_write(buf, rate, data)
            cancelled[0] = True
        with patch('zaaggenz_runtime.nyquismic_delivery.wavfile.write',
                   side_effect=write_then_cancel):
            with self.assertRaises(JobError):
                export_compose_controlled_wav48(handle,
                                                 cancelled=lambda: cancelled[0])
        self.assertTrue(cancelled[0])

    def test_stale_revision_cannot_be_reexported(self):
        handle = _handle(self.service, self.job_id)
        new_doc = deepcopy(self.document)
        new_doc['name'] = 'New revision'
        self.service.accept_document(new_doc)
        with self.assertRaises(JobError):
            export_compose_controlled_wav48(handle)


if __name__ == '__main__':
    unittest.main(verbosity=2)
