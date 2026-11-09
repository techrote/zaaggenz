"""NYQ-004 beat-grid sequencer: physical clock crossings and numerical PCM."""
from dataclasses import replace
from fractions import Fraction
import unittest

import numpy as np

from zaaggenz_contracts import ContractError
from zaaggenz_contracts.nyquismic import ClockSpec, Point, SonicSpec, VirtualRate
from zaaggenz_contracts.nyquismic_clock import ClockCancelled
from zaaggenz_contracts.nyquismic_beat_steps import BeatStepSource, METHOD
from zaaggenz_contracts.nyquismic_controls import (
    compile_step_clock_events, evaluate_instantaneous_rate,
)
from zaaggenz_dsp.nyquismic import FrozenInput
from zaaggenz_dsp.nyquismic_controlled_audio_proof import render_controlled_audio_proof


def target(rate=8000):
    n = np.arange(rate, dtype=np.int64)
    return FrozenInput.from_pcm(
        np.asarray(((n*47) % 263 - 131) / 280., dtype='<f4'), rate)


def sonic(route=None):
    return SonicSpec(instance_id='beat-step-physical-control',
                     clock=ClockSpec(rate=VirtualRate('360/1'),
                                     routes=() if route is None else (route,)))


class BeatStepPhysicalAudioTests(unittest.TestCase):
    def test_beat_tempo_transition_changes_actual_events_and_pcm(self):
        # Beat accumulator: 120 BPM through 1/2s gives 1 beat; then
        # 180 BPM gives another 1.5 beats before 1s. The half-beat steps
        # are exactly 1/4, 1/2, 2/3, 5/6 and 1 seconds.
        source = BeatStepSource(
            step_beats='1/2', levels=('-1/1', '1/1'),
            tempo_points=(Point('1/2', '180/1'),))
        route = source.compile_route('1/1', route_id='musical-grid', depth=80.)
        self.assertEqual(METHOD, 'nyq.beat-grid-step-source.v1')
        self.assertEqual(route.interpolation, 'step')
        self.assertEqual(tuple((p.time_s, p.value) for p in route.points),
                         (('1/4', '1/1'), ('1/2', '-1/1'),
                          ('2/3', '1/1'), ('5/6', '-1/1'),
                          ('1/1', '1/1')))
        self.assertEqual(BeatStepSource.from_json(source.to_json()).sha256,
                         source.sha256)
        self.assertEqual(source.value_at('1/2'), Fraction(-1))
        self.assertEqual(source.value_at('2/3'), Fraction(1))
        spec = sonic(route)
        for at, hz in (('0/1', 280), ('1/4', 440),
                       ('1/2', 280), ('2/3', 440), ('5/6', 280)):
            self.assertEqual(Fraction(evaluate_instantaneous_rate(
                spec, at).realized_hz), hz)
        events = compile_step_clock_events(spec, '1/1')
        # Integral of the declared rate is exactly 1040/3 cycles.
        # Half-open integer crossings k=0..346 therefore give 347 events.
        self.assertEqual(len(events), 347)
        self.assertEqual(events[70].coordinate_s, Fraction(1, 4))
        self.assertEqual(events[180].coordinate_s, Fraction(1, 2))
        self.assertTrue(all(a.coordinate_s < b.coordinate_s
                            for a, b in zip(events, events[1:])))
        self.assertTrue(all(e.coordinate_error_bound_s == 0 for e in events))

        no_tempo = replace(source, tempo_points=())
        old = sonic(no_tempo.compile_route('1/1', route_id='musical-grid', depth=80.))
        pcm = target()
        actual = render_controlled_audio_proof(pcm, spec)
        earlier = render_controlled_audio_proof(pcm, old)
        replay = render_controlled_audio_proof(pcm, SonicSpec.from_json(spec.to_json()))
        region = render_controlled_audio_proof(pcm, spec, start_frame=3200)
        # No phase reset or retrospective tempo/lookahead leakage.
        np.testing.assert_array_equal(actual.audio[:5200], earlier.audio[:5200])
        self.assertGreater(float(np.max(np.abs(
            actual.audio[5600:] - earlier.audio[5600:]))), .01)
        self.assertNotEqual(actual.diagnostics['event_ledger_sha256'],
                            earlier.diagnostics['event_ledger_sha256'])
        self.assertNotEqual(actual.diagnostics['pcm_sha256'],
                            earlier.diagnostics['pcm_sha256'])
        np.testing.assert_array_equal(actual.audio, replay.audio)
        np.testing.assert_array_equal(actual.audio[3200:], region.audio)
        self.assertFalse(actual.diagnostics['product_rack_export_qualified'])
        # Physical event ledger is independent of the native PCM grid chosen
        # for this limited proof bridge (not a full evaluation-convergence claim).
        high_grid = render_controlled_audio_proof(target(16000), spec)
        self.assertEqual(actual.diagnostics['event_ledger_sha256'],
                         high_grid.diagnostics['event_ledger_sha256'])

    def test_delayed_source_and_zero_depth_do_not_retime_project(self):
        source = BeatStepSource(origin_s='1/8', step_beats='1/4',
                                phase_steps=1, levels=('-1/1', '1/1'))
        route = source.compile_route('1/2', route_id='delayed-grid', depth=60.)
        self.assertEqual(route.initial, '0/1')
        self.assertEqual(tuple((p.time_s, p.value) for p in route.points[:2]),
                         (('1/8', '1/1'), ('1/4', '-1/1')))
        spec = sonic(route)
        self.assertEqual(Fraction(evaluate_instantaneous_rate(
            spec, '1/10').realized_hz), 360)
        self.assertEqual(Fraction(evaluate_instantaneous_rate(
            spec, '1/8').realized_hz), 420)
        self.assertEqual(Fraction(evaluate_instantaneous_rate(
            spec, '1/4').realized_hz), 300)
        pcm = target()
        active = render_controlled_audio_proof(pcm, spec)
        static = render_controlled_audio_proof(pcm, sonic())
        np.testing.assert_array_equal(active.audio[:1000], static.audio[:1000])
        self.assertGreater(float(np.max(np.abs(
            active.audio[1400:3500] - static.audio[1400:3500]))), .01)
        no_depth = sonic(replace(route, depth=0.))
        np.testing.assert_array_equal(
            render_controlled_audio_proof(pcm, no_depth).audio, static.audio)
        self.assertEqual(
            [e.coordinate_s for e in compile_step_clock_events(no_depth, '1/1')],
            [e.coordinate_s for e in compile_step_clock_events(sonic(), '1/1')])

    def test_delayed_onset_neutral_short_preview_and_future_full_pcm(self):
        # Render a legitimate 1/2-second preview with a musical source
        # scheduled to start at 3/4 second; no future beats should leak.
        beat = BeatStepSource(
            origin_s='3/4', step_beats='1/4',
            levels=('-1/1', '1/1'),
            tempo_points=(Point('7/8', '180/1'),),
        )
        short = beat.compile_route('1/2', route_id='future-beat', depth=80.)
        self.assertEqual((short.initial, short.points), ('0/1', ()))
        self.assertEqual(short.sha256, beat.compile_route(
            '1/2', route_id='future-beat', depth=80.).sha256)
        octave = beat.compile_route('1/2', route_id='future-octave',
                                    depth=1., mapping='log2_ratio')
        self.assertEqual((octave.initial, octave.points), ('0/1', ()))
        full_asset = target()
        preview_asset = FrozenInput.from_pcm(full_asset.pcm[:4000].copy(), 8000)
        clean_preview = render_controlled_audio_proof(preview_asset, sonic())
        additive_preview = render_controlled_audio_proof(preview_asset, sonic(short))
        octave_preview = render_controlled_audio_proof(preview_asset, sonic(octave))
        np.testing.assert_array_equal(additive_preview.audio, clean_preview.audio)
        np.testing.assert_array_equal(octave_preview.audio, clean_preview.audio)
        self.assertEqual(additive_preview.diagnostics['full_output_frames'], 4000)

        # A complete render still activates the scheduled beat, and its
        # pre-onset prefix is precisely the short preview's PCM.
        full = beat.compile_route('1/1', route_id='future-beat', depth=80.)
        self.assertEqual(full.points[0].time_s, '3/4')
        active = render_controlled_audio_proof(full_asset, sonic(full))
        baseline = render_controlled_audio_proof(full_asset, sonic())
        np.testing.assert_array_equal(active.audio[:4000], additive_preview.audio)
        self.assertGreater(float(np.max(np.abs(
            active.audio[6500:] - baseline.audio[6500:]))), .01)
        self.assertEqual(beat.value_at('7/8'), Fraction(1))
        with self.assertRaises(ContractError):
            beat.compile_route('-1/8', route_id='negative-time', depth=80.)
        with self.assertRaises(ClockCancelled):
            beat.compile_route('1/2', route_id='cancelled-before-onset',
                               depth=80., cancelled=lambda: True)

    def test_reject_invalid_bpm_budget_and_cancel_without_partial_route(self):
        with self.assertRaises(ContractError):
            BeatStepSource(tempo_points=(Point('1/2', '180/1'),
                                         Point('1/2', '120/1')))
        with self.assertRaises(ContractError):
            BeatStepSource(base_bpm='361/1')
        with self.assertRaises(ContractError):
            BeatStepSource(levels=('3/2',))
        with self.assertRaises(ContractError):
            BeatStepSource(phase_steps=2)
        with self.assertRaises(ContractError):
            BeatStepSource.from_json(BeatStepSource().to_json().replace(
                '"phase_steps":0', '"phase_steps":0,"foreign":true'))
        with self.assertRaises(ContractError):
            BeatStepSource(base_bpm='360/1', step_beats='1/1024').compile_route(
                '1/1', route_id='too-many-steps', depth=20.)
        steps = BeatStepSource(base_bpm='360/1', step_beats='1/32')
        checks = [0]

        def cancel_midway():
            checks[0] += 1
            return checks[0] > 3

        with self.assertRaises(ClockCancelled):
            steps.compile_route('1/1', route_id='cancelled', depth=20.,
                                cancelled=cancel_midway)
        good = steps.compile_route('1/1', route_id='replay', depth=20.)
        self.assertEqual(good.sha256,
            steps.compile_route('1/1', route_id='replay', depth=20.).sha256)


if __name__ == '__main__':
    unittest.main()
