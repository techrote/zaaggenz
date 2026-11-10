"""One-step saved-Compose NYQ A/B listening: source, PCM and failure-boundary proof."""
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

from zaaggenz_runtime import nyquismic_offline_audition as direct
from zaaggenz_runtime import nyquismic_offline_ab48 as ab
from zaaggenz_runtime import nyquismic_ab48_listen as listen
from test_nyquismic_compose_delivery import source_document


class DirectAuditionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "song.zgtimeline.json"
        self.project.write_text(json.dumps(source_document()), encoding="utf-8")
        self.output = self.root / "song-ab.html"

    def export(self, output=None, **kwargs):
        return direct.export_saved_compose_audition(
            self.project, output or self.output,
            virtual_rate_hz="4/1", **kwargs)

    def payload(self, output=None):
        html = (output or self.output).read_text(encoding="utf-8")
        match = re.search(
            r'<script id="nyq-payload" type="application/json">(.*?)</script>',
            html, re.DOTALL)
        self.assertIsNotNone(match)
        return json.loads(match.group(1))

    def assert_clean(self):
        self.assertEqual(sorted(self.root.iterdir()), [self.project])

    def test_real_compose_single_command_produces_only_verified_audible_page(self):
        receipt = self.export()
        self.assertEqual(sorted(self.root.iterdir()),
                         [self.project, self.output])
        self.assertEqual(receipt["html_sha256"],
                         hashlib.sha256(self.output.read_bytes()).hexdigest())
        self.assertEqual(receipt["source_zip_sha256"],
                         receipt["source_bundle_sha256"])
        self.assertEqual(receipt["project_file_sha256"],
                         hashlib.sha256(self.project.read_bytes()).hexdigest())
        payload = self.payload()
        manifest = payload["manifest"]
        self.assertEqual((receipt["frames"], receipt["delivery_hz"]), (28800, 48000))
        self.assertEqual(manifest["source_revision_sha256"],
                         receipt["source_revision_sha256"])
        self.assertEqual(manifest["compose_recipe_sha256"],
                         receipt["compose_recipe_sha256"])
        self.assertEqual(manifest["packet_sha256"], receipt["packet_sha256"])
        self.assertEqual(manifest["sample_rate_hz"], 48000)
        pcm = []
        for key in ("dry", "wet"):
            wav = base64.b64decode(payload[key], validate=True)
            self.assertEqual(hashlib.sha256(wav).hexdigest(),
                             manifest[key]["wav_sha256"])
            rate, decoded = wavfile.read(io.BytesIO(wav))
            self.assertEqual(rate, 48000)
            self.assertEqual(decoded.dtype, np.dtype("float32"))
            self.assertEqual(decoded.shape[0], 28800)
            self.assertTrue(np.isfinite(decoded).all())
            self.assertEqual(hashlib.sha256(
                np.asarray(decoded, dtype="<f4").tobytes(order="C")
            ).hexdigest(), manifest[key]["pcm_f32le_sha256"])
            pcm.append(decoded)
        self.assertFalse(np.array_equal(pcm[0], pcm[1]))
        self.assertGreater(float(np.max(np.abs(pcm[0]))), 0.)
        self.assertIn('source.start(when, offset)', self.output.read_text())
        print("NYQ_DIRECT_AUDITION_NUMERICS " + json.dumps({
            "project_sha256": receipt["project_file_sha256"],
            "source_revision_sha256": receipt["source_revision_sha256"],
            "packet_sha256": receipt["packet_sha256"],
            "dry_pcm_sha256": receipt["dry_pcm_f32le_sha256"],
            "wet_pcm_sha256": receipt["wet_pcm_f32le_sha256"],
            "page_sha256": receipt["html_sha256"],
            "frames": receipt["frames"], "rate_hz": receipt["delivery_hz"],
        }, sort_keys=True))

    def test_cold_saved_project_reopen_is_byte_exact_on_same_host(self):
        first = self.export()
        second_path = self.root / "second.html"
        second = self.export(second_path)
        self.assertEqual(first["html_sha256"], second["html_sha256"])
        self.assertEqual(first["source_bundle_sha256"],
                         second["source_bundle_sha256"])
        self.assertEqual(self.output.read_bytes(), second_path.read_bytes())

    def test_existing_destination_is_preserved_without_render(self):
        self.output.write_bytes(b"original owner HTML")
        with patch.object(direct, "export_saved_compose_ab48",
                          side_effect=AssertionError("render must not start")):
            with self.assertRaises(FileExistsError):
                self.export()
        self.assertEqual(self.output.read_bytes(), b"original owner HTML")
        self.assertEqual(sorted(self.root.iterdir()), [self.project, self.output])

    def test_invalid_destination_and_bad_project_never_publish(self):
        with self.assertRaises(ValueError):
            self.export(self.root / "wrong.zip")
        broken = self.root / "invalid.zgtimeline.json"
        broken.write_text('{"format":"wrong"}', encoding="utf-8")
        with self.assertRaises(Exception):
            direct.export_saved_compose_audition(
                broken, self.output, virtual_rate_hz="4/1")
        self.assertFalse(self.output.exists())
        self.assertEqual(sorted(self.root.iterdir()), [broken, self.project])

    def test_cancelled_after_source_export_leaves_no_html_or_working_zip(self):
        actual = direct.export_saved_compose_ab48
        cancelled = [False]
        def complete_then_cancel(*args, **kwargs):
            receipt = actual(*args, **kwargs)
            cancelled[0] = True
            return receipt
        with patch.object(direct, "export_saved_compose_ab48",
                          side_effect=complete_then_cancel):
            with self.assertRaisesRegex(RuntimeError, "cancelled"):
                self.export(cancelled=lambda: cancelled[0])
        self.assert_clean()

    def test_modified_intermediate_zip_fails_before_html_publication(self):
        actual = direct.export_saved_compose_ab48
        def mutate_after_export(project, staged, **kwargs):
            receipt = actual(project, staged, **kwargs)
            with Path(staged).open("ab") as out:
                out.write(b"unexpected byte")
            return receipt
        with patch.object(direct, "export_saved_compose_ab48",
                          side_effect=mutate_after_export):
            with self.assertRaisesRegex(RuntimeError, "identity changed"):
                self.export()
        self.assert_clean()

    def test_final_html_fsync_cancellation_cleans_both_stages(self):
        actual_publish = direct.publish_ab48_audition
        real_sync = listen.os.fsync
        cancelled = [False]
        def publish_with_cancel(*args, **kwargs):
            def cancel_after_sync(fd):
                real_sync(fd)
                cancelled[0] = True
            with patch.object(listen.os, "fsync", side_effect=cancel_after_sync):
                return actual_publish(*args, **kwargs)
        with patch.object(direct, "publish_ab48_audition",
                          side_effect=publish_with_cancel):
            with self.assertRaisesRegex(RuntimeError, "cancelled"):
                self.export(cancelled=lambda: cancelled[0])
        self.assert_clean()

    def test_competing_html_writer_is_never_overwritten(self):
        actual_publish = direct.publish_ab48_audition
        def publish_with_competitor(*args, **kwargs):
            def external_wins(_stage, destination):
                Path(destination).write_bytes(b"winner")
                raise FileExistsError(str(destination))
            with patch.object(listen.os, "link", side_effect=external_wins):
                return actual_publish(*args, **kwargs)
        with patch.object(direct, "publish_ab48_audition",
                          side_effect=publish_with_competitor):
            with self.assertRaises(FileExistsError):
                self.export()
        self.assertEqual(self.output.read_bytes(), b"winner")
        self.assertEqual(sorted(self.root.iterdir()), [self.project, self.output])

    def test_cli_one_command_returns_verifiable_receipt(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = direct.main([
                "--project", str(self.project), "--output", str(self.output),
                "--virtual-hz", "4/1"])
        self.assertEqual(code, 0)
        receipt = json.loads(buf.getvalue())
        self.assertEqual(receipt["html_sha256"],
                         hashlib.sha256(self.output.read_bytes()).hexdigest())
        self.assertEqual(receipt["dry_pcm_f32le_sha256"],
                         self.payload()["manifest"]["dry"]["pcm_f32le_sha256"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
