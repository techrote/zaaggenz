"""Original PCM alignment and adversarial A/B preview publication tests."""
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

import numpy as np
from scipy.io import wavfile
from zaaggenz_runtime import nyquismic_ab_bounce as ab


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def wave(samples):
    buf = io.BytesIO()
    wavfile.write(buf, 48000, np.asarray(samples, dtype=np.float32))
    return buf.getvalue()


class AuditionBounceTests(unittest.TestCase):
    def setUp(self):
        ctx = tempfile.TemporaryDirectory()
        self.addCleanup(ctx.cleanup)
        self.root = Path(ctx.name)
        self.project = self.root / "song.zgtimeline.json"
        self.project.write_bytes(b'{"valid-saved-compose":true}')
        self.kit = self.root / "kit.zip"
        self.dest = self.root / "audition.wav"
        self.dry = np.full(14400, .25, dtype=np.float32)
        self.wet = np.full(14400, .75, dtype=np.float32)
        self.other = np.full(14400, -.75, dtype=np.float32)
        self._kit()

    def _kit(self):
        self.bytes = [wave(x) for x in (self.dry, self.wet, self.other)]
        with zipfile.ZipFile(self.kit, "w", compression=zipfile.ZIP_STORED) as z:
            for name, data in zip(("original.wav", "nyq-rate-01.wav", "nyq-rate-02.wav"), self.bytes):
                z.writestr(name, data)
        self.receipt = {
            "zip_sha256": sha(self.kit.read_bytes()),
            "virtual_rates_hz": ["4/1", "5/1"],
            "frames": len(self.dry),
            "channels": 1 if self.dry.ndim == 1 else self.dry.shape[1],
            "tracks": [{"wav_sha256": sha(v)} for v in self.bytes],
            "source_project_sha256": sha(self.project.read_bytes()),
            "trusted_zip_sha_checked": False,
            "original_project_checked": True,
        }

    def render(self, **overrides):
        kw = dict(virtual_rate_hz="4/1", period_ms="100", crossfade_ms="10", project_path=self.project)
        kw.update(overrides)
        with mock.patch.object(ab, "verify_production_kit", return_value=self.receipt):
            return ab.bounce_ab_preview(self.kit, self.dest, **kw)

    def test_real_pcm_segment_alignment_envelope_and_receipt(self):
        info = self.render()
        rate, output = wavfile.read(self.dest)
        self.assertEqual(rate, 48000)
        self.assertEqual(output.dtype, np.float32)
        self.assertEqual(info["period_frames"], 4800)
        self.assertEqual(info["crossfade_frames"], 480)
        self.assertEqual(info["virtual_rate_hz"], "4/1")
        self.assertEqual(info["wav_sha256"], sha(self.dest.read_bytes()))
        self.assertEqual(info["pcm_f32le_sha256"], sha(output.astype("<f4").tobytes()))
        np.testing.assert_array_equal(output[:4800], self.dry[:4800])
        self.assertEqual(float(output[4800]), .25)
        self.assertEqual(float(output[5279]), .75)
        np.testing.assert_array_equal(output[5280:9600], self.wet[5280:9600])
        self.assertEqual(float(output[9600]), .75)
        self.assertEqual(float(output[10079]), .25)
        np.testing.assert_array_equal(output[10080:], self.dry[10080:])
        self.assertTrue(np.all(np.diff(output[4800:5280]) >= -1e-7))
        self.assertTrue(np.all(np.diff(output[9600:10080]) <= 1e-7))

    def test_stereo_identical_sources_are_pcm_identical(self):
        self.dry = np.stack([np.linspace(-.9, .9, 14400), np.linspace(.8, -.8, 14400)], axis=1).astype(np.float32)
        self.wet = self.dry.copy()
        self.other = -self.dry
        self._kit()
        result = self.render()
        _, actual = wavfile.read(self.dest)
        np.testing.assert_array_equal(actual, self.dry)
        self.assertEqual(result["channels"], 2)

    def test_other_rate_is_source_bound(self):
        result = self.render(virtual_rate_hz="5/1")
        _, output = wavfile.read(self.dest)
        self.assertEqual(result["wet_wav_sha256"], sha(self.bytes[2]))
        self.assertEqual(float(output[6000]), -.75)

    def test_invalid_rate_duration_and_existing_destination(self):
        for bad in ("7/1", "4/2", 4, ""):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "exactly match"):
                self.render(virtual_rate_hz=bad)
        for period, fade in (("nan", "12"), ("30", "12"), ("100", "100"), ("100", "0")):
            with self.subTest(period=period, fade=fade), self.assertRaises(ValueError):
                self.render(period_ms=period, crossfade_ms=fade)
        self.dest.write_bytes(b"independent-file")
        with self.assertRaises(FileExistsError):
            self.render()
        self.assertEqual(self.dest.read_bytes(), b"independent-file")

    def test_changed_kit_snapshot_is_rejected_before_commit(self):
        with mock.patch.object(ab, "verify_production_kit", side_effect=lambda *a, **k: (
                self.kit.write_bytes(b"mutated"), self.receipt)[1]):
            with self.assertRaisesRegex(RuntimeError, "changed after verification"):
                ab.bounce_ab_preview(self.kit, self.dest, virtual_rate_hz="4/1")
        self.assertFalse(self.dest.exists())

    def test_cancelled_before_render_is_inert(self):
        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            self.render(cancelled=lambda: True)
        self.assertFalse(self.dest.exists())

    def test_late_cancel_after_hardlink_rolls_back_only_own_output(self):
        pending = {"cancel": False}
        real = os.link
        def late(source, dest):
            real(source, dest)
            pending["cancel"] = True
        with mock.patch.object(ab.os, "link", side_effect=late):
            with self.assertRaisesRegex(RuntimeError, "cancelled"):
                self.render(cancelled=lambda: pending["cancel"])
        self.assertFalse(self.dest.exists())

    def test_late_project_edit_and_kit_change_roll_back(self):
        real = os.link
        def change_project(source, dest):
            real(source, dest)
            self.project.write_bytes(b"edited while publishing")
        with mock.patch.object(ab.os, "link", side_effect=change_project):
            with self.assertRaisesRegex(RuntimeError, "project changed"):
                self.render()
        self.assertFalse(self.dest.exists())
        self.project.write_bytes(b'{"valid-saved-compose":true}')
        self._kit()
        def change_kit(source, dest):
            real(source, dest)
            self.kit.write_bytes(b"changed after publication")
        with mock.patch.object(ab.os, "link", side_effect=change_kit):
            with self.assertRaisesRegex(RuntimeError, "source kit changed"):
                self.render()
        self.assertFalse(self.dest.exists())

    def test_competing_writer_race_cannot_be_overwritten(self):
        def competitor(source, dest):
            Path(dest).write_bytes(b"competing-writer")
            raise FileExistsError(dest)
        with mock.patch.object(ab.os, "link", side_effect=competitor):
            with self.assertRaises(FileExistsError):
                self.render()
        self.assertEqual(self.dest.read_bytes(), b"competing-writer")

    def test_deterministic_preview_pcm_and_output_sha(self):
        first = self.render()
        original = self.dest.read_bytes()
        self.dest.unlink()
        again = self.render()
        self.assertEqual(first["wav_sha256"], again["wav_sha256"])
        self.assertEqual(original, self.dest.read_bytes())


class OriginalSavedComposePreview(unittest.TestCase):
    def test_full_real_compose_kit_to_alternating_wav(self):
        root = Path(__file__).resolve().parents[2]
        if not (root / "zaaggenz_runtime" / "nyquismic_offline_audition.py").is_file():
            self.skipTest("full original-host NYQ Compose producer required")
        from zaaggenz_runtime import nyquismic_production_kit as kit_producer
        from test_nyquismic_compose_delivery import source_document
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder) / "song.zgtimeline.json"
            project.write_text(json.dumps(source_document()), encoding="utf-8")
            kit_path = Path(folder) / "kit.zip"
            kit_receipt = kit_producer.export_saved_compose_kit(
                project, kit_path, virtual_rates_hz=["4/1", "5/1"])
            output_path = Path(folder) / "ab.wav"
            receipt = ab.bounce_ab_preview(
                kit_path, output_path, virtual_rate_hz="4/1",
                period_ms="150", crossfade_ms="12", project_path=project,
                expected_zip_sha256=kit_receipt["zip_sha256"])
            self.assertTrue(receipt["trusted_kit_checked"])
            self.assertTrue(receipt["source_project_checked"])
            self.assertEqual(receipt["frames"], 28800)
            self.assertEqual(receipt["delivery_hz"], 48000)
            with zipfile.ZipFile(kit_path) as z:
                _, dry = wavfile.read(io.BytesIO(z.read("original.wav")))
                _, wet = wavfile.read(io.BytesIO(z.read("nyq-rate-01.wav")))
            rate, bounced = wavfile.read(output_path)
            self.assertEqual(rate, 48000)
            np.testing.assert_array_equal(bounced[:7200], dry[:7200])
            np.testing.assert_array_equal(bounced[7776:14400], wet[7776:14400])
            np.testing.assert_array_equal(bounced[14976:21600], dry[14976:21600])
            self.assertEqual(receipt["pcm_f32le_sha256"], sha(bounced.astype("<f4").tobytes()))
            print("NYQ_AB_BOUNCE_PCM " + json.dumps({
                "frames": len(bounced), "wav_sha256": receipt["wav_sha256"],
                "pcm_f32le_sha256": receipt["pcm_f32le_sha256"],
                "kit_sha256": receipt["kit_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
