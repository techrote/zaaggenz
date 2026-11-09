"""NYQ-004 v1 controlled-clock producer: exact-event and adversarial oracles."""
from dataclasses import replace
from fractions import Fraction
from hashlib import sha256
from math import ceil
import unittest

import numpy as np

from zaaggenz_contracts import ContractError
from zaaggenz_contracts.nyquismic import (
    ClockSpec, JitterSpec, ModulationRoute, Point, ResourceBudget,
    SonicSpec, VirtualRate,
)
from zaaggenz_contracts.nyquismic_clock import ClockCancelled
from zaaggenz_contracts.nyquismic_input_envelope import (
    UpstreamGraphEdge, UpstreamGraphSnapshot,
)
from zaaggenz_contracts.nyquismic_clock_packet import (
    AuthenticatedRouteReceiptV1, ControlledSamplerClockV1,
    compile_controlled_sampler_clock_v1, event_fraction, event_text,
)
from zaaggenz_dsp.nyquismic import FrozenInput
from zaaggenz_dsp.nyquismic_controlled_audio_proof import render_controlled_audio_proof

ONE = '1' * 64
TWO = '2' * 64
THREE = '3' * 64


def frozen_fixture(channels=1):
    ramp = (np.arange(48000, dtype=np.float32) / 48000)
    pcm = ramp if channels == 1 else np.column_stack((ramp, ramp)).astype('<f4')
    return FrozenInput.from_pcm(pcm, 48000)


def spec_for_six(channels=1, **kwargs):
    route = ModulationRoute(
        id='physical-step', mapping='add_hz', depth=4.0, initial='1/1',
        points=(Point('1/2', '0/1'),),
    )
    return SonicSpec(clock=ClockSpec(
        rate=VirtualRate('4/1'), routes=(route,), **kwargs,
    ), channels=channels)


def authored_receipt(spec):
    r = spec.clock.routes[0]
    return AuthenticatedRouteReceiptV1(
        route_id=r.id, route_sha256=r.sha256,
        source_sha256=TWO, source_method='nyq.step-source.v1',
    )


def packet_for(spec, *, asset=None, receipts=None, budget=None, **overrides):
    source = asset or frozen_fixture(spec.channels)
    args = dict(
        full_end_s='1/1',
        input_asset_sha256=source.asset.sha256,
        source_revision_sha256=ONE,
        graph_revision_sha256=THREE,
        expected_live_graph_sha256=THREE,
        upstream_route_receipts=(authored_receipt(spec),),
        budget=ResourceBudget(),
    )
    if receipts is not None:
        args['upstream_route_receipts'] = receipts
    if budget is not None:
        args['budget'] = budget
    args.update(overrides)
    return compile_controlled_sampler_clock_v1(spec, **args)


class PacketTests(unittest.TestCase):
    def test_frozen_six_events_and_cross_evaluation_rate_identity(self):
        spec = spec_for_six()
        source = frozen_fixture()
        packet = packet_for(spec, asset=source)
        self.assertEqual(packet.full_end_s, '1/1')
        self.assertEqual(packet.channels_count, 1)
        self.assertEqual(packet.channels[0].seed_identity_sha256.__len__(), 64)
        self.assertEqual(
            [e.coordinate_s for e in packet.channels[0].events],
            ['0/1', '1/8', '1/4', '3/8', '1/2', '3/4'],
        )
        self.assertEqual([e.crossing for e in packet.channels[0].events],
                         list(range(6)))
        self.assertEqual(
            [e.coordinate_error_bound_s for e in packet.channels[0].events],
            ['0/1'] * 6)
        self.assertEqual(packet.event_ledger_sha256, packet_for(
            spec, asset=source).event_ledger_sha256)
        self.assertEqual(ControlledSamplerClockV1.from_json(
            packet.to_json()), packet)
        self.assertFalse(packet.live_graph_authorized)
        self.assertFalse(packet.upstream_pcm_authorized)
        self.assertFalse(packet.sampler_checkpoint_qualified)
        for evaluation_hz in (192000, 384000, 768000):
            # Only a numerical ownership oracle: this DOES NOT execute the
            # NYQ-003 SamplerPlan consumer or prove final PCM/convergence.
            first = [ceil(Fraction(e.coordinate_s) * evaluation_hz)
                     for e in packet.channels[0].events]
            self.assertEqual(first, [
                0, evaluation_hz // 8, evaluation_hz // 4,
                3 * evaluation_hz // 8, evaluation_hz // 2,
                3 * evaluation_hz // 4,
            ])
            self.assertEqual(packet.event_ledger_sha256, packet_for(
                spec, asset=source).event_ledger_sha256)
        # Distinct pre-existing source-native PCM proof: no product adapter.
        audio = render_controlled_audio_proof(source, spec)
        self.assertEqual(audio.diagnostics['event_count_by_channel'], [6])
        self.assertAlmostEqual(float(audio.audio[30000]), 0.5, places=6)

    def test_stale_route_source_graph_and_missing_receipt_reject(self):
        spec = spec_for_six()
        packet = packet_for(spec)
        with self.assertRaises(ContractError):
            packet.require_claims(
                spec, full_end_s='1/1',
                input_asset_sha256=TWO,
                source_revision_sha256=ONE, graph_revision_sha256=THREE)
        with self.assertRaises(ContractError):
            packet.require_claims(
                spec, full_end_s='1/2',
                input_asset_sha256=frozen_fixture().asset.sha256,
                source_revision_sha256=ONE, graph_revision_sha256=THREE)
        with self.assertRaises(ContractError):
            packet_for(spec, expected_live_graph_sha256=TWO)
        with self.assertRaises(ContractError):
            packet_for(spec, upstream_route_receipts=())
        with self.assertRaises(ContractError):
            packet_for(spec, receipts=(replace(
                authored_receipt(spec), route_sha256=ONE),))
        with self.assertRaises(ContractError):
            replace(packet, event_ledger_sha256=ONE)
        with self.assertRaises(ContractError):
            replace(packet, live_graph_authorized=True)
        # Rehashing a truncated event ledger must not forge complete membership.
        from zaaggenz_contracts.nyquismic_clock_packet import _ledger_sha256
        shortened = replace(packet.channels[0],
                            events=packet.channels[0].events[:-1])
        forged_channels = (shortened,)
        forged = replace(packet, channels=forged_channels,
                         event_ledger_sha256=_ledger_sha256(forged_channels))
        with self.assertRaises(ContractError):
            forged.require_claims(
                spec, full_end_s='1/1',
                input_asset_sha256=frozen_fixture().asset.sha256,
                source_revision_sha256=ONE, graph_revision_sha256=THREE)
        self.assertEqual(event_fraction(event_text(Fraction(123456789, 2**64))),
                         Fraction(123456789, 2**64))
        with self.assertRaises(ContractError):
            event_fraction('h:02/4')

    def test_feature_must_have_snapshot_ancestry_and_full_support(self):
        spec = spec_for_six()
        graph = UpstreamGraphSnapshot(
            nodes=('mod', 'up'),
            edges=(UpstreamGraphEdge('up', 'mod'),),
        )
        spec = replace(spec, instance_id='mod')
        feature = AuthenticatedRouteReceiptV1(
            route_id=spec.clock.routes[0].id,
            route_sha256=spec.clock.routes[0].sha256,
            source_sha256=ONE, source_method='nyq.upstream-centroid.v1',
            source_kind='upstream_feature',
            feature_sha256=TWO, feature_method_sha256=THREE,
            input_pcm_sha256=ONE, upstream_source_id='up',
            graph_snapshot=graph, support_start_s='0/1',
            support_end_s='1/1', lookahead_s='1/100',
        )
        good = packet_for(spec, receipts=(feature,),
                          graph_revision_sha256=graph.sha256,
                          expected_live_graph_sha256=graph.sha256)
        self.assertFalse(good.upstream_pcm_authorized)
        for forged in (
            replace(feature, support_end_s='1/2'),
            replace(feature, upstream_source_id='mod'),
            replace(feature, graph_snapshot=UpstreamGraphSnapshot(
                nodes=('mod', 'up'), edges=())),
        ):
            with self.assertRaises(ContractError):
                packet_for(spec, receipts=(forged,),
                           graph_revision_sha256=graph.sha256,
                           expected_live_graph_sha256=graph.sha256)
        with self.assertRaises(ContractError):
            UpstreamGraphSnapshot(
                nodes=('mod', 'up'),
                edges=(UpstreamGraphEdge('mod', 'up'),
                       UpstreamGraphEdge('up', 'mod')))

    def test_stereo_seed_link_independence_and_packet_corruption(self):
        jitter = JitterSpec(
            model='uniform_frequency_cells_v1', amount=0.1,
            cell_s='1/8', seed='71', stream='packet',
        )
        linked = spec_for_six(2, jitter=jitter)
        linked_packet = packet_for(linked)
        self.assertEqual(linked_packet.channels[0].events,
                         linked_packet.channels[1].events)
        self.assertEqual(linked_packet.channels[0].seed_identity_sha256,
                         linked_packet.channels[1].seed_identity_sha256)
        independent = replace(linked, stereo_link='independent')
        independent_packet = packet_for(independent)
        self.assertNotEqual(independent_packet.channels[0].seed_identity_sha256,
                            independent_packet.channels[1].seed_identity_sha256)
        self.assertNotEqual(independent_packet.channels[0].events,
                            independent_packet.channels[1].events)
        with self.assertRaises(ContractError):
            replace(independent_packet, channels=tuple(reversed(
                independent_packet.channels)))

    def test_budget_cancellation_and_legacy_absence(self):
        spec = spec_for_six()
        with self.assertRaises(ContractError):
            packet_for(spec, budget=ResourceBudget(max_events=5))
        with self.assertRaises(ClockCancelled):
            packet_for(spec, cancelled=lambda: True)
        # This producer does not modify or invoke the original SamplerPlan.
        # Legacy absence/default-byte and real checkpoint qualification belong
        # to the disjoint NYQ-003 consumer regression, not this test.


if __name__ == '__main__':
    unittest.main()
