from __future__ import annotations

import hashlib
import json
import math
import unittest

from zaaggenz_jobs import JobError, RenderArtifact

R='a'*64;Q='b'*64;K='c'*64


def make_asset(payload:bytes):
    return dict(kind='AudioAssetRef',version='1.0.0',content_sha256=hashlib.sha256(payload).hexdigest(),
                identity_domain='pcm-f32le-interleaved-v1',sample_rate_hz=48000,channels=1,
                channel_layout='mono',frame_count=len(payload)//4,level_domain='source',sample_policy='unclamped_float')


def make_artifact():
    payload=b'1234';asset=make_asset(payload)
    scopes={'waveform':[0,1], 'nested':{'points':[1,2,3]}, 'region':{'start':0,'end':1}}
    return RenderArtifact(R,Q,'preview',K,payload,asset,scopes),asset,scopes


class RenderArtifactImmutabilityTests(unittest.TestCase):
    def test_constructor_owns_metadata_snapshot(self):
        artifact,asset,scopes=make_artifact();expected=artifact.metadata()
        asset['content_sha256']='0'*64
        scopes['waveform'][0]=99
        scopes['nested']['points'].append(4)
        self.assertEqual(artifact.metadata(),expected)

    def test_asset_accessor_is_defensive(self):
        artifact,_,_=make_artifact();expected=artifact.asset
        exposed=artifact.asset;exposed['content_sha256']='0'*64;exposed['frame_count']=999
        self.assertEqual(artifact.asset,expected)

    def test_nested_scopes_accessor_is_defensive(self):
        artifact,_,_=make_artifact();expected=artifact.scopes
        exposed=artifact.scopes
        exposed['waveform'][0]=99
        exposed['nested']['points'][1]=88
        exposed['region']['end']=999
        self.assertEqual(artifact.scopes,expected)

    def test_metadata_result_is_defensive_and_json_serializable(self):
        artifact,_,_=make_artifact();expected=artifact.metadata()
        exposed=artifact.metadata()
        exposed['asset']['content_sha256']='0'*64
        exposed['scopes']['nested']['points'].clear()
        exposed['revision_id']='f'*64
        self.assertEqual(artifact.metadata(),expected)
        self.assertEqual(json.loads(json.dumps(artifact.metadata())),expected)

    def test_cache_accounting_is_stable_after_public_mutation_attempts(self):
        artifact,_,_=make_artifact();before=artifact.cache_bytes
        artifact.asset['frame_count']=999
        artifact.scopes['waveform'].append(9)
        artifact.metadata()['product']='research'
        self.assertEqual(artifact.cache_bytes,before)

    def test_logically_identical_metadata_order_has_deterministic_equality_and_accounting(self):
        payload=b'1234';asset=make_asset(payload);scopes={'z':[3,2,1],'a':{'y':2,'x':1}}
        a=RenderArtifact(R,Q,'preview',K,payload,asset,scopes)
        b=RenderArtifact(R,Q,'preview',K,payload,dict(reversed(list(asset.items()))),
                         {'a':{'x':1,'y':2},'z':[3,2,1]})
        self.assertEqual(a,b)
        self.assertEqual(a.cache_bytes,b.cache_bytes)
        self.assertEqual(a.metadata(),b.metadata())

    def test_audio_bytes_are_retained_without_copy_and_metadata_cannot_invalidate_shape_or_hash(self):
        payload=b'1234';artifact=RenderArtifact(R,Q,'preview',K,payload,make_asset(payload),{})
        self.assertIs(artifact.audio_bytes,payload)
        artifact.asset['frame_count']=999
        artifact.asset['content_sha256']='0'*64
        self.assertEqual(artifact.asset['frame_count'],1)
        self.assertEqual(artifact.asset['content_sha256'],hashlib.sha256(payload).hexdigest())
        self.assertEqual(artifact.audio_bytes,payload)

    def test_scope_json_guards_still_reject_nonfinite_and_oversized_metadata(self):
        payload=b'1234';asset=make_asset(payload)
        with self.assertRaises(JobError):RenderArtifact(R,Q,'preview',K,payload,asset,{'x':math.nan})
        with self.assertRaises(JobError):RenderArtifact(R,Q,'preview',K,payload,asset,{'x':'a'*2_000_001})


if __name__=='__main__':unittest.main(verbosity=2)
