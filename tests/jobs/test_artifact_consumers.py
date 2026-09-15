from __future__ import annotations

import hashlib
import unittest

from zaaggenz_jobs import RenderArtifact, RenderCoordinator, RequestTicket

R='a'*64;Q='b'*64;K='c'*64


def artifact():
    payload=b'1234'
    asset=dict(kind='AudioAssetRef',version='1.0.0',content_sha256=hashlib.sha256(payload).hexdigest(),
               identity_domain='pcm-f32le-interleaved-v1',sample_rate_hz=48000,channels=1,
               channel_layout='mono',frame_count=1,level_domain='source',sample_policy='unclamped_float')
    return RenderArtifact(R,Q,'preview',K,payload,asset,
                          {'waveform':[0,1],'region':{'start_frame':0,'end_frame':1}})


class ArtifactConsumerSnapshotTests(unittest.TestCase):
    def test_preview_serialization_observes_original_validated_identity_after_mutation_attempt(self):
        a=artifact();expected=a.metadata()
        exposed_asset=a.asset;exposed_scopes=a.scopes
        exposed_asset['content_sha256']='0'*64;exposed_asset['frame_count']=999
        exposed_scopes['waveform'].append(99);exposed_scopes['region']['end_frame']=999
        ticket=RequestTicket('preview',1,R,None,'dedupe',True,Q,K,'preview')
        result=RenderCoordinator(None)._accepted(ticket,a)
        self.assertTrue(result['accepted'])
        self.assertEqual(result['artifact'],expected)
        self.assertEqual(result['audio'],b'1234')


if __name__=='__main__':unittest.main(verbosity=2)
