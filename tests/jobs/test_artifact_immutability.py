from __future__ import annotations

import hashlib
import json
import unittest

from zaaggenz_jobs import RenderArtifact

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


if __name__=='__main__':unittest.main(verbosity=2)
