"""NYQ-003 source-domain Catmull-Rom capture, independent of virtual reconstruction.

Actual fractional physical events and delivered alias PCM, not product export.
The midpoint oracle is the independently expanded four-sample polynomial.
"""
from dataclasses import replace
import unittest

import numpy as np

from zaaggenz_contracts import ContractError
from zaaggenz_contracts.nyquismic import ClockSpec, SonicSpec, VirtualRate
from zaaggenz_dsp.nyquismic import FrozenInput, SamplerPlan, sampler_evaluation
from zaaggenz_dsp.nyquismic_delivery import render_sampler_to_delivery


CUBIC = 'cubic_catmull_rom_v1'


def prepare(signal, *, capture=CUBIC, boundary='zero_pad', numerical_rate=96000,
            channels=1):
    src = FrozenInput.from_pcm(signal, 48000)
    spec = SonicSpec(capture=capture, input_boundary=boundary, channels=channels,
                     clock=ClockSpec(rate=VirtualRate('32000/1')))
    return SamplerPlan.prepare(src, spec, sampler_evaluation(numerical_rate))


class SourceCubicCaptureTests(unittest.TestCase):
    def test_four_source_sample_midpoint_and_exact_integer_capture(self):
        source = np.zeros(24, dtype='<f4')
        source[1:3] = 1
        cubic = prepare(source)
        linear = prepare(source, capture='linear_v1')
        # At physical event 1/32000 s, source position = 3/2 frames.
        # Catmull-Rom midpoint weights are (-1, 9, 9, -1)/16.
        self.assertEqual(float(cubic.captures[1, 0]), 1.125)
        self.assertEqual(float(linear.captures[1, 0]), 1.0)
        self.assertEqual(float(cubic.captures[2, 0]), float(source[3]))
        self.assertEqual(float(cubic.captures[0, 0]), float(source[0]))
        self.assertEqual(cubic.render().diagnostics['capture_support_source_frames'],
                         [-1, 0, 1, 2])
        self.assertEqual(linear.render().diagnostics['capture_support_source_frames'],
                         [0, 1])
        self.assertNotEqual(cubic.spec.sonic_sha256, linear.spec.sonic_sha256)
        self.assertEqual(SonicSpec.from_json(cubic.spec.to_json()), cubic.spec)
        self.assertEqual(SonicSpec().capture, 'linear_v1')

    def test_last_source_boundary_uses_declared_extension_not_hidden_clamp(self):
        source = np.zeros(24, dtype='<f4')
        source[21:] = [-.25, .75, 1.0]
        zero = prepare(source, boundary='zero_pad')
        edge = prepare(source, boundary='edge_hold')
        # Event #15 = 22.5 source frames, so q is frame 24, beyond
        # the source extent. The rest is an independent rational oracle.
        a = (-source[21] + 9*source[22] + 9*source[23]) / 16
        self.assertAlmostEqual(float(zero.captures[15, 0]), float(a), places=12)
        self.assertAlmostEqual(float(edge.captures[15, 0]),
                               float(a - source[23]/16), places=12)
        self.assertGreater(abs(float(zero.captures[15, 0] -
                                     edge.captures[15, 0])), .05)

    def test_stereo_chunk_checkpoint_grid_and_exact_bypass(self):
        t = np.arange(48, dtype=np.float64)
        signal = (.4*np.sin(t*.53) + .17*np.cos(t*.17)).astype('<f4')
        stereo = np.column_stack((signal, -signal)).astype('<f4')
        a = prepare(stereo, channels=2, numerical_rate=96000)
        b = prepare(stereo, channels=2, numerical_rate=192000)
        np.testing.assert_array_equal(a.captures, b.captures)
        np.testing.assert_array_equal(a.captures[:, 0], -a.captures[:, 1])
        all_audio = a.render().audio
        parts = [a.render(0, 19).audio,
                 a.render(checkpoint=a.checkpoint(19), stop_frame=53).audio,
                 a.render(checkpoint=a.checkpoint(53)).audio]
        np.testing.assert_array_equal(np.concatenate(parts), all_audio)
        for identity in (replace(a.spec, bypass=True),
                         replace(a.spec, wet=0.0)):
            dry = SamplerPlan.prepare(a.source, identity, sampler_evaluation(48000))
            np.testing.assert_array_equal(dry.render().audio, stereo)
        self.assertTrue(np.isfinite(all_audio).all())

    def test_short_silent_and_unsupported_capture_are_strict(self):
        empty = prepare(np.zeros(0, dtype='<f4'))
        self.assertEqual(empty.render().audio.size, 0)
        one = prepare(np.array([.75], dtype='<f4'), boundary='edge_hold')
        self.assertEqual(float(one.captures[0, 0]), .75)
        self.assertTrue(np.isfinite(one.render().audio).all())
        silent = prepare(np.zeros((24, 2), dtype='<f4'), channels=2)
        np.testing.assert_array_equal(silent.render().audio,
                                      np.zeros((48, 2), dtype=np.float64))
        with self.assertRaises(ContractError):
            SonicSpec(capture='cubic_future_v2')

    def test_fractional_source_capture_preserves_physical_alias_after_delivery(self):
        source_rate = 48000
        t = np.arange(4800, dtype=np.float64) / source_rate
        source = FrozenInput.from_pcm(
            np.sin(2 * np.pi * 6000 * t).astype('<f4'), source_rate)
        spec = SonicSpec(capture=CUBIC, prefilter='off_v1',
                         reconstruction='hold_v1',
                         clock=ClockSpec(rate=VirtualRate('8100/1')))
        amplitudes = []
        for numerical_hz in (192000, 384000):
            delivered = render_sampler_to_delivery(
                source, spec, numerical_rate_hz=numerical_hz)
            self.assertEqual(delivered.audio.shape, (4800,))
            self.assertFalse(delivered.audio.flags.writeable)
            self.assertEqual(delivered.diagnostics['sampler']['capture'], CUBIC)
            self.assertEqual(delivered.diagnostics['event_count'], 810)
            self.assertFalse(delivered.diagnostics['convergence_qualified'])
            interior = delivered.audio[1200:3600]
            # 6 kHz captured on 8.1 kHz lattice -> 2.1 kHz folded tone.
            # The 2400-frame physical-time window has exactly 105 cycles.
            folded = 2*abs(np.fft.rfft(interior)[105])/len(interior)
            self.assertGreater(folded, .5)
            amplitudes.append(float(folded))
        self.assertLess(abs(amplitudes[0] - amplitudes[1]), .04)


if __name__ == '__main__':
    unittest.main()
