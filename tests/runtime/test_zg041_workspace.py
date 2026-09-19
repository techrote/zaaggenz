from __future__ import annotations
import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request,urlopen
from zaaggenz_runtime import ZaaggenzServer


class ZG041WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.server=ZaaggenzServer(0,12000)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.base=f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join(3)

    def get(self,path,headers=None):
        with urlopen(Request(self.base+path,headers=headers or {}),timeout=30) as r:
            return r.status,dict(r.headers),r.read()

    def get_json(self,path):
        return json.loads(self.get(path)[2])

    def test_compose_is_default_and_research_is_explicit_isolated_route(self):
        before=self.server.session.snapshot()
        boot=self.get_json('/api/runtime/bootstrap')
        self.assertEqual(boot['workspace_policy'],{
            'default':'compose','compose_requires_research':False,
            'research_state':'derived-and-isolated','research_apply':'explicit-only'})
        self.assertEqual(boot['routes']['compose'],'/timeline')
        self.assertEqual(boot['routes']['research'],'/research')
        code,headers,body=self.get('/research')
        text=body.decode('utf-8')
        self.assertEqual(code,200)
        self.assertIn('ZAAGGENZ / RESEARCH',text)
        self.assertIn('Research never applies a transform implicitly',text)
        self.assertIn(before['timeline_revision_id'],text)
        self.assertIn('id="research-inspector" href="/inspector"',text)
        self.assertIn('id="research-listening" href="/listen"',text)
        self.assertIn('id="research-vocal" href="/vocal"',text)
        self.assertIn("script-src 'none'",headers['Content-Security-Policy'])
        self.assertEqual(self.server.session.snapshot(),before)

    def test_research_gets_cannot_widen_trusted_capability_or_mutate_compose(self):
        before=self.server.session.snapshot()
        for path in ('/research','/api/inspector/bootstrap','/api/listening/bootstrap','/api/vocal/bootstrap'):
            code,_,body=self.get(path);self.assertEqual(code,200)
            self.assertNotIn(self.server.trusted_token.encode(),body)
        self.assertEqual(self.server.session.snapshot(),before)
        root=self.get('/')[2].decode('utf-8')
        self.assertIn('href="/research"',root)

    def test_research_route_keeps_loopback_origin_boundary(self):
        with self.assertRaises(HTTPError) as cm:
            self.get('/research',{'Origin':'https://foreign.invalid'})
        self.assertEqual(cm.exception.code,403)


if __name__=='__main__':unittest.main(verbosity=2)
