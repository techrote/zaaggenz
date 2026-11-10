"""Original Compose job -> #267 clock -> #266 SamplerPlan integration tests.

Requires a real RuntimeSession and completed source audio, not caller-invented
source, graph or rack hashes. This is an opt-in full-mix integration slice.
"""
from copy import deepcopy
import json
import unittest

import numpy as np

from zaaggenz_contracts import ContractError
from zaaggenz_contracts.nyquismic import (
    ClockSpec, ModulationRoute, Point, ResourceBudget, SonicSpec, VirtualRate,
)
from zaaggenz_contracts.nyquismic_clock import ClockCancelled
from zaaggenz_contracts.nyquismic_clock_packet import (
    AuthenticatedRouteReceiptV1, compile_controlled_sampler_clock_v1,
)
from zaaggenz_dsp.nyquismic import sampler_evaluation
from zaaggenz_jobs import JobError
from zaaggenz_runtime import RuntimeSession
from zaaggenz_runtime.nyquismic_compose import bind_completed_compose
from zaaggenz_timeline.model import TimelineDocument, default_document
from zaaggenz_timeline.service import TimelineService


def source_document():
    data = default_document(12000).to_dict()
    data['name'] = 'NYQ live Compose source'
    data['end_beat'] = '2/1'
    data['notes'] = [
        {'id': 'n0', 'beat': '0/1', 'duration_beats': '1/1', 'degree': 0,
         'detune_cents': 0., 'gain_db': -12., 'muted': False, 'roll_density': 0}
    ]
    return data


def sonic():
    route = ModulationRoute(
        id='physical-step', mapping='add_hz', depth=4.,
        initial='1/1', points=(Point('1/2', '0/1'),))
    return SonicSpec(clock=ClockSpec(
        rate=VirtualRate('4/1'), routes=(route,)))


def authored_packet(binding, spec, *, graph=None):
    claims = binding.packet_claims
    route = spec.clock.routes[0]
    receipt = AuthenticatedRouteReceiptV1(
        route_id=route.id, route_sha256=route.sha256,
        source_sha256='2'*64, source_method='nyq.step-source.v1')
    revision = claims['graph_revision_sha256'] if graph is None else graph
    return compile_controlled_sampler_clock_v1(
        spec, full_end_s='1/1',
        input_asset_sha256=claims['input_asset_sha256'],
        source_revision_sha256=claims['source_revision_sha256'],
        graph_revision_sha256=revision,
        expected_live_graph_sha256=revision,
        upstream_route_receipts=(receipt,), budget=ResourceBudget())


class ComposeControlledSessionTests(unittest.TestCase):
    def setUp(self):
        self.document = source_document()
        self.service = TimelineService(debounce_seconds=0)
        request = self.service.submit(self.document)
        state = self.service.scheduler.wait(request['job_id'], 45)
        self.assertEqual(state.state, 'completed')
        self.job_id = request['job_id']

    def tearDown(self):
        self.service.close()

    def prepare(self):
        binding = bind_completed_compose(self.service, self.job_id)
        spec = sonic()
        packet = authored_packet(binding, spec)
        handle = binding.prepare(spec, packet, sampler_evaluation(192000))
        return binding, packet, handle

    def test_actual_full_compose_pcm_and_packet_produce_checkpoint_stable_audio(self):
        binding, packet, handle = self.prepare()
        self.assertEqual(binding.timeline_revision_id,
                         self.service.session.current_revision_id())
        self.assertEqual(packet.input_asset_sha256, binding.source.asset.sha256)
        self.assertEqual(packet.graph_revision_sha256, binding.recipe_sha256)
        self.assertEqual(handle._plan.packet.event_ledger_sha256,
                         packet.event_ledger_sha256)
        whole = handle.render(0, 35000)
        front = handle.render(0, 24005)
        restored = handle.checkpoint(24005)
        back = handle.render(checkpoint=restored, stop_frame=35000)
        np.testing.assert_array_equal(
            np.concatenate((front.audio, back.audio)), whole.audio)
        self.assertTrue(np.isfinite(whole.audio).all())
        # Component's conservative diagnostic remains true; this adapter is
        # not a registered per-band graph node or authorized upstream tap.
        self.assertFalse(whole.diagnostics['live_graph_authenticated'])
        self.assertGreater(len(binding.source.pcm), 0)

    def test_stale_edit_and_aba_generation_refuse_old_audio(self):
        old = deepcopy(self.document)
        binding, packet, handle = self.prepare()
        edited = deepcopy(old)
        edited['name'] = 'Other Compose revision'
        self.service.accept_document(edited)
        with self.assertRaises(JobError):
            handle.render(0, 500)
        with self.assertRaises(JobError):
            handle.checkpoint(500)
        with self.assertRaises(JobError):
            bind_completed_compose(self.service, self.job_id)
        self.service.accept_document(old)
        self.assertEqual(self.service.session.current_revision_id(),
                         binding.timeline_revision_id)
        with self.assertRaises(JobError):
            handle.render(0, 500)

    def test_claimed_graph_and_partial_region_cannot_authenticate(self):
        binding = bind_completed_compose(self.service, self.job_id)
        spec = sonic()
        forged = authored_packet(binding, spec, graph='a'*64)
        with self.assertRaises(ContractError):
            binding.prepare(spec, forged, sampler_evaluation(192000))
        region_job = self.service.submit(
            self.document, {'start_beat':'0/1', 'end_beat':'1/1'})
        state = self.service.scheduler.wait(region_job['job_id'], 45)
        self.assertEqual(state.state, 'completed')
        with self.assertRaises(JobError):
            bind_completed_compose(self.service, region_job['job_id'])

    def test_mutation_during_render_aborts_without_published_result(self):
        _, _, handle = self.prepare()
        modified = deepcopy(self.document)
        modified['name'] = 'Concurrent edit'
        moved = [False]
        def change_on_progress(value):
            if not moved[0]:
                moved[0] = True
                self.service.accept_document(modified)
        with self.assertRaises((ClockCancelled, JobError)):
            handle.render(0, 10000, progress=change_on_progress)
        self.assertTrue(moved[0])

    def test_cold_reopened_session_recompiles_identical_source_and_pcm(self):
        binding, _, handle = self.prepare()
        before = handle.render(0, 3000).audio
        saved = json.dumps(self.service.session.document().to_dict(),
                           sort_keys=True)
        reopened = TimelineService(
            session=RuntimeSession(TimelineDocument.from_json(saved)),
            debounce_seconds=0)
        try:
            request = reopened.submit(json.loads(saved))
            self.assertEqual(
                reopened.scheduler.wait(request['job_id'], 45).state, 'completed')
            other = bind_completed_compose(reopened, request['job_id'])
            self.assertEqual(other.recipe_sha256, binding.recipe_sha256)
            self.assertEqual(other.source.asset.sha256,
                             binding.source.asset.sha256)
            spec = sonic()
            other_handle = other.prepare(
                spec, authored_packet(other, spec), sampler_evaluation(192000))
            np.testing.assert_array_equal(
                before, other_handle.render(0, 3000).audio)
        finally:
            reopened.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
