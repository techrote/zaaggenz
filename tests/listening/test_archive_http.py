from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import numpy as np

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'app'))
from zaaggenz_contracts.examples import examples
from zaaggenz_jobs import RenderArtifact
from zaaggenz_listening.archive import ARCHIVE_MIME, decode_archive
from zaaggenz_listening.server import ListeningServer


def _sha(label):return hashlib.sha256(label.encode()).hexdigest()
def _artifact(label,phase=0):
    frames=128;channels=1
    x=np.where((np.arange(frames)+phase)%2,np.float32(-.1),np.float32(.1)).astype('<f4')[:,None]
    pcm=x.tobytes();asset=examples()['AudioAssetRef'];asset.update(content_sha256=hashlib.sha256(pcm).hexdigest(),identity_domain='pcm-f32le-interleaved-v1',sample_rate_hz=12000,channels=1,channel_layout='mono',frame_count=frames,level_domain='source',sample_policy='unclamped_float')
    return RenderArtifact(_sha(label+'r'),_sha(label+'q'),'synth',_sha(label+'c'),pcm,asset,{'region':None,'offset_sample':0})


class ArchiveHTTPTests(unittest.TestCase):
    def setUp(self):
        self.server=ListeningServer(0,12000);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.url=f'http://127.0.0.1:{self.server.server_port}'
        ids=[]
        for label,phase in (('a',0),('b',1)):
            ids.append(self.server.listening.audio.add_artifact(label,_artifact(label,phase=phase)).to_dict()['id'])
        matched=self.server.listening.match(ids)
        self.public=self.server.listening.create_participant_trial('archive','abx',matched,'7',['liking'],None)
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join(2)
    def request(self,path,data=None,*,participant=True,trusted=False,content_type='application/json'):
        headers={'Content-Type':content_type}
        if participant:headers['X-Zaaggenz-Token']=self.server.token
        if trusted:headers['X-Zaaggenz-Trusted-Token']=self.server.trusted_token
        body=data
        if content_type=='application/json' and data is not None:body=json.dumps(data).encode()
        with urlopen(Request(self.url+path,data=body,headers=headers),timeout=20) as r:return r.status,r.headers,r.read()
    def test_participant_archive_is_blind_and_trusted_archive_requires_trusted_capability(self):
        _,headers,safe=self.request('/api/listening/archive',{'trial_id':self.public['id']})
        self.assertEqual(headers.get_content_type(),ARCHIVE_MIME)
        manifest=decode_archive(safe)['manifest'];self.assertEqual(manifest['role'],'participant');self.assertIsNone(manifest['bundle']['trial']['abx_truth']);self.assertNotIn('seed',manifest['bundle']['trial'])
        with self.assertRaises(HTTPError) as cm:self.request('/api/listening/trusted-archive',{'trial_id':self.public['id']})
        self.assertEqual(cm.exception.code,403)
        _,headers,trusted=self.request('/api/listening/trusted-archive',{'trial_id':self.public['id']},participant=False,trusted=True)
        self.assertEqual(headers.get_content_type(),ARCHIVE_MIME);self.assertEqual(decode_archive(trusted)['manifest']['role'],'trusted')
    def test_binary_reopen_route_rejects_participant_capability_and_reopens_exact_archive(self):
        _,_,archive=self.request('/api/listening/trusted-archive',{'trial_id':self.public['id']},participant=False,trusted=True)
        fresh=ListeningServer(0,12000);thread=threading.Thread(target=fresh.serve_forever,daemon=True);thread.start();url=f'http://127.0.0.1:{fresh.server_port}'
        try:
            req=Request(url+'/api/listening/reopen-archive',data=archive,headers={'Content-Type':ARCHIVE_MIME,'X-Zaaggenz-Token':fresh.token})
            with self.assertRaises(HTTPError) as cm:urlopen(req,timeout=20)
            self.assertEqual(cm.exception.code,403)
            req=Request(url+'/api/listening/reopen-archive',data=archive,headers={'Content-Type':ARCHIVE_MIME,'X-Zaaggenz-Trusted-Token':fresh.trusted_token})
            with urlopen(req,timeout=20) as response:payload=json.loads(response.read())
            self.assertEqual(payload['trial']['format'],'zaaggenz-listening-participant-trial');self.assertEqual(fresh.listening.registry_accounting()['trial_count'],1)
        finally:
            fresh.shutdown();fresh.server_close();thread.join(2)

if __name__=='__main__':unittest.main()
