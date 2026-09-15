from __future__ import annotations

import hashlib
import struct
import unittest

from zaaggenz_jobs import RenderArtifact
from zaaggenz_listening.stimulus import freeze_artifact

R='a'*64;Q='b'*64;K='c'*64


class ListeningArtifactSnapshotTests(unittest.TestCase):
    def test_freeze_artifact_uses_original_validated_metadata_after_public_mutation_attempts(self):
        payload=struct.pack('<2f',0.25,-0.5)
        content_sha=hashlib.sha256(payload).hexdigest()
        asset=dict(kind='AudioAssetRef',version='1.0.0',content_sha256=content_sha,
                   identity_domain='pcm-f32le-interleaved-v1',sample_rate_hz=48000,channels=1,
                   channel_layout='mono',frame_count=2,level_domain='source',sample_policy='unclamped_float')
        scopes={'region':{'start_frame':0,'end_frame':2},'offset_sample':7,'nested':{'points':[1,2]}}
        artifact=RenderArtifact(R,Q,'synth',K,payload,asset,scopes)

        leaked_asset=artifact.asset;leaked_asset['content_sha256']='0'*64;leaked_asset['frame_count']=999
        leaked_scopes=artifact.scopes;leaked_scopes['region']['end_frame']=999;leaked_scopes['offset_sample']=999

        stimulus,raw=freeze_artifact('stable',artifact)
        frozen=stimulus.to_dict()
        self.assertEqual(raw,payload)
        self.assertEqual(frozen['raw_pcm_sha256'],content_sha)
        self.assertEqual(frozen['source_asset']['content_sha256'],content_sha)
        self.assertEqual(frozen['source_asset']['frame_count'],2)
        self.assertEqual(frozen['alignment']['artifact_region'],{'end_frame':2,'start_frame':0})
        self.assertEqual(frozen['alignment']['artifact_offset_sample'],7)


if __name__=='__main__':unittest.main(verbosity=2)
