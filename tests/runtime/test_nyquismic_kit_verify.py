"""Cold-reopened Nyquismic kit verification and adversarial integrity tests."""
import base64
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

import numpy as np
from scipy.io import wavfile
from zaaggenz_runtime import nyquismic_kit_verify as verify


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def wave(samples, rate=48000):
    stream = io.BytesIO()
    wavfile.write(stream, rate, np.asarray(samples, dtype=np.float32))
    return stream.getvalue()


class KitVerifyTests(unittest.TestCase):
    def setUp(self):
        ctx = tempfile.TemporaryDirectory()
        self.addCleanup(ctx.cleanup)
        self.root = Path(ctx.name)
        self.project = self.root / 'song.zgtimeline.json'
        self.project.write_bytes(b'{"project":true}')
        self.path = self.root / 'kit.zip'
        self.rates = ['4/1', '5/1']
        self.audio = [wave(np.array([0.5, -0.5, 0, 0.25], dtype=np.float32)),
                      wave(np.array([-0.5, 0.25, 0, 0.5], dtype=np.float32)),
                      wave(np.array([0.5, 0, 0.25, -0.5], dtype=np.float32))]
        self.anchor = {'project_file_sha256': sha(self.project.read_bytes()),
                       'source_asset_sha256': '1'*64, 'source_revision_sha256':'2'*64,
                       'compose_recipe_sha256':'3'*64,
                       'dry_pcm_f32le_sha256':sha(np.array([0.5,-0.5,0,0.25],dtype='<f4').tobytes()),
                       'frames':4,'channels':1}
        self.sweep = '4'*64
        self.packet = ['5'*64, '6'*64]
        self.names = ['original.wav','nyq-rate-01.wav','nyq-rate-02.wav']
        self.tracks = []
        for i, wav in enumerate(self.audio):
            _, pcm = wavfile.read(io.BytesIO(wav))
            self.tracks.append({'file':self.names[i], 'wav_sha256':sha(wav),
                                'pcm_f32le_sha256':sha(np.asarray(pcm,dtype='<f4').tobytes()),
                                'virtual_rate_hz':self.rates[i-1] if i else None,
                                'packet_sha256':self.packet[i-1] if i else None})
        self.receipt = {'format':verify.LISTENER_FORMAT,'source':self.anchor,
                        'archive_sha256':self.sweep,
                        'dry_wav_sha256':sha(self.audio[0]),
                        'rates':[{'rate':self.rates[i-1],'packet_sha256':self.packet[i-1],
                                  'wet_pcm_sha256':self.tracks[i]['pcm_f32le_sha256'],
                                  'wet_wav_sha256':self.tracks[i]['wav_sha256']} for i in (1,2)]}
        self.payload = {'format':verify.LISTENER_FORMAT,'frames':4,'channels':1,
                        'wavs':[base64.b64encode(x).decode() for x in self.audio],
                        'receipt':self.receipt}
        self.manifest = {'format':verify.FORMAT,'source':self.anchor,
                         'source_sweep_sha256':self.sweep,
                         'project_file_sha256':self.anchor['project_file_sha256'],
                         'evaluation_rate_hz':192000,'sample_rate_hz':48000,
                         'frames':4,'channels':1,'tracks':self.tracks}
        self.write()

    def write(self, compress=zipfile.ZIP_STORED, extra=None):
        page = b'<html><script id="nyq-compare-payload" type="application/json">' + json.dumps(self.payload).encode() + b'</script></html>'
        self.manifest['listen_html_sha256'] = sha(page)
        with zipfile.ZipFile(self.path,'w',compression=compress) as z:
            z.writestr('manifest.json',json.dumps(self.manifest))
            z.writestr('listen.html',page)
            for name, data in zip(self.names,self.audio):
                z.writestr(name,data)
            if extra is not None:
                z.writestr(extra,b'foreign')

    def test_cold_reopen_original_project_and_trusted_sha(self):
        expected = sha(self.path.read_bytes())
        self.assertEqual(verify.verify_production_kit(self.path)['virtual_rates_hz'],self.rates)
        result = verify.verify_production_kit(self.path,project_path=self.project,expected_zip_sha256=expected)
        self.assertEqual(result['tracks'][2]['wav_sha256'],sha(self.audio[2]))
        self.assertTrue(result['trusted_zip_sha_checked'])
        self.assertTrue(result['original_project_checked'])

    def test_changed_external_saved_project_and_expected_hash(self):
        with self.assertRaisesRegex(ValueError,'trusted ZIP'):
            verify.verify_production_kit(self.path, expected_zip_sha256='0'*64)
        self.project.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'supplied saved Compose'):
            verify.verify_production_kit(self.path, project_path=self.project)

    def test_damaged_wav_bytes_cannot_pass(self):
        self.audio[1] = wave([0.25,0.5,0,-0.5])
        self.write()
        with self.assertRaisesRegex(ValueError,'WAV byte identity'):
            verify.verify_production_kit(self.path)

    def test_manipulated_pcm_digest_is_detected(self):
        self.tracks[1]['pcm_f32le_sha256'] = '0'*64
        self.write()
        with self.assertRaisesRegex(ValueError,'decoded PCM identity'):
            verify.verify_production_kit(self.path)

    def test_foreign_clock_packet_and_noncanonical_rate_fail(self):
        self.packet[0] = 'f'*64
        self.tracks[1]['packet_sha256'] = 'f'*64
        self.write()
        with self.assertRaisesRegex(ValueError,'listener rate/PCM/packet'):
            verify.verify_production_kit(self.path)
        self.tracks[1]['packet_sha256'] = '5'*64
        self.tracks[1]['virtual_rate_hz'] = '8/2'
        self.write()
        with self.assertRaisesRegex(ValueError,'noncanonical'):
            verify.verify_production_kit(self.path)

    def test_listener_wav_mismatch_not_hidden_by_new_html_hash(self):
        self.payload['wavs'][2] = base64.b64encode(self.audio[0]).decode()
        self.write()
        with self.assertRaisesRegex(ValueError,'listener WAV differs'):
            verify.verify_production_kit(self.path)

    def test_changed_listener_source_receipt_is_rejected(self):
        self.receipt['source'] = {**self.anchor,'source_revision_sha256':'f'*64}
        self.write()
        with self.assertRaisesRegex(ValueError,'listening receipt'):
            verify.verify_production_kit(self.path)

    def test_wrong_sample_format_and_clock_are_detected(self):
        # An otherwise internally rehashed wrong-rate WAV is not acceptable.
        self.audio[2] = wave([0.5,0,0.25,-0.5], rate=44100)
        self.tracks[2]['wav_sha256'] = sha(self.audio[2])
        self.write()
        with self.assertRaisesRegex(ValueError,'48-kHz'):
            verify.verify_production_kit(self.path)

    def test_extra_archive_member_and_deflate_rejected(self):
        self.write(extra='../../unsafe')
        with self.assertRaisesRegex(ValueError,'ZIP structure'):
            verify.verify_production_kit(self.path)
        self.write(compress=zipfile.ZIP_DEFLATED)
        with self.assertRaisesRegex(ValueError,'ZIP structure'):
            verify.verify_production_kit(self.path)

    def test_cancellation_and_invalid_callbacks(self):
        with self.assertRaisesRegex(RuntimeError,'cancelled'):
            verify.verify_production_kit(self.path,cancelled=lambda:True)
        with self.assertRaises(ValueError):
            verify.verify_production_kit(self.path,cancelled=4)
        with self.assertRaises(ValueError):
            verify.verify_production_kit(self.path,expected_zip_sha256='123')


if __name__ == '__main__':
    unittest.main()
