"""Adversarial real-Compose coverage of opt-in NYQ atomic disk delivery.

No private recordings or external processes. All output stays in TemporaryDirectory.
"""
from copy import deepcopy
import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from scipy.io import wavfile

from zaaggenz_dsp.nyquismic import sampler_evaluation
from zaaggenz_jobs import JobError
from zaaggenz_runtime.nyquismic_compose import bind_completed_compose
from zaaggenz_runtime.nyquismic_compose_file_export import (
    save_compose_controlled_48k_wav_file,
)
from zaaggenz_timeline.service import TimelineService
from test_nyquismic_compose_delivery import source_document, sonic, packet_for


class AtomicControlledWav48kTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dest = Path(self.temp.name) / 'my-nyq-export.wav'
        self.document = source_document()
        self.service = TimelineService(debounce_seconds=0)
        submitted = self.service.submit(self.document)
        self.job_id = submitted['job_id']
        self.assertEqual(self.service.scheduler.wait(self.job_id, 45).state,
                         'completed')

    def tearDown(self):
        self.service.close()
        self.temp.cleanup()

    def save(self, *, cancelled=None):
        binding = bind_completed_compose(self.service, self.job_id)
        spec = sonic()
        packet = packet_for(binding, spec)
        return save_compose_controlled_48k_wav_file(
            binding, spec, packet, sampler_evaluation(192000), self.dest,
            cancelled=cancelled,
        )

    def test_actual_compose_to_atomic_decodable_file_and_exact_hash(self):
        receipt = self.save()
        self.assertEqual(receipt.absolute_path, str(self.dest))
        data = self.dest.read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), receipt.wav_sha256)
        rate, audio = wavfile.read(io.BytesIO(data))
        self.assertEqual(rate, 48000)
        self.assertEqual(audio.dtype, np.dtype('float32'))
        self.assertEqual(audio.shape, (receipt.frames,))
        self.assertEqual(receipt.channels, 1)
        self.assertTrue(np.isfinite(audio).all())
        self.assertGreater(float(np.max(np.abs(audio))), 0.)
        self.assertEqual(hashlib.sha256(
            audio.astype('<f4', copy=False).tobytes()).hexdigest(),
            receipt.pcm_f32le_sha256)
        self.assertEqual(receipt.source_revision_sha256,
                         self.service.session.document().revision_id)
        self.assertEqual(sorted(Path(self.temp.name).iterdir()), [self.dest])

    def test_existing_file_is_preserved_and_no_render_attempted(self):
        self.dest.write_bytes(b'existing user WAV placeholder')
        with patch(
            'zaaggenz_runtime.nyquismic_compose_file_export.render_compose_controlled_48k_wav',
            side_effect=AssertionError('render must not run'),
        ):
            with self.assertRaises(FileExistsError):
                self.save()
        self.assertEqual(self.dest.read_bytes(), b'existing user WAV placeholder')
        self.assertEqual(sorted(Path(self.temp.name).iterdir()), [self.dest])

    def test_compose_edit_during_staging_cannot_publish(self):
        from zaaggenz_runtime import nyquismic_compose_file_export as module
        edited = deepcopy(self.document)
        edited['name'] = 'edited during file staging'
        original_fsync = module.os.fsync
        invoked = [False]

        def fsync_then_edit(fd):
            original_fsync(fd)
            invoked[0] = True
            self.service.accept_document(edited)

        with patch.object(module.os, 'fsync', side_effect=fsync_then_edit):
            with self.assertRaises(JobError):
                self.save()
        self.assertTrue(invoked[0])
        self.assertFalse(self.dest.exists())
        self.assertEqual(list(Path(self.temp.name).iterdir()), [])

    def test_job_revocation_during_staging_refuses_disk_commit(self):
        from zaaggenz_runtime import nyquismic_compose_file_export as module
        original_fsync = module.os.fsync
        invoked = [False]

        def fsync_then_revoke(fd):
            original_fsync(fd)
            invoked[0] = True
            self.service.cancel(self.job_id)

        with patch.object(module.os, 'fsync', side_effect=fsync_then_revoke):
            with self.assertRaises(JobError):
                self.save()
        self.assertTrue(invoked[0])
        self.assertEqual(list(Path(self.temp.name).iterdir()), [])

    def test_cancellation_after_staging_refuses_disk_commit(self):
        from zaaggenz_runtime import nyquismic_compose_file_export as module
        original_fsync = module.os.fsync
        cancelled = [False]

        def fsync_then_cancel(fd):
            original_fsync(fd)
            cancelled[0] = True

        with patch.object(module.os, 'fsync', side_effect=fsync_then_cancel):
            with self.assertRaises(JobError):
                self.save(cancelled=lambda: cancelled[0])
        self.assertTrue(cancelled[0])
        self.assertEqual(list(Path(self.temp.name).iterdir()), [])

    def test_concurrent_external_destination_create_is_no_clobber(self):
        from zaaggenz_runtime import nyquismic_compose_file_export as module
        def competing_create(_source, destination):
            Path(destination).write_bytes(b'external writer won the race')
            raise FileExistsError(str(destination))

        with patch.object(module.os, 'link', side_effect=competing_create):
            with self.assertRaises(FileExistsError):
                self.save()
        self.assertEqual(self.dest.read_bytes(),
                         b'external writer won the race')
        self.assertEqual(sorted(Path(self.temp.name).iterdir()), [self.dest])

    def test_unsupported_target_does_not_render_or_make_files(self):
        from zaaggenz_runtime import nyquismic_compose_file_export as module
        binding = bind_completed_compose(self.service, self.job_id)
        spec = sonic()
        packet = packet_for(binding, spec)
        with patch.object(module, 'render_compose_controlled_48k_wav',
                          side_effect=AssertionError('should not render')):
            with self.assertRaises(JobError):
                save_compose_controlled_48k_wav_file(
                    binding, spec, packet, sampler_evaluation(192000),
                    Path(self.temp.name) / 'not-a-wav.txt',
                )
        self.assertEqual(list(Path(self.temp.name).iterdir()), [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
