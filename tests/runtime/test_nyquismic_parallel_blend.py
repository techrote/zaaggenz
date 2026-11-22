"""Source-verified Nyquismic parallel mix, PCM identity and publication races."""
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
from zaaggenz_runtime import nyquismic_parallel_blend as blend


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def wave(samples):
    buf = io.BytesIO()
    wavfile.write(buf, 48000, np.asarray(samples, dtype=np.float32))
    return buf.getvalue()


class ParallelBlendTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.project = self.root / "song.zgtimeline.json"
        self.project.write_bytes(b'{"saved":"compose"}')
        self.kit = self.root / "kit.zip"
        self.dest = self.root / "mix.wav"
        self.dry = np.full(12000, .25, np.float32)
        self.wet = np.full(12000, .75, np.float32)
        self.other = np.full(12000, -.75, np.float32)
        self.rebuild()

    def rebuild(self):
        self.wavs = [wave(x) for x in (self.dry, self.wet, self.other)]
        with zipfile.ZipFile(self.kit, "w", compression=zipfile.ZIP_STORED) as z:
            for name, raw in zip(("original.wav", "nyq-rate-01.wav", "nyq-rate-02.wav"), self.wavs):
                z.writestr(name, raw)
        self.receipt = {
            "zip_sha256": sha(self.kit.read_bytes()),
            "virtual_rates_hz": ["4/1", "5/1"],
            "frames": len(self.dry), "channels": 1 if self.dry.ndim == 1 else self.dry.shape[1],
            "tracks": [{"wav_sha256": sha(x)} for x in self.wavs],
            "source_project_sha256": sha(self.project.read_bytes()),
            "trusted_zip_sha_checked": False,
            "original_project_checked": True,
        }

    def render(self, **kwargs):
        options = dict(virtual_rate_hz="4/1", wet_percent="25", project_path=self.project)
        options.update(kwargs)
        with mock.patch.object(blend, "verify_production_kit", return_value=self.receipt):
            return blend.bounce_parallel_blend(self.kit, self.dest, **options)

    def test_weighted_original_pcm_and_receipts(self):
        receipt = self.render()
        rate, pcm = wavfile.read(self.dest)
        self.assertEqual(rate, 48000)
        self.assertEqual(pcm.dtype, np.float32)
        np.testing.assert_array_equal(pcm, np.full(12000, .375, np.float32))
        self.assertEqual(receipt["wav_sha256"], sha(self.dest.read_bytes()))
        self.assertEqual(receipt["pcm_f32le_sha256"], sha(pcm.astype("<f4").tobytes()))
        self.assertEqual(receipt["wet_percent"], "25")
        self.assertEqual(receipt["peak_abs"], .375)
        self.assertFalse(receipt["exceeds_unity_peak"])

    def test_endpoints_bit_identical_without_gain_change(self):
        self.dry = np.sin(np.arange(12000) * .027).astype(np.float32)
        self.wet = np.sin(np.arange(12000) * .058).astype(np.float32)
        self.rebuild()
        for pct, expected in (("0", self.dry), ("100", self.wet)):
            receipt = self.render(wet_percent=pct)
            _, pcm = wavfile.read(self.dest)
            np.testing.assert_array_equal(pcm, expected)
            self.assertEqual(receipt["pcm_f32le_sha256"], sha(expected.astype("<f4").tobytes()))
            self.dest.unlink()

    def test_stereo_identical_tracks_stay_exact(self):
        self.dry = np.stack([np.linspace(-.9, .9, 12000),
                             np.linspace(.8, -.8, 12000)], axis=1).astype(np.float32)
        self.wet = self.dry.copy()
        self.rebuild()
        receipt = self.render(wet_percent="33.333333")
        _, pcm = wavfile.read(self.dest)
        np.testing.assert_array_equal(pcm, self.dry)
        self.assertEqual(receipt["channels"], 2)

    def test_different_virtual_rate_and_peak_not_clipped(self):
        self.dry.fill(1.25)
        self.other.fill(-1.25)
        self.rebuild()
        receipt = self.render(virtual_rate_hz="5/1", wet_percent="50")
        _, pcm = wavfile.read(self.dest)
        np.testing.assert_array_equal(pcm, np.zeros(12000, np.float32))
        self.assertEqual(receipt["wet_wav_sha256"], sha(self.wavs[2]))
        self.dest.unlink()
        receipt = self.render(wet_percent="0")
        self.assertTrue(receipt["exceeds_unity_peak"])
        self.assertEqual(receipt["peak_abs"], 1.25)

    def test_invalid_percent_rate_target_and_no_clobber(self):
        for bad in ("nan", "inf", "-1", "100.0001", "0.0000001", "", True):
            with self.subTest(percent=bad), self.assertRaises(ValueError):
                self.render(wet_percent=bad)
        for rate in ("4/2", "7/1", 4, ""):
            with self.subTest(rate=rate), self.assertRaises(ValueError):
                self.render(virtual_rate_hz=rate)
        self.dest.write_bytes(b"other-writer")
        with self.assertRaises(FileExistsError):
            self.render()
        self.assertEqual(self.dest.read_bytes(), b"other-writer")

    def test_changed_kit_after_verification_is_rejected(self):
        with mock.patch.object(blend, "verify_production_kit",
                side_effect=lambda *a, **k: (self.kit.write_bytes(b"changed"), self.receipt)[1]):
            with self.assertRaisesRegex(RuntimeError, "changed after verification"):
                blend.bounce_parallel_blend(self.kit, self.dest, virtual_rate_hz="4/1")
        self.assertFalse(self.dest.exists())

    def test_forged_selected_wav_is_rejected(self):
        self.receipt["tracks"][1]["wav_sha256"] = sha(b"foreign")
        with self.assertRaisesRegex(RuntimeError, "differs from verified kit"):
            self.render()
        self.assertFalse(self.dest.exists())

    def test_cancelled_before_render_is_inert(self):
        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            self.render(cancelled=lambda: True)
        self.assertFalse(self.dest.exists())

    def test_late_cancellation_rolls_back(self):
        state = {"stop": False}
        real = os.link
        def interrupt(src, dst):
            real(src, dst)
            state["stop"] = True
        with mock.patch.object(blend.os, "link", side_effect=interrupt):
            with self.assertRaisesRegex(RuntimeError, "cancelled"):
                self.render(cancelled=lambda: state["stop"])
        self.assertFalse(self.dest.exists())

    def test_late_source_project_change_rolls_back(self):
        real = os.link
        def mutate(src, dst):
            real(src, dst)
            self.project.write_bytes(b"changed")
        with mock.patch.object(blend.os, "link", side_effect=mutate):
            with self.assertRaisesRegex(RuntimeError, "project changed"):
                self.render()
        self.assertFalse(self.dest.exists())

    def test_late_kit_change_rolls_back(self):
        real = os.link
        def mutate(src, dst):
            real(src, dst)
            self.kit.write_bytes(b"changed")
        with mock.patch.object(blend.os, "link", side_effect=mutate):
            with self.assertRaisesRegex(RuntimeError, "kit changed"):
                self.render()
        self.assertFalse(self.dest.exists())

    def test_competing_output_is_never_overwritten(self):
        def competing(src, dst):
            Path(dst).write_bytes(b"competing")
            raise FileExistsError(dst)
        with mock.patch.object(blend.os, "link", side_effect=competing):
            with self.assertRaises(FileExistsError):
                self.render()
        self.assertEqual(self.dest.read_bytes(), b"competing")

    def test_deterministic_full_mix(self):
        first = self.render(wet_percent="67.5")
        original = self.dest.read_bytes()
        self.dest.unlink()
        second = self.render(wet_percent="67.5")
        self.assertEqual(first["pcm_f32le_sha256"], second["pcm_f32le_sha256"])
        self.assertEqual(original, self.dest.read_bytes())


class OriginalSavedComposeBlend(unittest.TestCase):
    def test_real_compose_kit_to_parallel_wav(self):
        root = Path(__file__).resolve().parents[2]
        if not (root / "zaaggenz_runtime" / "nyquismic_offline_audition.py").is_file():
            self.skipTest("real saved-Compose NYQ producer required on original host")
        from zaaggenz_runtime import nyquismic_production_kit
        from test_nyquismic_compose_delivery import source_document
        with tempfile.TemporaryDirectory() as dirname:
            project = Path(dirname) / "song.zgtimeline.json"
            project.write_text(json.dumps(source_document()), encoding="utf-8")
            kit = Path(dirname) / "kit.zip"
            kit_receipt = nyquismic_production_kit.export_saved_compose_kit(
                project, kit, virtual_rates_hz=["4/1", "5/1"])
            output = Path(dirname) / "mixed.wav"
            receipt = blend.bounce_parallel_blend(
                kit, output, virtual_rate_hz="4/1",
                wet_percent="25", project_path=project,
                expected_zip_sha256=kit_receipt["zip_sha256"])
            self.assertTrue(receipt["trusted_kit_checked"])
            self.assertTrue(receipt["source_project_checked"])
            self.assertEqual(receipt["frames"], 28800)
            self.assertEqual(receipt["delivery_hz"], 48000)
            with zipfile.ZipFile(kit) as archive:
                _, dry = wavfile.read(io.BytesIO(archive.read("original.wav")))
                _, wet = wavfile.read(io.BytesIO(archive.read("nyq-rate-01.wav")))
            rate, pcm = wavfile.read(output)
            self.assertEqual(rate, 48000)
            expected = (dry.astype(np.float64) + (wet.astype(np.float64)
                        - dry.astype(np.float64)) * .25).astype(np.float32)
            same = dry == wet
            expected[same] = dry[same]
            np.testing.assert_array_equal(pcm, expected)
            self.assertEqual(receipt["pcm_f32le_sha256"], sha(pcm.astype("<f4").tobytes()))
            print("NYQ_PARALLEL_BLEND_PCM " + json.dumps({
                "frames": len(pcm), "wav_sha256": receipt["wav_sha256"],
                "pcm_f32le_sha256": receipt["pcm_f32le_sha256"],
                "kit_sha256": receipt["kit_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
