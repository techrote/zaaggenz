"""NYQ-004: delayed nonzero-phase LFO executes on the real physical event clock."""
from dataclasses import replace
from decimal import Decimal, localcontext
from fractions import Fraction
import unittest

import numpy as np

from zaaggenz_contracts import ContractError
from zaaggenz_contracts.nyquismic import ClockSpec, Point, SonicSpec, VirtualRate
from zaaggenz_contracts.nyquismic_clock import ClockCancelled
from zaaggenz_contracts.nyquismic_controls import (
    SampledLfoSource, compile_step_clock_events, evaluate_instantaneous_rate,
)
from zaaggenz_contracts.nyquismic_lfo_onset import (
    METHOD, compile_delayed_lfo_additive_routes,
)
from zaaggenz_dsp.nyquismic import FrozenInput
from zaaggenz_dsp.nyquismic_controlled_audio_proof import render_controlled_audio_proof


def signal(n):
    i = np.arange(n, dtype=np.int64)
    return FrozenInput.from_pcm(
        np.asarray(((i * 31) % 251 - 125) / 300., dtype='<f4'), 8000)


class DelayedLfoPcmTests(unittest.TestCase):
    def test_nonzero_onset_integrates_phase_and_changes_real_pcm_without_leak(self):
        source = SampledLfoSource(
            origin_s='1/8', phase_cycles='0/1', frequency='1/1',
            grid_s='1/16')
        # The old single-route authoring must continue to fail closed.
        with self.assertRaisesRegex(ContractError, 'zero-level onset'):
            source.compile_route('5/8', route_id='unsupported', depth=80.)
        pack = compile_delayed_lfo_additive_routes(
            source, '5/8', route_id='lfo-start', depth=80.)
        self.assertEqual(pack.method, METHOD)
        self.assertEqual(pack.source_sha256, source.sha256)
        self.assertEqual(pack.onset_s, '1/8')
        self.assertEqual([r.id for r in pack.routes],
                         ['lfo-start-onset', 'lfo-start-motion'])
        spec = SonicSpec(instance_id='lfo-a',
            clock=ClockSpec(rate=VirtualRate('360/1'), routes=pack.routes))
        steady = SonicSpec(instance_id='lfo-a',
            clock=ClockSpec(rate=VirtualRate('360/1')))
        for when in ('0/1', '1/16', '1/8', '1/4', '3/8', '1/2', '5/8'):
            measured = Fraction(evaluate_instantaneous_rate(spec, when).realized_hz)
            expected = Fraction(360) if Fraction(when) < Fraction(1, 8) else (
                Fraction(360) + 80 * source.value_at(when))
            self.assertEqual(measured, expected)
        events = compile_step_clock_events(spec, '5/8')
        self.assertEqual(len(events), 225)
        self.assertEqual((events[45].crossing, events[45].coordinate_s),
                         (45, Fraction(1, 8)))
        self.assertTrue(all(a.coordinate_s < b.coordinate_s
                            for a, b in zip(events, events[1:])))
        # Independent first post-onset crossing: phi=45+280*u+160*u*u.
        with localcontext() as ctx:
            ctx.prec = 70
            expected_u = Decimal(2) / (
                Decimal(280) + (Decimal(280)**2 + Decimal(640)).sqrt())
            actual_u = Decimal(events[46].coordinate_s.numerator) / (
                Decimal(events[46].coordinate_s.denominator)) - Decimal(1)/8
            self.assertLess(abs(actual_u - expected_u), Decimal('1e-18'))
        src_pcm = signal(5000)
        controlled = render_controlled_audio_proof(src_pcm, spec)
        baseline = render_controlled_audio_proof(src_pcm, steady)
        region = render_controlled_audio_proof(src_pcm, spec, start_frame=1000)
        np.testing.assert_array_equal(controlled.audio[:1000],
                                      baseline.audio[:1000])
        self.assertGreater(float(np.max(np.abs(
            controlled.audio[1000:] - baseline.audio[1000:]))), .01)
        np.testing.assert_array_equal(controlled.audio[1000:], region.audio)
        self.assertNotEqual(controlled.diagnostics['event_ledger_sha256'],
                            baseline.diagnostics['event_ledger_sha256'])
        self.assertEqual(controlled.diagnostics['pcm_sha256'],
                         render_controlled_audio_proof(src_pcm, spec).diagnostics['pcm_sha256'])
        self.assertFalse(controlled.diagnostics['product_rack_export_qualified'])

    def test_beat_sync_offgrid_tempo_and_zero_depth_are_exact(self):
        source = SampledLfoSource(
            mode='beat_sync', frequency='1/2', origin_s='1/8',
            phase_cycles='0/1', grid_s='1/32', base_bpm='120/1',
            tempo_points=(Point('1/3', '180/1'),))
        original = source.to_json()
        pair = compile_delayed_lfo_additive_routes(
            source, '3/4', route_id='tempo-start', depth=40.)
        spec = SonicSpec(clock=ClockSpec(
            rate=VirtualRate('400/1'), routes=pair.routes))
        for when in ('0/1', '1/16', '1/8', '1/5', '1/3', '5/12', '7/12', '3/4'):
            actual = Fraction(evaluate_instantaneous_rate(spec, when).realized_hz)
            expected = 400 if Fraction(when) < Fraction(1, 8) else (
                400 + 40 * source.value_at(when))
            self.assertEqual(actual, expected)
        full = render_controlled_audio_proof(signal(6000), spec)
        suffix = render_controlled_audio_proof(signal(6000), spec, start_frame=1403)
        np.testing.assert_array_equal(full.audio[1403:], suffix.audio)
        self.assertEqual(source.to_json(), original)
        repeat = compile_delayed_lfo_additive_routes(
            source, '3/4', route_id='tempo-start', depth=40.)
        self.assertEqual(tuple(r.to_json() for r in pair.routes),
                         tuple(r.to_json() for r in repeat.routes))
        zero = compile_delayed_lfo_additive_routes(
            source, '3/4', route_id='tempo-zero', depth=0.)
        dry = SonicSpec(clock=ClockSpec(rate=VirtualRate('400/1')))
        silent_control = replace(dry, clock=replace(dry.clock, routes=zero.routes))
        self.assertEqual(
            render_controlled_audio_proof(signal(6000), silent_control).diagnostics['event_ledger_sha256'],
            render_controlled_audio_proof(signal(6000), dry).diagnostics['event_ledger_sha256'])

    def test_invalid_and_cancelled_sources_fail_closed(self):
        source = SampledLfoSource(origin_s='1/8', phase_cycles='0/1',
                                  grid_s='1/32')
        with self.assertRaises(ContractError):
            compile_delayed_lfo_additive_routes(
                source, '1/2', route_id='broken', depth=float('nan'))
        with self.assertRaises(ContractError):
            compile_delayed_lfo_additive_routes(
                source, '1/2', route_id='bad id spaces', depth=1.)
        with self.assertRaises(ContractError):
            compile_delayed_lfo_additive_routes(
                replace(source, origin_s='0/1'), '1/2',
                route_id='no-delay', depth=1.)
        with self.assertRaises(ContractError):
            compile_delayed_lfo_additive_routes(
                source, '1/16', route_id='past', depth=1.)
        with self.assertRaises(ClockCancelled):
            compile_delayed_lfo_additive_routes(
                source, '1/2', route_id='cancel', depth=1.,
                cancelled=lambda: True)
        # No silent decimation when translation adds a counted onset point.
        crowded = replace(source, grid_s='1/1024')
        with self.assertRaises(ContractError):
            compile_delayed_lfo_additive_routes(
                crowded, '1/2', route_id='over-budget', depth=1.)


if __name__ == '__main__':
    unittest.main()
