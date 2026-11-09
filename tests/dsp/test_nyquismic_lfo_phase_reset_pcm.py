"""NYQ-004 physical-time LFO phase reset: independent event/real PCM oracles."""
from dataclasses import replace
from decimal import Decimal, localcontext
from fractions import Fraction
import unittest

import numpy as np

from zaaggenz_contracts import ContractError
from zaaggenz_contracts.nyquismic import ClockSpec, Point, Reset, SonicSpec, VirtualRate
from zaaggenz_contracts.nyquismic_clock import ClockCancelled
from zaaggenz_contracts.nyquismic_controls import (
    SampledLfoSource, compile_step_clock_events, evaluate_instantaneous_rate,
)
from zaaggenz_contracts.nyquismic_lfo_phase_reset import (
    METHOD, PhaseResetLfoSource, compile_phase_reset_lfo_additive_routes,
)
from zaaggenz_dsp.nyquismic import FrozenInput
from zaaggenz_dsp.nyquismic_controlled_audio_proof import render_controlled_audio_proof


def signal():
    n = np.arange(8000, dtype=np.int64)
    return FrozenInput.from_pcm(
        np.asarray(((n*47) % 263 - 131) / 280., dtype='<f4'), 8000)


class PhaseResetLfoPcmTests(unittest.TestCase):
    def test_free_hz_reset_changes_actual_clock_and_pcm_not_pre_reset(self):
        lfo = SampledLfoSource(mode='free_hz', frequency='1/1',
                               phase_cycles='0/1', grid_s='1/16')
        source = PhaseResetLfoSource(lfo=lfo, resets=(Reset('1/2', '0/1'),))
        saved = source.to_json()
        pair = compile_phase_reset_lfo_additive_routes(
            source, '1/1', route_id='free-reset', depth=40.)
        self.assertEqual(pair.method, METHOD)
        self.assertEqual(pair.source_sha256, source.sha256)
        self.assertEqual(pair.active_resets, 1)
        self.assertEqual([r.id for r in pair.routes],
                         ['free-reset-phase-jumps', 'free-reset-motion'])
        self.assertEqual(pair.routes[0].points[0].time_s, '1/2')
        self.assertEqual(Fraction(pair.routes[0].points[0].value), -1)
        self.assertEqual(PhaseResetLfoSource.from_json(saved), source)

        spec = SonicSpec(instance_id='independent-lfo',
            clock=ClockSpec(rate=VirtualRate('600/1'), routes=pair.routes))
        base_route = lfo.compile_route(
            '1/1', route_id='no-reset', depth=40.)
        no_reset = SonicSpec(instance_id='independent-lfo',
            clock=ClockSpec(rate=VirtualRate('600/1'), routes=(base_route,)))
        for when, expected in (('0/1', 560), ('1/4', 600),
                               ('1/2', 560), ('3/4', 600), ('1/1', 640)):
            self.assertEqual(Fraction(evaluate_instantaneous_rate(
                spec, when).realized_hz), expected)
        # Integrated phase is 300 cycles at t=1/2, not reset with the LFO.
        # On each half-second: f=560+160*u, phi increment=560*u+80*u**2.
        events = compile_step_clock_events(spec, '1/1')
        self.assertEqual(len(events), 600)
        self.assertEqual((events[300].crossing, events[300].epoch,
                          events[300].coordinate_s), (300, 0, Fraction(1, 2)))
        self.assertTrue(all(a.coordinate_s < b.coordinate_s
                            for a, b in zip(events, events[1:])))
        with localcontext() as ctx:
            ctx.prec = 70
            expected_u = Decimal(2) / (
                Decimal(560) + (Decimal(560)**2 + Decimal(320)).sqrt())
            at = events[301].coordinate_s
            actual_u = Decimal(at.numerator)/Decimal(at.denominator) - Decimal(1)/2
            self.assertLess(abs(actual_u-expected_u), Decimal('1e-18'))

        src = signal()
        audio = render_controlled_audio_proof(src, spec)
        baseline = render_controlled_audio_proof(src, no_reset)
        np.testing.assert_array_equal(audio.audio[:4000], baseline.audio[:4000])
        self.assertGreater(float(np.max(np.abs(
            audio.audio[4000:] - baseline.audio[4000:]))), .01)
        self.assertNotEqual(audio.diagnostics['event_ledger_sha256'],
                            baseline.diagnostics['event_ledger_sha256'])
        np.testing.assert_array_equal(
            render_controlled_audio_proof(src, spec, start_frame=4137).audio,
            audio.audio[4137:])
        self.assertEqual(audio.diagnostics['pcm_sha256'],
            render_controlled_audio_proof(src, SonicSpec.from_json(
                spec.to_json())).diagnostics['pcm_sha256'])
        self.assertFalse(audio.diagnostics['product_rack_export_qualified'])
        # The accepted NYQ-002 pathway must not silently adopt this compiler.
        with self.assertRaises(ContractError):
            spec.clock.require_geometry()

    def test_beat_sync_offgrid_tempo_and_phase_reset(self):
        lfo = SampledLfoSource(
            mode='beat_sync', frequency='1/2', grid_s='1/48',
            base_bpm='120/1', phase_cycles='0/1',
            tempo_points=(Point('1/3', '180/1'),))
        source = PhaseResetLfoSource(
            lfo=lfo, resets=(Reset('2/3', '1/4'), Reset('5/4', '0/1')))
        pair = compile_phase_reset_lfo_additive_routes(
            source, '1/1', route_id='beat-reset', depth=30.)
        self.assertEqual(pair.active_resets, 1)
        spec = SonicSpec(clock=ClockSpec(
            rate=VirtualRate('600/1'), routes=pair.routes))
        # Source phase: one-third cycle at tempo change, five-sixths just
        # before reset; source-independent reset then starts at 1/4 cycle.
        for stamp, expected in (('0/1', 570), ('1/3', 610),
                                ('2/3', 600), ('3/4', 615)):
            self.assertEqual(Fraction(evaluate_instantaneous_rate(
                spec, stamp).realized_hz), expected)
        pre = compile_step_clock_events(spec, '2/3')
        full = compile_step_clock_events(spec, '1/1')
        self.assertEqual(
            [(e.crossing, e.coordinate_s) for e in pre],
            [(e.crossing, e.coordinate_s) for e in full[:len(pre)]])
        data = signal()
        rendered = render_controlled_audio_proof(data, spec)
        np.testing.assert_array_equal(
            rendered.audio[3000:],
            render_controlled_audio_proof(data, spec, start_frame=3000).audio)
        self.assertEqual(rendered.diagnostics['pcm_sha256'],
                         render_controlled_audio_proof(data, spec).diagnostics['pcm_sha256'])
        # A later edit to an inactive future reset alters source identity,
        # but not the already compiled short-region physical-time realization.
        edited = replace(source, resets=(
            source.resets[0], Reset('5/4', '1/2')))
        edited_pair = compile_phase_reset_lfo_additive_routes(
            edited, '1/1', route_id='beat-reset', depth=30.)
        self.assertNotEqual(edited.sha256, source.sha256)
        self.assertEqual(edited_pair.routes, pair.routes)

    def test_static_zero_depth_identity_and_invalid_refusal(self):
        lfo = SampledLfoSource(mode='free_hz', frequency='1/1', grid_s='1/16')
        source = PhaseResetLfoSource(lfo=lfo, resets=(Reset('1/2', '0/1'),))
        pair = compile_phase_reset_lfo_additive_routes(
            source, '1/1', route_id='zero', depth=0.)
        plain = SonicSpec(clock=ClockSpec(rate=VirtualRate('600/1')))
        zero = SonicSpec(clock=ClockSpec(
            rate=VirtualRate('600/1'), routes=pair.routes))
        a, b = render_controlled_audio_proof(signal(), plain), render_controlled_audio_proof(signal(), zero)
        np.testing.assert_array_equal(a.audio, b.audio)
        self.assertEqual(a.diagnostics['event_ledger_sha256'],
                         b.diagnostics['event_ledger_sha256'])
        with self.assertRaises(ContractError):
            PhaseResetLfoSource(lfo=lfo, resets=(
                Reset('1/2'), Reset('1/4')))
        with self.assertRaises(ContractError):
            PhaseResetLfoSource(lfo=replace(lfo, origin_s='1/8'),
                                resets=(Reset('1/2'),))
        with self.assertRaises(ContractError):
            compile_phase_reset_lfo_additive_routes(
                source, '0/1', route_id='invalid', depth=40.)
        with self.assertRaises(ContractError):
            compile_phase_reset_lfo_additive_routes(
                source, '1/1', route_id='invalid space', depth=40.)
        with self.assertRaises(ContractError):
            compile_phase_reset_lfo_additive_routes(
                source, '1/1', route_id='bad', depth=float('nan'))
        with self.assertRaises(ClockCancelled):
            compile_phase_reset_lfo_additive_routes(
                source, '1/1', route_id='cancel', depth=40.,
                cancelled=lambda: True)
        with self.assertRaises(ContractError):
            compile_phase_reset_lfo_additive_routes(
                replace(source, lfo=replace(lfo, grid_s='1/1024')),
                '1/1', route_id='over-budget', depth=40.)


if __name__ == '__main__':
    unittest.main()
