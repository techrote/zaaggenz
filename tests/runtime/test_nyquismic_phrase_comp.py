"""Adversarial, numerical and real Compose tests for the offline NYQ phrase comp."""
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

from zaaggenz_runtime import nyquismic_phrase_comp as comp


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def wav(samples):
    buffer = io.BytesIO()
    wavfile.write(buffer, 48000, np.asarray(samples, dtype=np.float32))
    return buffer.getvalue()


def pcm_hash(samples):
    return sha(np.asarray(samples, dtype="<f4").tobytes(order="C"))


class PhraseCompTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root / "song.zgtimeline.json"
        self.project.write_bytes(b'{"saved":"compose"}')
        self.kit = self.root / "listen.zip"
        self.dest = self.root / "arranged.wav"
        self.dry = np.full(12000, .25, dtype=np.float32)
        self.rate4 = np.full(12000, .75, dtype=np.float32)
        self.rate5 = np.full(12000, -.5, dtype=np.float32)
        self.rebuild()

    def rebuild(self):
        tracks = [self.dry, self.rate4, self.rate5]
        self.wavs = [wav(track) for track in tracks]
        with zipfile.ZipFile(self.kit, "w", compression=zipfile.ZIP_STORED) as archive:
            for name, data in zip(("original.wav", "nyq-rate-01.wav", "nyq-rate-02.wav"),
                                  self.wavs):
                archive.writestr(name, data)
        self.receipt = {
            "zip_sha256": sha(self.kit.read_bytes()),
            "virtual_rates_hz": ["4/1", "5/1"],
            "frames": len(self.dry),
            "channels": 1 if self.dry.ndim == 1 else self.dry.shape[1],
            "tracks": [{"wav_sha256": sha(data), "pcm_f32le_sha256": pcm_hash(track)}
                       for data, track in zip(self.wavs, tracks)],
            "source_project_sha256": sha(self.project.read_bytes()),
            "trusted_zip_sha_checked": True,
            "original_project_checked": True,
        }

    def render(self, **extra):
        options = {
            "cues": ["0=original", "60=4/1", "120=5/1", "180=original"],
            "crossfade_ms": "5",
            "project_path": self.project,
        }
        options.update(extra)
        with mock.patch.object(comp, "verify_production_kit", return_value=self.receipt):
            return comp.bounce_phrase_comp(self.kit, self.dest, **options)

    def test_multirate_segments_and_raised_cosine_endpoints(self):
        result = self.render()
        sample_rate, pcm = wavfile.read(self.dest)
        self.assertEqual(sample_rate, 48000)
        self.assertEqual(pcm.dtype, np.float32)
        self.assertEqual(result["crossfade_frames"], 240)
        self.assertEqual([x["frame"] for x in result["cues"]], [0, 2880, 5760, 8640])
        np.testing.assert_array_equal(pcm[:2881], self.dry[:2881])
        np.testing.assert_array_equal(pcm[3119:5761], self.rate4[3119:5761])
        np.testing.assert_array_equal(pcm[5999:8641], self.rate5[5999:8641])
        np.testing.assert_array_equal(pcm[8879:], self.dry[8879:])
        pos = 2880 + 100
        w = .5 - .5 * np.cos(np.pi * 100 / 239)
        self.assertEqual(pcm[pos], np.float32(.25 + (.75 - .25) * w))
        self.assertEqual(result["pcm_f32le_sha256"], pcm_hash(pcm))
        self.assertEqual(result["wav_sha256"], sha(self.dest.read_bytes()))
        self.assertEqual(result["source_wav_sha256"]["5/1"], sha(self.wavs[2]))
        self.assertTrue(result["trusted_kit_checked"])

    def test_unaltered_identity_stereo_and_signed_zero(self):
        self.dry = np.tile(np.array([[-0., .25], [.5, -.75]], np.float32), (6000, 1))
        self.rate4 = self.dry.copy()
        self.rate5 = self.dry.copy()
        self.rebuild()
        receipt = self.render()
        _, pcm = wavfile.read(self.dest)
        self.assertEqual(receipt["channels"], 2)
        self.assertEqual(pcm.tobytes(), self.dry.tobytes())

    def test_bounded_peak_not_normalized_or_limited(self):
        self.dry.fill(1.5)
        self.rate4.fill(1.25)
        self.rate5.fill(1.75)
        self.rebuild()
        receipt = self.render()
        _, pcm = wavfile.read(self.dest)
        self.assertTrue(receipt["exceeds_unity_peak"])
        self.assertEqual(receipt["peak_abs"], 1.75)
        self.assertEqual(pcm[4000], 1.25)
        self.assertEqual(pcm[7000], 1.75)

    def test_no_clobber_and_invalid_cue_or_fade(self):
        wrong = [
            [], ["0=original"], ["1=original", "50=4/1"],
            ["0=original", "0.000001=4/1"],
            ["0=original", "60=7/1"],
            ["0=original", "60=original"],
            ["0=original", "60=4/1", "62=5/1"],
            ["0=original", "249=4/1"],
            ["0=original", "250=4/1"],
            ["0=original", "nope"],
            ["0=original", "60=4/2"],
            ["0=original", "60.0000001=4/1"],
            ["0=original", "nan=4/1"],
            ["0=original", "60=4/1"] * 33,
        ]
        for cues in wrong:
            with self.subTest(cues=cues), self.assertRaises(ValueError):
                self.render(cues=cues)
            self.assertFalse(self.dest.exists())
        for fade in ("nan", "-1", "0", "1.99", "101", "2.0000001", "Inf"):
            with self.subTest(fade=fade), self.assertRaises(ValueError):
                self.render(crossfade_ms=fade)
        self.dest.write_bytes(b"competing output")
        with self.assertRaises(FileExistsError):
            self.render()
        self.assertEqual(self.dest.read_bytes(), b"competing output")

    def test_frame_quantization_and_repeated_source_rejection(self):
        valid = self.render(cues=["0.000000=original", "50.010416=4/1"],
                            crossfade_ms="2.5")
        self.assertEqual(valid["cues"][1]["frame"], 2400)
        self.assertEqual(valid["crossfade_frames"], 120)
        self.dest.unlink()
        with self.assertRaises(ValueError):
            self.render(cues=["0=original", "60=4/1", "60.0000001=5/1"])

    def test_source_changed_after_verifier_is_rejected(self):
        with mock.patch.object(comp, "verify_production_kit",
                side_effect=lambda *a, **kw: (self.kit.write_bytes(b"replaced"),
                                                self.receipt)[1]):
            with self.assertRaisesRegex(RuntimeError, "changed after verification"):
                comp.bounce_phrase_comp(self.kit, self.dest,
                                      cues=["0=original", "60=4/1"])
        self.assertFalse(self.dest.exists())

    def test_forged_selected_track_wav_and_pcm_rejected(self):
        self.receipt["tracks"][1]["wav_sha256"] = sha(b"foreign")
        with self.assertRaisesRegex(RuntimeError, "differs from verified"):
            self.render()
        self.assertFalse(self.dest.exists())
        self.rebuild()
        self.receipt["tracks"][1]["pcm_f32le_sha256"] = sha(b"foreign")
        with self.assertRaisesRegex(RuntimeError, "source-verified"):
            self.render()
        self.assertFalse(self.dest.exists())

    def test_preflight_cancellation(self):
        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            self.render(cancelled=lambda: True)
        self.assertFalse(self.dest.exists())

    def test_late_cancellation_rolls_back(self):
        cancel = {"value": False}
        link = os.link

        def cancel_after_link(source, dest):
            link(source, dest)
            cancel["value"] = True

        with mock.patch.object(comp.os, "link", side_effect=cancel_after_link):
            with self.assertRaisesRegex(RuntimeError, "cancelled"):
                self.render(cancelled=lambda: cancel["value"])
        self.assertFalse(self.dest.exists())

    def test_late_project_edit_rolls_back(self):
        link = os.link

        def mutate(source, dest):
            link(source, dest)
            self.project.write_bytes(b"modified")

        with mock.patch.object(comp.os, "link", side_effect=mutate):
            with self.assertRaisesRegex(RuntimeError, "project changed"):
                self.render()
        self.assertFalse(self.dest.exists())

    def test_late_source_kit_edit_rolls_back(self):
        link = os.link

        def mutate(source, dest):
            link(source, dest)
            self.kit.write_bytes(b"modified")

        with mock.patch.object(comp.os, "link", side_effect=mutate):
            with self.assertRaisesRegex(RuntimeError, "kit changed"):
                self.render()
        self.assertFalse(self.dest.exists())

    def test_competing_writer_is_not_unlinked(self):
        cancel = {"value": False}
        link = os.link

        def replace_after_link(source, dest):
            link(source, dest)
            Path(dest).unlink()
            Path(dest).write_bytes(b"other writer")
            cancel["value"] = True

        with mock.patch.object(comp.os, "link", side_effect=replace_after_link):
            with self.assertRaisesRegex(RuntimeError, "cancelled"):
                self.render(cancelled=lambda: cancel["value"])
        self.assertEqual(self.dest.read_bytes(), b"other writer")

    def test_competing_publish_never_overwritten(self):
        def competing(source, dest):
            Path(dest).write_bytes(b"other writer")
            raise FileExistsError(dest)

        with mock.patch.object(comp.os, "link", side_effect=competing):
            with self.assertRaises(FileExistsError):
                self.render()
        self.assertEqual(self.dest.read_bytes(), b"other writer")

    def test_deterministic_cold_reopen(self):
        first = self.render()
        original = self.dest.read_bytes()
        self.dest.unlink()
        second = self.render()
        self.assertEqual(first["pcm_f32le_sha256"], second["pcm_f32le_sha256"])
        self.assertEqual(original, self.dest.read_bytes())


class OriginalSavedComposePhraseComp(unittest.TestCase):
    def test_real_compose_kit_rate_sequence(self):
        root = Path(__file__).resolve().parents[2]
        if not (root / "zaaggenz_runtime" / "nyquismic_offline_audition.py").is_file():
            self.skipTest("original host must provide saved-Compose NYQ producer")
        from zaaggenz_runtime import nyquismic_production_kit
        from test_nyquismic_compose_delivery import source_document

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "song.zgtimeline.json"
            project.write_text(json.dumps(source_document()), encoding="utf-8")
            kit = Path(directory) / "listen.zip"
            kit_receipt = nyquismic_production_kit.export_saved_compose_kit(
                project, kit, virtual_rates_hz=["4/1", "5/1"])
            output = Path(directory) / "arranged.wav"
            receipt = comp.bounce_phrase_comp(
                kit, output,
                cues=["0=original", "150=4/1", "300=5/1", "450=original"],
                crossfade_ms="12", project_path=project,
                expected_zip_sha256=kit_receipt["zip_sha256"])
            self.assertEqual(receipt["frames"], 28800)
            self.assertEqual(receipt["delivery_hz"], 48000)
            self.assertEqual(receipt["crossfade_frames"], 576)
            self.assertTrue(receipt["trusted_kit_checked"])
            self.assertTrue(receipt["source_project_checked"])
            with zipfile.ZipFile(kit) as archive:
                source = []
                for name in ("original.wav", "nyq-rate-01.wav", "nyq-rate-02.wav"):
                    rate, samples = wavfile.read(io.BytesIO(archive.read(name)))
                    self.assertEqual(rate, 48000)
                    source.append(samples)
            rate, pcm = wavfile.read(output)
            self.assertEqual(rate, 48000)
            self.assertEqual(pcm.dtype, np.float32)
            self.assertEqual(len(pcm), 28800)
            np.testing.assert_array_equal(pcm[:7201], source[0][:7201])
            np.testing.assert_array_equal(pcm[7775:14401], source[1][7775:14401])
            np.testing.assert_array_equal(pcm[14975:21601], source[2][14975:21601])
            np.testing.assert_array_equal(pcm[22175:], source[0][22175:])
            self.assertEqual(receipt["pcm_f32le_sha256"], pcm_hash(pcm))
            self.assertEqual(receipt["wav_sha256"], sha(output.read_bytes()))
            print("NYQ_PHRASE_COMP_PCM " + json.dumps({
                "frames": len(pcm),
                "wav_sha256": receipt["wav_sha256"],
                "pcm_f32le_sha256": receipt["pcm_f32le_sha256"],
                "dry_wav_sha256": receipt["source_wav_sha256"]["original"],
                "rates": [receipt["source_wav_sha256"]["4/1"],
                          receipt["source_wav_sha256"]["5/1"]],
            }, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
