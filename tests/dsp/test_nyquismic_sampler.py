"""NYQ-002 independent signal, exact-state and failure-boundary acceptance."""
from dataclasses import replace
from decimal import Decimal, localcontext
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import unittest

import numpy as np

from zaaggenz_contracts import Contract, ContractError
from zaaggenz_contracts.nyquismic import (
    ClockSpec, EvaluationPolicy, JitterSpec, ModulationRoute, PlaybackMap, Point,
    RateQuantizer, RateReference, Reset, ResourceBudget, SonicSpec,
    UnsupportedNyquismic, VirtualRate, qtext,
)
from zaaggenz_contracts.nyquismic_clock import ClockCancelled
from zaaggenz_dsp.nyquismic import (
    FrozenInput, SamplerCheckpoint, SamplerPlan, sampler_evaluation,
)
import nyquismic_audio_oracles as oracle

ROOT = Path(__file__).resolve().parents[2]
FROZEN = ROOT / 'tests/contracts/fixtures/nyquismic-v1.json'
FROZEN_SHA = 'b42b2d9988df822169d8fd6e02a28dd208eff2b1e0ddf4a2d15df13c6c9ee5bd'


def rate(value):
    return VirtualRate(qtext(Fraction(value)))


def spec(value='11730', **kwargs):
    return SonicSpec(clock=ClockSpec(rate=rate(value)), **kwargs)


def signal(n=384, channels=1):
    # Nonlinear PCM with transients and sign changes; the same frozen source is
    # reused when evaluation rate changes, rather than synthesised anew.
    t = np.arange(n, dtype=np.float64)
    a = (.55 * np.sin(.351 * t) + .21 * np.cos(.812 * t)).astype(np.float32)
    if n > 12:
        a[7], a[12] = 1.4, -.9
    return a if channels == 1 else np.column_stack((a, -.7 * a + .09))


def make(source=None, sonic=None, source_rate=48000, output_rate=None, **kwargs):
    source = signal() if source is None else source
    frozen = source if isinstance(source, FrozenInput) else FrozenInput.from_pcm(source, source_rate)
    return SamplerPlan.prepare(frozen, spec() if sonic is None else sonic,
                               sampler_evaluation(output_rate or source_rate), **kwargs)


def frozen_clock(case):
    kwargs = {'rate': rate(case['rate']), 'phase_cycles': qtext(Fraction(case.get('phase', '0')))}
    if case['kind'] == 'ramp':
        end = Fraction(case['extent'])
        final = Fraction(case['rate']) + Fraction(case['slope']) * end
        kwargs.update(points_hz=(Point(qtext(end), qtext(final)),), interpolation='linear')
    elif case['kind'] == 'step':
        kwargs['points_hz'] = (Point(case['step_time'], qtext(Fraction(case['next_rate']))),)
    elif case['kind'] == 'reset':
        kwargs['resets'] = (Reset(case['reset_time'], qtext(Fraction(case['reset_phase']))),)
    return ClockSpec(**kwargs)


class IndependentAudioTests(unittest.TestCase):
    def assert_pcm(self, actual, expected):
        expected = np.asarray(expected, dtype=np.float64)
        if actual.ndim == 1:
            expected = expected.reshape(-1)
        np.testing.assert_allclose(actual, expected, atol=oracle.ABS_TOL, rtol=oracle.REL_TOL)

    def test_frozen_clock_bytes_and_independent_signal_oracle(self):
        self.assertEqual(hashlib.sha256(FROZEN.read_bytes()).hexdigest(), FROZEN_SHA)
        source = Path(oracle.__file__).read_text()
        self.assertNotIn('zaaggenz_', source)
        self.assertEqual((oracle.ABS_TOL, oracle.REL_TOL), (2e-12, 2e-12))

    def test_divisible_hold_is_exact_and_has_no_amplitude_quantizer(self):
        x = signal(71)
        plan = make(x, spec('12000'))
        expected = x[(np.arange(len(x)) // 4) * 4]
        np.testing.assert_array_equal(plan.render().audio, expected)
        np.testing.assert_array_equal(plan.captures[:, 0], x[::4])
        self.assertEqual(len(plan.events), math.ceil(len(x) / 4))

    def test_fractional_and_near_integer_rates_match_independent_pcm(self):
        x = signal(193)
        extent = Fraction(len(x), 48000)
        for virtual in ('11137', '11730', '159999999/10000', '160000001/10000', '1414213562373/100000000'):
            times = oracle.constant_events(virtual, 0, extent)
            for capture in ('linear_v1', 'nearest_left_tie_v1'):
                for reconstruction in ('hold_v1', 'linear_time_v1'):
                    with self.subTest(rate=virtual, capture=capture, reconstruction=reconstruction):
                        plan = make(x, spec(virtual, capture=capture, reconstruction=reconstruction))
                        expected = oracle.render(x.tolist(), 48000, times, 48000, len(x),
                                                 capture=capture, reconstruction=reconstruction)
                        self.assert_pcm(plan.render().audio, expected)
                        self.assertEqual([e.time_s for e in plan.events], list(map(float, times)))

    def test_explicit_ratio_reference_matches_hz_without_rounding_hold(self):
        x = signal(144)
        for ratio in ('1/3', '2/5', '3/7', '5/11', '7/13'):
            clock = ClockSpec(rate=VirtualRate(ratio, 'ratio', RateReference('48000/1')))
            by_ratio = make(x, SonicSpec(clock=clock))
            by_hz = make(x, spec(Fraction(ratio) * 48000))
            self.assertEqual(by_ratio.events, by_hz.events)
            np.testing.assert_array_equal(by_ratio.render().audio, by_hz.render().audio)
        below = make(x, spec('159999999/10000'))
        above = make(x, spec('160000001/10000'))
        self.assertNotEqual(below.events[1].time_s, above.events[1].time_s)
        self.assertFalse(np.array_equal(below.render().audio, above.render().audio))

    def test_every_original_frozen_clock_schedule_reaches_audio_kernel(self):
        frozen = json.loads(FROZEN.read_text())
        for case in frozen['clock_cases']:
            with self.subTest(case=case['name']):
                frames = int(Fraction(case['extent']) * 8000)
                plan = make(signal(frames), SonicSpec(clock=frozen_clock(case)), source_rate=8000)
                self.assertEqual(len(plan.events), len(case['events']))
                for index, (actual, expected) in enumerate(zip(plan.events, case['events'])):
                    self.assertEqual((actual.index, actual.epoch, actual.crossing),
                                     (index, expected.get('epoch', 0), expected['crossing']))
                    wanted = float(Decimal(expected['time_s']))
                    self.assertLessEqual(abs(actual.time_s - wanted),
                                         frozen['time_abs_tolerance_s'] + frozen['time_ulps'] * math.ulp(wanted))
                self.assertEqual(plan.render().audio.shape, (frames,))

    def test_ramp_and_step_pcm_match_frozen_time_aware_oracle(self):
        cases = json.loads(FROZEN.read_text())['clock_cases']
        for case in cases:
            if case['name'] not in ('ramp-up', 'ramp-down', 'step-on-crossing', 'reset-nonzero-phase'):
                continue
            x = signal(8000)
            times = [Decimal(e['time_s']) for e in case['events']]
            for reconstruction in ('hold_v1', 'linear_time_v1'):
                with self.subTest(case=case['name'], reconstruction=reconstruction):
                    plan = make(x, SonicSpec(clock=frozen_clock(case), reconstruction=reconstruction), source_rate=8000)
                    expected = oracle.render(x.tolist(), 8000, times, 8000, len(x), reconstruction=reconstruction)
                    self.assert_pcm(plan.render().audio, expected)

    def test_multiple_events_per_evaluation_interval_are_not_dropped(self):
        x = np.asarray([1., 3., -2., 5., 0.], dtype=np.float32)
        plan = make(x, spec('64000'), source_rate=8000)
        self.assertEqual(len(plan.events), len(x) * 8)
        np.testing.assert_array_equal(plan.render().audio, x)
        np.testing.assert_array_equal(plan.captures[::8, 0], x)
        self.assertEqual(plan.captures[1, 0], 1.25)

    def test_nearest_capture_exact_halfway_ties_go_left(self):
        x = np.asarray([2., 6., -4.], dtype=np.float32)
        plan = make(x, spec('16000', capture='nearest_left_tie_v1'), source_rate=8000)
        np.testing.assert_array_equal(plan.captures[:, 0], [2., 2., 6., 6., -4., -4.])

    def test_original_nonlinear_source_and_captures_survive_evaluation_rate_change(self):
        frozen = FrozenInput.from_pcm(signal(480), 48000)
        for reconstruction in ('hold_v1', 'linear_time_v1'):
            s = spec('11730', reconstruction=reconstruction)
            plans = [make(frozen, s, output_rate=r) for r in (48000, 96000, 192000)]
            for factor, plan in zip((1, 2, 4), plans):
                self.assertEqual(plan.events, plans[0].events)
                np.testing.assert_array_equal(plan.captures, plans[0].captures)
                self.assertEqual(plan.identity.input_asset, plans[0].identity.input_asset)
                np.testing.assert_allclose(plan.render().audio[::factor], plans[0].render().audio,
                                           atol=oracle.ABS_TOL, rtol=oracle.REL_TOL)
            self.assertEqual(len({p.render_sha256 for p in plans}), 3)

    def test_sampler_clock_modulation_does_not_integrate_playback_speed(self):
        x = (np.arange(8000, dtype=np.float32) / 8192)
        clock = ClockSpec(rate=rate(4), points_hz=(Point('1/1', '12/1'),), interpolation='linear')
        plan = make(x, SonicSpec(clock=clock), source_rate=8000)
        # The source is exactly linear between samples; at every event it still
        # addresses source t, rather than an integrated virtual-rate warp.
        expected = [e.time_s * 8000 / 8192 for e in plan.events]
        np.testing.assert_allclose(plan.captures[:, 0], expected, atol=oracle.ABS_TOL, rtol=oracle.REL_TOL)
        self.assertEqual(len(plan.render().audio), len(x))

    def test_six_khz_at_eight_khz_clock_has_independently_predicted_two_khz_alias(self):
        rate_hz, frames = 48000, 4800
        t = np.arange(frames) / rate_hz
        x = np.sin(2 * np.pi * 6000 * t).astype(np.float32)
        out = make(x, spec('8000')).render().audio
        expected = x[(np.arange(frames) // 6) * 6]
        np.testing.assert_array_equal(out, expected)
        spectrum = np.abs(np.fft.rfft(out))
        frequencies = np.fft.rfftfreq(frames, 1 / rate_hz)
        band = (frequencies > 0) & (frequencies < 4000)
        self.assertEqual(frequencies[np.flatnonzero(band)[np.argmax(spectrum[band])]], 2000)
        # Analytic amplitude of a six-point discrete hold, no fitted threshold.
        amplitude = abs(math.sin(math.pi * 2000 * 6 / rate_hz) /
                        (6 * math.sin(math.pi * 2000 / rate_hz)))
        self.assertAlmostEqual(2 * spectrum[np.where(frequencies == 2000)[0][0]] / frames,
                               amplitude, delta=2e-7)  # canonical float32 input quantization

    def test_partial_wet_uses_declared_dry_source_and_does_not_normalize(self):
        x = signal(180) * 8
        s = spec('11137', wet=.37, reconstruction='linear_time_v1')
        plan = make(x, s, output_rate=96000)
        times = oracle.constant_events('11137', 0, Fraction(len(x), 48000))
        expected = oracle.render(x.tolist(), 48000, times, 96000, len(x) * 2,
                                 reconstruction='linear_time_v1', wet=.37)
        self.assert_pcm(plan.render().audio, expected)
        self.assertGreater(np.max(np.abs(plan.render().audio)), 1.)


class BoundaryAndStateTests(unittest.TestCase):
    def test_plan_factory_cannot_be_bypassed_with_constructor_or_replace(self):
        plan = make(signal(96))
        accepted = plan.render()
        with self.assertRaises(ContractError):
            SamplerPlan()
        for replacement in ({'captures': np.zeros_like(plan.captures)},
                            {'spec': replace(plan.spec, wet=0)},
                            {'frame_count': plan.frame_count + 1}):
            with self.subTest(replacement=next(iter(replacement))):
                with self.assertRaises(ContractError):
                    replace(plan, **replacement)
        self.assertEqual(accepted.render_sha256, plan.render().render_sha256)
        np.testing.assert_array_equal(accepted.audio, plan.render().audio)

    def test_bypass_and_zero_wet_are_exact_pcm_including_signed_zero(self):
        x = np.asarray([0., -0., .12345679, -2.5, np.finfo(np.float32).max], dtype=np.float32)
        for s in (spec(bypass=True), spec(wet=0.)):
            out = make(x, s).render().audio
            self.assertEqual(out.dtype, x.dtype)
            self.assertEqual(out.tobytes(), x.tobytes())

    def test_mismatched_grid_bypass_is_rejected_without_silent_resampling(self):
        for s in (spec(bypass=True), spec(wet=0.)):
            with self.assertRaises((ContractError, UnsupportedNyquismic)):
                make(signal(50), s, output_rate=96000)

    def test_zero_silence_empty_one_sample_and_boundary_extension(self):
        for shape in ((0,), (1,), (33,), (0, 2), (1, 2), (33, 2)):
            channels = 1 if len(shape) == 1 else 2
            for boundary in ('zero_pad', 'edge_hold'):
                with self.subTest(shape=shape, boundary=boundary):
                    plan = make(np.zeros(shape, dtype=np.float32), spec(channels=channels, input_boundary=boundary))
                    self.assertEqual(plan.render().audio.shape, shape)
                    self.assertFalse(np.any(plan.render().audio))
        for boundary, wanted in (('zero_pad', [3., 1.5, 0., 0.]), ('edge_hold', [3., 3., 3., 3.])):
            plan = make(np.asarray([3.], dtype=np.float32), spec('16000', input_boundary=boundary),
                        source_rate=8000, output_rate=16000, frame_count=4)
            np.testing.assert_array_equal(plan.render().audio, wanted)

    def test_linear_lookahead_uses_full_context_then_holds_last_admitted_capture(self):
        x = np.arange(8000, dtype=np.float32) / 8192
        plan = make(x, spec('4', reconstruction='linear_time_v1'), source_rate=8000)
        whole = plan.render().audio
        self.assertAlmostEqual(whole[1000], float(x[1000]), delta=oracle.ABS_TOL)
        np.testing.assert_array_equal(plan.render(900, 1100).audio, whole[900:1100])
        self.assertEqual(whole[-1], float(x[6000]))
        self.assertEqual(len(plan.events), 4)  # no invented event at excluded t=1

    def test_nonzero_initial_phase_is_zero_before_first_capture(self):
        s = SonicSpec(clock=ClockSpec(rate=rate(4), phase_cycles='1/2'))
        plan = make(np.ones(8000, dtype=np.float32), s, source_rate=8000)
        out = plan.render().audio
        np.testing.assert_array_equal(out[:1000], 0.)
        np.testing.assert_array_equal(out[1000:], 1.)

    def test_continuous_chunks_explicit_resets_and_per_note_origin(self):
        x = signal(819)
        clock = ClockSpec(rate=rate('11730'),
                          points_hz=(Point('1/200', '16384/1'), Point('1/100', '8192/1')),
                          interpolation='linear', resets=(Reset('1/150', '1/3'),))
        for reconstruction in ('hold_v1', 'linear_time_v1'):
            plan = make(x, SonicSpec(clock=clock, reconstruction=reconstruction))
            whole = plan.render().audio
            cuts = [0, 1, 7, 239, 240, 241, 319, 320, 321, 517, 818, 819]
            state = plan.checkpoint(0)
            pieces = []
            for a, b in zip(cuts, cuts[1:]):
                part = plan.render(a, b, checkpoint=SamplerCheckpoint.from_json(state.to_json()))
                pieces.append(part.audio)
                state = part.checkpoint
                self.assertEqual(state.next_frame, b)
            np.testing.assert_array_equal(np.concatenate(pieces), whole)
            np.testing.assert_array_equal(plan.render(319, 518).audio, whole[319:518])
            np.testing.assert_array_equal(plan.render(checkpoint=plan.checkpoint(321)).audio, whole[321:])
        # A separate explicitly originated note resets only its own clock.
        a = make(x, spec('11137'))
        b = make(x, SonicSpec(clock=ClockSpec(rate=rate('11137'), origin_s='2/1')))
        np.testing.assert_array_equal(a.render().audio, b.render().audio)
        np.testing.assert_array_equal(a.captures, b.captures)

    def test_reset_on_output_boundary_replaces_capture_without_duplicate(self):
        x = np.arange(8000, dtype=np.float32) / 8192
        s = SonicSpec(clock=ClockSpec(rate=rate(4), resets=(Reset('1/2'),)))
        plan = make(x, s, source_rate=8000)
        self.assertEqual([(e.epoch, e.crossing) for e in plan.events], [(0, 0), (0, 1), (1, 0), (1, 1)])
        self.assertEqual(plan.render().audio[4000], float(x[4000]))
        np.testing.assert_array_equal(plan.render(checkpoint=plan.checkpoint(4000)).audio,
                                      plan.render().audio[4000:])

    def test_stereo_channels_and_unrelated_instances_have_separate_histories(self):
        x = signal(291, 2)
        for link in ('linked', 'independent'):
            stereo = make(x, spec('11137', channels=2, stereo_link=link, reconstruction='linear_time_v1'))
            mono = [make(x[:, c], spec('11137', reconstruction='linear_time_v1')).render().audio for c in range(2)]
            np.testing.assert_array_equal(stereo.render().audio, np.column_stack(mono))
        a = make(x, spec('11137', channels=2, instance_id='a'))
        b = make(x, spec('11137', channels=2, instance_id='b'))
        np.testing.assert_array_equal(a.render().audio, b.render().audio)
        with self.assertRaises(ContractError):
            b.render(checkpoint=a.checkpoint(100))

    def test_input_snapshot_cannot_be_mutated_through_original_or_public_pcm(self):
        x = signal(80)
        frozen = FrozenInput.from_pcm(x, 48000)
        original = frozen.pcm.copy()
        x[:] = 0
        np.testing.assert_array_equal(frozen.pcm, original)
        with self.assertRaises(ValueError):
            frozen.pcm[0] = 10
        with self.assertRaises(ValueError):
            frozen.pcm.setflags(write=True)

    def test_checkpoint_roundtrip_tamper_foreign_source_quality_and_context(self):
        source = FrozenInput.from_pcm(signal(180), 48000)
        plan = make(source, spec(reconstruction='linear_time_v1'))
        state = plan.checkpoint(77)
        restored = SamplerCheckpoint.from_json(state.to_json())
        self.assertEqual(restored, state)
        data = json.loads(state.to_json())
        data['next_frame'] += 1
        tampered = SamplerCheckpoint.from_json(json.dumps(data))
        with self.assertRaises(ContractError):
            plan.render(checkpoint=tampered)
        with self.assertRaises(ContractError):
            plan.render(76, 100, checkpoint=state)
        for other in (make(signal(180) + .001, spec(reconstruction='linear_time_v1')),
                      make(source, spec(reconstruction='linear_time_v1'), output_rate=96000),
                      make(source, spec(reconstruction='linear_time_v1'), context_sha256='a' * 64),
                      make(source, spec(reconstruction='linear_time_v1'), frame_count=179)):
            with self.assertRaises(ContractError):
                other.render(checkpoint=state)

    def test_display_label_is_not_a_new_sonic_execution(self):
        source = FrozenInput.from_pcm(signal(180), 48000)
        a, b = [make(source, spec(label=label)) for label in ('old', 'new')]
        self.assertEqual(a.render_sha256, b.render_sha256)
        np.testing.assert_array_equal(b.render(checkpoint=a.checkpoint(61)).audio,
                                      a.render().audio[61:])

    def test_checkpoint_capture_history_is_verified_not_trusted(self):
        plan = make(signal(180), spec(reconstruction='linear_time_v1'))
        original = json.loads(plan.checkpoint(77).to_json())
        for field in ('previous_capture', 'next_capture'):
            data = json.loads(json.dumps(original))
            self.assertTrue(data[field])
            data[field][0] += .125
            tampered = SamplerCheckpoint.from_json(json.dumps(data))
            with self.subTest(field=field), self.assertRaises(ContractError):
                plan.render(checkpoint=tampered)
        for field in ('previous_event_index', 'next_event_index'):
            data = json.loads(json.dumps(original))
            data[field] += 1
            tampered = SamplerCheckpoint.from_json(json.dumps(data))
            with self.subTest(field=field), self.assertRaises(ContractError):
                plan.render(checkpoint=tampered)

    def test_diagnostics_disclose_full_context_and_numerical_output(self):
        plan = make(signal(180), spec('11137'), output_rate=96000)
        report = plan.render(11, 43).diagnostics
        self.assertEqual(report['source_rate_hz'], 48000)
        self.assertEqual(report['numerical_rate_hz'], 96000)
        self.assertEqual(report['full_output_frames'], 360)
        self.assertEqual(report['region_frames'], [11, 43])
        self.assertEqual(Fraction(report['output_extent_s']), Fraction(32, 96000))
        self.assertEqual(report['captured_event_count'], len(plan.events))
        self.assertEqual(report['admitted_event_count'], len(plan.events))
        self.assertEqual(report['requested_rate_range_hz'], [11137., 11137.])
        self.assertEqual(report['render_sha256'], plan.render_sha256)
        self.assertFalse(report['delivery_conversion_performed'])
        self.assertTrue(report['finite'])

    def test_decimal_ambient_context_does_not_change_audio_or_captures(self):
        s = SonicSpec(clock=ClockSpec(rate=rate(4), points_hz=(Point('1/1', '12/1'),), interpolation='linear'),
                      reconstruction='linear_time_v1')
        source = FrozenInput.from_pcm(signal(8000), 8000)
        normal = make(source, s, source_rate=8000)
        with localcontext() as context:
            context.prec = 6
            context.rounding = 'ROUND_FLOOR'
            lowered = make(source, s, source_rate=8000)
            np.testing.assert_array_equal(lowered.captures, normal.captures)
            np.testing.assert_array_equal(lowered.render().audio, normal.render().audio)


class AdmissionAndCancellationTests(unittest.TestCase):
    def test_explicit_invalid_revision_identity_is_not_replaced_by_default(self):
        for field in ('source_revision_sha256', 'context_sha256'):
            for invalid in ('', False, 0, 'invalid', '0' * 63):
                with self.subTest(field=field, value=invalid), self.assertRaises(ContractError):
                    make(signal(30), **{field: invalid})

    def test_invalid_nonfinite_or_mismatched_pcm_is_rejected(self):
        for x in (np.asarray([np.nan]), np.asarray([np.inf]), np.asarray([1 + 2j]),
                  np.asarray([True]), np.zeros((2, 3)), np.zeros((1, 1, 1)),
                  np.asarray([np.finfo(np.float64).max])):
            with self.subTest(dtype=x.dtype, shape=x.shape), self.assertRaises((ContractError, ValueError)):
                FrozenInput.from_pcm(x, 48000)
        good = FrozenInput.from_pcm(signal(20), 48000)
        asset = good.asset.to_dict()
        asset['content_sha256'] = '0' * 64
        with self.assertRaises((ContractError, ValueError)):
            FrozenInput.from_pcm(good.pcm, 48000, asset=Contract(asset))
        with self.assertRaises(ContractError):
            make(good, spec(channels=2))

    def test_unavailable_evaluation_and_unsupported_features_fail_even_when_bypassed(self):
        source = FrozenInput.from_pcm(signal(100), 48000)
        with self.assertRaises((ContractError, UnsupportedNyquismic)):
            SamplerPlan.prepare(source, spec(), EvaluationPolicy())
        unsupported = [SonicSpec(mode='playback_warp', playback=PlaybackMap()),
                       SonicSpec(mode='cascade', clock=None),
                       SonicSpec(clock=ClockSpec(routes=(ModulationRoute(depth=0),))),
                       SonicSpec(clock=ClockSpec(jitter=JitterSpec(model='uniform_frequency_cells_v1', amount=0))),
                       SonicSpec(clock=ClockSpec(quantizer=RateQuantizer('nearest_hz', ('8000/1',))))]
        for s in unsupported:
            for bypass in (False, True):
                with self.subTest(mode=s.mode, bypass=bypass), self.assertRaises((ContractError, UnsupportedNyquismic)):
                    make(source, replace(s, bypass=bypass))

    def test_event_frame_read_and_independent_channel_budgets_are_admission_gates(self):
        cases = [
            (signal(100), spec('48000'), ResourceBudget(max_events=99), 100),
            (signal(100), spec(bypass=True), ResourceBudget(max_frames=99), 100),
            (signal(20), spec('1/1000', wet=0), ResourceBudget(max_read_s=1), 48001),
            (signal(32, 2), spec('48000', channels=2, stereo_link='independent'), ResourceBudget(max_events=63), 32),
        ]
        for x, s, budget, frames in cases:
            with self.subTest(budget=budget), self.assertRaises(ContractError):
                SamplerPlan.prepare(FrozenInput.from_pcm(x, 48000), s,
                                    sampler_evaluation(48000, budget=budget), frame_count=frames)
        source = FrozenInput.from_pcm(signal(33), 48000)
        for frames in (-1, True, 2.5):
            with self.subTest(frames=frames), self.assertRaises(ContractError):
                SamplerPlan.prepare(source, spec(), sampler_evaluation(48000), frame_count=frames)

    def test_cancellation_before_during_and_after_prepare_never_returns_partial_plan(self):
        source = FrozenInput.from_pcm(signal(4800), 48000)
        with self.assertRaises(ClockCancelled):
            SamplerPlan.prepare(source, spec(), sampler_evaluation(48000), cancelled=lambda: True)
        calls = [0]
        def cancel_in_work():
            calls[0] += 1
            return calls[0] >= 4
        with self.assertRaises(ClockCancelled):
            SamplerPlan.prepare(source, spec(), sampler_evaluation(48000), cancelled=cancel_in_work)
        self.assertGreaterEqual(calls[0], 4)
        for threshold in (.2, 1.):
            cancelled = [False]
            def on_progress(value):
                if value >= threshold:
                    cancelled[0] = True
            with self.subTest(threshold=threshold), self.assertRaises(ClockCancelled):
                SamplerPlan.prepare(source, spec(), sampler_evaluation(48000),
                                    cancelled=lambda: cancelled[0], progress=on_progress)
        self.assertEqual(make(source).render().audio.shape, (4800,))

    def test_cancelled_render_does_not_mutate_reusable_state_or_publish_success(self):
        plan = make(signal(4800), spec(reconstruction='linear_time_v1'))
        good = plan.render().audio.copy()
        state = plan.checkpoint(21)
        for threshold in (0., .2, 1.):
            cancelled = [threshold == 0]
            progress = []
            def on_progress(value):
                progress.append(value)
                if value >= threshold:
                    cancelled[0] = True
            with self.subTest(threshold=threshold), self.assertRaises(ClockCancelled):
                plan.render(checkpoint=state, cancelled=lambda: cancelled[0], progress=on_progress)
            self.assertEqual(progress, sorted(progress))
            self.assertEqual(state, plan.checkpoint(21))
            np.testing.assert_array_equal(plan.render().audio, good)

    def test_progress_is_bounded_monotone_and_complete(self):
        capture_progress, output_progress = [], []
        plan = make(signal(4800), progress=capture_progress.append)
        plan.render(progress=output_progress.append)
        for values in (capture_progress, output_progress):
            self.assertTrue(values)
            self.assertEqual(values[-1], 1.)
            self.assertEqual(values, sorted(values))
            self.assertTrue(all(type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1 for v in values))


if __name__ == '__main__':
    unittest.main()
