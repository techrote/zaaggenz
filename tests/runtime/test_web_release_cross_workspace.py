from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'app'))

from zaaggenz_runtime import ZaaggenzServer
from zaaggenz_web_release import RELEASE_HEADER


class CrossWorkspaceReleaseTests(unittest.TestCase):
    def setUp(self):
        self.server = ZaaggenzServer(0, 12000)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(3)

    def get_json(self, path):
        with urlopen(self.base + path, timeout=30) as response:
            return json.loads(response.read())

    def post(self, path, payload, headers):
        body = json.dumps(payload).encode()
        with urlopen(Request(self.base + path, data=body, headers={
                'Content-Type': 'application/json', **headers}), timeout=30) as response:
            return response.status, json.loads(response.read())

    def test_current_listening_release_can_render_exact_timeline_source(self):
        runtime = self.get_json('/api/runtime/bootstrap')
        boot = self.get_json('/api/timeline/bootstrap')
        document = deepcopy(boot['document'])
        document['name'] = 'Listening exact-source render'
        browser = {
            'X-Zaaggenz-Token': boot['token'],
            'Origin': self.base,
            'Sec-Fetch-Site': 'same-origin',
            RELEASE_HEADER: runtime['web_releases']['listening']['release_id'],
        }
        status, result = self.post('/api/timeline/render', {
            'document': document, 'region': None, 'name': 'listening source'}, browser)
        self.assertEqual(status, 202)
        self.assertRegex(result['job_id'], r'^[0-9a-f]{32}$')

    def test_unapproved_current_workspace_release_cannot_mutate_timeline(self):
        runtime = self.get_json('/api/runtime/bootstrap')
        boot = self.get_json('/api/timeline/bootstrap')
        document = deepcopy(boot['document'])
        document['name'] = 'Must not be accepted from Vocal release'
        before = self.server.session.snapshot()
        browser = {
            'X-Zaaggenz-Token': boot['token'],
            'Origin': self.base,
            'Sec-Fetch-Site': 'same-origin',
            RELEASE_HEADER: runtime['web_releases']['vocal']['release_id'],
        }
        with self.assertRaises(HTTPError) as cm:
            self.post('/api/timeline/validate', {'document': document}, browser)
        self.assertEqual(cm.exception.code, 409)
        self.assertEqual(self.server.session.snapshot(), before)


if __name__ == '__main__':
    unittest.main(verbosity=2)
