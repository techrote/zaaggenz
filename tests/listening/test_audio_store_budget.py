from __future__ import annotations

import hashlib
import threading
import unittest

import numpy as np

from zaaggenz_jobs import RenderArtifact
from zaaggenz_listening import ListeningAudioStore, ListeningError


def _artifact(label: str, values, *, sample_rate: int = 48000) -> RenderArtifact:
    pcm = np.asarray(values, dtype='<f4').tobytes()
    content_sha = hashlib.sha256(pcm).hexdigest()
    identity = hashlib.sha256(label.encode('utf-8')).hexdigest()
    recipe = hashlib.sha256((label + ':recipe').encode('utf-8')).hexdigest()
    cache = hashlib.sha256((label + ':cache').encode('utf-8')).hexdigest()
    frames = len(pcm) // 4
    asset = {
        'kind': 'AudioAssetRef',
        'version': '1.0.0',
        'content_sha256': content_sha,
        'identity_domain': 'pcm-f32le-interleaved-v1',
        'sample_rate_hz': sample_rate,
        'channels': 1,
        'channel_layout': 'mono',
        'frame_count': frames,
        'level_domain': 'source',
        'sample_policy': 'unclamped_float',
    }
    return RenderArtifact(identity, recipe, 'synth', cache, pcm, asset, {})


A_VALUES = [0.25, -0.5, 0.375, -0.125, 0.2, -0.4, 0.3, -0.1]
B_VALUES = [0.4, -0.1, 0.2, -0.35, 0.1, -0.3, 0.45, -0.2]
C_VALUES = [0.12, -0.31, 0.22, -0.41, 0.18, -0.27, 0.36, -0.16]


class ListeningAudioStoreBudgetTests(unittest.TestCase):
    def _freeze_pair(self, store, *, same_pcm=False):
        a = store.add_artifact('A', _artifact('a', A_VALUES))
        b = store.add_artifact('B', _artifact('b', A_VALUES if same_pcm else B_VALUES))
        return a.to_dict()['id'], b.to_dict()['id']

    def test_accounting_reports_one_authoritative_physical_pcm_total(self):
        store = ListeningAudioStore(max_bytes=1024)
        a, b = self._freeze_pair(store)
        before = store.accounting()
        self.assertEqual(before['method'], 'retained-pcm-physical-bytes-v1')
        self.assertEqual(before['raw_entries'], 2)
        self.assertEqual(before['playback_entries'], 0)
        self.assertEqual(before['total_pcm_bytes'], before['raw_pcm_bytes'])
        store.match([a, b], target_rms_dbfs=-60.0)
        after = store.accounting()
        self.assertEqual(after['total_pcm_bytes'], after['raw_pcm_bytes'] + after['playback_pcm_bytes'])
        self.assertEqual(after['max_bytes'], 1024)
        self.assertLessEqual(after['total_pcm_bytes'], after['max_bytes'])

    def test_raw_only_exact_boundary_succeeds_and_one_more_artifact_fails_cleanly(self):
        a_artifact = _artifact('raw-a', A_VALUES)
        b_artifact = _artifact('raw-b', B_VALUES)
        store = ListeningAudioStore(max_bytes=len(a_artifact.audio_bytes))
        a = store.add_artifact('A', a_artifact)
        before = store.accounting()
        self.assertEqual(before['total_pcm_bytes'], len(a_artifact.audio_bytes))
        with self.assertRaisesRegex(ListeningError, 'store budget exceeded'):
            store.add_artifact('B', b_artifact)
        self.assertEqual(store.accounting(), before)
        self.assertEqual(store.stimulus(a.to_dict()['id']).to_dict(), a.to_dict())

    def test_existing_playback_bytes_participate_in_later_add_artifact_admission(self):
        probe = ListeningAudioStore(max_bytes=4096)
        a, b = self._freeze_pair(probe)
        probe.match([a, b], target_rms_dbfs=-60.0)
        resident = probe.accounting()['total_pcm_bytes']
        c_artifact = _artifact('c', C_VALUES)
        limit = resident + len(c_artifact.audio_bytes) - 1

        store = ListeningAudioStore(max_bytes=limit)
        a, b = self._freeze_pair(store)
        matched = store.match([a, b], target_rms_dbfs=-60.0)
        before = store.accounting()
        self.assertEqual(before['total_pcm_bytes'], resident)
        self.assertLess(sum(len(v) for v in store._raw.values()) + len(c_artifact.audio_bytes), limit)
        with self.assertRaisesRegex(ListeningError, 'store budget exceeded'):
            store.add_artifact('C', c_artifact)
        self.assertEqual(store.accounting(), before)
        self.assertTrue(all(store.has_playback(row['playback_sha256']) for row in matched))

    def test_match_accepts_exact_total_limit_and_rejects_one_byte_less_before_mutation(self):
        probe = ListeningAudioStore(max_bytes=4096)
        a, b = self._freeze_pair(probe)
        probe.match([a, b], target_rms_dbfs=-60.0)
        exact = probe.accounting()['total_pcm_bytes']

        at_limit = ListeningAudioStore(max_bytes=exact)
        a, b = self._freeze_pair(at_limit)
        rows = at_limit.match([a, b], target_rms_dbfs=-60.0)
        self.assertEqual(at_limit.accounting()['total_pcm_bytes'], exact)
        self.assertEqual(len(rows), 2)

        below = ListeningAudioStore(max_bytes=exact - 1)
        a, b = self._freeze_pair(below)
        before = below.accounting()
        with self.assertRaisesRegex(ListeningError, 'matched playback store budget exceeded'):
            below.match([a, b], target_rms_dbfs=-60.0)
        self.assertEqual(below.accounting(), before)
        self.assertEqual(below._playback, {})

    def test_identical_playback_is_physically_counted_once_and_repeated_match_is_idempotent(self):
        store = ListeningAudioStore(max_bytes=4096)
        a, b = self._freeze_pair(store, same_pcm=True)
        rows = store.match([a, b], target_rms_dbfs=-60.0)
        self.assertEqual(rows[0]['playback_sha256'], rows[1]['playback_sha256'])
        first = store.accounting()
        self.assertEqual(first['raw_entries'], 2)
        self.assertEqual(first['playback_entries'], 1)
        self.assertEqual(first['playback_pcm_bytes'], len(store.playback_pcm(rows[0]['playback_sha256'])))
        again = store.match([a, b], target_rms_dbfs=-60.0)
        self.assertEqual([r['playback_sha256'] for r in again], [r['playback_sha256'] for r in rows])
        self.assertEqual(store.accounting(), first)

    def test_failed_new_match_preserves_preexisting_shared_playback_bit_exactly(self):
        store = ListeningAudioStore(max_bytes=4096)
        a = store.add_artifact('A', _artifact('shared-a', A_VALUES)).to_dict()['id']
        b = store.add_artifact('B', _artifact('shared-b', A_VALUES)).to_dict()['id']
        c = store.add_artifact('C', _artifact('shared-c', A_VALUES)).to_dict()['id']
        d = store.add_artifact('D', _artifact('different-d', B_VALUES)).to_dict()['id']
        existing = store.match([a, b], target_rms_dbfs=-60.0)
        shared_sha = existing[0]['playback_sha256']
        shared_pcm = store.playback_pcm(shared_sha)
        store.max_bytes = store.accounting()['total_pcm_bytes']
        before = store.accounting()
        with self.assertRaisesRegex(ListeningError, 'matched playback store budget exceeded'):
            store.match([c, d], target_rms_dbfs=-60.0)
        self.assertEqual(store.accounting(), before)
        self.assertEqual(store.playback_pcm(shared_sha), shared_pcm)

    def test_concurrent_adds_share_the_same_locked_total_budget(self):
        first = _artifact('thread-a', A_VALUES)
        second = _artifact('thread-b', B_VALUES)
        store = ListeningAudioStore(max_bytes=len(first.audio_bytes))
        barrier = threading.Barrier(2)
        accepted = []
        rejected = []

        def worker(name, artifact):
            barrier.wait()
            try:
                accepted.append(store.add_artifact(name, artifact).to_dict()['id'])
            except ListeningError as exc:
                rejected.append(str(exc))

        threads = [threading.Thread(target=worker, args=('A', first)), threading.Thread(target=worker, args=('B', second))]
        for thread in threads: thread.start()
        for thread in threads: thread.join(5)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(len(accepted), 1)
        self.assertEqual(len(rejected), 1)
        self.assertIn('store budget exceeded', rejected[0])
        usage = store.accounting()
        self.assertEqual(usage['raw_entries'], 1)
        self.assertEqual(usage['total_pcm_bytes'], len(first.audio_bytes))
        self.assertLessEqual(usage['total_pcm_bytes'], usage['max_bytes'])

    def test_max_bytes_must_be_a_positive_integer(self):
        for value in (0, -1, True, 1.5, '1024'):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ListeningError, 'positive integer'):
                    ListeningAudioStore(max_bytes=value)


if __name__ == '__main__':
    unittest.main(verbosity=2)
