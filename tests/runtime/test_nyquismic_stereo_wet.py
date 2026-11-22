"""Spatial Nyquismic production, original PCM, stereo projection and publication regressions."""
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
from zaaggenz_runtime import nyquismic_stereo_wet as spatial


def sha(data):
    return hashlib.sha256(data).hexdigest()


def wave(data):
    out = io.BytesIO()
    wavfile.write(out, 48000, np.asarray(data, dtype=np.float32))
    return out.getvalue()


class SpatialWetTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.project = self.root / "song.zgtimeline.json"
        self.project.write_bytes(b'{"saved":"compose"}')
        self.kit = self.root / "listen.zip"
        self.dest = self.root / "spatial.wav"
        self.dry = np.tile(np.array([.2, .6], dtype=np.float32), (12000, 1))
        self.wet = np.tile(np.array([1., -.2], dtype=np.float32), (12000, 1))
        self.other = np.tile(np.array([-.5, .5], dtype=np.float32), (12000, 1))
        self.rebuild()

    def rebuild(self):
        self.wavs = [wave(x) for x in (self.dry, self.wet, self.other)]
        with zipfile.ZipFile(self.kit, "w", compression=zipfile.ZIP_STORED) as archive:
            for filename, data in zip(("original.wav", "nyq-rate-01.wav", "nyq-rate-02.wav"), self.wavs):
                archive.writestr(filename, data)
        self.receipt = {
            "zip_sha256": sha(self.kit.read_bytes()),
            "virtual_rates_hz": ["4/1", "5/1"],
            "frames": len(self.dry), "channels": 1 if self.dry.ndim == 1 else 2,
            "tracks": [{"wav_sha256": sha(w), "pcm_f32le_sha256": sha(
                np.asarray(x, dtype="<f4").tobytes())} for w, x in zip(self.wavs, (self.dry, self.wet, self.other))],
            "source_project_sha256": sha(self.project.read_bytes()),
            "trusted_zip_sha_checked": False, "original_project_checked": True,
        }

    def render(self, **options):
        args = dict(virtual_rate_hz="4/1", wet_percent="50", mode="side", project_path=self.project)
        args.update(options)
        with mock.patch.object(spatial, "verify_production_kit", return_value=self.receipt):
            return spatial.bounce_stereo_wet(self.kit, self.dest, **args)

    def read(self):
        hz, pcm = wavfile.read(self.dest)
        self.assertEqual(hz, 48000)
        self.assertEqual(pcm.dtype, np.float32)
        return pcm

    def test_side_only_changes_width_not_mid(self):
        receipt = self.render()
        pcm = self.read().astype(np.float64)
        dry = self.dry.astype(np.float64)
        wet = self.wet.astype(np.float64)
        np.testing.assert_allclose(pcm.sum(axis=1), dry.sum(axis=1), atol=1e-7)
        expected = dry + .5 * np.column_stack((
            (wet[:, 0]-dry[:, 0]-wet[:, 1]+dry[:, 1])/2,
            -(wet[:, 0]-dry[:, 0]-wet[:, 1]+dry[:, 1])/2))
        np.testing.assert_allclose(pcm, expected, atol=1e-7)
        self.assertEqual(receipt["mode"], "side")
        self.assertEqual(receipt["pcm_f32le_sha256"], sha(self.read().astype("<f4").tobytes()))

    def test_mid_only_preserves_side(self):
        self.wet = np.tile(np.array([.75, .85], np.float32), (12000, 1))
        self.rebuild()
        self.render(mode="mid", wet_percent="75")
        pcm = self.read().astype(np.float64)
        np.testing.assert_allclose(pcm[:, 0]-pcm[:, 1],
                                   self.dry[:, 0].astype(np.float64)-self.dry[:, 1].astype(np.float64), atol=1e-7)
        self.assertGreater(abs(float(pcm[0, 0]-self.dry[0, 0])), .05)

    def test_all_wet_endpoints_exact_with_signed_zeros(self):
        self.dry = np.stack([np.zeros(12000, np.float32), np.ones(12000, np.float32)*.25], axis=1)
        self.wet = self.dry.copy()
        self.wet[:, 0] = -0.0
        self.rebuild()
        for amount, expected in (("0", self.dry), ("100", self.wet)):
            with self.subTest(amount=amount):
                self.render(mode="both", wet_percent=amount)
                np.testing.assert_array_equal(self.read().view(np.uint32), expected.view(np.uint32))
                self.dest.unlink()

    def test_selected_left_right_and_second_rate(self):
        for mode, untouched in (("left", 1), ("right", 0)):
            with self.subTest(mode=mode):
                receipt = self.render(mode=mode, virtual_rate_hz="5/1", wet_percent="100")
                pcm = self.read()
                np.testing.assert_array_equal(pcm[:, untouched], self.dry[:, untouched])
                np.testing.assert_array_equal(pcm[:, 1-untouched], self.other[:, 1-untouched])
                self.assertEqual(receipt["wet_wav_sha256"], sha(self.wavs[2]))
                self.dest.unlink()

    def test_mono_only_both_and_blended_identity(self):
        self.dry = np.full(12000, .2, np.float32)
        self.wet = np.full(12000, .8, np.float32)
        self.other = np.full(12000, .5, np.float32)
        self.rebuild()
        with self.assertRaisesRegex(ValueError, "stereo"):
            self.render(mode="side")
        with mock.patch.object(spatial, "verify_production_kit", return_value=self.receipt):
            spatial.bounce_stereo_wet(self.kit, self.dest, virtual_rate_hz="4/1",
                                      wet_percent="25", project_path=self.project)
        np.testing.assert_allclose(self.read(), np.full(12000, .35, np.float32), atol=1e-7)

    def test_same_signal_all_modes_preserve_exact_bits(self):
        self.wet = self.dry.copy()
        self.rebuild()
        for mode in spatial.MODES:
            with self.subTest(mode=mode):
                self.render(mode=mode)
                np.testing.assert_array_equal(self.read().view(np.uint32), self.dry.view(np.uint32))
                self.dest.unlink()

    def test_chunk_boundary_is_sample_continuous(self):
        self.dry = np.tile(np.array([-.25, .7], np.float32), (75000, 1))
        self.wet = np.tile(np.array([.8, -.8], np.float32), (75000, 1))
        self.other = self.wet.copy()
        self.rebuild()
        self.render(mode="side", wet_percent="27.5")
        pcm = self.read()
        np.testing.assert_array_equal(pcm[65530:65540], np.tile(pcm[0], (10, 1)))
        self.dest.unlink()
        a = self.render(mode="side", wet_percent="27.5")
        self.assertEqual(a["pcm_f32le_sha256"], sha(pcm.astype("<f4").tobytes()))

    def test_invalid_controls_rejected_before_publication(self):
        for percent in ("nan", "inf", "-1", "100.001", "0.0000001", "hi", 20, ""):
            with self.subTest(percent=percent), self.assertRaises(ValueError):
                self.render(wet_percent=percent)
        for mode in ("middle", "", 20):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                self.render(mode=mode)
        for rate in ("4/2", "7/1", 4):
            with self.subTest(rate=rate), self.assertRaises(ValueError):
                self.render(virtual_rate_hz=rate)
        with self.assertRaises(ValueError):
            self.render(cancelled=True)
        self.assertFalse(self.dest.exists())

    def test_no_overwrite(self):
        self.dest.write_bytes(b"previous")
        with self.assertRaises(FileExistsError):
            self.render()
        self.assertEqual(self.dest.read_bytes(), b"previous")
        self.dest.unlink()
        self.dest = self.root / "wrong.mp3"
        with self.assertRaises(ValueError):
            self.render()

    def test_forged_track_and_changed_kit_after_verifier(self):
        self.receipt["tracks"][1]["wav_sha256"] = "f"*64
        with self.assertRaisesRegex(RuntimeError, "differs from verified"):
            self.render()
        self.rebuild()
        def change(*_a, **_kw):
            self.kit.write_bytes(b"changed")
            return self.receipt
        with mock.patch.object(spatial, "verify_production_kit", side_effect=change):
            with self.assertRaisesRegex(RuntimeError, "changed after verification"):
                spatial.bounce_stereo_wet(self.kit, self.dest, virtual_rate_hz="4/1", wet_percent="50")
        self.assertFalse(self.dest.exists())

    def test_cancel_before_and_after_link(self):
        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            self.render(cancelled=lambda: True)
        source = os.link
        flag = {"stop": False}
        def cancel_after(src, dst):
            source(src, dst)
            flag["stop"] = True
        with mock.patch.object(spatial.os, "link", side_effect=cancel_after):
            with self.assertRaisesRegex(RuntimeError, "cancelled"):
                self.render(cancelled=lambda: flag["stop"])
        self.assertFalse(self.dest.exists())

    def test_late_kit_or_project_mutation_rolls_back(self):
        for target in ("kit", "project"):
            with self.subTest(target=target):
                original = os.link
                def mutate(src, dst):
                    original(src, dst)
                    if target == "kit":
                        self.kit.write_bytes(b"changed")
                    else:
                        self.project.write_bytes(b"changed")
                with mock.patch.object(spatial.os, "link", side_effect=mutate):
                    with self.assertRaisesRegex(RuntimeError, "changed"):
                        self.render()
                self.assertFalse(self.dest.exists())
                self.project.write_bytes(b'{"saved":"compose"}')
                self.rebuild()

    def test_competing_destination_and_replacement_preserved(self):
        def competing(src, dst):
            Path(dst).write_bytes(b"other")
            raise FileExistsError(dst)
        with mock.patch.object(spatial.os, "link", side_effect=competing):
            with self.assertRaises(FileExistsError):
                self.render()
        self.assertEqual(self.dest.read_bytes(), b"other")
        self.dest.unlink()
        original = os.link
        state = {"stop": False}
        def replace(src, dst):
            original(src, dst)
            Path(dst).unlink()
            Path(dst).write_bytes(b"other2")
            state["stop"] = True
        with mock.patch.object(spatial.os, "link", side_effect=replace):
            with self.assertRaisesRegex(RuntimeError, "cancelled"):
                self.render(cancelled=lambda: state["stop"])
        self.assertEqual(self.dest.read_bytes(), b"other2")

    def test_peak_not_normalized_or_clipped(self):
        self.dry = np.tile(np.array([1.2, -1.2], np.float32), (12000, 1))
        self.wet = np.tile(np.array([1.5, -1.5], np.float32), (12000, 1))
        self.rebuild()
        receipt = self.render(mode="both", wet_percent="100")
        self.assertTrue(receipt["exceeds_unity_peak"])
        np.testing.assert_array_equal(self.read(), self.wet)


class OriginalSavedComposeSpatialWet(unittest.TestCase):
    def test_real_compose_kit_to_source_verified_pcm(self):
        root = Path(__file__).resolve().parents[2]
        if not (root / "zaaggenz_runtime" / "nyquismic_offline_audition.py").is_file():
            self.skipTest("requires original source-backed Compose renderer")
        from zaaggenz_runtime import nyquismic_production_kit
        from test_nyquismic_compose_delivery import source_document
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "song.zgtimeline.json"
            project.write_text(json.dumps(source_document()), encoding="utf-8")
            kit = Path(tmp) / "kit.zip"
            kr = nyquismic_production_kit.export_saved_compose_kit(
                project, kit, virtual_rates_hz=["4/1", "5/1"])
            output = Path(tmp) / "spatial.wav"
            receipt = spatial.bounce_stereo_wet(
                kit, output, virtual_rate_hz="4/1", wet_percent="37.5", mode="both",
                project_path=project, expected_zip_sha256=kr["zip_sha256"])
            with zipfile.ZipFile(kit) as archive:
                _, dry = wavfile.read(io.BytesIO(archive.read("original.wav")))
                _, wet = wavfile.read(io.BytesIO(archive.read("nyq-rate-01.wav")))
            hz, pcm = wavfile.read(output)
            self.assertEqual(hz, 48000)
            self.assertEqual(receipt["frames"], 28800)
            self.assertEqual(receipt["channels"], 1)  # current real Compose fixture is mono
            expected = (dry.astype(np.float64) + .375 * (wet.astype(np.float64) - dry.astype(np.float64))).astype(np.float32)
            expected = np.where(dry == wet, dry, expected)
            np.testing.assert_array_equal(pcm, expected)
            self.assertTrue(receipt["source_project_checked"])
            self.assertTrue(receipt["trusted_kit_checked"])
            self.assertEqual(receipt["pcm_f32le_sha256"], sha(pcm.astype("<f4").tobytes()))
            print("NYQ_STEREO_WET_PCM " + json.dumps({
                "frames": receipt["frames"], "mode": receipt["mode"],
                "source_kit_sha256": receipt["kit_sha256"],
                "wav_sha256": receipt["wav_sha256"],
                "pcm_f32le_sha256": receipt["pcm_f32le_sha256"],
                "dry_wav_sha256": receipt["dry_wav_sha256"],
                "wet_wav_sha256": receipt["wet_wav_sha256"],
            }, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
