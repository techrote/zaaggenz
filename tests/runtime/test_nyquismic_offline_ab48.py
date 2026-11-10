"""Synthetic original Compose source -> deterministic dry/NYQ audition ZIP.

No private material. Tests exercise real TimelineService jobs and decoded audio.
"""
from copy import deepcopy
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import numpy as np
from scipy.io import wavfile

from zaaggenz_contracts.nyquismic import ResourceBudget
from zaaggenz_jobs import JobError
from zaaggenz_runtime import nyquismic_offline_ab48 as ab
from zaaggenz_runtime.nyquismic_compose import bind_completed_compose
from zaaggenz_timeline.model import default_document
from zaaggenz_timeline.service import TimelineService
from test_nyquismic_compose_delivery import source_document


class SavedComposeAuditionBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.document = source_document()
        self.project = self.root / 'song.zgtimeline.json'
        self.project.write_text(json.dumps(self.document), encoding='utf-8')
        self.destination = self.root / 'audition.zip'

    def export(self, output=None, **kwargs):
        return ab.export_saved_compose_ab48(
            self.project, self.destination if output is None else output,
            virtual_rate_hz='4/1', **kwargs)

    def read_pair(self, path=None):
        with zipfile.ZipFile(path or self.destination) as packed:
            self.assertEqual(packed.namelist(), [
                'compose-dry.wav', 'compose-nyquismic.wav', 'manifest.json'])
            dry = packed.read('compose-dry.wav')
            wet = packed.read('compose-nyquismic.wav')
            manifest = json.loads(packed.read('manifest.json'))
        return dry, wet, manifest

    def test_authentic_pair_decodes_48k_and_matches_all_bundle_receipts(self):
        receipt = self.export()
        dry, wet, manifest = self.read_pair()
        dry_rate, dry_pcm = wavfile.read(io.BytesIO(dry))
        wet_rate, wet_pcm = wavfile.read(io.BytesIO(wet))
        self.assertEqual((dry_rate, wet_rate), (48000, 48000))
        self.assertEqual((dry_pcm.dtype, wet_pcm.dtype),
                         (np.dtype('float32'), np.dtype('float32')))
        self.assertEqual(dry_pcm.shape, wet_pcm.shape)
        self.assertEqual(len(dry_pcm), 28800)
        self.assertTrue(np.isfinite(dry_pcm).all())
        self.assertTrue(np.isfinite(wet_pcm).all())
        self.assertGreater(float(np.max(np.abs(dry_pcm))), 0.)
        self.assertFalse(np.array_equal(dry_pcm, wet_pcm))
        self.assertEqual(receipt['manifest'], manifest)
        self.assertEqual(receipt['format'], ab.FORMAT)
        self.assertEqual(receipt['archive_sha256'],
                         hashlib.sha256(self.destination.read_bytes()).hexdigest())
        self.assertEqual(manifest['project_file_sha256'],
                         hashlib.sha256(self.project.read_bytes()).hexdigest())
        for data, row in ((dry, manifest['dry']), (wet, manifest['wet'])):
            self.assertEqual(row['wav_sha256'], hashlib.sha256(data).hexdigest())
            _, pcm = wavfile.read(io.BytesIO(data))
            self.assertEqual(row['pcm_f32le_sha256'], hashlib.sha256(
                np.asarray(pcm, dtype='<f4').tobytes()).hexdigest())
        self.assertEqual(manifest['dry']['source_rate_hz'], 12000)
        self.assertEqual(manifest['dry']['ratio_up'], 4)
        self.assertEqual(manifest['dry']['ratio_down'], 1)
        self.assertEqual(sorted(self.root.iterdir()), [self.destination, self.project])
        print('NYQ_AB48_ORIGINAL_NUMERICS ' + json.dumps({
            'source_asset_sha256': manifest['source_asset_sha256'],
            'source_revision_sha256': manifest['source_revision_sha256'],
            'packet_sha256': manifest['packet_sha256'],
            'dry_pcm_sha256': manifest['dry']['pcm_f32le_sha256'],
            'wet_pcm_sha256': manifest['wet']['pcm_f32le_sha256'],
            'dry_wav_sha256': manifest['dry']['wav_sha256'],
            'wet_wav_sha256': manifest['wet']['wav_sha256'],
            'bundle_sha256': receipt['archive_sha256'],
            'frames': manifest['frames'], 'rate_hz': manifest['sample_rate_hz'],
        }, sort_keys=True))

    def test_cold_saved_reopen_reproduces_byte_exact_zip(self):
        first = self.export()
        other_path = self.root / 'audition-reopen.zip'
        second = self.export(other_path)
        self.assertEqual(first['archive_sha256'], second['archive_sha256'])
        self.assertEqual(self.destination.read_bytes(), other_path.read_bytes())
        self.assertEqual(first['manifest'], second['manifest'])

    def test_already_existing_bundle_refuses_before_compose_render(self):
        self.destination.write_bytes(b'owned user data')
        with patch.object(ab, 'TimelineService',
                          side_effect=AssertionError('must not render')):
            with self.assertRaises(FileExistsError):
                self.export()
        self.assertEqual(self.destination.read_bytes(), b'owned user data')

    def test_late_compose_edit_after_wet_render_prevents_any_publication(self):
        actual = ab.render_compose_controlled_48k_wav
        changed = deepcopy(self.document)
        changed['name'] = 'edit after NYQ render'
        def render_then_edit(binding, *args, **kwargs):
            result = actual(binding, *args, **kwargs)
            binding.timeline.accept_document(changed)
            return result
        with patch.object(ab, 'render_compose_controlled_48k_wav',
                          side_effect=render_then_edit):
            with self.assertRaises(JobError):
                self.export()
        self.assertFalse(self.destination.exists())

    def test_owned_job_revocation_after_wet_render_refuses_publication(self):
        actual = ab.render_compose_controlled_48k_wav
        def render_then_revoke(binding, *args, **kwargs):
            result = actual(binding, *args, **kwargs)
            binding.timeline.cancel(binding.job_id)
            return result
        with patch.object(ab, 'render_compose_controlled_48k_wav',
                          side_effect=render_then_revoke):
            with self.assertRaises(JobError):
                self.export()
        self.assertFalse(self.destination.exists())

    def test_cancellation_after_zip_fsync_removes_partial_and_no_bundle(self):
        actual = ab.os.fsync
        cancelled = [False]
        def fsync_then_cancel(fd):
            actual(fd)
            cancelled[0] = True
        with patch.object(ab.os, 'fsync', side_effect=fsync_then_cancel):
            with self.assertRaises(JobError):
                self.export(cancelled=lambda: cancelled[0])
        self.assertTrue(cancelled[0])
        self.assertEqual(sorted(self.root.iterdir()), [self.project])

    def test_competing_filesystem_writer_is_never_overwritten(self):
        actual = ab.os.link
        def external_wins(source, target):
            Path(target).write_bytes(b'external winner')
            raise FileExistsError(str(target))
        with patch.object(ab.os, 'link', side_effect=external_wins):
            with self.assertRaises(FileExistsError):
                self.export()
        self.assertEqual(self.destination.read_bytes(), b'external winner')
        self.assertEqual(sorted(self.root.iterdir()), [self.destination, self.project])

    def test_48k_compose_dry_reference_preserves_original_f32_pcm(self):
        document = default_document(48000).to_dict()
        document['name'] = 'identity baseline'
        document['end_beat'] = '2/1'
        document['notes'] = deepcopy(self.document['notes'])
        service = TimelineService(debounce_seconds=0)
        try:
            job = service.submit(document)['job_id']
            self.assertEqual(service.scheduler.wait(job, 45).state, 'completed')
            binding = bind_completed_compose(service, job)
            data, info = ab._dry_48k_wav(binding, ResourceBudget(), None)
            rate, pcm = wavfile.read(io.BytesIO(data))
            self.assertEqual(rate, 48000)
            self.assertEqual(info['fir_taps'], 1)
            self.assertEqual(pcm.tobytes(order='C'),
                             binding.source.pcm.astype('<f4').tobytes(order='C'))
        finally:
            service.close()

    def test_actual_cli_and_bad_project_are_fail_closed(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = ab.main(['--project', str(self.project), '--output',
                            str(self.destination), '--virtual-hz', '4/1'])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())['archive_sha256'],
                         hashlib.sha256(self.destination.read_bytes()).hexdigest())
        with self.assertRaises(ValueError):
            self.export(self.root / 'not-a-zip.wav')
        invalid = self.root / 'bad.zgtimeline.json'
        invalid.write_text('{"format":"wrong"}', encoding='utf-8')
        with self.assertRaises(Exception):
            ab.export_saved_compose_ab48(invalid, self.root / 'bad.zip')
        self.assertFalse((self.root / 'bad.zip').exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
