from __future__ import annotations

import base64
from copy import deepcopy
import hashlib
import json
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import numpy as np

from zaaggenz_jobs import RenderArtifact
from zaaggenz_listening import ListeningError
from zaaggenz_listening.server import ListeningServer
from zaaggenz_listening.service import (
    ListeningService,
    MAX_ARCHIVE_BLOBS,
    MAX_ARCHIVE_PCM_BYTES,
    TRUSTED_BUNDLE_VERSION,
    _bundle_sha256,
)


def _artifact(label: str, values, *, sample_rate: int = 48000, channels: int = 1) -> RenderArtifact:
    samples = np.asarray(values, dtype='<f4').reshape(-1)
    if samples.size % channels:
        raise AssertionError('test fixture samples must divide evenly into channels')
    pcm = samples.tobytes()
    content_sha = hashlib.sha256(pcm).hexdigest()
    identity = hashlib.sha256(label.encode('utf-8')).hexdigest()
    recipe = hashlib.sha256((label + ':recipe').encode('utf-8')).hexdigest()
    cache = hashlib.sha256((label + ':cache').encode('utf-8')).hexdigest()
    frames = samples.size // channels
    asset = {
        'kind': 'AudioAssetRef',
        'version': '1.0.0',
        'content_sha256': content_sha,
        'identity_domain': 'pcm-f32le-interleaved-v1',
        'sample_rate_hz': sample_rate,
        'channels': channels,
        'channel_layout': 'mono' if channels == 1 else 'stereo',
        'frame_count': frames,
        'level_domain': 'source',
        'sample_policy': 'unclamped_float',
    }
    return RenderArtifact(identity, recipe, 'synth', cache, pcm, asset, {})


A = [0.25, -0.5, 0.375, -0.125, 0.2, -0.4, 0.3, -0.1]
B = [0.4, -0.1, 0.2, -0.35, 0.1, -0.3, 0.45, -0.2]
STEREO = [0.25, -0.2, -0.5, 0.4, 0.375, -0.3, -0.125, 0.1, 0.2, -0.16, -0.4, 0.32, 0.3, -0.24, -0.1, 0.08]


class DurableArchiveTests(unittest.TestCase):
    def _service(self, *, same_pcm=False, stereo_second=False):
        service = ListeningService(object())
        a = service.audio.add_artifact('A', _artifact('archive-a', A)).to_dict()['id']
        b_values = A if same_pcm else (STEREO if stereo_second else B)
        b_channels = 2 if stereo_second else 1
        b = service.audio.add_artifact('B', _artifact('archive-b', b_values, channels=b_channels)).to_dict()['id']
        matched = service.match([a, b], target_rms_dbfs=-60.0)
        public = service.create_trial('durable archive', 'ab', matched, seed='98', endpoints=('liking',))
        return service, public, matched

    @staticmethod
    def _completed_payload(public, *, liking=61):
        return {
            'status': 'completed',
            'choice': public['presentation_order'][0],
            'ratings': {'liking': liking},
            'confidence': 70,
            'effort': 20,
            'comfortable_level': 55,
            'replay_counts': {sid: 1 for sid in public['presentation_order']},
            'x_replay_count': 0,
            'annotations': [],
            'note': '',
        }

    def test_fresh_service_reopens_exact_pcm_without_render_or_rematch(self):
        source, public, matched = self._service()
        source.submit(public['id'], self._completed_payload(public))
        archive = source.export_bundle(public['id'])
        self.assertEqual(archive['version'], TRUSTED_BUNDLE_VERSION)
        expected_raw = {s['id']: source.audio.raw_pcm(s['id']) for s in archive['stimuli']}
        expected_playback = {row['playback_sha256']: source.audio.playback_pcm(row['playback_sha256']) for row in matched}

        fresh = ListeningService(object())
        with patch.object(fresh.audio, 'match', side_effect=AssertionError('reopen must not rematch')):
            reopened = fresh.reopen_bundle(archive)
        self.assertEqual(reopened['results'][0]['ratings']['liking'], 61)
        self.assertEqual(reopened['bundle_sha256'], archive['bundle_sha256'])
        for sid, pcm in expected_raw.items():
            self.assertEqual(fresh.audio.raw_pcm(sid), pcm)
            self.assertEqual(hashlib.sha256(pcm).hexdigest(), next(s['raw_pcm_sha256'] for s in archive['stimuli'] if s['id'] == sid))
        for psha, pcm in expected_playback.items():
            self.assertEqual(fresh.audio.playback_pcm(psha), pcm)
            self.assertEqual(hashlib.sha256(pcm).hexdigest(), psha)

    def test_corrupt_or_missing_pcm_fails_before_publication(self):
        source, public, _ = self._service()
        archive = source.export_bundle(public['id'])
        playback = next(b for b in archive['audio']['blobs'] if b['kind'] == 'matched-playback')

        corrupt = deepcopy(archive)
        target = next(b for b in corrupt['audio']['blobs'] if b['kind'] == 'matched-playback' and b['sha256'] == playback['sha256'])
        pcm = bytearray(base64.b64decode(target['data_base64']))
        pcm[0] ^= 1
        target['data_base64'] = base64.b64encode(bytes(pcm)).decode('ascii')
        fresh = ListeningService(object())
        with self.assertRaisesRegex(ListeningError, 'content hash mismatch'):
            fresh.reopen_bundle(corrupt)
        self.assertEqual(fresh.audio.accounting()['total_pcm_bytes'], 0)
        self.assertEqual(fresh.trials, {})

        missing = deepcopy(archive)
        missing['audio']['blobs'] = [b for b in missing['audio']['blobs'] if not (b['kind'] == 'matched-playback' and b['sha256'] == playback['sha256'])]
        missing['audio']['blob_count'] = len(missing['audio']['blobs'])
        missing['audio']['pcm_bytes'] = sum(b['byte_length'] for b in missing['audio']['blobs'])
        missing['bundle_sha256'] = _bundle_sha256(missing)
        with self.assertRaisesRegex(ListeningError, 'missing matched playback PCM'):
            fresh.reopen_bundle(missing)
        self.assertEqual(fresh.audio.accounting()['total_pcm_bytes'], 0)
        self.assertEqual(fresh.trials, {})

    def test_duplicate_raw_and_playback_content_is_archived_once_but_restored_logically(self):
        source, public, matched = self._service(same_pcm=True)
        archive = source.export_bundle(public['id'])
        raw_blobs = [b for b in archive['audio']['blobs'] if b['kind'] == 'raw-excerpt']
        playback_blobs = [b for b in archive['audio']['blobs'] if b['kind'] == 'matched-playback']
        self.assertEqual(len(raw_blobs), 1)
        self.assertEqual(len(raw_blobs[0]['stimulus_ids']), 2)
        self.assertEqual(len(playback_blobs), 1)
        self.assertEqual(len(playback_blobs[0]['stimulus_ids']), 2)
        self.assertEqual(matched[0]['playback_sha256'], matched[1]['playback_sha256'])

        fresh = ListeningService(object())
        fresh.reopen_bundle(archive)
        accounting = fresh.audio.accounting()
        self.assertEqual(accounting['raw_entries'], 2)
        self.assertEqual(accounting['playback_entries'], 1)

    def test_mono_and_stereo_shapes_and_hashes_roundtrip(self):
        source, public, _ = self._service(stereo_second=True)
        archive = source.export_bundle(public['id'])
        channels = sorted(s['channels'] for s in archive['stimuli'])
        self.assertEqual(channels, [1, 2])
        fresh = ListeningService(object())
        fresh.reopen_bundle(archive)
        for stimulus in archive['stimuli']:
            sid = stimulus['id']
            self.assertEqual(len(fresh.audio.raw_pcm(sid)), stimulus['frame_count'] * stimulus['channels'] * 4)
            self.assertEqual(hashlib.sha256(fresh.audio.raw_pcm(sid)).hexdigest(), stimulus['raw_pcm_sha256'])
        for row in archive['manifest']['matched_stimuli']:
            stimulus = next(s for s in archive['stimuli'] if s['id'] == row['stimulus_id'])
            pcm = fresh.audio.playback_pcm(row['playback_sha256'])
            self.assertEqual(len(pcm), stimulus['frame_count'] * stimulus['channels'] * 4)

    def test_completed_aborted_and_missing_results_roundtrip_under_corrected_semantics(self):
        source, public, _ = self._service()
        source.submit(public['id'], self._completed_payload(public, liking=44))
        counts = {sid: 0 for sid in public['presentation_order']}
        first = public['presentation_order'][0]
        counts[first] = 2
        source.submit(public['id'], {
            'status': 'aborted', 'choice': None, 'ratings': {}, 'confidence': None, 'effort': 83,
            'comfortable_level': None, 'replay_counts': counts, 'x_replay_count': 0,
            'annotations': [{'stimulus_id': first, 'time_seconds': 0.0, 'label': 'start', 'note': 'partial'}], 'note': 'stopped',
        })
        source.submit(public['id'], {
            'status': 'missing', 'choice': None, 'ratings': {}, 'confidence': None, 'effort': None,
            'comfortable_level': None, 'replay_counts': {sid: 0 for sid in public['presentation_order']},
            'x_replay_count': 0, 'annotations': [], 'note': '',
        })
        archive = source.export_bundle(public['id'])
        fresh = ListeningService(object())
        reopened = fresh.reopen_bundle(archive)
        self.assertEqual([r['status'] for r in reopened['results']], ['completed', 'aborted', 'missing'])
        self.assertEqual(reopened['results'][1]['annotations'][0]['label'], 'start')

    def test_bounds_and_pathless_schema_fail_before_decode_or_mutation(self):
        source, public, _ = self._service()
        archive = source.export_bundle(public['id'])

        too_many = deepcopy(archive)
        too_many['audio']['blobs'] = [deepcopy(archive['audio']['blobs'][0]) for _ in range(MAX_ARCHIVE_BLOBS + 1)]
        too_many['audio']['blob_count'] = len(too_many['audio']['blobs'])
        fresh = ListeningService(object())
        with self.assertRaisesRegex(ListeningError, 'blob count'):
            fresh.reopen_bundle(too_many)
        self.assertEqual(fresh.audio.accounting()['total_pcm_bytes'], 0)

        too_large = deepcopy(archive)
        too_large['audio']['pcm_bytes'] = MAX_ARCHIVE_PCM_BYTES + 1
        with self.assertRaisesRegex(ListeningError, 'PCM exceeds'):
            fresh.reopen_bundle(too_large)

        hostile = deepcopy(archive)
        hostile['audio']['blobs'][0]['path'] = '../../private-reference.wav'
        with self.assertRaisesRegex(ListeningError, 'unknown fields'):
            fresh.reopen_bundle(hostile)
        self.assertEqual(fresh.trials, {})

    def test_export_bound_failure_does_not_mutate_retained_evidence(self):
        source, public, _ = self._service()
        before_accounting = source.audio.accounting()
        before_manifest = source.manifest(public['id']).to_dict()
        with patch('zaaggenz_listening.service.MAX_ARCHIVE_PCM_BYTES', 1):
            with self.assertRaisesRegex(ListeningError, 'PCM exceeds export bound'):
                source.export_bundle(public['id'])
        self.assertEqual(source.audio.accounting(), before_accounting)
        self.assertEqual(source.manifest(public['id']).to_dict(), before_manifest)

    def test_legacy_metadata_only_and_participant_bundles_fail_closed(self):
        source, public, _ = self._service()
        archive = source.export_bundle(public['id'])
        legacy = {
            'format': 'zaaggenz-listening-bundle', 'version': '1.0.0',
            'stimuli': deepcopy(archive['stimuli']), 'manifest': deepcopy(archive['manifest']), 'results': deepcopy(archive['results']),
        }
        fresh = ListeningService(object())
        with self.assertRaisesRegex(ListeningError, 'metadata-only'):
            fresh.reopen_bundle(legacy)

        participant = source.export_participant_bundle(public['id'])
        self.assertEqual(participant['version'], '1.0.0')
        self.assertNotIn('audio', participant)
        self.assertNotIn('seed', participant['trial'])
        self.assertIsNone(participant['trial']['abx_truth'])
        with self.assertRaisesRegex(ListeningError, 'participant bundle'):
            fresh.reopen_bundle(participant)

    def test_tampered_stimulus_provenance_cannot_keep_old_identity(self):
        source, public, _ = self._service()
        archive = source.export_bundle(public['id'])
        tampered = deepcopy(archive)
        tampered['stimuli'][0]['raw_pcm_sha256'] = '0' * 64
        tampered['bundle_sha256'] = _bundle_sha256(tampered)
        fresh = ListeningService(object())
        with self.assertRaisesRegex(ListeningError, 'stimulus identity'):
            fresh.reopen_bundle(tampered)
        self.assertEqual(fresh.audio.accounting()['total_pcm_bytes'], 0)


class DurableArchiveHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ListeningServer(0, 12000)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(2)

    def _post(self, path, payload, *, trusted=True):
        headers = {'Content-Type': 'application/json'}
        if trusted:
            headers['X-Zaaggenz-Trusted-Token'] = self.server.trusted_token
        else:
            headers['X-Zaaggenz-Token'] = self.server.token
        body = json.dumps(payload, separators=(',', ':')).encode('utf-8')
        with urlopen(Request(self.url + path, data=body, headers=headers), timeout=20) as response:
            return json.loads(response.read())

    def test_trusted_http_export_reopens_after_service_state_is_destroyed(self):
        listening = self.server.listening
        a = listening.audio.add_artifact('A', _artifact('http-a', A, sample_rate=12000)).to_dict()['id']
        b = listening.audio.add_artifact('B', _artifact('http-b', B, sample_rate=12000)).to_dict()['id']
        matched = listening.match([a, b], target_rms_dbfs=-60.0)
        public = listening.create_trial('HTTP durable', 'ab', matched, seed='98', endpoints=('liking',))
        archive = self._post('/api/listening/trusted-export', {'trial_id': public['id']})
        self.assertEqual(archive['version'], TRUSTED_BUNDLE_VERSION)
        expected = {row['playback_sha256']: listening.audio.playback_pcm(row['playback_sha256']) for row in matched}

        self.server.listening = ListeningService(self.server.timeline)
        reopened = self._post('/api/listening/reopen', {'bundle': archive})
        self.assertEqual(reopened['bundle_sha256'], archive['bundle_sha256'])
        for psha, pcm in expected.items():
            self.assertEqual(self.server.listening.audio.playback_pcm(psha), pcm)

        with self.assertRaises(HTTPError) as cm:
            self._post('/api/listening/reopen', {'bundle': archive}, trusted=False)
        self.assertEqual(cm.exception.code, 403)


if __name__ == '__main__':
    unittest.main(verbosity=2)
