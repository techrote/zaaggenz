from __future__ import annotations
from unittest import mock
import unittest
import numpy as np

from zaaggenz_components import (
    ComponentAnalysis,ComponentError,analyse_components,reconstruct_components,
)
from zaaggenz_components.model import pcm_asset_ref
from zaaggenz_contracts import Contract

SR=12000

def _bundle(source,transient,residual,sr=SR):
    return Contract(dict(
        kind='PartialTrackBundle',version='1.0.0',
        asset=pcm_asset_ref(source,sr),
        method=dict(id='identity-fixture',version='1.0.0',configuration={}),
        phase_convention='cosine-at-anchor-radians-v1',
        channel_policy='shared-frequency-independent-channel-coefficients',
        data_origin='source_known',tracks=[],
        residual_asset=pcm_asset_ref(residual,sr),
        transient_asset=pcm_asset_ref(transient,sr),
        remainder_policy='additive-owned-remainders-v1',
    ))

def _analysis(source,*,sr=SR):
    source=np.asarray(source,dtype=np.float32)
    zero=np.zeros_like(source)
    mask=np.zeros(source.shape[0],dtype=np.float32)
    return ComponentAnalysis(_bundle(source,zero,zero,sr),source,zero.copy(),zero.copy(),zero.copy(),
                             mask,{'fixture':True},sr)

def _clone(base,bundle,**changes):
    values=dict(
        bundle=bundle,source=np.array(base.source,copy=True),
        sinusoidal=np.array(base.sinusoidal,copy=True),
        transient=np.array(base.transient,copy=True),
        residual=np.array(base.residual,copy=True),
        transient_mask=np.array(base.transient_mask,copy=True),
        diagnostics=dict(base.diagnostics),sample_rate_hz=base.sample_rate_hz,
    )
    values.update(changes)
    return ComponentAnalysis(**values)

class ComponentIdentityBindingTests(unittest.TestCase):
    def setUp(self):
        self.source=np.linspace(-.25,.25,64,dtype=np.float32)
        self.analysis=_analysis(self.source)

    def mutated_bundle(self,mutator):
        data=self.analysis.bundle.to_dict()
        mutator(data)
        return Contract(data)

    def test_tracker_produced_aggregate_is_bound_and_valid(self):
        t=np.arange(2400,dtype=np.float64)/SR
        tracked=analyse_components((.2*np.cos(2*np.pi*440*t)).astype(np.float32),SR)
        self.assertEqual(tracked.sample_rate_hz,SR)
        self.assertEqual(tracked.bundle.to_dict()['asset']['frame_count'],len(tracked.source))
        self.assertEqual(tracked.reconstruction.shape,tracked.source.shape)

    def test_wrong_frame_count_is_rejected(self):
        bundle=self.mutated_bundle(lambda d:d['asset'].__setitem__('frame_count',len(self.source)+1))
        with self.assertRaisesRegex(ComponentError,'frame_count mismatch'):
            _clone(self.analysis,bundle)

    def test_wrong_channel_count_and_layout_are_rejected(self):
        def mutate(d):
            d['asset']['channels']=2
            d['asset']['channel_layout']='stereo-lr'
        bundle=self.mutated_bundle(mutate)
        with self.assertRaisesRegex(ComponentError,'channels mismatch'):
            _clone(self.analysis,bundle)

    def test_same_shape_wrong_sample_rate_is_rejected(self):
        def mutate(d):
            for key in ('asset','residual_asset','transient_asset'):
                d[key]['sample_rate_hz']=SR+1
        bundle=self.mutated_bundle(mutate)
        with self.assertRaisesRegex(ComponentError,'sample_rate_hz mismatch'):
            _clone(self.analysis,bundle)

    def test_source_content_hash_mismatch_is_rejected(self):
        bundle=self.mutated_bundle(lambda d:d['asset'].__setitem__('content_sha256','0'*64))
        with self.assertRaisesRegex(ComponentError,'content_sha256 mismatch'):
            _clone(self.analysis,bundle)

    def test_different_source_same_shape_is_rejected(self):
        changed=np.array(self.analysis.source,copy=True)
        changed[7]+=np.float32(.125)
        with self.assertRaisesRegex(ComponentError,'content_sha256 mismatch'):
            _clone(self.analysis,self.analysis.bundle,source=changed)

    def test_transient_and_residual_assets_are_bound_to_arrays(self):
        bad_transient=np.array(self.analysis.transient,copy=True);bad_transient[3]=.1
        with self.assertRaisesRegex(ComponentError,'transient asset content_sha256 mismatch'):
            _clone(self.analysis,self.analysis.bundle,transient=bad_transient)
        bad_residual=np.array(self.analysis.residual,copy=True);bad_residual[5]=-.1
        with self.assertRaisesRegex(ComponentError,'residual asset content_sha256 mismatch'):
            _clone(self.analysis,self.analysis.bundle,residual=bad_residual)

    def test_one_frame_source_mismatch_is_rejected(self):
        shortened=np.array(self.analysis.source[:-1],copy=True)
        zeros=np.zeros_like(shortened)
        with self.assertRaisesRegex(ComponentError,'frame_count mismatch'):
            _clone(self.analysis,self.analysis.bundle,source=shortened,sinusoidal=zeros.copy(),
                   transient=zeros.copy(),residual=zeros.copy(),
                   transient_mask=np.zeros(len(shortened),dtype=np.float32))

    def test_nonfinite_aggregate_arrays_and_mask_fail_closed(self):
        for field in ('source','sinusoidal','transient','residual'):
            for value in (np.nan,np.inf,-np.inf):
                changed=np.array(getattr(self.analysis,field),copy=True)
                changed[0]=value
                with self.subTest(field=field,value=str(value)):
                    with self.assertRaises(ComponentError):
                        _clone(self.analysis,self.analysis.bundle,**{field:changed})
        for value in (np.nan,np.inf,-np.inf):
            mask=np.array(self.analysis.transient_mask,copy=True);mask[0]=value
            with self.subTest(field='transient_mask',value=str(value)):
                with self.assertRaisesRegex(ComponentError,'transient mask must be finite numeric'):
                    _clone(self.analysis,self.analysis.bundle,transient_mask=mask)

    def test_missing_or_untrusted_sample_rate_fails_closed(self):
        with self.assertRaisesRegex(ComponentError,'trusted sample_rate_hz required'):
            _clone(self.analysis,self.analysis.bundle,sample_rate_hz=None)
        with self.assertRaisesRegex(ComponentError,'trusted sample_rate_hz required'):
            _clone(self.analysis,self.analysis.bundle,sample_rate_hz=True)

    def test_mono_vector_and_single_column_share_canonical_identity(self):
        column=self.source[:,None]
        a=_analysis(self.source)
        b=_analysis(column)
        aa=a.bundle.to_dict()['asset'];bb=b.bundle.to_dict()['asset']
        self.assertEqual(aa['channels'],1);self.assertEqual(bb['channels'],1)
        self.assertEqual(aa['channel_layout'],'mono');self.assertEqual(bb['channel_layout'],'mono')
        self.assertEqual(aa['content_sha256'],bb['content_sha256'])
        self.assertEqual(b.source.shape,(len(self.source),1))

    def test_zero_track_and_empty_source_are_valid(self):
        empty=_analysis(np.zeros(0,dtype=np.float32))
        self.assertEqual(empty.bundle.to_dict()['tracks'],[])
        self.assertEqual(reconstruct_components(empty.bundle,source=empty.source,
                                                sample_rate_hz=empty.sample_rate_hz).shape,(0,))

    def test_large_legitimate_zero_track_source_has_no_arbitrary_cap(self):
        source=np.zeros(65536,dtype=np.float32)
        analysis=_analysis(source)
        rendered=reconstruct_components(analysis.bundle,source=analysis.source,
                                        sample_rate_hz=analysis.sample_rate_hz)
        self.assertEqual(rendered.shape,source.shape)
        self.assertTrue(np.array_equal(rendered,source))

    def test_concrete_source_mismatch_rejected_before_any_output_allocation(self):
        data=self.analysis.bundle.to_dict()
        data['asset']['frame_count']=1_000_000_000
        forged=Contract(data)
        with mock.patch('zaaggenz_components.reconstruct.np.zeros',
                        side_effect=AssertionError('allocation happened')) as zeros:
            with self.assertRaisesRegex(ComponentError,'frame_count mismatch'):
                reconstruct_components(forged,source=self.analysis.source,
                                       sample_rate_hz=self.analysis.sample_rate_hz)
            zeros.assert_not_called()

    def test_bound_reconstruction_is_bit_identical_to_portable_bundle_mode(self):
        portable=reconstruct_components(self.analysis.bundle)
        bound=reconstruct_components(self.analysis.bundle,source=self.analysis.source,
                                     sample_rate_hz=self.analysis.sample_rate_hz)
        self.assertTrue(np.array_equal(portable,bound))

if __name__=='__main__':
    unittest.main(verbosity=2)
