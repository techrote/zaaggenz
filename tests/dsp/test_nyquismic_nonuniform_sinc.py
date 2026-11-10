"""NYQ-003 opt-in irregular-clock sinc quadrature: actual PCM and strict limits.

An independent physical-time reference checks the 17-event density-weighted
kernel, not merely object serialization or a static inspector. This method
is experimental and not ideal irregular sampling inversion.
"""
from dataclasses import replace
from fractions import Fraction
import math
import unittest

import numpy as np

from zaaggenz_contracts import ContractError
from zaaggenz_contracts.nyquismic import (
    ClockSpec, Point, ResourceBudget, SonicSpec, VirtualRate,
)
from zaaggenz_contracts.nyquismic_clock import ClockCancelled
from zaaggenz_dsp.nyquismic import FrozenInput, SamplerPlan, sampler_evaluation


METHOD = 'sinc8_hann_local_time_v1'


def source_pcm(frames=1440, *, stereo=False):
    t = np.arange(frames, dtype=np.float64) / 48000
    left = (.65 * np.sin(2 * np.pi * 570 * t)
            + .24 * np.sin(2 * np.pi * 2390 * t)
            + .11 * np.sin(2 * np.pi * 6340 * t))
    if stereo:
        right = (.37 * np.cos(2 * np.pi * 410 * t)
                 - .21 * np.sin(2 * np.pi * 3070 * t))
        return np.column_stack((left, right)).astype('<f4')
    return left.astype('<f4')


def plan_for(pcm, *, variable=True, method=METHOD, budget=None, **changes):
    clock = ClockSpec(
        rate=VirtualRate('8000/1'),
        points_hz=(Point('1/100', '12000/1'),) if variable else (),
    )
    channels = 2 if pcm.ndim == 2 else 1
    spec = SonicSpec(reconstruction=method, channels=channels,
                     input_boundary='edge_hold', clock=clock, **changes)
    frozen = FrozenInput.from_pcm(pcm, 48000)
    return SamplerPlan.prepare(frozen, spec,
        sampler_evaluation(48000, budget or ResourceBudget()))


class NonuniformSincTests(unittest.TestCase):
    def test_physical_time_density_quadrature_matches_independent_reference(self):
        plan = plan_for(source_pcm())
        frame = 741  # beyond physical-time clock transition at 10 ms
        owner = int(np.searchsorted(plan._first_frames, frame, side='right') - 1)
        self.assertGreater(owner, 8)
        self.assertLess(owner + 9, len(plan.events))
        actual = float(plan.render(frame, frame + 1).audio[0])
        t = Fraction(frame, 48000)
        weights = []
        taps = []
        for k in range(owner - 8, owner + 9):
            # Independent binary64 physical-time reference: the NYQ-002
            # event authority may return Decimal80 roots on Hz ramps, so
            # mixing Fraction and Decimal with native subtraction is invalid.
            event_times = plan._coordinates
            if k == 0:
                h = float(event_times[1]) - float(event_times[0])
            elif k == len(plan.events) - 1:
                h = float(event_times[-1]) - float(event_times[-2])
            else:
                h = (float(event_times[k + 1]) - float(event_times[k - 1])) / 2
            delta = float(t) - float(event_times[k])
            if delta == 0:
                weights, taps = [1.], [float(plan.captures[k, 0])]
                break
            x = delta / h
            w = (float(h) * (np.sin(np.pi * x) / (np.pi * x))
                 * (1 + np.cos(np.pi * x / 8)) / 2) if abs(x) < 8 else 0.
            weights.append(w)
            taps.append(float(plan.captures[k, 0]))
        reference = float(np.dot(weights, taps) / sum(weights))
        self.assertAlmostEqual(actual, reference, delta=2e-11)
        self.assertEqual(plan.render().diagnostics['reconstruction_window'],
                         'hann_radius_8_local_time_density_weighted_sinc_v1')
        # Compare actual sonic character with the separate positive-weight
        # non-bandlimited Shepard reconstruction on identical source/events.
        shepard = plan_for(source_pcm(), method='shepard8_hann_local_time_v1')
        self.assertEqual(plan.events, shepard.events)
        self.assertGreater(float(np.max(np.abs(
            plan.render(250, 1100).audio - shepard.render(250, 1100).audio))), 1e-4)

    def test_uniform_lattice_reduces_to_existing_cardinal_hann_sinc(self):
        pcm = source_pcm(960)
        time_aware = plan_for(pcm, variable=False)
        cardinal = plan_for(pcm, variable=False,
                            method='sinc8_hann_uniform_v1')
        result = time_aware.render().audio
        np.testing.assert_allclose(result, cardinal.render().audio,
                                   atol=2e-11, rtol=0)
        for index in (15, 32, 61):
            event_frame = time_aware._coordinates[index] * 48000
            self.assertEqual(event_frame.denominator, 1)
            self.assertEqual(result[event_frame.numerator],
                             time_aware.captures[index, 0])
        np.testing.assert_array_equal(time_aware.render(201, 611).audio,
                                      result[201:611])

    def test_captured_alias_is_not_unconditionally_cleaned(self):
        frames = 4800
        t = np.arange(frames, dtype=np.float64) / 48000
        pcm = np.sin(2 * np.pi * 6000 * t).astype('<f4')
        plan = plan_for(pcm, variable=False)
        audio = plan.render().audio
        # Exact 0.1-s DFT bins: 6 kHz sampled at virtual 8 kHz folds to
        # 2 kHz; the new *reconstruction* must not erase that capture alias.
        folded_bin = int(2000 * frames / 48000)
        amplitude = float(2 * abs(np.fft.rfft(audio)[folded_bin]) / frames)
        self.assertGreater(amplitude, .5)

    def test_stereo_region_checkpoint_bypass_budget_and_cancellation(self):
        pcm = source_pcm(stereo=True)
        plan = plan_for(pcm)
        complete = plan.render().audio
        self.assertEqual(complete.shape, pcm.shape)
        np.testing.assert_array_equal(
            plan.render(333, 991, checkpoint=plan.checkpoint(333)).audio,
            complete[333:991])
        self.assertGreater(float(np.max(np.abs(complete[:, 0] - complete[:, 1]))), .2)
        np.testing.assert_array_equal(
            plan_for(pcm, bypass=True).render().audio, pcm)
        np.testing.assert_array_equal(
            plan_for(pcm, wet=0.).render().audio, pcm)
        with self.assertRaises(ContractError):
            plan_for(pcm, budget=ResourceBudget(max_filter_taps=16))
        with self.assertRaises(ClockCancelled):
            frozen = FrozenInput.from_pcm(pcm, 48000)
            SamplerPlan.prepare(
                frozen, plan.spec, sampler_evaluation(48000),
                cancelled=lambda: True)
        # A uniform kernel must never be applied silently to these
        # irregular time stamps, even if the output sample rate is fixed.
        with self.assertRaises(ContractError):
            plan_for(pcm, method='sinc8_hann_uniform_v1')


if __name__ == '__main__':
    unittest.main()
