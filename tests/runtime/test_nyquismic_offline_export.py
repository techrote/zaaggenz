"""Original saved-project -> ordinary Compose -> #267/#266 -> atomic 48k WAV.

All input and output remain synthetic in temporary directories.
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

import numpy as np
from scipy.io import wavfile

from zaaggenz_jobs import JobError
from zaaggenz_runtime import nyquismic_offline_export as cli
from zaaggenz_timeline.model import TimelineDocument
from test_nyquismic_compose_delivery import source_document


class SavedComposeNyqOfflineExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / 'actual-save.zgtimeline.json'
        self.document = source_document()
        self.project.write_text(json.dumps(self.document), encoding='utf-8')
        self.output = self.root / 'nyq.wav'

    def export(self, output=None, **kwargs):
        return cli.export_saved_compose_nyq48(
            self.project, self.output if output is None else output,
            virtual_rate_hz='4/1', **kwargs)

    def test_saved_project_to_nonzero_decoded_wav_and_exact_pcm_receipt(self):
        receipt = self.export()
        wav_bytes = self.output.read_bytes()
        rate, pcm = wavfile.read(io.BytesIO(wav_bytes))
        self.assertEqual(receipt['format'], 'nyq.saved-compose-wav48-receipt.v1')
        self.assertEqual(receipt['absolute_path'], str(self.output))
        self.assertEqual(receipt['saved_project_file_sha256'],
                         hashlib.sha256(self.project.read_bytes()).hexdigest())
        self.assertEqual(receipt['source_revision_sha256'],
                         TimelineDocument(self.document).revision_id)
        self.assertEqual(rate, 48000)
        self.assertEqual(pcm.dtype, np.dtype('float32'))
        self.assertEqual(len(pcm), receipt['frames'])
        self.assertEqual(receipt['channels'], 1)
        self.assertTrue(np.isfinite(pcm).all())
        self.assertGreater(float(np.max(np.abs(pcm))), 0.)
        self.assertEqual(receipt['wav_sha256'], hashlib.sha256(wav_bytes).hexdigest())
        self.assertEqual(receipt['pcm_f32le_sha256'], hashlib.sha256(
            pcm.astype('<f4', copy=False).tobytes()).hexdigest())
        self.assertEqual(sorted(self.root.iterdir()), [self.project, self.output])
        print('NYQ_SAVED_PROJECT_ORIGINAL_NUMERICS ' + json.dumps({
            'project_file_sha256': receipt['saved_project_file_sha256'],
            'source_revision_sha256': receipt['source_revision_sha256'],
            'packet_sha256': receipt['packet_sha256'],
            'render_identity_sha256': receipt['render_identity_sha256'],
            'pcm_f32le_sha256': receipt['pcm_f32le_sha256'],
            'wav_sha256': receipt['wav_sha256'],
            'frames': receipt['frames'], 'rate_hz': receipt['sample_rate_hz'],
        }, sort_keys=True))

    def test_cold_saved_reopen_replays_identical_wav_bytes(self):
        first = self.export()
        second_path = self.root / 'cold-reopen.wav'
        second = self.export(second_path)
        self.assertEqual(first['wav_sha256'], second['wav_sha256'])
        self.assertEqual(self.output.read_bytes(), second_path.read_bytes())
        self.assertEqual(first['pcm_f32le_sha256'], second['pcm_f32le_sha256'])
        self.assertEqual(first['render_identity_sha256'], second['render_identity_sha256'])

    def test_existing_file_cannot_be_overwritten_or_start_render(self):
        self.output.write_bytes(b'existing user file')
        with patch.object(cli, 'TimelineService',
                          side_effect=AssertionError('must not render')):
            with self.assertRaises(FileExistsError):
                self.export()
        self.assertEqual(self.output.read_bytes(), b'existing user file')

    def test_stale_compose_revision_refuses_publication(self):
        actual = cli.save_compose_controlled_48k_wav_file
        def edit_before_publication(binding, *args, **kwargs):
            changed = deepcopy(self.document)
            changed['name'] = 'concurrent edit'
            binding.timeline.accept_document(changed)
            return actual(binding, *args, **kwargs)
        with patch.object(cli, 'save_compose_controlled_48k_wav_file',
                          side_effect=edit_before_publication):
            with self.assertRaises(JobError):
                self.export()
        self.assertFalse(self.output.exists())

    def test_cancellation_after_staging_fsync_removes_partial(self):
        from zaaggenz_runtime import nyquismic_compose_file_export as disk
        original = disk.os.fsync
        cancelled = [False]
        def fsync_then_cancel(fd):
            original(fd)
            cancelled[0] = True
        with patch.object(disk.os, 'fsync', side_effect=fsync_then_cancel):
            with self.assertRaises(JobError):
                self.export(cancelled=lambda: cancelled[0])
        self.assertTrue(cancelled[0])
        self.assertEqual(sorted(self.root.iterdir()), [self.project])

    def test_real_cli_entrypoint_and_invalid_input_refusal(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = cli.main(['--project', str(self.project), '--output',
                               str(self.output), '--virtual-hz', '4/1'])
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output.getvalue())['wav_sha256'],
                         hashlib.sha256(self.output.read_bytes()).hexdigest())
        other = self.root / 'invalid.wav'
        with self.assertRaises(ValueError):
            self.export(other, evaluation_rate_hz=48000)
        with self.assertRaises(ValueError):
            self.export(other.with_suffix('.mp3'))
        invalid = self.root / 'invalid.zgtimeline.json'
        invalid.write_text('{"format":"not-a-timeline"}', encoding='utf-8')
        with self.assertRaises(Exception):
            cli.export_saved_compose_nyq48(invalid, other)
        self.assertFalse(other.exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
