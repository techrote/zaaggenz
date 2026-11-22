"""NYQ-003 real SamplerPlan controlled-packet PCM/restore contract tests.

The #267 packet module is deliberately NOT copied into #266. On an isolated
#266 branch these cross-PR cases are skipped, NOT qualified; Integration must
execute the exact pinned combined source on both hosts before admission.
"""
from dataclasses import fields, replace
from fractions import Fraction
from hashlib import sha256
from math import ceil
import importlib.util
import unittest

import numpy as np

from zaaggenz_contracts import ContractError
from zaaggenz_contracts.nyquismic import (
    ClockSpec, ModulationRoute, Point, ResourceBudget, SonicSpec, VirtualRate,
)
from zaaggenz_contracts.nyquismic_clock import ClockCancelled
from zaaggenz_dsp.nyquismic import (
    FrozenInput, SamplerCheckpoint, SamplerPlan, sampler_evaluation,
)
from zaaggenz_dsp.nyquismic_controlled_consumer import (
    ControlledSamplerCheckpoint, ControlledSamplerPlan, _owned_grid_frame,
)

HAS_PACKET = importlib.util.find_spec(
    'zaaggenz_contracts.nyquismic_clock_packet') is not None
ONE, TWO, THREE, FOUR = '1'*64, '2'*64, '3'*64, '4'*64


def fixture(channels=1, *, short=False, silent=False):
    length = 1 if short else 48000
    ramp = np.arange(length, dtype=np.float32)/48000
    if silent:
        ramp = np.zeros_like(ramp)
    pcm = ramp if channels == 1 else np.column_stack(
        (ramp, 1-ramp if not silent else ramp)).astype('<f4')
    return FrozenInput.from_pcm(pcm, 48000)


def sonic(channels=1, **kw):
    route = ModulationRoute(
        id='physical-step', mapping='add_hz', depth=4.,
        initial='1/1', points=(Point('1/2', '0/1'),))
    return SonicSpec(
        clock=ClockSpec(rate=VirtualRate('4/1'), routes=(route,)),
        channels=channels, **kw)


def producer(source, spec):
    from zaaggenz_contracts.nyquismic_clock_packet import (
        AuthenticatedRouteReceiptV1, compile_controlled_sampler_clock_v1)
    route = spec.clock.routes[0]
    receipt = AuthenticatedRouteReceiptV1(
        route_id=route.id, route_sha256=route.sha256,
        source_sha256=TWO, source_method='nyq.step-source.v1',
    )
    return compile_controlled_sampler_clock_v1(
        spec, full_end_s='1/1', input_asset_sha256=source.asset.sha256,
        source_revision_sha256=ONE, graph_revision_sha256=THREE,
        expected_live_graph_sha256=THREE,
        upstream_route_receipts=(receipt,), budget=ResourceBudget())


def plan(source, spec, packet, rate, *, frame_count=None):
    return SamplerPlan.prepare(
        source, spec, sampler_evaluation(rate), frame_count=frame_count,
        controlled_clock=packet,
        source_revision_sha256=ONE, graph_revision_sha256=THREE,
        rack_revision_sha256=FOUR)


@unittest.skipUnless(HAS_PACKET, 'requires exact #267 producer in an Integration-approved combined test source')
class ActualControlledPCMTests(unittest.TestCase):
    def test_six_event_ramp_exact_pcm_192_384_768_and_checkpoint_replay(self):
        source, spec = fixture(), sonic()
        packet = producer(source, spec)
        expected = [Fraction(0), Fraction(1,8), Fraction(1,4),
                    Fraction(3,8), Fraction(1,2), Fraction(3,4)]
        seen = set()
        for rate in (192000, 384000, 768000):
            admitted = plan(source, spec, packet, rate)
            self.assertIsInstance(admitted, ControlledSamplerPlan)
            self.assertEqual(admitted.packet.event_ledger_sha256,
                             packet.event_ledger_sha256)
            self.assertEqual(admitted._coordinates[0], tuple(expected))
            self.assertEqual(admitted._first_frames[0].tolist(),
                             [int(t*rate) for t in expected])
            self.assertEqual([e.index for e in admitted.events[0]], list(range(6)))
            full = admitted.render()
            self.assertEqual(full.audio.shape, (rate,))
            self.assertTrue(np.isfinite(full.audio).all())
            self.assertFalse(full.diagnostics['live_graph_authenticated'])
            # Independently specified per-frame source PCM: floor by true
            # event membership, *not* a reimplementation of SamplerPlan.render.
            frames = np.arange(rate, dtype=np.int64)
            owners = np.searchsorted(np.array([int(t*rate) for t in expected]),
                                     frames, side='right') - 1
            oracle = np.array([float(t) for t in expected])[owners]
            np.testing.assert_array_equal(full.audio, oracle)
            parts = []
            positions = (0, rate//8+7, rate//2+3, rate)
            for start, stop in zip(positions, positions[1:]):
                original = admitted.checkpoint(start)
                restored = ControlledSamplerCheckpoint.from_json(original.to_json())
                self.assertEqual(original, restored)
                actual = admitted.render(checkpoint=restored, stop_frame=stop)
                np.testing.assert_array_equal(actual.audio, full.audio[start:stop])
                parts.append(actual.audio)
            np.testing.assert_array_equal(np.concatenate(parts), full.audio)
            seen.add(packet.event_ledger_sha256)
        self.assertEqual(len(seen), 1)

    def test_all_admitted_time_aware_reconstruction_mappings(self):
        source = fixture()
        event_times = np.array([0., .125, .25, .375, .5, .75])
        frames = np.arange(192000, dtype=np.int64)
        physical = frames / 192000
        owners = np.searchsorted(event_times, physical, side='right') - 1
        for method in ('hold_v1', 'nearest_time_v1', 'linear_time_v1',
                       'cubic_time_v1'):
            spec = sonic(reconstruction=method)
            pkt = producer(source, spec)
            admitted = plan(source, spec, pkt, 192000)
            output = admitted.render().audio
            if method == 'hold_v1':
                expected = event_times[owners]
                np.testing.assert_array_equal(output, expected)
            elif method == 'nearest_time_v1':
                nxt = np.minimum(owners + 1, len(event_times)-1)
                exact_left = 2*(physical-event_times[owners]) <= (
                    event_times[nxt]-event_times[owners])
                expected = np.where(exact_left, event_times[owners],
                                    event_times[nxt])
                np.testing.assert_array_equal(output, expected)
            else:
                # A sampled affine ramp reproduces an affine ramp through
                # time-aware linear and cubic Hermite, then holds its last
                # actual physical capture. This is not a grid-rate oscillator.
                np.testing.assert_allclose(
                    output, np.minimum(physical, .75), atol=2e-12, rtol=0)
            np.testing.assert_array_equal(
                admitted.render(30001, 55555).audio, output[30001:55555])
        for mode in ('sinc4_hann_uniform_v1',
                     'shepard8_hann_local_time_v1'):
            spec = sonic(reconstruction=mode)
            packet = producer(source, spec)
            with self.assertRaises(ContractError):
                plan(source, spec, packet, 192000)

    def test_linked_and_independent_stereo_and_captured_channel_identity(self):
        for link in ('linked', 'independent'):
            source, spec = fixture(2), sonic(2, stereo_link=link)
            packet = producer(source, spec)
            admitted = plan(source, spec, packet, 192000)
            self.assertEqual([len(events) for events in admitted.events], [6,6])
            self.assertEqual(float(admitted.captures[0][4]), .5)
            self.assertEqual(float(admitted.captures[1][4]), .5)
            self.assertEqual(float(admitted.captures[0][1]), .125)
            self.assertEqual(float(admitted.captures[1][1]), .875)
            self.assertEqual(packet.channels[0].seed_identity_sha256 ==
                             packet.channels[1].seed_identity_sha256,
                             link == 'linked')
            full = admitted.render().audio
            front = admitted.render(0, 100001).audio
            back = admitted.render(checkpoint=admitted.checkpoint(100001)).audio
            np.testing.assert_array_equal(np.vstack((front, back)), full)
            np.testing.assert_array_equal(full[:,1], 1-full[:,0])
            self.assertEqual(admitted.checkpoint(100001).events_before, (5,5))

    def test_wrong_source_route_graph_and_checkpoint_refuse(self):
        source, spec = fixture(), sonic()
        packet = producer(source, spec)
        admitted = plan(source, spec, packet, 192000)
        with self.assertRaises(ContractError):
            plan(fixture(silent=True), spec, packet, 192000)
        with self.assertRaises(ContractError):
            SamplerPlan.prepare(
                source, spec, sampler_evaluation(192000),
                controlled_clock=packet, source_revision_sha256=ONE,
                graph_revision_sha256=FOUR, rack_revision_sha256=FOUR)
        with self.assertRaises(ContractError):
            SamplerPlan.prepare(
                source, spec, sampler_evaluation(192000),
                controlled_clock=packet, source_revision_sha256=TWO,
                graph_revision_sha256=THREE, rack_revision_sha256=FOUR)
        with self.assertRaises(ContractError):
            SamplerPlan.prepare(
                source, spec, sampler_evaluation(192000),
                controlled_clock=packet, source_revision_sha256=ONE,
                graph_revision_sha256=THREE)
        with self.assertRaises(ContractError):
            plan(source, replace(spec, clock=ClockSpec(rate=VirtualRate('4/1'))),
                 packet, 192000)
        with self.assertRaises(ContractError):
            plan(source, spec, packet, 384000).render(
                checkpoint=admitted.checkpoint(120000))
        cp = admitted.checkpoint(120000)
        with self.assertRaises(ContractError):
            admitted.render(checkpoint=replace(cp, events_before=(0,)))
        with self.assertRaises(ContractError):
            admitted.render(checkpoint=replace(cp, previous_capture=((42.,),)))
        with self.assertRaises(ContractError):
            admitted.render(checkpoint=SamplerCheckpoint.from_json(
                SamplerPlan.prepare(
                    source, SonicSpec(clock=ClockSpec(rate=VirtualRate('8000/1'))),
                    sampler_evaluation(192000)).checkpoint(100).to_json()))
        with self.assertRaises(ClockCancelled):
            SamplerPlan.prepare(
                source, spec, sampler_evaluation(192000),
                controlled_clock=packet, source_revision_sha256=ONE,
                graph_revision_sha256=THREE, rack_revision_sha256=FOUR,
                cancelled=lambda: True)
        with self.assertRaises(ContractError):
            plan(source, spec, packet, 192000).render(stop_frame=192001)
        with self.assertRaises(ContractError):
            _owned_grid_frame(Fraction(1,8), Fraction(1,10**18),
                              Fraction(0), 192000, 192000)


    def test_controlled_factory_does_not_admit_executable_subclass(self):
        # Independent review #5833322358: an inherited factory could build an
        # executable subclass whose capture accessor changes the PCM while
        # preserving the canonical render/event/checkpoint identity.
        class CaptureSwap(ControlledSamplerPlan):
            def __getattribute__(self, name):
                value = super().__getattribute__(name)
                if name == 'captures':
                    copied = np.array(value[0], copy=True)
                    copied[1] = 0.625
                    copied.flags.writeable = False
                    return (copied,)
                return value

        source, spec = fixture(), sonic()
        packet = producer(source, spec)
        canonical = plan(source, spec, packet, 192000)
        self.assertEqual(float(canonical.render(24000, 24001).audio[0]), 0.125)
        with self.assertRaises(ContractError):
            CaptureSwap.prepare(
                source, spec, sampler_evaluation(192000),
                frame_count=None, cancelled=None, progress=None,
                source_revision_sha256=ONE, context_sha256=None,
                delivery_rate_hz=None, controlled_clock=packet,
                graph_revision_sha256=THREE, rack_revision_sha256=FOUR)
        # Rejected subclass attempt must leave admitted PCM/identity unchanged.
        self.assertEqual(float(canonical.render(24000, 24001).audio[0]), 0.125)
        self.assertEqual(canonical.checkpoint(24000).render_sha256,
                         canonical.render_sha256)

    def test_public_replace_cannot_forge_capture_or_checkpoint_identity(self):
        source, spec = fixture(), sonic()
        admitted = plan(source, spec, producer(source, spec), 192000)
        original_hash = admitted.render_sha256
        original_checkpoint = admitted.checkpoint(24000)
        original_pcm = admitted.render(24000, 24001).audio
        self.assertEqual(float(admitted.captures[0][1]), 0.125)
        self.assertEqual(float(original_pcm[0]), 0.125)

        # Source-critical adversarial fixture from independent review
        # #5832465615: a second event capture of 0.625 would have made
        # different executable PCM at frame 24000 while keeping the packet,
        # checkpoint and render SHA identical.
        forged_capture = np.array(admitted.captures[0], copy=True)
        forged_capture[1] = 0.625
        forged_capture.flags.writeable = False
        with self.assertRaises(ContractError):
            replace(admitted, captures=(forged_capture,))

        # Ordinary dataclass rebuilding cannot bypass admission by replacing
        # another executable field (event ownership or source), either.
        forged_owners = np.array(admitted._first_frames[0], copy=True)
        forged_owners[1] += 1
        forged_owners.flags.writeable = False
        with self.assertRaises(ContractError):
            replace(admitted, _first_frames=(forged_owners,))
        with self.assertRaises(ContractError):
            replace(admitted, source=fixture(silent=True))
        with self.assertRaises(ContractError):
            ControlledSamplerPlan(**{
                field.name: getattr(admitted, field.name)
                for field in fields(ControlledSamplerPlan)
            })

        self.assertEqual(admitted.render_sha256, original_hash)
        self.assertEqual(admitted.checkpoint(24000), original_checkpoint)
        np.testing.assert_array_equal(admitted.render(24000, 24001).audio,
                                      original_pcm)

    def test_short_and_silent_source_remain_bounded_and_finite(self):
        for short, silent in ((True, False), (False, True)):
            source = fixture(short=short, silent=silent)
            spec = sonic()
            packet = producer(source, spec)
            admitted = plan(source, spec, packet, 192000,
                            frame_count=192000)
            full = admitted.render().audio
            self.assertTrue(np.isfinite(full).all())
            self.assertEqual(full.shape, (192000,))
            if silent:
                np.testing.assert_array_equal(full, np.zeros_like(full))
            if short:
                np.testing.assert_array_equal(full, np.zeros_like(full))



class ControlledConstructionGateTests(unittest.TestCase):
    def test_subclass_factory_refuses_before_packet_or_source_work(self):
        # This must execute on isolated #266 even without #267's packet module.
        class UntrustedPlan(ControlledSamplerPlan):
            pass

        with self.assertRaisesRegex(ContractError, 'exact ControlledSamplerPlan'):
            UntrustedPlan.prepare(
                None, None, None,
                frame_count=None, cancelled=None, progress=None,
                source_revision_sha256=None, context_sha256=None,
                delivery_rate_hz=None, controlled_clock=None,
                graph_revision_sha256=None, rack_revision_sha256=None)

    def test_direct_unadmitted_constructor_refuses_without_packet_dependency(self):
        # Runs even on the isolated #266 branch, where #267 packet tests skip.
        with self.assertRaises(ContractError):
            ControlledSamplerPlan()


class LegacyAbsenceTests(unittest.TestCase):
    def test_absent_packet_does_not_change_legacy_pcm_identity_checkpoint(self):
        source = FrozenInput.from_pcm(
            np.array([0., -0., .25, -.25, .75, 1.], dtype='<f4'), 48000)
        spec = SonicSpec(clock=ClockSpec(rate=VirtualRate('8000/1')))
        policy = sampler_evaluation(48000)
        old = SamplerPlan.prepare(source, spec, policy)
        absent = SamplerPlan.prepare(
            source, spec, policy, controlled_clock=None)
        self.assertIsInstance(absent.checkpoint(3), SamplerCheckpoint)
        self.assertEqual(old.render_sha256, absent.render_sha256)
        self.assertEqual(old.checkpoint(3).to_json(),
                         absent.checkpoint(3).to_json())
        self.assertEqual(old.render().audio.tobytes(),
                         absent.render().audio.tobytes())
        with self.assertRaises(ContractError):
            SamplerPlan.prepare(
                source, spec, policy, graph_revision_sha256=THREE)


if __name__ == '__main__':
    unittest.main()
