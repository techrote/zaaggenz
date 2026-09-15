from __future__ import annotations

from copy import deepcopy
import unittest

import numpy as np

from zaaggenz_components import ComponentAnalysis, ComponentError, analyse_components
from zaaggenz_contracts import Contract

SR=12000


def tone(frames=2048):
    t=np.arange(frames,dtype=np.float64)/SR
    return (.4*np.cos(2*np.pi*440*t+.13)).astype(np.float32)


def rebuild(original,bundle_dict,**arrays):
    values=dict(source=np.asarray(original.source).copy(),sinusoidal=np.asarray(original.sinusoidal).copy(),
                transient=np.asarray(original.transient).copy(),residual=np.asarray(original.residual).copy(),
                transient_mask=np.asarray(original.transient_mask).copy())
    values.update(arrays)
    return ComponentAnalysis(Contract(bundle_dict),values['source'],values['sinusoidal'],values['transient'],
                             values['residual'],values['transient_mask'],deepcopy(original.diagnostics),SR)


class ComponentIdentityBindingTests(unittest.TestCase):
    def setUp(self):self.analysis=analyse_components(tone(),SR)

    def test_tracker_product_is_bound_and_reconstructs(self):
        a=self.analysis
        self.assertEqual(a.sample_rate_hz,SR)
        self.assertTrue(np.isfinite(a.reconstruction).all())
        self.assertEqual(a.reconstruction.shape,a.source.shape)

    def test_forged_source_content_identity_fails(self):
        d=self.analysis.bundle.to_dict();d['asset']['content_sha256']='0'*64
        with self.assertRaisesRegex(ComponentError,'source content identity mismatch'):rebuild(self.analysis,d)

    def test_frame_extent_mismatch_fails_before_reconstruction(self):
        d=self.analysis.bundle.to_dict();d['asset']['frame_count']+=1
        with self.assertRaisesRegex(ComponentError,'source frame_count mismatch'):rebuild(self.analysis,d)

    def test_huge_declared_extent_is_rejected_before_proportional_allocation(self):
        empty=analyse_components(np.zeros(0,dtype=np.float32),SR);d=empty.bundle.to_dict();d['asset']['frame_count']=1_000_000_000
        with self.assertRaisesRegex(ComponentError,'source frame_count mismatch'):
            ComponentAnalysis(Contract(d),np.zeros(0,dtype=np.float32),np.zeros(0,dtype=np.float32),
                              np.zeros(0,dtype=np.float32),np.zeros(0,dtype=np.float32),
                              np.zeros(0,dtype=np.float32),deepcopy(empty.diagnostics),SR)

    def test_wrong_bundle_sample_rate_cannot_reinterpret_phase_time(self):
        d=self.analysis.bundle.to_dict();d['asset']['sample_rate_hz']=24000
        with self.assertRaisesRegex(ComponentError,'source sample_rate_hz mismatch'):rebuild(self.analysis,d)

    def test_remainder_assets_are_bound_to_actual_arrays(self):
        for key,label in (('transient_asset','transient'),('residual_asset','residual')):
            d=self.analysis.bundle.to_dict();d[key]['content_sha256']='1'*64
            with self.subTest(key=key),self.assertRaisesRegex(ComponentError,label+' content identity mismatch'):
                rebuild(self.analysis,d)

    def test_wrong_channels_fail_even_for_zero_track_bundle(self):
        empty=analyse_components(np.zeros(0,dtype=np.float32),SR);d=empty.bundle.to_dict()
        for key in ('asset','transient_asset','residual_asset'):
            d[key]['channels']=2;d[key]['channel_layout']='stereo-lr'
        with self.assertRaisesRegex(ComponentError,'source channel metadata mismatch'):
            ComponentAnalysis(Contract(d),np.zeros(0,dtype=np.float32),np.zeros(0,dtype=np.float32),
                              np.zeros(0,dtype=np.float32),np.zeros(0,dtype=np.float32),
                              np.zeros(0,dtype=np.float32),deepcopy(empty.diagnostics),SR)

    def test_nonfinite_concrete_arrays_fail_closed(self):
        d=self.analysis.bundle.to_dict();bad=np.asarray(self.analysis.source).copy();bad[0]=np.nan
        with self.assertRaisesRegex(ComponentError,'source must be finite numeric data'):
            rebuild(self.analysis,d,source=bad)

    def test_stereo_binding_uses_interleaved_pcm_identity(self):
        x=tone();st=np.column_stack((x,-x));a=analyse_components(st,SR)
        self.assertEqual(a.bundle.to_dict()['asset']['channels'],2)
        self.assertEqual(a.source.shape[1],2)
        self.assertEqual(a.sample_rate_hz,SR)


if __name__=='__main__':unittest.main(verbosity=2)
