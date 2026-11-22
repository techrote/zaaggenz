"""Two independently selected NYQ virtual-rate takes into one authenticated stereo WAV."""
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
from zaaggenz_runtime import nyquismic_dual_rate_stereo as dual


def sha(data):
    return hashlib.sha256(data).hexdigest()


def wave(data):
    handle = io.BytesIO()
    wavfile.write(handle, 48000, np.asarray(data, np.float32))
    return handle.getvalue()


class DualRateStereoTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.kit = self.root / "kit.zip"
        self.dest = self.root / "dual.wav"
        self.project = self.root / "song.zgtimeline.json"
        self.project.write_bytes(b'{"saved":"compose"}')
        self.dry = np.tile(np.array([.25, -.125], np.float32), (12000, 1))
        self.a = np.tile(np.array([.75, .5], np.float32), (12000, 1))
        self.b = np.tile(np.array([-.5, .875], np.float32), (12000, 1))
        self.rebuild()

    def rebuild(self):
        tracks = [self.dry, self.a, self.b]
        self.wavs = [wave(t) for t in tracks]
        with zipfile.ZipFile(self.kit, "w", compression=zipfile.ZIP_STORED) as z:
            for name, raw in zip(("original.wav", "nyq-rate-01.wav", "nyq-rate-02.wav"), self.wavs):
                z.writestr(name, raw)
        self.receipt = {
            "zip_sha256": sha(self.kit.read_bytes()),
            "frames": len(self.dry), "channels": (1 if self.dry.ndim == 1 else 2),
            "virtual_rates_hz": ["4/1", "5/1"],
            "source_project_sha256": sha(self.project.read_bytes()),
            "tracks": [
                {"wav_sha256": sha(w), "pcm_f32le_sha256": sha(
                    np.asarray(t, dtype="<f4").tobytes())}
                for t, w in zip(tracks, self.wavs)],
            "trusted_zip_sha_checked": False, "original_project_checked": True,
        }

    def render(self, **opts):
        args = {
            "left_rate_hz": "4/1", "right_rate_hz": "5/1",
            "wet_percent": "100", "project_path": self.project,
        }
        args.update(opts)
        with mock.patch.object(dual, "verify_production_kit", return_value=self.receipt):
            return dual.bounce_dual_rate_stereo(self.kit, self.dest, **args)

    def read(self):
        rate, pcm = wavfile.read(self.dest)
        self.assertEqual(rate, 48000)
        self.assertEqual(pcm.dtype, np.float32)
        self.assertEqual(pcm.shape, (len(self.dry), 2))
        return pcm

    def test_distinct_stereo_rate_tracks_and_original_channel_mapping(self):
        r = self.render()
        pcm = self.read()
        np.testing.assert_array_equal(pcm[:, 0], self.a[:, 0])
        np.testing.assert_array_equal(pcm[:, 1], self.b[:, 1])
        self.assertEqual(r["left_rate_hz"], "4/1")
        self.assertEqual(r["right_rate_hz"], "5/1")
        self.assertEqual(r["pcm_f32le_sha256"], sha(pcm.astype("<f4").tobytes()))

    def test_swapping_rates_changes_channels_not_time(self):
        self.render(left_rate_hz="5/1", right_rate_hz="4/1")
        pcm = self.read()
        np.testing.assert_array_equal(pcm[:, 0], self.b[:, 0])
        np.testing.assert_array_equal(pcm[:, 1], self.a[:, 1])

    def test_mono_source_expands_to_true_two_rate_stereo(self):
        self.dry = np.full(12000, .1, np.float32)
        self.a = np.full(12000, .8, np.float32)
        self.b = np.full(12000, -.5, np.float32)
        self.rebuild()
        receipt = self.render()
        pcm = self.read()
        self.assertEqual(receipt["source_channels"], 1)
        self.assertEqual(receipt["channels"], 2)
        np.testing.assert_array_equal(pcm[:, 0], self.a)
        np.testing.assert_array_equal(pcm[:, 1], self.b)
        self.assertGreater(float(np.max(np.abs(pcm[:, 0] - pcm[:, 1]))), 1)

    def test_zero_wet_is_exact_dry_in_both_channels_including_signed_zero(self):
        self.dry[:, 0] = -0.0
        self.dry[:, 1] = 0.0
        self.rebuild()
        self.render(wet_percent="0")
        np.testing.assert_array_equal(self.read().view(np.uint32), self.dry.view(np.uint32))

    def test_partial_wet_linear_amplitude_without_normalization(self):
        receipt = self.render(wet_percent="37.5")
        pcm = self.read()
        expected = np.column_stack((
            self.dry[:, 0].astype(np.float64) + .375 * (
                self.a[:, 0].astype(np.float64) - self.dry[:, 0].astype(np.float64)),
            self.dry[:, 1].astype(np.float64) + .375 * (
                self.b[:, 1].astype(np.float64) - self.dry[:, 1].astype(np.float64)),
        )).astype(np.float32)
        np.testing.assert_array_equal(pcm, expected)
        self.assertEqual(receipt["wet_percent"], "37.5")

    def test_bit_identity_when_source_equals_wet_at_partial_mix(self):
        self.a[:, 0] = self.dry[:, 0]
        self.b[:, 1] = self.dry[:, 1]
        self.dry[0, 0] = -0.0
        self.a[0, 0] = -0.0
        self.rebuild()
        self.render(wet_percent="50")
        np.testing.assert_array_equal(self.read().view(np.uint32), self.dry.view(np.uint32))

    def test_unity_peak_is_reported_not_limited(self):
        self.a[:, 0] = np.float32(1.7)
        self.b[:, 1] = np.float32(-1.3)
        self.rebuild()
        r = self.render()
        self.assertTrue(r["exceeds_unity_peak"])
        self.assertGreater(r["peak_abs"], 1.6)
        self.assertGreater(float(np.max(np.abs(self.read()))), 1.6)

    def test_invalid_rates_percent_and_target_rejected(self):
        for choices in (
            {"left_rate_hz": "5/1", "right_rate_hz": "5/1"},
            {"left_rate_hz": "4", "right_rate_hz": "5/1"},
            {"left_rate_hz": "6/1", "right_rate_hz": "4/1"},
            {"wet_percent": "NaN"}, {"wet_percent": "Infinity"},
            {"wet_percent": "-0.1"}, {"wet_percent": "101"},
            {"wet_percent": "50.00001"}, {"wet_percent": None},
            {"cancelled": "not callable"},
        ):
            with self.subTest(choices=choices):
                with self.assertRaises((ValueError, TypeError)):
                    self.render(**choices)
                self.assertFalse(self.dest.exists())

    def test_no_overwrite_and_output_directory_preservation(self):
        self.dest.write_bytes(b"other writer")
        with self.assertRaises(ValueError):
            self.render()
        self.assertEqual(self.dest.read_bytes(), b"other writer")

    def test_forged_receipt_or_mutated_kit_rejected(self):
        self.receipt["tracks"][1]["pcm_f32le_sha256"] = "0" * 64
        with self.assertRaises(RuntimeError):
            self.render()
        self.assertFalse(self.dest.exists())
        self.rebuild()
        self.kit.write_bytes(self.kit.read_bytes() + b"x")
        with self.assertRaises(RuntimeError):
            self.render()
        self.assertFalse(self.dest.exists())

    def test_cancellation_before_publication(self):
        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            self.render(cancelled=lambda: True)
        self.assertFalse(self.dest.exists())

    def test_cancel_after_actual_link_rolls_back_own_file(self):
        original_link = os.link
        reached = {"value": False}
        def after_link(a, b):
            original_link(a, b)
            reached["value"] = True
        with mock.patch.object(dual.os, "link", side_effect=after_link):
            with self.assertRaisesRegex(RuntimeError, "cancelled"):
                self.render(cancelled=lambda: reached["value"])
        self.assertTrue(reached["value"])
        self.assertFalse(self.dest.exists())

    def test_project_mutation_after_link_rolls_back_own_file(self):
        original_link = os.link
        def after_link(a, b):
            original_link(a, b)
            self.project.write_bytes(b"changed project")
        with mock.patch.object(dual.os, "link", side_effect=after_link):
            with self.assertRaisesRegex(RuntimeError, "project changed"):
                self.render()
        self.assertFalse(self.dest.exists())

    def test_kit_mutation_after_link_rolls_back_own_file(self):
        original_link = os.link
        def after_link(a, b):
            original_link(a, b)
            self.kit.write_bytes(self.kit.read_bytes() + b"x")
        with mock.patch.object(dual.os, "link", side_effect=after_link):
            with self.assertRaisesRegex(RuntimeError, "kit changed"):
                self.render()
        self.assertFalse(self.dest.exists())

    def test_competing_replacement_is_never_rolled_back(self):
        original_link = os.link
        def after_link(a, b):
            original_link(a, b)
            replacement = self.root / "competitor.wav"
            replacement.write_bytes(b"competing writer")
            os.replace(replacement, b)
            self.project.write_bytes(b"changed project")
        with mock.patch.object(dual.os, "link", side_effect=after_link):
            with self.assertRaises(RuntimeError):
                self.render()
        self.assertEqual(self.dest.read_bytes(), b"competing writer")


class OriginalSavedComposeDualRateStereo(unittest.TestCase):
    def test_real_saved_compose_source_to_two_rate_stereo_pcm(self):
        root = Path(__file__).resolve().parents[2]
        if not (root / "zaaggenz_runtime" / "nyquismic_offline_audition.py").is_file():
            self.skipTest("requires original source-backed Compose renderer")
        from zaaggenz_runtime import nyquismic_production_kit
        from test_nyquismic_compose_delivery import source_document
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder) / "source.zgtimeline.json"
            project.write_text(json.dumps(source_document()), encoding="utf-8")
            kit = Path(folder) / "kit.zip"
            kr = nyquismic_production_kit.export_saved_compose_kit(
                project, kit, virtual_rates_hz=["4/1", "5/1"])
            output = Path(folder) / "dual.wav"
            r = dual.bounce_dual_rate_stereo(
                kit, output, left_rate_hz="4/1", right_rate_hz="5/1",
                project_path=project, expected_zip_sha256=kr["zip_sha256"])
            with zipfile.ZipFile(kit) as archive:
                _, a = wavfile.read(io.BytesIO(archive.read("nyq-rate-01.wav")))
                _, b = wavfile.read(io.BytesIO(archive.read("nyq-rate-02.wav")))
            hz, pcm = wavfile.read(output)
            self.assertEqual(hz, 48000)
            self.assertEqual(r["frames"], 28800)
            self.assertEqual(r["source_channels"], 1)
            self.assertEqual(pcm.shape, (28800, 2))
            np.testing.assert_array_equal(pcm[:, 0], a)
            np.testing.assert_array_equal(pcm[:, 1], b)
            self.assertNotEqual(sha(a.astype("<f4").tobytes()), sha(b.astype("<f4").tobytes()))
            self.assertEqual(r["pcm_f32le_sha256"], sha(pcm.astype("<f4").tobytes()))
            self.assertTrue(r["source_project_checked"])
            self.assertTrue(r["trusted_kit_checked"])
            print("NYQ_DUAL_RATE_STEREO_PCM " + json.dumps({
                "frames": r["frames"], "sample_rate_hz": hz,
                "source_project_sha256": r["source_project_sha256"],
                "kit_sha256": r["kit_sha256"],
                "left_rate_hz": r["left_rate_hz"],
                "right_rate_hz": r["right_rate_hz"],
                "left_wav_sha256": r["left_wav_sha256"],
                "right_wav_sha256": r["right_wav_sha256"],
                "wav_sha256": r["wav_sha256"],
                "pcm_f32le_sha256": r["pcm_f32le_sha256"],
            }, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
