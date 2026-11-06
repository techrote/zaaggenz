"""NYQ-003 independent physical-frequency alias and hold-image oracles.

The virtual 8 kHz clock deliberately aliases a 6 kHz input to 2 kHz.
The image at 6 kHz in the *reconstructed* waveform is not a
numerical-evaluation-clock alias and must not be silently removed.
These are analytic static-clock tests, not listening or export evidence.
"""
import unittest

import numpy as np

from zaaggenz_contracts.nyquismic import ClockSpec, SonicSpec, VirtualRate
from zaaggenz_dsp.nyquismic import FrozenInput, SamplerPlan, sampler_evaluation


SOURCE_HZ = 48000
VIRTUAL_HZ = 8000
DURATION_S = .1


def amplitude(audio, frequency_hz, evaluation_hz):
    length = audio.shape[0]
    target = frequency_hz * length // evaluation_hz
    assert target * evaluation_hz == frequency_hz * length
    return float(2 * abs(np.fft.rfft(audio)[target]) / length)


def render(reconstruction, rate_hz):
    time = np.arange(4800, dtype=np.float64) / SOURCE_HZ
    signal = np.sin(2 * np.pi * 6000 * time).astype('<f4')
    source = FrozenInput.from_pcm(signal, SOURCE_HZ)
    spec = SonicSpec(
        reconstruction=reconstruction,
        clock=ClockSpec(rate=VirtualRate(f'{VIRTUAL_HZ}/1')),
    )
    plan = SamplerPlan.prepare(
        source, spec, sampler_evaluation(rate_hz),
        frame_count=rate_hz // 10,
    )
    output = plan.render()
    return signal, plan, output.audio


class PhysicalAliasAndImageOracles(unittest.TestCase):
    def test_static_fold_and_hold_image_are_stable_in_physical_hz(self):
        observations = {}
        for rate_hz in (192000, 384000):
            source, plan, audio = render('hold_v1', rate_hz)
            self.assertEqual(plan.clock.event_count, 800)
            self.assertEqual(len(audio), rate_hz // 10)
            self.assertLess(amplitude(source, 2000, SOURCE_HZ), 1e-6)
            fold = amplitude(audio, 2000, rate_hz)
            image = amplitude(audio, 6000, rate_hz)
            self.assertGreater(fold, .75)
            self.assertGreater(image, .20)
            self.assertLess(image, fold)
            observations[rate_hz] = (fold, image)
        for k in (0, 1):
            self.assertLess(abs(observations[192000][k] -
                                observations[384000][k]), .02)

    def test_time_linear_reconstruction_reduces_image_not_capture_alias(self):
        _, hold_plan, hold = render('hold_v1', 192000)
        _, linear_plan, linear = render('linear_time_v1', 192000)
        self.assertEqual(
            [hold_plan.clock.event_coordinate(k) for k in range(800)],
            [linear_plan.clock.event_coordinate(k) for k in range(800)],
        )
        self.assertGreater(amplitude(linear, 2000, 192000), .6)
        self.assertLess(amplitude(linear, 6000, 192000),
                        amplitude(hold, 6000, 192000) * .8)
        self.assertTrue(np.isfinite(linear).all())


if __name__ == '__main__':
    unittest.main()
