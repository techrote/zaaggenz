"""Isolated original-WAV, source-revision, safety and publication regressions."""
import base64
import hashlib
import io
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest import mock
import zipfile

import numpy as np
from scipy.io import wavfile

from zaaggenz_runtime import nyquismic_rate_compare as compare


def sha(data):
    return hashlib.sha256(data).hexdigest()


def wav(values):
    output = io.BytesIO()
    wavfile.write(output, 48000, np.asarray(values, dtype='<f4'))
    raw = output.getvalue()
    return raw, {"wav_sha256": sha(raw), "pcm_f32le_sha256":
                 sha(np.asarray(values, dtype='<f4').tobytes())}


class RateComparisonTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.archive = self.root / 'sweep.zip'
        self.output = self.root / 'compare.html'
        self.dry, self.dry_receipt = wav([0, 0.25, -0.5, 0.2] * 120)
        self.wets = [wav([0, 0.15, -0.4, 0.1] * 120),
                     wav([0, 0.05, -0.3, 0.3] * 120)]
        self.source = {key: digit * 64 for key, digit in (
            ('project_file_sha256', '1'), ('source_asset_sha256', '2'),
            ('source_revision_sha256', '3'), ('compose_recipe_sha256', '4'))}
        self.source.update(dry_pcm_f32le_sha256=self.dry_receipt['pcm_f32le_sha256'],
                           frames=480, channels=1)
        self.build_archive()

    def build_archive(self, *, page_mutation=None, entry_mutation=None, zip_names=None):
        entries, pages = [], []
        for i, rate in enumerate(('4/1', '5/1')):
            wet, wet_receipt = self.wets[i]
            packet = sha(('packet:' + rate).encode())
            manifest = {**{k: self.source[k] for k in (
                'project_file_sha256', 'source_asset_sha256',
                'source_revision_sha256', 'compose_recipe_sha256')},
                'sample_rate_hz': 48000, 'frames': 480, 'channels': 1,
                'dry': self.dry_receipt, 'wet': wet_receipt,
                'virtual_rate_hz': rate, 'evaluation_rate_hz': 192000,
                'packet_sha256': packet}
            payload = {'format': 'nyq.ab48-local-audition-html.v1',
                       'frames': 480, 'channels': 1, 'manifest': manifest,
                       'dry': base64.b64encode(self.dry).decode('ascii'),
                       'wet': base64.b64encode(wet).decode('ascii')}
            if page_mutation:
                page_mutation(i, payload)
            page = ('<!doctype html><script id="nyq-payload" type="application/json">'
                    + json.dumps(payload, sort_keys=True).replace('<', '\\u003c')
                    + '</script>').encode()
            name = f'variant-{i+1:02d}.html'
            pages.append((name, page))
            entries.append({'page': name, 'page_sha256': sha(page),
                            'virtual_rate_hz': rate, 'packet_sha256': packet,
                            'wet_pcm_f32le_sha256': wet_receipt['pcm_f32le_sha256']})
        if entry_mutation:
            entry_mutation(entries)
        metadata = {'format': compare.SWEEP_FORMAT,
                    'project_file_sha256': self.source['project_file_sha256'],
                    'source': self.source, 'delivery_rate_hz': 48000,
                    'evaluation_rate_hz': 192000, 'variants': entries}
        names = zip_names or ['index.html', 'manifest.json'] + [x[0] for x in pages]
        content = {'index.html': b'<h1>Rate sweep</h1>',
                   'manifest.json': json.dumps(metadata).encode(), **dict(pages)}
        with zipfile.ZipFile(self.archive, 'w', compression=zipfile.ZIP_STORED) as target:
            for name in names:
                target.writestr(name, content.get(name, b'bad'))

    def test_two_original_wav_renders_are_embedded_unchanged_and_synchronized(self):
        receipt = compare.publish_rate_comparison(self.archive, self.output)
        page = self.output.read_text()
        payload = json.loads(re.search(
            r'<script id="nyq-compare-payload" type="application/json">(.*?)</script>',
            page, re.S).group(1))
        self.assertEqual([base64.b64decode(x) for x in payload['wavs']],
                         [self.dry] + [pair[0] for pair in self.wets])
        self.assertEqual([v['rate'] for v in payload['receipt']['rates']], ['4/1', '5/1'])
        self.assertEqual(receipt['html_sha256'], sha(self.output.read_bytes()))
        self.assertEqual(payload['receipt']['source']['source_revision_sha256'], '3'*64)
        self.assertIn('s.start(when,offset)', page)
        self.assertIn('g.cancelAndHoldAtTime(t)', page)
        self.assertIn('g.setValueAtTime(from,t)', page)
        self.assertIn("connect-src 'none'", page)
        self.assertEqual(page.count('id="choice-'), 3)
        self.assertEqual(page.count('id="download-'), 3)
        self.assertEqual(sorted(self.root.iterdir()), [self.output, self.archive])
        print('NYQ_MULTI_RATE_ORIGINAL_WAV ' + json.dumps({
            'dry_wav_sha256': sha(self.dry),
            'wet_wav_sha256': [sha(pair[0]) for pair in self.wets],
            'html_sha256': receipt['html_sha256'],
            'frames': receipt['frames'], 'delivery_hz': receipt['delivery_hz']},
            sort_keys=True))

    def test_same_host_cold_reopen_byte_equality(self):
        first = compare.publish_rate_comparison(self.archive, self.output)
        first_page = self.output.read_bytes()
        self.output.rename(self.root / 'first.html')
        again = compare.publish_rate_comparison(self.archive, self.output)
        self.assertEqual(first['html_sha256'], again['html_sha256'])
        self.assertEqual(first_page, self.output.read_bytes())

    def test_page_payload_tamper_rejected_without_output(self):
        self.build_archive(page_mutation=lambda i,p: p.update(wet='AA==') if i==1 else None)
        with self.assertRaisesRegex(ValueError, 'WAV'):
            compare.publish_rate_comparison(self.archive, self.output)
        self.assertFalse(self.output.exists())

    def test_foreign_revision_even_with_rehashed_page_is_rejected(self):
        self.build_archive(page_mutation=lambda i,p: p['manifest'].update(
            source_revision_sha256='e'*64) if i==1 else None)
        with self.assertRaisesRegex(ValueError, 'foreign Compose source'):
            compare.publish_rate_comparison(self.archive, self.output)
        self.assertFalse(self.output.exists())

    def test_forged_outer_wet_pcm_hash_cannot_pass(self):
        self.build_archive(entry_mutation=lambda items: items[0].update(
            wet_pcm_f32le_sha256='0'*64))
        with self.assertRaisesRegex(ValueError, 'wet PCM'):
            compare.publish_rate_comparison(self.archive, self.output)

    def test_duplicate_rate_rejected(self):
        self.build_archive(entry_mutation=lambda items: items[1].update(
            virtual_rate_hz='4/1'))
        with self.assertRaisesRegex(ValueError, 'rate/packet'):
            compare.publish_rate_comparison(self.archive, self.output)

    def test_unexpected_entry_and_zip_slip_rejected(self):
        self.build_archive(zip_names=['index.html', 'manifest.json',
                                      'variant-01.html', '../escape.html'])
        with self.assertRaisesRegex(ValueError, 'contents'):
            compare.publish_rate_comparison(self.archive, self.output)
        self.assertFalse((self.root / 'escape.html').exists())

    def test_existing_output_never_overwritten_or_input_read(self):
        self.output.write_bytes(b'existing user asset')
        with mock.patch.object(compare, '_verified_sweep',
                               side_effect=AssertionError('should not read')):
            with self.assertRaises(FileExistsError):
                compare.publish_rate_comparison(self.archive, self.output)
        self.assertEqual(self.output.read_bytes(), b'existing user asset')

    def test_cancel_after_fsync_removes_staging(self):
        signal = [False]
        fsync = compare.os.fsync
        def cancel(fd):
            fsync(fd)
            signal[0] = True
        with mock.patch.object(compare.os, 'fsync', side_effect=cancel):
            with self.assertRaisesRegex(RuntimeError, 'cancelled'):
                compare.publish_rate_comparison(self.archive, self.output,
                                                cancelled=lambda: signal[0])
        self.assertEqual(list(self.root.iterdir()), [self.archive])

    def test_concurrent_writer_not_clobbered(self):
        def competitor(_, dest):
            Path(dest).write_bytes(b'other publisher')
            raise FileExistsError(dest)
        with mock.patch.object(compare.os, 'link', side_effect=competitor):
            with self.assertRaises(FileExistsError):
                compare.publish_rate_comparison(self.archive, self.output)
        self.assertEqual(self.output.read_bytes(), b'other publisher')

    def test_invalid_document_type_and_callback(self):
        with self.assertRaises(ValueError):
            compare.publish_rate_comparison(self.archive, self.root / 'output.wav')
        with self.assertRaisesRegex(ValueError, 'callable'):
            compare.publish_rate_comparison(self.archive, self.output, cancelled=True)

    def test_cli_receipt_has_unchanged_wav_sha(self):
        import contextlib
        import sys
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            status=compare.main(['--sweep', str(self.archive), '--output', str(self.output)])
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(out.getvalue())['html_sha256'], sha(self.output.read_bytes()))


class OriginalComposeComparisonTests(unittest.TestCase):
    def test_saved_compose_two_rate_original_pcm_is_not_modified(self):
        root = Path(__file__).resolve().parents[2]
        if not (root / 'zaaggenz_runtime' / 'nyquismic_audition_sweep.py').is_file():
            self.skipTest('local isolated source tree does not contain the Compose renderer')
        from test_nyquismic_compose_delivery import source_document
        from zaaggenz_runtime.nyquismic_audition_sweep import export_saved_compose_rate_sweep
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            project = folder / 'song.zgtimeline.json'
            project.write_text(json.dumps(source_document()), encoding='utf-8')
            sweep = folder / 'rates.zip'
            export_saved_compose_rate_sweep(project, sweep, virtual_rates_hz=['4/1', '5/1'])
            result = compare.publish_rate_comparison(sweep, folder / 'compare.html')
            source = compare._verified_sweep(sweep)
            html = (folder / 'compare.html').read_text()
            payload = json.loads(re.search(
                r'<script id="nyq-compare-payload" type="application/json">(.*?)</script>',
                html, re.S).group(1))
            assert result['frames'] == 28800 and result['delivery_hz'] == 48000
            self.assertEqual(base64.b64decode(payload['wavs'][0]), source['dry'])
            for index, record in enumerate(source['variants'], 1):
                self.assertEqual(base64.b64decode(payload['wavs'][index]), record['wet'])
            self.assertNotEqual(source['variants'][0]['wet_pcm_sha256'],
                                source['variants'][1]['wet_pcm_sha256'])
            print('NYQ_MULTI_RATE_COMPOSE_NUMERICS ' + json.dumps({
                'frames': result['frames'], 'delivery_hz': result['delivery_hz'],
                'dry_wav_sha256': sha(source['dry']),
                'wet_pcm_sha256_by_rate': [v['wet_pcm_sha256'] for v in source['variants']],
                'html_sha256': result['html_sha256']}, sort_keys=True))


if __name__ == '__main__':
    unittest.main(verbosity=2)
