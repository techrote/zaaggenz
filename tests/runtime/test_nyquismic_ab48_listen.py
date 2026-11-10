"""Adversarial source and file-publication checks for the opt-in NYQ A/B player."""
import base64
import contextlib
import hashlib
import io
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import numpy as np
from scipy.io import wavfile

from zaaggenz_runtime import nyquismic_offline_ab48 as ab
from zaaggenz_runtime import nyquismic_ab48_listen as listen
from test_nyquismic_compose_delivery import source_document


class LocalAuditionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base_temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.base_temp.name)
        cls.project = cls.root / "song.zgtimeline.json"
        cls.project.write_text(json.dumps(source_document()), encoding="utf-8")
        cls.bundle = cls.root / "original-ab.zip"
        cls.original = ab.export_saved_compose_ab48(
            cls.project, cls.bundle, virtual_rate_hz="4/1")

    @classmethod
    def tearDownClass(cls):
        cls.base_temp.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.output = self.work / "audition.html"

    def build(self, path=None, **kwargs):
        return listen.publish_ab48_audition(
            self.bundle if path is None else path, self.output, **kwargs)

    def altered(self, *, mutate_manifest=None, replace=None, extra=None):
        path = self.work / "modified.zip"
        with zipfile.ZipFile(self.bundle) as source:
            items = {name: source.read(name) for name in listen.NAMES}
        if mutate_manifest:
            manifest = json.loads(items["manifest.json"])
            mutate_manifest(manifest)
            items["manifest.json"] = json.dumps(manifest, sort_keys=True).encode()
        if replace:
            items.update(replace)
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as target:
            for name in listen.NAMES:
                target.writestr(name, items[name])
            if extra:
                target.writestr("unexpected.json", b"{}")
        return path

    def test_real_compose_pair_is_embedded_exactly_without_audio_mutation(self):
        receipt = self.build()
        html = self.output.read_text(encoding="utf-8")
        match = re.search(r'<script id="nyq-payload" type="application/json">(.*?)</script>',
                          html, re.DOTALL)
        self.assertIsNotNone(match)
        payload = json.loads(match.group(1))
        with zipfile.ZipFile(self.bundle) as source:
            for key, filename in (("dry", "compose-dry.wav"),
                                  ("wet", "compose-nyquismic.wav")):
                self.assertEqual(base64.b64decode(payload[key]), source.read(filename))
        self.assertEqual(payload["manifest"], self.original["manifest"])
        self.assertEqual(payload["frames"], 28800)
        self.assertIn('document.getElementById("nyq-payload")', html)
        self.assertIn('context.createBufferSource()', html)
        self.assertIn('source.start(context.currentTime, offset)', html)
        self.assertIn('g.linearRampToValueAtTime', html)
        self.assertIn("connect-src 'none'", html)
        self.assertEqual(receipt["html_sha256"],
                         hashlib.sha256(self.output.read_bytes()).hexdigest())
        self.assertEqual(receipt["source_zip_sha256"],
                         hashlib.sha256(self.bundle.read_bytes()).hexdigest())
        self.assertEqual(receipt["source_asset_sha256"],
                         self.original["manifest"]["source_asset_sha256"])
        self.assertEqual(sorted(self.work.iterdir()), [self.output])
        print("NYQ_AB48_LISTEN_ORIGINAL_NUMERICS " + json.dumps({
            "frames": receipt["frames"], "channels": receipt["channels"],
            "rate_hz": receipt["delivery_hz"],
            "source_bundle_sha256": receipt["source_zip_sha256"],
            "dry_pcm_sha256": payload["manifest"]["dry"]["pcm_f32le_sha256"],
            "wet_pcm_sha256": payload["manifest"]["wet"]["pcm_f32le_sha256"],
            "html_sha256": receipt["html_sha256"],
        }, sort_keys=True))

    def test_existing_html_is_never_overwritten_or_reparsed(self):
        self.output.write_bytes(b"existing user file")
        with patch.object(listen, "_read_verified_bundle",
                          side_effect=AssertionError("must not read bundle")):
            with self.assertRaises(FileExistsError):
                self.build()
        self.assertEqual(self.output.read_bytes(), b"existing user file")

    def test_original_wav_modified_without_manifest_receipt_is_rejected(self):
        with zipfile.ZipFile(self.bundle) as source:
            dry = bytearray(source.read("compose-dry.wav"))
        dry[-1] ^= 1
        altered = self.altered(replace={"compose-dry.wav": bytes(dry)})
        with self.assertRaisesRegex(ValueError, "SHA"):
            self.build(altered)
        self.assertFalse(self.output.exists())

    def test_manifest_pcm_mismatch_is_rejected_even_when_wav_hash_matches(self):
        path = self.altered(mutate_manifest=lambda m:
                            m["wet"].__setitem__("pcm_f32le_sha256", "0" * 64))
        with self.assertRaisesRegex(ValueError, "decoded PCM"):
            self.build(path)
        self.assertFalse(self.output.exists())

    def test_integer_pcm_with_matching_manufactured_hashes_is_rejected(self):
        with zipfile.ZipFile(self.bundle) as source:
            dry = source.read("compose-dry.wav")
            manifest = json.loads(source.read("manifest.json"))
        rate, float_pcm = wavfile.read(io.BytesIO(dry))
        self.assertEqual(rate, 48000)
        pcm = np.zeros_like(float_pcm, dtype=np.int16)
        target = io.BytesIO()
        wavfile.write(target, 48000, pcm)
        int_wav = target.getvalue()
        def substitute(m):
            m["dry"]["wav_sha256"] = hashlib.sha256(int_wav).hexdigest()
            m["dry"]["pcm_f32le_sha256"] = hashlib.sha256(
                pcm.astype("<f4").tobytes()).hexdigest()
        path = self.altered(mutate_manifest=substitute,
                            replace={"compose-dry.wav": int_wav})
        with self.assertRaisesRegex(ValueError, "float32"):
            self.build(path)
        self.assertFalse(self.output.exists())

    def test_unexpected_entry_is_rejected_before_output(self):
        with self.assertRaisesRegex(ValueError, "entries"):
            self.build(self.altered(extra=True))
        self.assertFalse(self.output.exists())

    def test_cancel_after_staging_sync_leaves_no_partial_file(self):
        original = listen.os.fsync
        cancelled = [False]
        def cancel_after_sync(fd):
            original(fd)
            cancelled[0] = True
        with patch.object(listen.os, "fsync", side_effect=cancel_after_sync):
            with self.assertRaisesRegex(RuntimeError, "cancelled"):
                self.build(cancelled=lambda: cancelled[0])
        self.assertEqual(list(self.work.iterdir()), [])

    def test_competing_writer_is_never_clobbered(self):
        def competing_link(source, destination):
            Path(destination).write_bytes(b"won by another process")
            raise FileExistsError(str(destination))
        with patch.object(listen.os, "link", side_effect=competing_link):
            with self.assertRaises(FileExistsError):
                self.build()
        self.assertEqual(self.output.read_bytes(), b"won by another process")
        self.assertEqual(sorted(self.work.iterdir()), [self.output])

    def test_malicious_manifest_text_cannot_escape_json_script(self):
        attack = '</script><script>alert("external")</script>'
        def inject(m):
            m["source_asset_sha256"] = attack
        self.build(self.altered(mutate_manifest=inject))
        html = self.output.read_text()
        self.assertNotIn(attack, html)
        self.assertIn("\\u003c/script", html)
        self.assertEqual(html.count('<script'), 2)

    def test_cli_emits_receipt_for_unchanged_audio(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = listen.main(["--bundle", str(self.bundle), "--output",
                                str(self.output)])
        self.assertEqual(code, 0)
        receipt = json.loads(output.getvalue())
        self.assertEqual(receipt["html_sha256"],
                         hashlib.sha256(self.output.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main(verbosity=2)
