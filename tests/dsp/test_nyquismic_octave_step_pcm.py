"""NYQ-004 exact stepped octave clocks must drive real native-grid PCM.

This bounds a genuine physical-time log2 subset; it does NOT claim a general
fractional-exponential clock, registered sampler or product delivery adapter.
"""
from dataclasses import replace
from fractions import Fraction
import unittest

import numpy as np

from zaaggenz_contracts import ContractError
from zaaggenz_contracts.nyquismic import (
    ClockSpec, JitterSpec, ModulationRoute, Point, RateQuantizer, SonicSpec,
    UnsupportedNyquismic, VirtualRate,
)
from zaaggenz_contracts.nyquismic_controls import (
    STEP_LOG2_METHOD, compile_step_clock_events, evaluate_instantaneous_rate,
)
from zaaggenz_dsp.nyquismic import FrozenInput
from zaaggenz_dsp.nyquismic_controlled_audio_proof import render_controlled_audio_proof


def frozen_input(channels=1, frames=8000):
    i = np.arange(frames, dtype=np.int64)
    samples = np.asarray(((i * 37) % 253 - 126) / 290., dtype='<f4')
    if channels == 2:
        samples = np.column_stack((samples, samples)).astype('<f4')
    return FrozenInput.from_pcm(samples, 8000)


def octave_spec(*, channels=1):
    octave = ModulationRoute(
        id='four-section-octaves', mapping='log2_ratio', depth=1.,
        initial='0/1',
        points=(Point('1/4', '1/1'), Point('1/2', '-1/1'),
                Point('3/4', '0/1')),
        interpolation='step',
    )
    return SonicSpec(channels=channels, instance_id='source-clock',
                     clock=ClockSpec(rate=VirtualRate('200/1'),
                                     routes=(octave,)))


class OctaveStepClockPcmTests(unittest.TestCase):
    def test_exact_octave_phase_crossings_and_real_pcm_are_source_bound(self):
        self.assertEqual(STEP_LOG2_METHOD, 'nyq.exact-integer-octave-step-clock.v1')
        source, spec = frozen_input(), octave_spec()
        original = spec.to_json()
        for time, expected in (('0/1', 200), ('1/8', 200),
                               ('1/4', 400), ('3/8', 400),
                               ('1/2', 100), ('5/8', 100),
                               ('3/4', 200), ('7/8', 200)):
            self.assertEqual(Fraction(evaluate_instantaneous_rate(
                spec, time).realized_hz), expected)

        events = compile_step_clock_events(spec, '1/1')
        self.assertEqual(len(events), 225)
        self.assertEqual([events[i].coordinate_s for i in (0, 50, 150, 175)],
                         [Fraction(0), Fraction(1, 4),
                          Fraction(1, 2), Fraction(3, 4)])
        for k, event in enumerate(events):
            expected = (Fraction(k, 200) if k < 50 else
                        Fraction(1, 4) + Fraction(k-50, 400) if k < 150 else
                        Fraction(1, 2) + Fraction(k-150, 100) if k < 175 else
                        Fraction(3, 4) + Fraction(k-175, 200))
            self.assertEqual((event.index, event.crossing, event.epoch),
                             (k, k, 0))
            self.assertEqual(event.coordinate_s, expected)
            self.assertEqual(event.coordinate_error_bound_s, 0)
        self.assertTrue(all(a.coordinate_s < b.coordinate_s
                            for a, b in zip(events, events[1:])))

        controlled = render_controlled_audio_proof(source, spec)
        static_spec = replace(spec, clock=ClockSpec(rate=VirtualRate('200/1')))
        static = render_controlled_audio_proof(source, static_spec)
        np.testing.assert_array_equal(controlled.audio[:2000], static.audio[:2000])
        self.assertGreater(float(np.max(np.abs(
            controlled.audio[2000:] - static.audio[2000:]))), .01)
        self.assertEqual(controlled.diagnostics['event_count_by_channel'], [225])
        self.assertNotEqual(controlled.diagnostics['event_ledger_sha256'],
                            static.diagnostics['event_ledger_sha256'])
        reopened = SonicSpec.from_json(original)
        replay = render_controlled_audio_proof(source, reopened)
        self.assertEqual(replay.diagnostics['pcm_sha256'],
                         controlled.diagnostics['pcm_sha256'])
        region = render_controlled_audio_proof(source, spec, start_frame=2999)
        np.testing.assert_array_equal(region.audio, controlled.audio[2999:])
        self.assertFalse(controlled.diagnostics['product_rack_export_qualified'])

    def test_ordered_add_and_log2_have_noncommuting_real_pcm(self):
        plus = ModulationRoute(id='plus', mapping='add_hz',
                               initial='1/1', depth=30.)
        octave = ModulationRoute(id='octave', mapping='log2_ratio',
                                 initial='1/1', depth=1.)
        a = SonicSpec(clock=ClockSpec(rate=VirtualRate('200/1'),
                                     routes=(plus, octave)))
        b = replace(a, clock=ClockSpec(rate=VirtualRate('200/1'),
                                      routes=(octave, plus)))
        self.assertEqual(len(compile_step_clock_events(a, '1/5')), 92)
        self.assertEqual(len(compile_step_clock_events(b, '1/5')), 86)
        self.assertEqual(Fraction(evaluate_instantaneous_rate(
            a, '0/1').realized_hz), 460)
        self.assertEqual(Fraction(evaluate_instantaneous_rate(
            b, '0/1').realized_hz), 430)
        source = frozen_input(frames=1600)
        aa = render_controlled_audio_proof(source, a)
        bb = render_controlled_audio_proof(source, b)
        self.assertNotEqual(aa.diagnostics['pcm_sha256'],
                            bb.diagnostics['pcm_sha256'])
        self.assertGreater(float(np.max(np.abs(aa.audio - bb.audio))), .01)

    def test_linked_or_independent_octave_jitter_and_quantization(self):
        spec = octave_spec(channels=2)
        jitter = JitterSpec(model='uniform_frequency_cells_v1',
                            amount=.125, cell_s='1/64',
                            seed='2301', stream='octave')
        quantizer = RateQuantizer(policy='nearest_hz',
                                  levels_hz=('100/1', '200/1', '400/1'))
        spec = replace(spec, clock=replace(spec.clock,
                                           quantizer=quantizer, jitter=jitter),
                       clock_group='group-lowmid')
        source = frozen_input(channels=2)
        linked = render_controlled_audio_proof(source, spec)
        np.testing.assert_array_equal(linked.audio[:, 0], linked.audio[:, 1])
        relabelled = replace(spec, instance_id='relocated', label='cosmetic')
        other = render_controlled_audio_proof(source, relabelled)
        np.testing.assert_array_equal(other.audio, linked.audio)
        self.assertEqual(other.diagnostics['event_ledger_sha256'],
                         linked.diagnostics['event_ledger_sha256'])
        independent = render_controlled_audio_proof(
            source, replace(spec, stereo_link='independent'))
        self.assertGreater(float(np.max(np.abs(
            independent.audio[:, 0] - independent.audio[:, 1]))), .01)
        self.assertEqual(independent.diagnostics['pcm_sha256'],
                         render_controlled_audio_proof(
                             source, replace(spec, stereo_link='independent')
                         ).diagnostics['pcm_sha256'])

    def test_fractional_exponent_ramps_invalid_clock_and_cancellation_refuse(self):
        fractional = SonicSpec(clock=ClockSpec(rate=VirtualRate('200/1'),
            routes=(ModulationRoute(id='half-octave', mapping='log2_ratio',
                                    initial='1/2', depth=1.),)))
        # Inspector supports an irrational instantaneous rate. The physical
        # clock must not approximate its exponential phase as constant Hz.
        with self.assertRaisesRegex(ContractError, 'integral log2 exponent'):
            compile_step_clock_events(fractional, '1/4')
        ramp = SonicSpec(clock=ClockSpec(rate=VirtualRate('200/1'),
            routes=(ModulationRoute(id='ramp-octave', mapping='log2_ratio',
                initial='0/1', points=(Point('1/4', '1/1'),),
                interpolation='linear', depth=1.),)))
        with self.assertRaisesRegex(UnsupportedNyquismic, 'exponential ramp'):
            compile_step_clock_events(ramp, '1/2')
        spec = octave_spec()
        with self.assertRaises(UnsupportedNyquismic):
            spec.clock.require_geometry()  # frozen NYQ-002 boundary
        with self.assertRaises(ContractError):
            compile_step_clock_events(spec, '1/1', channel=True)
        from zaaggenz_contracts.nyquismic_clock import ClockCancelled
        with self.assertRaises(ClockCancelled):
            compile_step_clock_events(spec, '1/1', cancelled=lambda: True)


if __name__ == '__main__':
    unittest.main()
