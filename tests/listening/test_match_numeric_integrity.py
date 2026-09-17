from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import sys
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'app'))

from zaaggenz_listening import ListeningAudioStore, ListeningError, Stimulus
from zaaggenz_listening.server import ListeningServer


def _stimulus(sid: str, raw: bytes, *, sample_rate: int = 48000) -> Stimulus:
    frames = len(raw) // 4
    raw_sha = hashlib.sha256(raw).hexdigest()
    return Stimulus({
        'format': 'zaaggenz-listening-stimulus',
        'version': '1.0.0',
        'id': sid,
        'name': 'numeric-integrity-fixture',
        'revision_id': 'a' * 64,
        'recipe_sha256': 'b' * 64,
        'product': 'synth',
        'cache_key': 'c' * 64,
        'source_asset': {
            'content_sha256': 'd' * 64,
            'identity_domain': 'pcm-f32le-interleaved-v1',
            'sample_rate_hz': sample_rate,
            'channels': 1,
            'frame_count': frames,
        },
        'excerpt': {'start_frame': 0, 'end_frame': frames},
        'raw_pcm_sha256': raw_sha,
        'sample_rate_hz': sample_rate,
        'channels': 1,
        'frame_count': frames,
        'alignment': {},
    })


def _raw(values) -> bytes:
    return np.asarray(values, dtype='<f4').tobytes()


def _store(rows, *, max_bytes=256 * 1024 * 1024):
    store = ListeningAudioStore(max_bytes=max_bytes)
    for sid, raw in rows:
        store._stimuli[sid] = _stimulus(sid, raw)
        store._raw[sid] = raw
    return store


class MatchNumericIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.a = '1' * 64
        self.b = '2' * 64
        self.raw_a = _raw([0.25, -0.5, 0.375, -0.125, 0.2, -0.4, 0.3, -0.1])
        self.raw_b = _raw([0.4, -0.1, 0.2, -0.35, 0.1, -0.3, 0.45, -0.2])
        self.store = _store([(self.a, self.raw_a), (self.b, self.raw_b)])

    def test_nan_and_infinities_are_rejected_before_playback_mutation(self):
        before = dict(self.store._playback)
        for value in (float('nan'), float('inf'), float('-inf')):
            with self.subTest(target=value):
                with self.assertRaisesRegex(ListeningError, 'RMS target must be a finite numeric dBFS value'):
                    self.store.match([self.a, self.b], target_rms_dbfs=value)
                self.assertEqual(self.store._playback, before)
            with self.subTest(peak=value):
                with self.assertRaisesRegex(ListeningError, 'peak ceiling must be a finite numeric dBFS value'):
                    self.store.match([self.a, self.b], peak_ceiling_dbfs=value)
                self.assertEqual(self.store._playback, before)

    def test_non_numeric_and_boolean_controls_do_not_gain_coercion_semantics(self):
        for value in ('-6', True, False):
            with self.subTest(target=value):
                with self.assertRaises(ListeningError):
                    self.store.match([self.a, self.b], target_rms_dbfs=value)
            with self.subTest(peak=value):
                with self.assertRaises(ListeningError):
                    self.store.match([self.a, self.b], peak_ceiling_dbfs=value)
        self.assertEqual(self.store._playback, {})

    def test_peak_ceiling_boundaries_and_finite_explicit_target_remain_valid(self):
        low = self.store.match([self.a, self.b], target_rms_dbfs=-60.0, peak_ceiling_dbfs=-24.0)
        high = self.store.match([self.a, self.b], target_rms_dbfs=-60.0, peak_ceiling_dbfs=-0.1)
        for rows in (low, high):
            self.assertEqual(len(rows), 2)
            json.dumps(rows, allow_nan=False)
            for row in rows:
                for key, value in row.items():
                    if type(value) in (int, float):
                        self.assertTrue(math.isfinite(float(value)), (key, value))
                pcm = np.frombuffer(self.store.playback_pcm(row['playback_sha256']), dtype='<f4')
                self.assertTrue(np.all(np.isfinite(pcm)))
        with self.assertRaisesRegex(ListeningError, 'peak ceiling must be -24..-0.1 dBFS'):
            self.store.match([self.a, self.b], peak_ceiling_dbfs=-24.000001)
        with self.assertRaisesRegex(ListeningError, 'peak ceiling must be -24..-0.1 dBFS'):
            self.store.match([self.a, self.b], peak_ceiling_dbfs=-0.099999)

    def test_nonfinite_source_pcm_cannot_create_playback_or_metadata(self):
        bad = '3' * 64
        raw_bad = _raw([0.25, float('nan'), -0.25, 0.5])
        store = _store([(self.a, self.raw_a), (bad, raw_bad)])
        with self.assertRaisesRegex(ListeningError, 'stimulus PCM must be finite'):
            store.match([self.a, bad], target_rms_dbfs=-60.0)
        self.assertEqual(store._playback, {})

    def test_budget_failure_preserves_preexisting_deduplicated_playback(self):
        c = '3' * 64
        d = '4' * 64
        raw_d = _raw([0.5, 0.25, -0.1, -0.4, 0.15, -0.45, 0.35, -0.05])
        store = _store([(self.a, self.raw_a), (self.b, self.raw_a), (c, self.raw_a), (d, raw_d)])
        existing = store.match([self.a, self.b], target_rms_dbfs=-60.0)
        self.assertEqual(existing[0]['playback_sha256'], existing[1]['playback_sha256'])
        shared_sha = existing[0]['playback_sha256']
        self.assertEqual(len(store._playback), 1)
        store.max_bytes = sum(len(v) for v in store._raw.values()) + sum(len(v[0]) for v in store._playback.values())
        before = dict(store._playback)
        with self.assertRaisesRegex(ListeningError, 'matched playback store budget exceeded'):
            store.match([c, d], target_rms_dbfs=-60.0)
        self.assertEqual(store._playback, before)
        self.assertTrue(store.has_playback(shared_sha))
        self.assertEqual(store.playback_pcm(shared_sha), before[shared_sha][0])

    def test_extreme_finite_target_that_cannot_convert_fails_without_mutation(self):
        for target in (1e308, -1e308):
            with self.subTest(target=target):
                with self.assertRaisesRegex(ListeningError, 'finite positive linear amplitude'):
                    self.store.match([self.a, self.b], target_rms_dbfs=target)
                self.assertEqual(self.store._playback, {})


class MatchHTTPNumericIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ListeningServer(0, 12000)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(2)

    def _raw_post(self, body: bytes):
        request = Request(
            self.url + '/api/listening/match',
            data=body,
            headers={
                'Content-Type': 'application/json',
                'X-Zaaggenz-Token': self.server.token,
            },
        )
        return urlopen(request, timeout=10)

    def test_nonstandard_json_nan_and_infinity_tokens_are_rejected_at_api_boundary(self):
        for token in (b'NaN', b'Infinity', b'-Infinity'):
            with self.subTest(token=token):
                body = b'{"stimulus_ids":[],"target_rms_dbfs":' + token + b',"peak_ceiling_dbfs":-3.0}'
                with self.assertRaises(HTTPError) as cm:
                    self._raw_post(body)
                self.assertEqual(cm.exception.code, 400)
                error = json.loads(cm.exception.read())['error']
                self.assertIn('nonfinite JSON token', error)
                self.assertEqual(self.server.listening.audio._playback, {})


if __name__ == '__main__':
    unittest.main()
