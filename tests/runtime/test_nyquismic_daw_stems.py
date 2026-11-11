"""Original-WAV DAW export, no-clobber, cancellation and source-identity tests."""
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

import numpy as np
from scipy.io import wavfile

from zaaggenz_runtime import nyquismic_daw_stems as stems


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def wav(samples):
    f = io.BytesIO()
    pcm = np.asarray(samples, dtype='<f4')
    wavfile.write(f, 48000, pcm)
    return f.getvalue(), sha(pcm.tobytes())


class DawStemExports(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.source = self.root / 'rates.zip'
        self.source.write_bytes(b'unchanged-authenticated-sweep-snapshot')
        self.output = self.root / 'stems.zip'
        dry, dry_pcm = wav([0., .25, -.5, .15] * 100)
        wet4, pcm4 = wav([0., .15, -.4, .12] * 100)
        wet5, pcm5 = wav([0., .05, -.3, .32] * 100)
        self.record = {
            'archive_sha256': sha(self.source.read_bytes()),
            'source': {'project_file_sha256': '1'*64, 'source_asset_sha256': '2'*64,
                       'source_revision_sha256': '3'*64, 'compose_recipe_sha256': '4'*64,
                       'dry_pcm_f32le_sha256': dry_pcm, 'frames': 400, 'channels': 1},
            'frames': 400, 'channels': 1, 'dry': dry,
            'variants': [
                {'rate': '4/1', 'wet': wet4, 'wet_pcm_sha256': pcm4, 'packet_sha256': '5'*64},
                {'rate': '5/1', 'wet': wet5, 'wet_pcm_sha256': pcm5, 'packet_sha256': '6'*64},
            ]}
        patch = mock.patch.object(stems.compare, '_verified_sweep', return_value=self.record)
        patch.start()
        self.addCleanup(patch.stop)

    def test_exact_original_wavs_and_manifest(self):
        receipt = stems.export_daw_stems(self.source, self.output)
        self.assertEqual(receipt['zip_sha256'], sha(self.output.read_bytes()))
        with zipfile.ZipFile(self.output) as z:
            self.assertEqual(z.namelist(), ['manifest.json', 'original.wav', 'nyq-rate-01.wav', 'nyq-rate-02.wav'])
            raw = [z.read(name) for name in z.namelist()[1:]]
            self.assertEqual(raw, [self.record['dry'], *[x['wet'] for x in self.record['variants']]])
            manifest = json.loads(z.read('manifest.json'))
            self.assertEqual(manifest['source_sweep_sha256'], sha(self.source.read_bytes()))
            self.assertEqual(manifest['sample_rate_hz'], 48000)
            for i, item in enumerate(manifest['stems']):
                self.assertEqual(item['wav_sha256'], sha(raw[i]))
                self.assertEqual(z.getinfo(item['file']).date_time, (1980,1,1,0,0,0))
                rate, decoded = wavfile.read(io.BytesIO(raw[i]))
                self.assertEqual(rate, 48000)
                self.assertEqual(decoded.dtype, np.float32)
                self.assertEqual(sha(np.asarray(decoded, dtype='<f4').tobytes()), item['pcm_f32le_sha256'])
        print('NYQ_DAW_STEMS_PCM ' + json.dumps({'frames':400, 'delivery_hz':48000,
            'dry_wav_sha256':sha(raw[0]), 'wet_wav_sha256':[sha(x) for x in raw[1:]],
            'zip_sha256':receipt['zip_sha256']}, sort_keys=True))

    def test_cold_reopen_deterministic(self):
        a = stems.export_daw_stems(self.source, self.output)
        self.output.rename(self.root / 'old.zip')
        b = stems.export_daw_stems(self.source, self.output)
        self.assertEqual(a['zip_sha256'], b['zip_sha256'])
        self.assertEqual((self.root / 'old.zip').read_bytes(), self.output.read_bytes())

    def test_existing_output_read_guard_and_preservation(self):
        self.output.write_bytes(b'user-owned-data')
        with mock.patch.object(stems.compare, '_verified_sweep', side_effect=AssertionError('input must not read')):
            with self.assertRaises(FileExistsError):
                stems.export_daw_stems(self.source, self.output)
        self.assertEqual(self.output.read_bytes(), b'user-owned-data')

    def test_cancel_during_zip_removes_stage(self):
        call = [0]
        def cancelled():
            call[0] += 1
            return call[0] >= 3
        with self.assertRaisesRegex(RuntimeError, 'cancelled'):
            stems.export_daw_stems(self.source, self.output, cancelled=cancelled)
        self.assertEqual(sorted(x.name for x in self.root.iterdir()), ['rates.zip'])

    def test_cancel_after_fsync_removes_stage(self):
        flag = [False]
        original = stems.os.fsync
        def fsync(fd):
            original(fd)
            flag[0] = True
        with mock.patch.object(stems.os, 'fsync', side_effect=fsync):
            with self.assertRaisesRegex(RuntimeError, 'cancelled'):
                stems.export_daw_stems(self.source, self.output, cancelled=lambda: flag[0])
        self.assertEqual(sorted(x.name for x in self.root.iterdir()), ['rates.zip'])

    def test_source_edit_before_commit_refused(self):
        original = stems._file_sha
        def modify(path, cancelled=None):
            if path == self.source:
                self.source.write_bytes(b'mutated-but-valid-length')
            return original(path, cancelled)
        with mock.patch.object(stems, '_file_sha', side_effect=modify):
            with self.assertRaisesRegex(RuntimeError, 'source sweep changed'):
                stems.export_daw_stems(self.source, self.output)
        self.assertFalse(self.output.exists())
        self.assertEqual(sorted(x.name for x in self.root.iterdir()), ['rates.zip'])

    def test_concurrent_destination_writer_not_clobbered(self):
        def competitor(src, dst):
            Path(dst).write_bytes(b'competitor-data')
            raise FileExistsError(dst)
        with mock.patch.object(stems.os, 'link', side_effect=competitor):
            with self.assertRaises(FileExistsError):
                stems.export_daw_stems(self.source, self.output)
        self.assertEqual(self.output.read_bytes(), b'competitor-data')
        self.assertEqual(sorted(x.name for x in self.root.iterdir()), ['rates.zip', 'stems.zip'])

    def test_invalid_output_and_cancellation_callback(self):
        with self.assertRaises(ValueError):
            stems.export_daw_stems(self.source, self.root / 'stems.wav')
        with self.assertRaisesRegex(ValueError, 'callable'):
            stems.export_daw_stems(self.source, self.output, cancelled=True)


class OriginalComposeStemExports(unittest.TestCase):
    def test_actual_compose_two_rate_wavs_are_unmodified(self):
        root = Path(__file__).resolve().parents[2]
        if not (root/'zaaggenz_runtime'/'nyquismic_audition_sweep.py').is_file():
            self.skipTest('requires original checkout with #289 source')
        from test_nyquismic_compose_delivery import source_document
        from zaaggenz_runtime.nyquismic_audition_sweep import export_saved_compose_rate_sweep
        from zaaggenz_runtime.nyquismic_rate_compare import _verified_sweep
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            project = base/'project.zgtimeline.json'
            project.write_text(json.dumps(source_document()), encoding='utf-8')
            sweep = base/'rates.zip'
            export_saved_compose_rate_sweep(project,sweep,virtual_rates_hz=['4/1','5/1'])
            original = _verified_sweep(sweep)
            destination = base/'stems.zip'
            receipt = stems.export_daw_stems(sweep,destination)
            with zipfile.ZipFile(destination) as z:
                self.assertEqual(z.read('original.wav'), original['dry'])
                for n, variant in enumerate(original['variants'],1):
                    self.assertEqual(z.read(f'nyq-rate-{n:02d}.wav'), variant['wet'])
            self.assertEqual(receipt['frames'],28800)
            self.assertEqual(receipt['delivery_hz'],48000)
            print('NYQ_DAW_STEMS_COMPOSE ' + json.dumps({'frames':receipt['frames'],
                'source_sweep_sha256':receipt['source_sweep_sha256'],
                'dry_wav_sha256':sha(original['dry']),
                'wet_pcm_f32le_sha256':[v['wet_pcm_sha256'] for v in original['variants']]},sort_keys=True))


if __name__=='__main__':
    unittest.main(verbosity=2)
