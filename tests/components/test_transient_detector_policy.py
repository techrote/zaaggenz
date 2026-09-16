from __future__ import annotations
import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np

import zaaggenz_components.tracker as tracker
from zaaggenz_components import analyse_components

SR=12000


def tone(f=440.0,duration=1.0,amp=.6):
    t=np.arange(round(SR*duration),dtype=np.float64)/SR
    return (amp*np.cos(2*np.pi*f*t+.2)).astype(np.float32)


class TransientDetectorPolicyTests(unittest.TestCase):
    def test_normal_multiresolution_path_is_provenance_visible(self):
        result=analyse_components(tone(),SR)
        provenance=result.diagnostics['transient_detector']
        self.assertEqual(provenance['policy'],'short-flux-plus-derivative-fail-closed-v1')
        self.assertEqual(provenance['primary'],'zg-multiresolution-features-v1')
        self.assertEqual(provenance['mode'],'short-flux-plus-derivative')
        self.assertEqual(provenance['primary_status'],'ok')
        self.assertEqual(provenance['fallback_class'],'none')
        self.assertEqual(provenance['fallback_reason'],'none')
        self.assertEqual(provenance['transform_eligibility'],'normal')
        self.assertGreater(result.diagnostics['transform_frames'],0)
        config=result.bundle.to_dict()['method']['configuration']
        self.assertEqual(config['transient_detector_policy'],provenance['policy'])
        self.assertEqual(config['transient_detector_mode'],provenance['mode'])
        self.assertEqual(config['transient_detector_primary_status'],'ok')
        self.assertEqual(config['transient_detector_transform_eligibility'],'normal')

    def test_declared_primary_abstention_is_preserve_only_not_transform_permission(self):
        # A successful primary analysis with no eligible short-flux frames is the one
        # intentionally supported fallback. Simulate that valid abstention while leaving
        # the component candidate tracker enough clean-tone evidence to form tracks.
        primary={'short':SimpleNamespace(frames=())}
        with mock.patch.object(tracker,'analyse_multiresolution',return_value=primary):
            result=tracker.analyse_components(tone(),SR)
        provenance=result.diagnostics['transient_detector']
        self.assertEqual(provenance['mode'],'derivative-only-primary-abstained')
        self.assertEqual(provenance['primary_status'],'abstained')
        self.assertEqual(provenance['fallback_class'],'analysis-abstention')
        self.assertEqual(provenance['fallback_reason'],'no-full-support-spectral-flux-frames')
        self.assertEqual(provenance['transform_eligibility'],'preserve-only')
        tracks=result.bundle.to_dict()['tracks']
        self.assertTrue(tracks,'fixture must exercise transform-eligible component tracks')
        self.assertEqual(result.diagnostics['transform_frames'],0)
        self.assertTrue(all(frame['action']=='preserve' for tr in tracks for frame in tr['frames']))
        config=result.bundle.to_dict()['method']['configuration']
        self.assertEqual(config['transient_detector_mode'],'derivative-only-primary-abstained')
        self.assertEqual(config['transient_detector_transform_eligibility'],'preserve-only')

    def test_programmer_and_dependency_failures_propagate_without_fallback(self):
        x=np.zeros(256,dtype=np.float32)
        for error in (ValueError('bad analysis state'),RuntimeError('implementation fault'),ImportError('dependency fault')):
            with self.subTest(error=type(error).__name__):
                with mock.patch.object(tracker,'analyse_multiresolution',side_effect=error):
                    with self.assertRaises(type(error)) as raised:
                        tracker.analyse_components(x,SR)
                self.assertIs(raised.exception,error)

    def test_resource_and_cancellation_failures_keep_their_native_class(self):
        x=np.zeros(256,dtype=np.float32)
        for error in (MemoryError('allocation failed'),OSError('resource failed'),KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__):
                with mock.patch.object(tracker,'analyse_multiresolution',side_effect=error):
                    with self.assertRaises(type(error)) as raised:
                        tracker.analyse_components(x,SR)
                self.assertIs(raised.exception,error)

    def test_malformed_primary_result_fails_closed_instead_of_derivative_fallback(self):
        with mock.patch.object(tracker,'analyse_multiresolution',return_value={}):
            with self.assertRaises(KeyError):
                tracker.analyse_components(np.zeros(256,dtype=np.float32),SR)

    def test_transient_protection_and_reconstruction_invariants_remain_intact(self):
        x=tone(330.0)
        mid=len(x)//2
        x[mid]+=1.0
        result=analyse_components(x,SR)
        self.assertEqual(result.diagnostics['transient_detector']['mode'],'short-flux-plus-derivative')
        self.assertEqual(result.transient_mask[mid],1)
        self.assertGreater(abs(float(result.transient[mid])),.5)
        self.assertLess(result.diagnostics['reconstruction_rms_error'],1e-6)
        self.assertTrue(np.array_equal(tracker.exact_bypass(x),x.astype(np.float32)))

    def test_empty_input_is_explicit_non_applicable_not_an_error_fallback(self):
        result=analyse_components(np.zeros(0,dtype=np.float32),SR)
        provenance=result.diagnostics['transient_detector']
        self.assertEqual(provenance['mode'],'not-run-empty-input')
        self.assertEqual(provenance['primary_status'],'not-applicable')
        self.assertEqual(provenance['fallback_class'],'none')
        self.assertEqual(provenance['transform_eligibility'],'preserve-only')


if __name__=='__main__':
    unittest.main(verbosity=2)
