from __future__ import annotations
import asyncio
import unittest
from unittest.mock import patch

import numpy as np

from zaaggenz_components import analyse_components
from zaaggenz_contracts import validate

SR=12000


def tone(f=440.0,duration=1.0,amp=.6):
    t=np.arange(round(SR*duration))/SR
    return (amp*np.cos(2*np.pi*f*t+.2)).astype(np.float32)


class _Frame:
    def __init__(self,anchor,support_fraction=.5,flux=.01):
        self.anchor_sample=anchor
        self.support_fraction=support_fraction
        self.spectral_flux=flux


class _Timeline:
    def __init__(self,frames):
        self.frames=tuple(frames)


class TransientFallbackTests(unittest.TestCase):
    def test_normal_detector_is_provenance_visible(self):
        r=analyse_components(tone(),SR)
        detector=r.diagnostics['transient_detector']
        self.assertEqual(detector['policy'],'zg013-transient-detector-fail-closed-v1')
        self.assertEqual(detector['mode'],'multiresolution-flux-plus-derivative-v1')
        self.assertEqual(detector['failure_class'],'none')
        self.assertEqual(detector['reason'],'none')
        self.assertEqual(detector['transform_eligibility'],'normal')
        conf=r.bundle.to_dict()['method']['configuration']
        self.assertEqual(conf['transient_detector_policy'],detector['policy'])
        self.assertEqual(conf['transient_detector_mode'],detector['mode'])
        self.assertEqual(conf['transient_detector_failure_class'],'none')
        self.assertEqual(conf['transient_detector_reason'],'none')
        self.assertEqual(conf['transient_transform_eligibility'],'normal')
        validate(r.bundle.to_dict(),'PartialTrackBundle')

    def test_successful_timeline_without_eligible_flux_fails_closed(self):
        degraded={'short':_Timeline([_Frame(100,.5,.03),_Frame(200,.9,.04)])}
        with patch('zaaggenz_components.tracker.analyse_multiresolution',return_value=degraded):
            r=analyse_components(tone(),SR)
        detector=r.diagnostics['transient_detector']
        self.assertEqual(detector['mode'],'derivative-only-degraded-v1')
        self.assertEqual(detector['failure_class'],'data-level-abstention')
        self.assertEqual(detector['reason'],'no-full-support-short-flux')
        self.assertEqual(detector['transform_eligibility'],'preserve-all')
        frames=[f for tr in r.bundle.to_dict()['tracks'] for f in tr['frames']]
        self.assertGreater(len(frames),0)
        self.assertTrue(all(f['action']=='preserve' for f in frames))
        self.assertEqual(r.diagnostics['transform_frames'],0)
        self.assertLess(r.diagnostics['reconstruction_rms_error'],1e-6)

    def test_programming_dependency_and_resource_errors_propagate_with_context(self):
        cases=(ValueError('bad frame'),RuntimeError('bug'),ModuleNotFoundError('missing dependency'),MemoryError('oom'))
        for failure in cases:
            with self.subTest(kind=type(failure).__name__):
                with patch('zaaggenz_components.tracker.analyse_multiresolution',side_effect=failure):
                    with self.assertRaises(type(failure)) as caught:
                        analyse_components(tone(),SR)
                notes=getattr(caught.exception,'__notes__',())
                self.assertTrue(any('no derivative-only fallback was used' in note for note in notes))
                self.assertEqual(str(caught.exception),str(failure))

    def test_cancellation_is_not_reclassified_as_data_abstention(self):
        with patch('zaaggenz_components.tracker.analyse_multiresolution',side_effect=asyncio.CancelledError('cancelled')):
            with self.assertRaises(asyncio.CancelledError):
                analyse_components(tone(),SR)

    def test_transient_protection_still_overrides_transform_permission(self):
        x=tone(330.0)
        mid=len(x)//2
        x[mid]+=1.0
        r=analyse_components(x,SR)
        self.assertEqual(r.diagnostics['transient_detector']['transform_eligibility'],'normal')
        self.assertEqual(r.transient_mask[mid],1)
        for tr in r.bundle.to_dict()['tracks']:
            for frame in tr['frames']:
                anchor=frame['support']['anchor_sample']
                if r.transient_mask[anchor]>=.5:
                    self.assertEqual(frame['action'],'preserve')
        self.assertGreater(abs(float(r.transient[mid])),.5)
        self.assertLess(r.diagnostics['reconstruction_rms_error'],1e-6)

    def test_empty_and_short_inputs_record_degraded_policy(self):
        empty=analyse_components(np.zeros(0,dtype=np.float32),SR)
        self.assertEqual(empty.diagnostics['transient_detector']['mode'],'empty-source-v1')
        self.assertEqual(empty.diagnostics['transient_detector']['transform_eligibility'],'preserve-all')
        short=analyse_components(np.zeros(100,dtype=np.float32),SR)
        self.assertEqual(short.diagnostics['transient_detector']['mode'],'derivative-only-degraded-v1')
        self.assertEqual(short.diagnostics['transient_detector']['transform_eligibility'],'preserve-all')
        self.assertEqual(short.diagnostics['transform_frames'],0)


if __name__=='__main__':
    unittest.main(verbosity=2)
