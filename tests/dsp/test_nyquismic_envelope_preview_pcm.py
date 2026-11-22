"""NYQ-004: partial triggered-ADSR previews reach real physical-clock PCM."""
from dataclasses import replace
from fractions import Fraction
import unittest

import numpy as np

from zaaggenz_contracts import ContractError
from zaaggenz_contracts.nyquismic import ClockSpec, SonicSpec, VirtualRate
from zaaggenz_contracts.nyquismic_clock import ClockCancelled
from zaaggenz_contracts.nyquismic_controls import (
    EnvelopeGate, TriggeredEnvelopeSource, compile_step_clock_events,
    evaluate_instantaneous_rate,
)
from zaaggenz_dsp.nyquismic import FrozenInput
from zaaggenz_dsp.nyquismic_controlled_audio_proof import render_controlled_audio_proof


def source_pcm(frames):
    i = np.arange(frames, dtype=np.int64)
    return FrozenInput.from_pcm(
        np.asarray(((i * 37) % 257 - 128) / 300., dtype='<f4'), 8000)


def sonic(route=None):
    return SonicSpec(clock=ClockSpec(
        rate=VirtualRate('360/1'),
        routes=() if route is None else (route,)))


class EnvelopePreviewPcmTests(unittest.TestCase):
    def source(self):
        return TriggeredEnvelopeSource(
            origin_s='1/4', attack_s='1/4', decay_s='1/4',
            sustain='1/2', release_s='1/4',
            gates=(EnvelopeGate('1/4', '3/4'),
                   EnvelopeGate('5/4', '3/2')))

    def test_pre_onset_and_mid_attack_previews_preserve_full_pcm(self):
        source = self.source()
        saved = source.to_json()
        early = source.compile_route('1/8', route_id='env', depth=160.)
        short = source.compile_route('3/8', route_id='env', depth=160.)
        full = source.compile_route('2/1', route_id='env', depth=160.)
        self.assertEqual((early.initial, early.points), ('0/1', ()))
        self.assertEqual([p.time_s for p in short.points],
                         ['1/4', '3/8'])
        self.assertEqual([p.value for p in short.points],
                         ['0/1', '1/2'])
        self.assertEqual(source.to_json(), saved)
        self.assertEqual(source, TriggeredEnvelopeSource.from_json(saved))
        self.assertEqual(short, source.compile_route(
            '3/8', route_id='env', depth=160.))

        base = sonic()
        early_spec, short_spec, full_spec = sonic(early), sonic(short), sonic(full)
        for time in ('0/1', '1/8', '1/4', '5/16', '3/8'):
            expected = Fraction(360)
            if Fraction(time) >= Fraction(1, 4):
                expected += 160 * source.value_at(time)
            self.assertEqual(Fraction(evaluate_instantaneous_rate(
                short_spec, time).realized_hz), expected)
            self.assertEqual(Fraction(evaluate_instantaneous_rate(
                full_spec, time).realized_hz), expected)

        # Independent phase integral: 360 * (1/4) + mean(360, 440) * (1/8)
        # = 90 + 50 = 140 exact physical cycles at the short preview end.
        short_events = compile_step_clock_events(short_spec, '3/8')
        full_events = compile_step_clock_events(full_spec, '2/1')
        self.assertEqual(len(short_events), 140)
        self.assertEqual(short_events, full_events[:140])
        self.assertEqual((short_events[90].crossing,
                          short_events[90].coordinate_s),
                         (90, Fraction(1, 4)))
        self.assertTrue(all(a.coordinate_s < b.coordinate_s
                            for a, b in zip(short_events, short_events[1:])))

        a = render_controlled_audio_proof(source_pcm(1000), early_spec)
        b = render_controlled_audio_proof(source_pcm(3000), short_spec)
        c = render_controlled_audio_proof(source_pcm(16000), full_spec)
        dry = render_controlled_audio_proof(source_pcm(3000), base)
        np.testing.assert_array_equal(a.audio, dry.audio[:1000])
        np.testing.assert_array_equal(a.audio, c.audio[:1000])
        np.testing.assert_array_equal(b.audio, c.audio[:3000])
        np.testing.assert_array_equal(b.audio[:2000], dry.audio[:2000])
        self.assertGreater(float(np.max(np.abs(
            b.audio[2000:] - dry.audio[2000:]))), .01)
        self.assertEqual(b.diagnostics['event_ledger_sha256'],
                         render_controlled_audio_proof(
                             source_pcm(3000), short_spec).diagnostics['event_ledger_sha256'])
        self.assertFalse(b.diagnostics['product_rack_export_qualified'])

        zero = source.compile_route('3/8', route_id='no-depth', depth=0.)
        self.assertEqual(
            render_controlled_audio_proof(source_pcm(3000), sonic(zero)).diagnostics[
                'event_ledger_sha256'],
            dry.diagnostics['event_ledger_sha256'])
        edited_future = replace(source, gates=(
            source.gates[0], EnvelopeGate('3/2', '7/4')))
        self.assertNotEqual(source.sha256, edited_future.sha256)
        self.assertEqual(short, edited_future.compile_route(
            '3/8', route_id='env', depth=160.))

    def test_mid_release_and_interrupted_attack_endpoint(self):
        source = self.source()
        partial = source.compile_route('7/8', route_id='release', depth=80.)
        full = source.compile_route('2/1', route_id='release', depth=80.)
        self.assertEqual(partial.points[-1].time_s, '7/8')
        self.assertEqual(partial.points[-1].value, '1/4')
        for at in ('1/8', '1/4', '3/8', '1/2', '3/4', '13/16', '7/8'):
            a = evaluate_instantaneous_rate(sonic(partial), at).realized_hz
            b = evaluate_instantaneous_rate(sonic(full), at).realized_hz
            self.assertEqual(a, b)
        a = render_controlled_audio_proof(source_pcm(7000), sonic(partial))
        b = render_controlled_audio_proof(source_pcm(16000), sonic(full))
        np.testing.assert_array_equal(a.audio, b.audio[:7000])

        interrupted = replace(source, gates=(EnvelopeGate('1/4', '3/8'),))
        route = interrupted.compile_route('1/2', route_id='interrupted', depth=80.)
        self.assertEqual([(p.time_s, p.value) for p in route.points],
                         [('1/4', '0/1'), ('3/8', '1/2'), ('1/2', '1/4')])
        self.assertEqual(Fraction(evaluate_instantaneous_rate(
            sonic(route), '1/2').realized_hz), Fraction(380))

    def test_invalid_extent_budget_cancellation_and_default_guards(self):
        source = self.source()
        with self.assertRaises(ContractError):
            source.compile_route('-1/100', route_id='bad', depth=80.)
        with self.assertRaises(ContractError):
            source.compile_route('3601/1', route_id='bad', depth=80.)
        with self.assertRaises(ContractError):
            source.compile_route('3/8', route_id='bad', depth=float('nan'))
        with self.assertRaises(ClockCancelled):
            source.compile_route('3/8', route_id='cancel',
                                 depth=80., cancelled=lambda: True)
        # A future inactive source still has to validate; no invalid saved
        # gate can be ignored simply because a preview ends before its onset.
        with self.assertRaises(ContractError):
            replace(source, gates=(EnvelopeGate('1/4', '3/4'),
                                   EnvelopeGate('1/2', '3/2')))
        self.assertEqual(source.compile_route(
            '0/1', route_id='neutral', depth=80.).points, ())


if __name__ == '__main__':
    unittest.main()
