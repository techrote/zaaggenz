"""NYQ-004 beat-synchronised integral-octave steps into physical events/PCM.

The independent rational oracle checks real sampled output and does not
claim a general exponential-phase integrator or production SamplerPlan.
"""
from dataclasses import replace
from fractions import Fraction
import unittest

import numpy as np

from zaaggenz_contracts import ContractError
from zaaggenz_contracts.nyquismic import (
    ClockSpec, Point, SonicSpec, UnsupportedNyquismic, VirtualRate,
)
from zaaggenz_contracts.nyquismic_beat_steps import BeatStepSource
from zaaggenz_contracts.nyquismic_clock import ClockCancelled
from zaaggenz_contracts.nyquismic_controls import (
    compile_step_clock_events, evaluate_instantaneous_rate,
)
from zaaggenz_dsp.nyquismic import FrozenInput
from zaaggenz_dsp.nyquismic_controlled_audio_proof import render_controlled_audio_proof


def source_pcm(rate=8000):
    frames = np.arange(rate, dtype=np.int64)
    signal = np.asarray(((frames * 47) % 263 - 131) / 280., dtype='<f4')
    return FrozenInput.from_pcm(signal, rate)


def musical_source():
    return BeatStepSource(
        step_beats='1/2', levels=('-1/1', '1/1'),
        tempo_points=(Point('1/2', '180/1'),),
    )


def clock_spec(route):
    return SonicSpec(
        instance_id='tempo-octave-physical',
        clock=ClockSpec(rate=VirtualRate('200/1'),
                        routes=() if route is None else (route,)),
    )


class BeatOctavePhysicalPcmTests(unittest.TestCase):
    def test_tempo_synced_octaves_have_exact_crossings_and_real_pcm(self):
        source = musical_source()
        route = source.compile_route('1/1', route_id='musical-octaves',
                                     depth=1., mapping='log2_ratio')
        self.assertEqual(route.mapping, 'log2_ratio')
        self.assertEqual(route.interpolation, 'step')
        self.assertEqual(
            tuple((p.time_s, p.value) for p in route.points),
            (('1/4', '1/1'), ('1/2', '-1/1'), ('2/3', '1/1'),
             ('5/6', '-1/1'), ('1/1', '1/1')),
        )
        self.assertEqual(BeatStepSource.from_json(source.to_json()), source)
        spec = clock_spec(route)
        for at, hz in (('0/1', 100), ('1/4', 400), ('1/2', 100),
                       ('2/3', 400), ('5/6', 100)):
            self.assertEqual(
                Fraction(evaluate_instantaneous_rate(spec, at).realized_hz),
                Fraction(hz),
            )
        events = compile_step_clock_events(spec, '1/1')
        self.assertEqual(len(events), 225)
        self.assertEqual(
            [events[k].coordinate_s for k in (0, 25, 125, 224)],
            [Fraction(0), Fraction(1, 4),
             Fraction(1, 2), Fraction(99, 100)],
        )
        self.assertTrue(all(
            a.coordinate_s < b.coordinate_s for a, b in zip(events, events[1:])
        ))
        self.assertTrue(all(e.coordinate_error_bound_s == 0 for e in events))
        self.assertTrue(all(e.epoch == 0 for e in events))

        constant_tempo = replace(source, tempo_points=())
        other = clock_spec(constant_tempo.compile_route(
            '1/1', route_id='musical-octaves', depth=1.,
            mapping='log2_ratio'))
        pcm = source_pcm()
        active = render_controlled_audio_proof(pcm, spec)
        unchanged_tempo = render_controlled_audio_proof(pcm, other)
        np.testing.assert_array_equal(
            active.audio[:4000], unchanged_tempo.audio[:4000])
        self.assertGreater(float(np.max(np.abs(
            active.audio[5500:] - unchanged_tempo.audio[5500:]))), .01)
        self.assertNotEqual(active.diagnostics['pcm_sha256'],
                            unchanged_tempo.diagnostics['pcm_sha256'])
        self.assertEqual(active.diagnostics['event_count_by_channel'], [225])
        replay = render_controlled_audio_proof(
            pcm, SonicSpec.from_json(spec.to_json()))
        np.testing.assert_array_equal(active.audio, replay.audio)
        suffix = render_controlled_audio_proof(
            pcm, spec, start_frame=3333)
        np.testing.assert_array_equal(active.audio[3333:], suffix.audio)
        high_grid = render_controlled_audio_proof(source_pcm(16000), spec)
        self.assertEqual(active.diagnostics['event_ledger_sha256'],
                         high_grid.diagnostics['event_ledger_sha256'])
        self.assertFalse(active.diagnostics['product_rack_export_qualified'])

    def test_integral_fractional_levels_zero_depth_and_refusal(self):
        source = musical_source()
        halves = replace(source, levels=('-1/2', '1/2'))
        half_route = halves.compile_route(
            '1/1', route_id='musical-octaves', depth=2.,
            mapping='log2_ratio')
        whole_route = source.compile_route(
            '1/1', route_id='musical-octaves', depth=1.,
            mapping='log2_ratio')
        a = compile_step_clock_events(clock_spec(half_route), '1/1')
        b = compile_step_clock_events(clock_spec(whole_route), '1/1')
        self.assertEqual([e.coordinate_s for e in a],
                         [e.coordinate_s for e in b])
        quiet_route = source.compile_route(
            '1/1', route_id='zero-depth', depth=0.,
            mapping='log2_ratio')
        static = clock_spec(None)
        zeros = clock_spec(quiet_route)
        self.assertEqual(
            [e.coordinate_s for e in compile_step_clock_events(zeros, '1/1')],
            [e.coordinate_s for e in compile_step_clock_events(static, '1/1')],
        )
        np.testing.assert_array_equal(
            render_controlled_audio_proof(source_pcm(), zeros).audio,
            render_controlled_audio_proof(source_pcm(), static).audio,
        )
        self.assertEqual(
            source.compile_route('1/2', route_id='legacy', depth=20.).mapping,
            'add_hz',
        )
        with self.assertRaisesRegex(UnsupportedNyquismic, 'integral log2'):
            halves.compile_route('1/1', route_id='fractional',
                                 depth=1., mapping='log2_ratio')
        with self.assertRaises(ContractError):
            source.compile_route('1/1', route_id='unsupported',
                                 depth=1., mapping='mystery')
        with self.assertRaises(ClockCancelled):
            source.compile_route('1/1', route_id='cancelled', depth=1.,
                                 mapping='log2_ratio', cancelled=lambda: True)
        with self.assertRaises(UnsupportedNyquismic):
            clock_spec(whole_route).clock.require_geometry()


if __name__ == '__main__':
    unittest.main()
