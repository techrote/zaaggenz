"""NYQ-003 numerical qualification of independently declared delivery clocks."""
import unittest
from unittest.mock import patch

import numpy as np

from zaaggenz_contracts import ContractError
from zaaggenz_contracts.nyquismic import ClockSpec, ResourceBudget, SonicSpec, VirtualRate
from zaaggenz_dsp.nyquismic import FrozenInput, SamplerPlan, sampler_evaluation
from zaaggenz_dsp.nyquismic_convergence import evaluate_sampler_convergence
from zaaggenz_dsp.nyquismic_delivery import (
    convert_numerical_to_delivery, render_sampler_to_delivery,
)
from zaaggenz_dsp.nyquismic_sampler_convergence import evaluate_sampler_model_convergence


SOURCE_HZ = 96000
DELIVERY_HZ = 48000
RATES = (192000, 384000, 768000)
SOURCE_FRAMES = 9600


def source_tone(hz=6000):
    t = np.arange(SOURCE_FRAMES, dtype=np.float64) / SOURCE_HZ
    return FrozenInput.from_pcm(np.sin(2 * np.pi * hz * t).astype('<f4'), SOURCE_HZ)


def coherent_amplitude(audio, frequency_hz, rate=DELIVERY_HZ):
    bin_index, leftover = divmod(frequency_hz * len(audio), rate)
    assert leftover == 0
    return float(2 * abs(np.fft.rfft(audio)[bin_index]) / len(audio))


class IndependentDeliveryClockTests(unittest.TestCase):
    def test_real_96k_source_8k_dirty_capture_to_48k_delivery(self):
        source = source_tone()
        sonic = SonicSpec(clock=ClockSpec(rate=VirtualRate('8000/1')),
                          reconstruction='hold_v1', prefilter='off_v1')
        amplitudes = []
        for rate in RATES[:2]:
            result = render_sampler_to_delivery(
                source, sonic, numerical_rate_hz=rate,
                delivery_rate_hz=DELIVERY_HZ)
            self.assertEqual(result.audio.shape, (4800,))
            self.assertFalse(result.audio.flags.writeable)
            self.assertEqual(result.diagnostics['event_count'], 800)
            self.assertEqual(result.diagnostics['source_rate_hz'], SOURCE_HZ)
            self.assertEqual(result.diagnostics['delivery_rate_hz'], DELIVERY_HZ)
            self.assertEqual(result.diagnostics['expected_delivery_frames'], 4800)
            self.assertEqual(result.diagnostics['source_extent_s'], '1/10')
            self.assertEqual(result.diagnostics['method'],
                             'nyq.local-physical-sampler-to-crossrate-delivery.v1')
            self.assertEqual(result.diagnostics['sampler']['pcm_sha256'],
                             result.diagnostics['delivery']['source_pcm_sha256'])
            fold = coherent_amplitude(result.audio, 2000)
            self.assertGreater(fold, .75)
            amplitudes.append(fold)
        self.assertLess(abs(amplitudes[0] - amplitudes[1]), .02)
        same_source_delivery = render_sampler_to_delivery(
            source, sonic, numerical_rate_hz=192000)
        explicit_48k_delivery = render_sampler_to_delivery(
            source, sonic, numerical_rate_hz=192000,
            delivery_rate_hz=DELIVERY_HZ)
        self.assertEqual(same_source_delivery.audio.shape, (SOURCE_FRAMES,))
        self.assertEqual(same_source_delivery.diagnostics['method'],
                         'nyq.local-physical-sampler-to-delivery.v1')
        self.assertNotEqual(same_source_delivery.diagnostics['sampler_render_sha256'],
                            explicit_48k_delivery.diagnostics['sampler_render_sha256'])

    def test_real_three_rate_convergence_and_compatibility_share_final_clock(self):
        source = source_tone()
        sonic = SonicSpec(clock=ClockSpec(rate=VirtualRate('8000/1')))
        canonical = evaluate_sampler_convergence(
            source, sonic, delivery_rate_hz=DELIVERY_HZ)
        legacy = evaluate_sampler_model_convergence(
            source, sonic, delivery_rate_hz=DELIVERY_HZ)
        d = canonical.diagnostics
        self.assertEqual(d['rates_hz'], list(RATES))
        self.assertEqual(d['event_counts_by_rate'], [800] * 3)
        self.assertEqual(len(set(d['event_ledger_sha256_by_rate'])), 1)
        self.assertEqual(d['delivery_rate_hz'], DELIVERY_HZ)
        self.assertEqual([row['output_frames'] for row in
                          d['candidate_conversion']], [4800] * 3)
        self.assertEqual(d['exact_event_ledger_sha256'],
                         legacy.diagnostics['exact_event_ledger_sha256'])
        self.assertEqual(d['numerical_pcm_sha256_by_rate'],
                         legacy.diagnostics['numerical_pcm_sha256_by_rate'])
        self.assertEqual([row['output_pcm_sha256'] for row in d['candidate_conversion']],
                         [row['output_pcm_sha256'] for row in
                          legacy.diagnostics['candidate_conversion']])
        self.assertEqual(canonical.status, legacy.status)
        self.assertEqual(canonical.selected_audio is None,
                         legacy.selected_audio is None)
        if canonical.selected_audio is not None:
            np.testing.assert_array_equal(canonical.selected_audio,
                                          legacy.selected_audio)

    def test_boundary_bypass_exact_before_declared_nonidentity_final_fir(self):
        pcm = np.arange(960, dtype='<f4') / 1024
        source = FrozenInput.from_pcm(pcm, SOURCE_HZ)
        sonic = SonicSpec(bypass=True, clock=ClockSpec(rate=VirtualRate('8000/1')))
        plan = SamplerPlan.prepare(
            source, sonic, sampler_evaluation(SOURCE_HZ),
            delivery_rate_hz=DELIVERY_HZ)
        np.testing.assert_array_equal(plan.render().audio, source.pcm)
        self.assertEqual(plan.identity.delivery_rate_hz, DELIVERY_HZ)
        final = render_sampler_to_delivery(
            source, sonic, numerical_rate_hz=SOURCE_HZ,
            delivery_rate_hz=DELIVERY_HZ)
        self.assertEqual(final.audio.shape, (480,))
        self.assertEqual(final.diagnostics['delivery']['ratio_down'], 2)
        self.assertFalse(final.audio.flags.writeable)
        with self.assertRaisesRegex(ContractError, 'exact bypass requires matched'):
            render_sampler_to_delivery(
                source, sonic, numerical_rate_hz=192000,
                delivery_rate_hz=DELIVERY_HZ)

    def test_nonintegral_delivery_bad_fir_and_cancel_refuse_without_capture(self):
        sonic = SonicSpec(clock=ClockSpec(rate=VirtualRate('8000/1')))
        half_frame = FrozenInput.from_pcm(np.ones(1, dtype='<f4'), SOURCE_HZ)
        source = source_tone()
        with patch('zaaggenz_dsp.nyquismic.SamplerPlan.prepare',
                   side_effect=AssertionError('capture may not execute')):
            with self.assertRaisesRegex(ContractError, 'integral final physical extent'):
                render_sampler_to_delivery(
                    half_frame, sonic, numerical_rate_hz=192000,
                    delivery_rate_hz=DELIVERY_HZ)
            with self.assertRaisesRegex(ContractError, 'integral delivery extent'):
                evaluate_sampler_convergence(
                    half_frame, sonic, delivery_rate_hz=DELIVERY_HZ)
            with self.assertRaisesRegex(ContractError, 'FIR ratio'):
                render_sampler_to_delivery(
                    source, sonic, numerical_rate_hz=192000,
                    delivery_rate_hz=44100)
            with self.assertRaisesRegex(ContractError, 'unsupported delivery FIR taps'):
                evaluate_sampler_convergence(
                    source, sonic, delivery_rate_hz=44100)
        with self.assertRaisesRegex(ContractError, 'frame budget'):
            render_sampler_to_delivery(
                source, sonic, numerical_rate_hz=192000,
                delivery_rate_hz=DELIVERY_HZ,
                budget=ResourceBudget(max_frames=4800))
        with self.assertRaises(ContractError):
            render_sampler_to_delivery(
                source, sonic, numerical_rate_hz=192000,
                delivery_rate_hz=True)
        from zaaggenz_contracts.nyquismic_clock import ClockCancelled
        with self.assertRaises(ClockCancelled):
            render_sampler_to_delivery(
                source, sonic, numerical_rate_hz=192000,
                delivery_rate_hz=DELIVERY_HZ, cancelled=lambda: True)

    def test_real_sampler_preserves_nonlinear_difference_before_final_fir(self):
        # 28/33 kHz parents are real in the immutable 96-kHz input and
        # below 80-kHz virtual capture Nyquist, but above 48-kHz delivery
        # Nyquist. Squaring after sampler generates a new 5-kHz product.
        # Conversion BEFORE that nonlinear operation destroys this product.
        # No nonlinear graph node or default sonic processing is changed.
        t = np.arange(SOURCE_FRAMES, dtype=np.float64) / SOURCE_HZ
        parents = (.4 * np.sin(2 * np.pi * 28000 * t) +
                   .4 * np.sin(2 * np.pi * 33000 * t))
        source = FrozenInput.from_pcm(parents.astype('<f4'), SOURCE_HZ)
        sonic = SonicSpec(clock=ClockSpec(rate=VirtualRate('80000/1')),
                          reconstruction='hold_v1', prefilter='off_v1')
        products = []
        for rate in RATES[:2]:
            plan = SamplerPlan.prepare(
                source, sonic, sampler_evaluation(rate),
                frame_count=rate // 10, delivery_rate_hz=DELIVERY_HZ)
            numerical = plan.render().audio
            proper = convert_numerical_to_delivery(
                numerical * numerical, rate, DELIVERY_HZ).audio
            premature = convert_numerical_to_delivery(
                numerical, rate, DELIVERY_HZ).audio ** 2
            good, lost = coherent_amplitude(proper, 5000), coherent_amplitude(premature, 5000)
            self.assertGreater(good, .07)
            self.assertLess(lost, .02)
            self.assertGreater(good, 5 * lost)
            products.append(good)
        self.assertLess(abs(products[0] - products[1]), .015)


    def test_real_post_sampler_clipping_and_folding_before_delivery(self):
        # The immutable 96 kHz source contains two separate 28/33 kHz
        # components. Both fit below the *virtual* 80 kHz Nyquist, but
        # neither fits below the 48 kHz delivery Nyquist. Diode half-wave
        # clipping and full-wave folding AFTER actual virtual capture
        # generate a 5 kHz intermodulation difference component. Converting
        # first removes the high-frequency parents before they can mix.
        # This is a local numerical placement oracle, not a graph stage.
        t = np.arange(SOURCE_FRAMES, dtype=np.float64) / SOURCE_HZ
        parents = (.4 * np.sin(2 * np.pi * 28000 * t) +
                   .4 * np.sin(2 * np.pi * 33000 * t))
        source = FrozenInput.from_pcm(parents.astype('<f4'), SOURCE_HZ)
        sonic = SonicSpec(clock=ClockSpec(rate=VirtualRate('80000/1')),
                          reconstruction='hold_v1', prefilter='off_v1')
        operations = (
            ('half_wave_clip', lambda pcm: np.maximum(pcm, 0.), .06),
            ('full_wave_fold', np.abs, .12),
        )
        amplitudes = {name: [] for name, _, _ in operations}
        for rate in RATES[:2]:
            plan = SamplerPlan.prepare(
                source, sonic, sampler_evaluation(rate),
                frame_count=rate // 10, delivery_rate_hz=DELIVERY_HZ)
            self.assertEqual(len(plan.events), 8000)
            numerical = plan.render().audio
            premature = convert_numerical_to_delivery(
                numerical, rate, DELIVERY_HZ).audio
            for name, nonlinearity, minimum in operations:
                proper_pcm = convert_numerical_to_delivery(
                    nonlinearity(numerical), rate, DELIVERY_HZ).audio
                incorrect_pcm = nonlinearity(premature)
                self.assertEqual(proper_pcm.shape, (4800,))
                self.assertFalse(proper_pcm.flags.writeable)
                proper_5k = coherent_amplitude(proper_pcm, 5000)
                premature_5k = coherent_amplitude(incorrect_pcm, 5000)
                self.assertGreater(proper_5k, minimum, (name, rate))
                self.assertGreater(proper_5k, 2. * premature_5k,
                                   (name, rate, proper_5k, premature_5k))
                amplitudes[name].append(proper_5k)
        # The identical virtual capture lattice, physical source and
        # nonlinear placement preserve low-band products across both
        # numerical evaluation grids, without claiming bit identity.
        for values in amplitudes.values():
            self.assertLess(abs(values[0] - values[1]), .015)


if __name__ == '__main__':
    unittest.main()
