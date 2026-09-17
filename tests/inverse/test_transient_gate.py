import json
import math
import unittest

import numpy as np

from zaaggenz_inverse import ValidationPolicy
from zaaggenz_inverse.objectives import validation_measurements
from zaaggenz_inverse.transient import METHOD_ID, transient_preservation

SR = 48000
FRAMES = 18432


def reasons(report):
    return set(report['rejected_reasons'])


def _base(root_hz=247., phases=(0., 0., 0., 0.), amplitudes=(1., .31, .14, .06),
          attack_ms=7., decay_ms=270., frames=FRAMES):
    t = np.arange(frames, dtype=np.float64)/SR
    envelope = np.minimum(t/(attack_ms/1000.), 1.)*np.exp(-t/(decay_ms/1000.))
    harmonics = (1, 3, 4, 7)
    signal = sum(a*np.sin(2*np.pi*root_hz*h*t+p)
                 for h, a, p in zip(harmonics, amplitudes, phases))*envelope
    signal /= np.max(np.abs(signal))
    return signal.astype(np.float32)


def _rms_match(value, reference):
    value = np.asarray(value, dtype=np.float64)
    reference = np.asarray(reference, dtype=np.float64)
    gain = math.sqrt(float(np.mean(reference*reference)))/max(
        math.sqrt(float(np.mean(value*value))), 1e-30)
    return (value*gain).astype(np.float32)


def _burst(root_hz=247., frames=None):
    frames = round(.016*SR) if frames is None else frames
    t = np.arange(frames, dtype=np.float64)/SR
    envelope = np.minimum(t/.0025, 1.)*np.exp(-t/.007)
    harmonics, amplitudes = (1, 3, 4, 7), (1., .31, .14, .06)
    signal = sum(a*np.sin(2*np.pi*root_hz*h*t)
                 for h, a in zip(harmonics, amplitudes))*envelope
    signal /= np.max(np.abs(signal))
    return signal.astype(np.float32)


class TransientGateTests(unittest.TestCase):
    def setUp(self):
        self.target = _base()

    def assert_transient_accepts(self, candidate):
        report = validation_measurements(self.target, candidate, SR)
        self.assertNotIn('transient_loss', reasons(report), report['measurements'].get('transient_measurements'))
        self.assertEqual(report['measurements']['transient_method'], METHOD_ID)
        return report

    def assert_transient_rejects(self, target, candidate):
        report = validation_measurements(target, candidate, SR)
        self.assertIn('transient_loss', reasons(report), report['measurements'].get('transient_measurements'))
        self.assertEqual(report['measurements']['transient_method'], METHOD_ID)
        return report

    def test_preserved_gain_phase_root_and_timbre_are_not_transient_loss(self):
        candidates = (
            self.target,
            (self.target*.58).astype(np.float32),
            _base(phases=(.3, 1.7, 2.6, .9)),
            _base(root_hz=369.99),
            _base(amplitudes=(1., .11, .38, .16)),
        )
        for candidate in candidates:
            with self.subTest(candidate_sha=hash(candidate.tobytes())):
                report = self.assert_transient_accepts(candidate)
                finding = next(x for x in report['findings'] if x['gate'] == 'transient_loss')
                self.assertGreaterEqual(finding['value'], .4)

    def test_removed_smoothed_attenuated_lowpass_and_flattened_attacks_reject(self):
        target = self.target.astype(np.float64)
        n22, n6 = round(.022*SR), round(.006*SR)
        damaged = {}

        candidate = target.copy()
        n30, n4 = round(.030*SR), round(.004*SR)
        candidate[:n30] = 0.
        candidate[n30:n30+n4] *= np.linspace(0., 1., n4, endpoint=False)
        damaged['removed'] = _rms_match(candidate, target)

        t = np.arange(FRAMES, dtype=np.float64)/SR
        n48 = round(.048*SR)
        ramp = np.ones(FRAMES)
        phase = np.arange(n48)/(n48-1)
        ramp[:n48] = .5-.5*np.cos(np.pi*phase)
        carrier = sum(a*np.sin(2*np.pi*247.*h*t)
                      for h, a in zip((1, 3, 4, 7), (1., .31, .14, .06)))
        candidate = carrier*np.exp(-t/.270)*ramp
        candidate /= np.max(np.abs(candidate))
        damaged['smoothed'] = _rms_match(candidate, target)

        candidate = target.copy()
        candidate[:n22] *= .12
        candidate[n22:n22+n6] *= np.linspace(.12, 1., n6, endpoint=False)
        damaged['attenuated'] = _rms_match(candidate, target)

        kernel = np.ones(round(.003*SR))/round(.003*SR)
        filtered = np.convolve(target, kernel, mode='same')
        candidate = target.copy()
        candidate[:n22] = filtered[:n22]
        blend = np.linspace(0., 1., n6, endpoint=False)
        candidate[n22:n22+n6] = ((1.-blend)*filtered[n22:n22+n6] +
                                 blend*target[n22:n22+n6])
        damaged['onset_lowpass'] = _rms_match(candidate, target)

        candidate = target.copy()
        limit = .16*np.max(np.abs(target))
        candidate[:n22] = np.clip(candidate[:n22], -limit, limit)
        damaged['flattened'] = _rms_match(candidate, target)

        for name, candidate in damaged.items():
            with self.subTest(name=name):
                report = self.assert_transient_rejects(self.target, candidate)
                finding = next(x for x in report['findings'] if x['gate'] == 'transient_loss')
                self.assertLess(finding['value'], .4)
                json.dumps(report, allow_nan=False)

    def test_missing_secondary_onset_rejects_even_if_later_candidate_onset_survives(self):
        burst = _burst()
        start = round(.096*SR)
        target = self.target.copy()
        target[start:start+len(burst)] += burst
        candidate = self.target.copy()
        # Add a strong later onset: candidate-side re-anchoring must not hide the
        # missing target onset at 96 ms.
        later = round(.180*SR)
        candidate[later:later+len(burst)] += 1.3*burst
        report = self.assert_transient_rejects(target, candidate)
        records = report['measurements']['transient_measurements'][0]['anchors']
        self.assertTrue(any(record['onset_contrast_ratio'] == 0. for record in records))

    def test_multiple_onsets_and_one_damaged_stereo_channel_are_protected(self):
        burst = _burst()
        target = self.target.copy()
        candidate = self.target.copy()
        first, second = round(.072*SR), round(.144*SR)
        target[first:first+len(burst)] += .8*burst
        target[second:second+len(burst)] += .9*burst
        candidate[first:first+len(burst)] += .8*burst
        candidate[second:second+len(burst)] += .09*burst
        self.assert_transient_rejects(target, candidate)

        stereo_target = np.column_stack((self.target, self.target))
        stereo_candidate = stereo_target.copy()
        n22, n6 = round(.022*SR), round(.006*SR)
        stereo_candidate[:n22, 0] *= .08
        stereo_candidate[n22:n22+n6, 0] *= np.linspace(.08, 1., n6, endpoint=False)
        report = self.assert_transient_rejects(stereo_target, stereo_candidate)
        ratios = report['measurements']['transient_channel_ratios']
        self.assertLess(ratios[0], .4)
        self.assertGreaterEqual(ratios[1], .4)

    def test_threshold_boundary_is_strict_and_raw_records_survive_rejection(self):
        candidate = self.target.copy()
        n22, n6 = round(.022*SR), round(.006*SR)
        candidate[:n22] *= .12
        candidate[n22:n22+n6] *= np.linspace(.12, 1., n6, endpoint=False)
        measured = transient_preservation(self.target, candidate, SR)['ratio']
        self.assertGreater(measured, 0.)
        self.assertLess(measured, 1.)

        at_boundary = ValidationPolicy(min_transient_ratio=measured)
        just_above = ValidationPolicy(min_transient_ratio=math.nextafter(measured, math.inf))
        self.assertNotIn('transient_loss', reasons(validation_measurements(self.target, candidate, SR, at_boundary)))
        rejected = validation_measurements(self.target, candidate, SR, just_above)
        self.assertIn('transient_loss', reasons(rejected))
        self.assertTrue(rejected['measurements']['transient_measurements'][0]['anchors'])

    def test_minimum_length_silence_near_silence_and_low_rate_are_finite(self):
        cases = (
            (np.linspace(-.1, .1, 32, dtype=np.float32), 48000),
            (np.zeros(64, dtype=np.float32), 48000),
            ((self.target[:256]*1e-10).astype(np.float32), 48000),
            (np.sin(np.arange(64)*.2).astype(np.float32), 8000),
        )
        for value, sr in cases:
            with self.subTest(length=len(value), sr=sr):
                result = transient_preservation(value, value, sr)
                self.assertTrue(math.isfinite(result['ratio']))
                self.assertEqual(result['ratio'], 1.)
                json.dumps(result, allow_nan=False)

    def test_method_record_is_explicit_and_bounded(self):
        result = transient_preservation(self.target, self.target, SR)
        self.assertEqual(result['method'], 'zg.inverse.transient-onset-contrast.v3')
        self.assertEqual(result['parameters']['max_anchors_per_channel'], 8)
        self.assertEqual(result['parameters']['high_band_cutoff_hz'], 1000.)
        self.assertLessEqual(len(result['anchor_samples'][0]), 8)
        for record in result['channels'][0]['anchors']:
            self.assertEqual(set(record), {
                'anchor_sample', 'target_onset_contrast', 'candidate_onset_contrast',
                'onset_contrast_ratio', 'amplitude_ratio', 'spectral_ratio',
                'spectral_applicable', 'target_high_band_fraction_early',
                'target_high_band_fraction_late', 'candidate_high_band_fraction_early',
                'candidate_high_band_fraction_late', 'score'})


if __name__ == '__main__':
    unittest.main()
