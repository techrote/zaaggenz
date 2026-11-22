"""NYQ-003 numerical qualification of independently declared delivery clocks."""
import unittest
from unittest.mock import patch

import numpy as np

from zaaggenz_contracts import ContractError
from zaaggenz_contracts.nyquismic import ClockSpec, ResourceBudget, SonicSpec, VirtualRate
from zaaggenz_dsp.nyquismic import FrozenInput, SamplerPlan, sampler_evaluation
from zaaggenz_dsp.nyquismic_convergence import evaluate_sampler_convergence
from zaaggenz_dsp.nyquismic_delivery import (
    STAGED_44100_METHOD, STAGED_44100_CEIL_TAIL_METHOD, DeliveryConversionPolicy,
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

    def test_staged_44100_convergence_uses_real_events_and_identical_fir(self):
        source = source_tone()
        sonic = SonicSpec(clock=ClockSpec(rate=VirtualRate('8000/1')),
                          reconstruction='hold_v1', prefilter='off_v1')
        staged = DeliveryConversionPolicy(method=STAGED_44100_METHOD)
        canonical = evaluate_sampler_convergence(
            source, sonic, delivery_rate_hz=44100, delivery_policy=staged)
        diagnostics = canonical.diagnostics
        self.assertEqual(diagnostics['delivery_rate_hz'], 44100)
        self.assertEqual(diagnostics['delivery_method'], STAGED_44100_METHOD)
        self.assertEqual(diagnostics['delivery_policy_sha256'], staged.sha256)
        self.assertEqual(diagnostics['rates_hz'], list(RATES))
        self.assertEqual(diagnostics['event_counts_by_rate'], [800] * 3)
        self.assertEqual(len(set(diagnostics['event_ledger_sha256_by_rate'])), 1)
        for rate, row in zip(RATES, diagnostics['candidate_conversion']):
            self.assertEqual(row['policy_sha256'], staged.sha256)
            self.assertEqual(row['output_frames'], 4410)
            self.assertEqual(
                [(part['input_rate_hz'], part['output_rate_hz']) for part in row['stages']],
                [(rate, 48000), (48000, 44100)])
        # The comparator must convert the same actual 768-kHz sampler PCM
        # as a separate source-matched sampler/delivery execution.
        direct = render_sampler_to_delivery(
            source, sonic, numerical_rate_hz=RATES[-1],
            delivery_rate_hz=44100, policy=staged)
        self.assertEqual(diagnostics['candidate_conversion'][-1]['output_pcm_sha256'],
                         direct.diagnostics['output_pcm_sha256'])
        self.assertGreater(coherent_amplitude(direct.audio, 2000, 44100), .75)
        self.assertEqual(canonical.selected_audio is not None,
                         canonical.status == 'converged')
        legacy = evaluate_sampler_model_convergence(
            source, sonic, delivery_rate_hz=44100, delivery_policy=staged)
        self.assertEqual(legacy.diagnostics['exact_event_ledger_sha256'],
                         diagnostics['exact_event_ledger_sha256'])
        self.assertEqual(
            [row['output_pcm_sha256'] for row in legacy.diagnostics['candidate_conversion']],
            [row['output_pcm_sha256'] for row in diagnostics['candidate_conversion']])
        self.assertEqual(legacy.status, canonical.status)

    def test_staged_44100_preflight_refuses_before_physical_capture(self):
        source = source_tone()
        sonic = SonicSpec(clock=ClockSpec(rate=VirtualRate('8000/1')))
        staged = DeliveryConversionPolicy(method=STAGED_44100_METHOD)
        with patch('zaaggenz_dsp.nyquismic.SamplerPlan.prepare',
                   side_effect=AssertionError('captured before admission')):
            with self.assertRaisesRegex(ContractError, 'unsupported delivery FIR taps'):
                evaluate_sampler_convergence(source, sonic, delivery_rate_hz=44100)
            with self.assertRaisesRegex(ContractError, 'staged 44.1 kHz delivery'):
                evaluate_sampler_convergence(
                    source, sonic, delivery_rate_hz=48000, delivery_policy=staged)
            with self.assertRaisesRegex(ContractError, 'kernel tap budget'):
                evaluate_sampler_convergence(
                    source, sonic, delivery_rate_hz=44100, delivery_policy=staged,
                    budget=ResourceBudget(max_filter_taps=100))
            # At 1 ms, the 48k intermediate has 48 frames, but 44.1k
            # final delivery has 44.1 frames: no fractional tail rounding.
            tiny = FrozenInput.from_pcm(np.zeros(96, dtype='<f4'), SOURCE_HZ)
            with self.assertRaisesRegex(ContractError, 'integral delivery extent'):
                evaluate_sampler_convergence(
                    tiny, sonic, delivery_rate_hz=44100, delivery_policy=staged)

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

    def test_44100_opt_in_staged_real_alias_exact_independent_fir(self):
        # Physical 8 kHz capture of a 6 kHz source folds to 2 kHz, even
        # after two final anti-imaging/anti-evaluation-alias FIR stages.
        from scipy.signal import firwin, resample_poly
        source = source_tone()
        sonic = SonicSpec(clock=ClockSpec(rate=VirtualRate('8000/1')))
        policy = DeliveryConversionPolicy(method=STAGED_44100_METHOD)
        observed = []
        for rate in RATES[:2]:
            actual = render_sampler_to_delivery(
                source, sonic, numerical_rate_hz=rate,
                delivery_rate_hz=44100, policy=policy)
            self.assertEqual(actual.audio.shape, (4410,))
            self.assertFalse(actual.audio.flags.writeable)
            self.assertEqual(actual.diagnostics['event_count'], 800)
            d = actual.diagnostics['delivery']
            self.assertEqual(d['method'], STAGED_44100_METHOD)
            self.assertEqual(d['window'], 'staged_kaiser_beta10_v1')
            self.assertEqual([row['kernel_taps'] for row in d['stages']],
                             [24 * (rate // 48000) + 1, 3841])
            self.assertEqual(d['source_pcm_sha256'],
                             actual.diagnostics['sampler']['pcm_sha256'])
            amplitude = coherent_amplitude(actual.audio, 2000, 44100)
            self.assertGreater(amplitude, .70)
            observed.append(amplitude)
            plan = SamplerPlan.prepare(
                source, sonic, sampler_evaluation(rate),
                frame_count=rate // 10, delivery_rate_hz=44100)
            first = resample_poly(plan.render().audio, 1, rate // 48000,
                window=firwin(24 * (rate // 48000) + 1,
                              1. / (rate // 48000), window=('kaiser', 10.)))
            expected = resample_poly(first, 147, 160,
                window=firwin(3841, 1. / 160, window=('kaiser', 10.)))
            np.testing.assert_array_equal(actual.audio, expected)
        self.assertLess(abs(observed[0] - observed[1]), .02)
        self.assertNotEqual(DeliveryConversionPolicy().sha256, policy.sha256)

    def test_opt_in_fractional_final_tail_preserves_physical_sampling(self):
        # A normal source length need not align to a whole 44.1-kHz frame.
        # This fixture also triggers an extra stage-rounding frame to crop.
        from fractions import Fraction
        from scipy.signal import firwin, resample_poly
        n, final_frames = 9613, 4416
        source = FrozenInput.from_pcm(
            np.sin(2 * np.pi * 6000 * np.arange(n) / SOURCE_HZ).astype('<f4'),
            SOURCE_HZ)
        sonic = SonicSpec(clock=ClockSpec(rate=VirtualRate('8000/1')))
        strict = DeliveryConversionPolicy(method=STAGED_44100_METHOD)
        tail = DeliveryConversionPolicy(method=STAGED_44100_CEIL_TAIL_METHOD)
        self.assertNotEqual(tail.sha256, strict.sha256)
        with patch('zaaggenz_dsp.nyquismic.SamplerPlan.prepare',
                   side_effect=AssertionError('strict mode captured invalid tail')):
            with self.assertRaisesRegex(ContractError, 'integral final physical extent'):
                render_sampler_to_delivery(
                    source, sonic, numerical_rate_hz=192000,
                    delivery_rate_hz=44100, policy=strict)
            with self.assertRaisesRegex(ContractError, 'integral delivery extent'):
                evaluate_sampler_convergence(
                    source, sonic, delivery_rate_hz=44100, delivery_policy=strict)

        outputs = []
        for rate in RATES:
            result = render_sampler_to_delivery(
                source, sonic, numerical_rate_hz=rate,
                delivery_rate_hz=44100, policy=tail)
            self.assertEqual(result.audio.shape, (final_frames,))
            self.assertFalse(result.audio.flags.writeable)
            self.assertEqual(result.diagnostics['expected_delivery_frames'], final_frames)
            self.assertEqual(result.diagnostics['source_extent_s'], str(Fraction(n, SOURCE_HZ)))
            self.assertEqual(result.diagnostics['delivery']['tail_policy'],
                             'ceil_final_frame_zero_pad_v1')
            self.assertEqual(result.diagnostics['delivery']['nominal_source_extent_s'],
                             str(Fraction(n, SOURCE_HZ)))
            self.assertEqual(result.diagnostics['delivery']['tail_overhang_s'],
                             str(Fraction(final_frames, 44100) - Fraction(n, SOURCE_HZ)))
            self.assertEqual(result.diagnostics['delivery']['cropped_rounding_frames'], 1)
            plan = SamplerPlan.prepare(source, sonic, sampler_evaluation(rate),
                frame_count=n * rate // SOURCE_HZ, delivery_rate_hz=44100)
            numerical = plan.render().audio
            first = resample_poly(numerical, 1, rate // 48000,
                window=firwin(24 * (rate // 48000) + 1,
                              1. / (rate // 48000), window=('kaiser', 10.)))
            second = resample_poly(first, 147, 160,
                window=firwin(3841, 1. / 160, window=('kaiser', 10.)))
            self.assertEqual(len(second), final_frames + 1)
            np.testing.assert_array_equal(result.audio, second[:final_frames])
            outputs.append(result)
        self.assertEqual(len({o.diagnostics['event_count'] for o in outputs}), 1)
        self.assertEqual(len({o.diagnostics['clock_sha256'] for o in outputs}), 1)
        comparison = evaluate_sampler_convergence(
            source, sonic, delivery_rate_hz=44100, delivery_policy=tail)
        self.assertEqual(comparison.diagnostics['event_counts_by_rate'],
                         [outputs[0].diagnostics['event_count']] * 3)
        self.assertEqual(len(set(comparison.diagnostics['event_ledger_sha256_by_rate'])), 1)
        self.assertEqual([row['output_frames'] for row in
                          comparison.diagnostics['candidate_conversion']], [final_frames] * 3)
        self.assertEqual(comparison.diagnostics['candidate_conversion'][-1]['output_pcm_sha256'],
                         outputs[-1].diagnostics['output_pcm_sha256'])
        self.assertEqual(comparison.selected_audio is not None,
                         comparison.status == 'converged')

    def test_44100_staging_refuses_wrong_clock_ratio_budget_and_extent_before_capture(self):
        source = source_tone()
        sonic = SonicSpec(clock=ClockSpec(rate=VirtualRate('8000/1')))
        policy = DeliveryConversionPolicy(method=STAGED_44100_METHOD)
        with patch('zaaggenz_dsp.nyquismic.SamplerPlan.prepare',
                   side_effect=AssertionError('failed admission must not capture')):
            for rate, delivered, budget in (
                (192000, 48000, ResourceBudget()),
                (192000, 44100, ResourceBudget(max_filter_taps=3840)),
                (200000, 44100, ResourceBudget()),
            ):
                with self.subTest(rate=rate, delivered=delivered), self.assertRaises(ContractError):
                    render_sampler_to_delivery(source, sonic,
                        numerical_rate_hz=rate, delivery_rate_hz=delivered,
                        policy=policy, budget=budget)
            with self.assertRaises(ContractError):
                render_sampler_to_delivery(
                    FrozenInput.from_pcm(np.ones(1, dtype='<f4'), SOURCE_HZ),
                    sonic, numerical_rate_hz=192000,
                    delivery_rate_hz=44100, policy=policy)
            # Keep old direct converter's 15,361-tap refusal unchanged.
            with self.assertRaises(ContractError):
                render_sampler_to_delivery(
                    source, sonic, numerical_rate_hz=192000,
                    delivery_rate_hz=44100)
        silence = np.zeros((19200, 2), dtype=np.float64)
        converted = convert_numerical_to_delivery(
            silence, 192000, 44100, policy=policy)
        self.assertEqual(converted.audio.shape, (4410, 2))
        np.testing.assert_array_equal(converted.audio, np.zeros((4410, 2)))
        with self.assertRaises(ContractError):
            convert_numerical_to_delivery(
                np.zeros(3, dtype=np.float64), 192000, 44100, policy=policy)


if __name__ == '__main__':
    unittest.main()
