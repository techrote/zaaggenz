from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'app'))

from zaaggenz_runtime import ZaaggenzServer
from zaaggenz_timeline.server import TimelineServer
from zaaggenz_listening.server import ListeningServer
from zaaggenz_inspector.server import InspectorServer
from zaaggenz_vocal.server import VocalServer
import zaaggenz_web_release as web_release
from zaaggenz_web_release import RELEASE_HEADER, RELEASE_QUERY, build_web_releases


class WebReleaseRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.server = ZaaggenzServer(0, 12000)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(3)

    def request(self, path, data=None, *, headers=None):
        body = None if data is None else json.dumps(data).encode()
        request_headers = dict(headers or {})
        if data is not None:
            request_headers.setdefault('Content-Type', 'application/json')
        with urlopen(Request(self.base + path, data=body, headers=request_headers), timeout=30) as response:
            return response.status, dict(response.headers), response.read()

    def json_get(self, path):
        return json.loads(self.request(path)[2])

    def test_every_workspace_has_content_bound_bootstrap_and_no_store_assets(self):
        runtime = self.json_get('/api/runtime/bootstrap')
        self.assertEqual(runtime['api_version'], web_release.WEB_API_VERSION)
        cases = {
            'timeline': ('/timeline', '/timeline/app.mjs', '/timeline/style.css', '/api/timeline/bootstrap'),
            'listening': ('/listen', '/listen/app.mjs', '/listen/style.css', '/api/listening/bootstrap'),
            'inspector': ('/inspector', '/inspector/app.mjs', '/inspector/style.css', '/api/inspector/bootstrap'),
            'vocal': ('/vocal', '/vocal/app.mjs', '/vocal/style.css', '/api/vocal/bootstrap'),
        }
        for workspace, (page_path, app_path, css_path, bootstrap_path) in cases.items():
            with self.subTest(workspace=workspace):
                expected = runtime['web_releases'][workspace]
                self.assertRegex(expected['release_id'], r'^[0-9a-f]{64}$')
                self.assertRegex(expected['frontend_sha256'], r'^[0-9a-f]{64}$')
                self.assertRegex(expected['backend_sha256'], r'^[0-9a-f]{64}$')
                self.assertEqual(self.json_get(bootstrap_path)['web_release'], expected)

                code, headers, html = self.request(page_path)
                self.assertEqual(code, 200)
                self.assertIn('no-store', headers['Cache-Control'])
                self.assertEqual(headers[RELEASE_HEADER], expected['release_id'])
                text = html.decode()
                self.assertIn(f'{RELEASE_QUERY}={expected["release_id"]}', text)
                self.assertIn('zaaggenz-web-release', text)

                exact = f'{app_path}?{RELEASE_QUERY}={expected["release_id"]}'
                code, app_headers, app = self.request(exact)
                self.assertEqual(code, 200)
                self.assertIn('no-store', app_headers['Cache-Control'])
                app_text = app.decode()
                self.assertIn(expected['release_id'], app_text)
                self.assertIn(RELEASE_HEADER, app_text)

                with self.assertRaises(HTTPError) as cm:
                    self.request(f'{app_path}?{RELEASE_QUERY}={"0" * 64}')
                self.assertEqual(cm.exception.code, 409)
                with self.assertRaises(HTTPError) as cm:
                    self.request(f'{css_path}?{RELEASE_QUERY}={"f" * 64}')
                self.assertEqual(cm.exception.code, 409)

        timeline_release = runtime['web_releases']['timeline']['release_id']
        _, _, timeline_app = self.request(f'/timeline/app.mjs?{RELEASE_QUERY}={timeline_release}')
        self.assertIn(f'./editor.mjs?{RELEASE_QUERY}={timeline_release}', timeline_app.decode())
        self.assertIn(f'./jobs_transport.mjs?{RELEASE_QUERY}={timeline_release}', timeline_app.decode())
        vocal_release = runtime['web_releases']['vocal']['release_id']
        _, _, vocal_app = self.request(f'/vocal/app.mjs?{RELEASE_QUERY}={vocal_release}')
        self.assertIn(f'?{RELEASE_QUERY}={vocal_release}', vocal_app.decode())

    def test_browser_mutation_missing_or_wrong_release_fails_before_state_change(self):
        boot = self.json_get('/api/timeline/bootstrap')
        token = boot['token']
        release_id = boot['web_release']['release_id']
        document = deepcopy(boot['document'])
        document['name'] = 'Release-gated mutation'
        before = self.server.session.snapshot()
        browser = {
            'Content-Type': 'application/json',
            'X-Zaaggenz-Token': token,
            'Origin': self.base,
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-Mode': 'cors',
        }
        with self.assertRaises(HTTPError) as cm:
            self.request('/api/timeline/validate', {'document': document}, headers=browser)
        self.assertEqual(cm.exception.code, 409)
        self.assertEqual(self.server.session.snapshot(), before)

        wrong = {**browser, RELEASE_HEADER: '0' * 64}
        with self.assertRaises(HTTPError) as cm:
            self.request('/api/timeline/validate', {'document': document}, headers=wrong)
        self.assertEqual(cm.exception.code, 409)
        self.assertEqual(self.server.session.snapshot(), before)

        exact = {**browser, RELEASE_HEADER: release_id}
        code, _, raw = self.request('/api/timeline/validate', {'document': document}, headers=exact)
        self.assertEqual(code, 200)
        accepted = json.loads(raw)
        self.assertEqual(self.server.session.snapshot()['timeline_revision_id'], accepted['revision_id'])

        # Non-browser API clients remain protocol-compatible and are not falsely
        # treated as cached browser bundles merely because they do not execute JS.
        api_document = deepcopy(document)
        api_document['name'] = 'Programmatic API compatibility'
        code, _, _ = self.request('/api/timeline/validate', {'document': api_document}, headers={
            'Content-Type': 'application/json', 'X-Zaaggenz-Token': token})
        self.assertEqual(code, 200)

    def test_already_loaded_frontend_fails_when_backend_release_changes_until_reload(self):
        boot = self.json_get('/api/timeline/bootstrap')
        old = self.server.web_releases['timeline']
        replacement_id = ('0' if old.release_id[0] != '0' else '1') + old.release_id[1:]
        self.server.web_releases['timeline'] = replace(old, release_id=replacement_id)
        document = deepcopy(boot['document'])
        document['name'] = 'Stale running page must fail'
        stale_headers = {
            'Content-Type': 'application/json',
            'X-Zaaggenz-Token': boot['token'],
            'Origin': self.base,
            'Sec-Fetch-Site': 'same-origin',
            RELEASE_HEADER: old.release_id,
        }
        with self.assertRaises(HTTPError) as cm:
            self.request('/api/timeline/validate', {'document': document}, headers=stale_headers)
        self.assertEqual(cm.exception.code, 409)
        self.assertIn('reload', cm.exception.read().decode().lower())

        reloaded_headers = {**stale_headers, RELEASE_HEADER: replacement_id}
        code, _, _ = self.request('/api/timeline/validate', {'document': document}, headers=reloaded_headers)
        self.assertEqual(code, 200)
        reloaded_page = self.request('/timeline')[2].decode()
        self.assertIn(replacement_id, reloaded_page)
        self.assertNotIn(f'{RELEASE_QUERY}={old.release_id}', reloaded_page)

    def test_release_id_tracks_frontend_and_backend_bytes(self):
        needed = {web_release._HELPER_PATH}
        for paths in web_release._FRONTEND_PATHS.values():
            needed.update(paths)
        for paths in web_release._BACKEND_PATHS.values():
            needed.update(paths)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for rel in needed:
                destination = root / rel
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / rel, destination)
            first = build_web_releases(root)
            with (root / 'web/timeline/style.css').open('ab') as stream:
                stream.write(b'\n/* release-boundary-test */\n')
            frontend_changed = build_web_releases(root)
            self.assertNotEqual(first['timeline'].release_id, frontend_changed['timeline'].release_id)
            self.assertEqual(first['listening'].release_id, frontend_changed['listening'].release_id)

            with (root / 'zaaggenz_timeline/server.py').open('ab') as stream:
                stream.write(b'\n# release-boundary-test\n')
            backend_changed = build_web_releases(root)
            for workspace in ('timeline', 'listening', 'inspector', 'vocal'):
                self.assertNotEqual(frontend_changed[workspace].release_id,
                                    backend_changed[workspace].release_id)


class StandaloneReleasePolicyTests(unittest.TestCase):
    def _check(self, server_type, page, bootstrap, workspace, *args, **kwargs):
        server = server_type(0, *args, **kwargs)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            with urlopen(base + page, timeout=30) as response:
                headers = dict(response.headers)
                body = response.read().decode()
            self.assertIn('no-store', headers['Cache-Control'])
            release_id = headers[RELEASE_HEADER]
            self.assertIn(release_id, body)
            with urlopen(base + bootstrap, timeout=30) as response:
                payload = json.loads(response.read())
            self.assertEqual(payload['web_release']['release_id'], release_id)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(3)

    def test_retained_standalone_servers_share_the_same_policy(self):
        cases = (
            (TimelineServer, '/timeline', '/api/timeline/bootstrap', 'timeline', (12000,), {}),
            (ListeningServer, '/listen', '/api/listening/bootstrap', 'listening', (12000,), {}),
            (InspectorServer, '/inspector', '/api/inspector/bootstrap', 'inspector', (12000,), {'demo_fixture': False}),
            (VocalServer, '/vocal', '/api/vocal/bootstrap', 'vocal', (12000,), {}),
        )
        for server_type, page, bootstrap, workspace, args, kwargs in cases:
            with self.subTest(workspace=workspace):
                self._check(server_type, page, bootstrap, workspace, *args, **kwargs)


if __name__ == '__main__':
    unittest.main(verbosity=2)
