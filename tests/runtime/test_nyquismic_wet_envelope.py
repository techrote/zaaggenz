"""Original-source Nyquismic wet-envelope PCM, musical automation and race regressions."""
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
from zaaggenz_runtime import nyquismic_wet_envelope as env


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def wave(samples):
    buffer = io.BytesIO()
    wavfile.write(buffer, 48000, np.asarray(samples, dtype=np.float32))
    return buffer.getvalue()


class WetEnvelopeTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.project = self.root / "song.zgtimeline.json"
        self.project.write_bytes(b'{"saved":"compose"}')
        self.kit = self.root / "listening.zip"
        self.dest = self.root / "automated.wav"
        self.dry = np.full(12000, .25, np.float32)
        self.wet = np.full(12000, .75, np.float32)
        self.other = np.full(12000, -.5, np.float32)
        self.rebuild()

    def rebuild(self):
        self.wavs = [wave(x) for x in (self.dry, self.wet, self.other)]
        with zipfile.ZipFile(self.kit, "w", compression=zipfile.ZIP_STORED) as archive:
            for name, raw in zip(
                ("original.wav", "nyq-rate-01.wav", "nyq-rate-02.wav"), self.wavs
            ):
                archive.writestr(name, raw)
        self.receipt = {
            "zip_sha256": sha(self.kit.read_bytes()),
            "virtual_rates_hz": ["4/1", "5/1"],
            "frames": len(self.dry),
            "channels": 1 if self.dry.ndim == 1 else self.dry.shape[1],
            "tracks": [{"wav_sha256": sha(raw)} for raw in self.wavs],
            "source_project_sha256": sha(self.project.read_bytes()),
            "trusted_zip_sha_checked": False,
            "original_project_checked": True,
        }

    def render(self, **options):
        choices = {
            "virtual_rate_hz": "4/1",
            "points_ms": ["0=0", "100=100", "200=0"],
            "project_path": self.project,
        }
        choices.update(options)
        with mock.patch.object(env, "verify_production_kit", return_value=self.receipt):
            return env.bounce_wet_envelope(self.kit, self.dest, **choices)

    def test_framewise_linear_ramp_endpoints_and_receipt(self):
        receipt = self.render()
        rate, pcm = wavfile.read(self.dest)
        self.assertEqual(rate, 48000)
        self.assertEqual(pcm.dtype, np.float32)
        weights = np.interp(np.arange(12000), [0, 4800, 9600], [0, 1, 0])
        expected = (.25 + .5 * weights).astype(np.float32)
        np.testing.assert_array_equal(pcm, expected)
        self.assertEqual(pcm[0], self.dry[0])
        self.assertEqual(pcm[4800], self.wet[4800])
        self.assertEqual(pcm[9600], self.dry[9600])
        self.assertEqual(pcm[-1], self.dry[-1])
        self.assertEqual(receipt["wav_sha256"], sha(self.dest.read_bytes()))
        self.assertEqual(receipt["pcm_f32le_sha256"], sha(pcm.astype("<f4").tobytes()))
        self.assertEqual([p["frame"] for p in receipt["keyframes"]], [0, 4800, 9600])
        self.assertEqual(receipt["interpolation"],
                         "linear_amplitude_at_each_48khz_frame_hold_after_last")

    def test_fractional_millisecond_keyframe_half_up(self):
        receipt = self.render(points_ms=["0=0", "0.031=100", "200=100"])
        self.assertEqual([p["frame"] for p in receipt["keyframes"]], [0, 1, 9600])
        _, pcm = wavfile.read(self.dest)
        self.assertEqual(pcm[0], self.dry[0])
        self.assertEqual(pcm[1], self.wet[1])
        self.assertEqual(pcm[-1], self.wet[-1])

    def test_zero_and_hundred_percent_keep_bit_identical_pcm(self):
        self.dry = np.sin(np.arange(12000) * .027).astype(np.float32)
        self.wet = np.cos(np.arange(12000) * .033).astype(np.float32)
        self.rebuild()
        for percent, source in [("0", self.dry), ("100", self.wet)]:
            with self.subTest(percent=percent):
                receipt = self.render(points_ms=[f"0={percent}", f"200={percent}"])
                _, pcm = wavfile.read(self.dest)
                np.testing.assert_array_equal(pcm, source)
                self.assertEqual(receipt["pcm_f32le_sha256"],
                                 sha(source.astype("<f4").tobytes()))
                self.dest.unlink()

    def test_identical_stereo_sources_remain_exact_during_automation(self):
        left = np.linspace(-.9, .9, 12000)
        right = np.linspace(.7, -.7, 12000)
        self.dry = np.stack([left, right], axis=1).astype(np.float32)
        self.wet = self.dry.copy()
        self.rebuild()
        receipt = self.render(points_ms=["0=14", "50=83", "199=6"])
        _, pcm = wavfile.read(self.dest)
        np.testing.assert_array_equal(pcm, self.dry)
        self.assertEqual(receipt["channels"], 2)

    def test_select_second_rate_hold_final_and_peak_not_limited(self):
        self.dry.fill(1.25)
        self.other.fill(-1.25)
        self.rebuild()
        receipt = self.render(virtual_rate_hz="5/1", points_ms=["0=0", "10=100"])
        _, pcm = wavfile.read(self.dest)
        self.assertEqual(pcm[0], np.float32(1.25))
        self.assertEqual(pcm[480], np.float32(-1.25))
        self.assertEqual(pcm[-1], np.float32(-1.25))
        self.assertTrue(receipt["exceeds_unity_peak"])
        self.assertEqual(receipt["wet_wav_sha256"], sha(self.wavs[2]))

    def test_chunk_boundary_does_not_reset_envelope(self):
        frames = 75000
        self.dry = np.full(frames, -.25, np.float32)
        self.wet = np.full(frames, .75, np.float32)
        self.other = np.zeros(frames, np.float32)
        self.rebuild()
        self.render(points_ms=["0=0", "1000=100", "1400=0"])
        _, pcm = wavfile.read(self.dest)
        positions = np.array([65534, 65535, 65536, 65537])
        weights = np.interp(positions, [0, 48000, 67200], [0, 1, 0])
        np.testing.assert_array_equal(pcm[positions], (-.25 + weights).astype(np.float32))

    def test_invalid_keyframes_rate_and_target_do_not_publish(self):
        invalid = [
            [], ["0=0"], ["0=0", "0=100"], ["0=0", "0.001=100"],
            ["0=0", "20=80", "10=40"], ["10=0", "20=100"],
            ["0=-1", "20=100"], ["0=0", "20=101"],
            ["0=nan", "20=50"], ["0=0", "20=inf"],
            ["0=0.0000001", "20=50"], ["0=0", "20=1.0000001"],
            ["0=0", "20=hi"], ["0=0", "20=30=40"],
            ["0=0", "250=100"], ["0=0"] + [f"{i}=50" for i in range(1, 65)],
        ]
        for points in invalid:
            with self.subTest(points=points), self.assertRaises(ValueError):
                self.render(points_ms=points)
            self.assertFalse(self.dest.exists())
        for rate in ("4/2", "7/1", 4, ""):
            with self.subTest(rate=rate), self.assertRaises(ValueError):
                self.render(virtual_rate_hz=rate)
        with self.assertRaises(ValueError):
            self.render(cancelled=True)
        self.assertFalse(self.dest.exists())

    def test_output_no_overwrite_and_wrong_extension(self):
        self.dest.write_bytes(b"another writer")
        with self.assertRaises(FileExistsError):
            self.render()
        self.assertEqual(self.dest.read_bytes(), b"another writer")
        self.dest.unlink()
        self.dest = self.root / "automated.mp3"
        with self.assertRaises(ValueError):
            self.render()

    def test_mutation_after_verification_is_rejected(self):
        def mutate(*args, **kwargs):
            self.kit.write_bytes(b"changed")
            return self.receipt
        with mock.patch.object(env, "verify_production_kit", side_effect=mutate):
            with self.assertRaisesRegex(RuntimeError, "changed after verification"):
                env.bounce_wet_envelope(self.kit, self.dest, virtual_rate_hz="4/1",
                                        points_ms=["0=0", "20=100"])
        self.assertFalse(self.dest.exists())

    def test_foreign_track_wav_is_rejected(self):
        self.receipt["tracks"][1]["wav_sha256"] = sha(b"foreign")
        with self.assertRaisesRegex(RuntimeError, "differs from verified kit"):
            self.render()
        self.assertFalse(self.dest.exists())

    def test_early_cancellation_and_late_cancellation_rollback(self):
        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            self.render(cancelled=lambda: True)
        self.assertFalse(self.dest.exists())
        state = {"stop": False}
        original = os.link
        def stop_after_link(src, dst):
            original(src, dst)
            state["stop"] = True
        with mock.patch.object(env.os, "link", side_effect=stop_after_link):
            with self.assertRaisesRegex(RuntimeError, "cancelled"):
                self.render(cancelled=lambda: state["stop"])
        self.assertFalse(self.dest.exists())

    def test_late_kit_or_project_edit_rolls_back(self):
        for altered in ("kit", "project"):
            with self.subTest(altered=altered):
                original = os.link
                def change_after_link(src, dst):
                    original(src, dst)
                    if altered == "kit":
                        self.kit.write_bytes(b"modified")
                    else:
                        self.project.write_bytes(b"modified")
                with mock.patch.object(env.os, "link", side_effect=change_after_link):
                    with self.assertRaisesRegex(RuntimeError, "changed"):
                        self.render()
                self.assertFalse(self.dest.exists())
                self.project.write_bytes(b'{"saved":"compose"}')
                self.rebuild()

    def test_competing_destination_writer_is_never_clobbered(self):
        def competing(src, dst):
            Path(dst).write_bytes(b"other-writer")
            raise FileExistsError(dst)
        with mock.patch.object(env.os, "link", side_effect=competing):
            with self.assertRaises(FileExistsError):
                self.render()
        self.assertEqual(self.dest.read_bytes(), b"other-writer")

    def test_competing_replacement_after_link_is_preserved(self):
        original = os.link
        flag = {"stop": False}
        def replacement(src, dst):
            original(src, dst)
            Path(dst).unlink()
            Path(dst).write_bytes(b"another-writer")
            flag["stop"] = True
        with mock.patch.object(env.os, "link", side_effect=replacement):
            with self.assertRaisesRegex(RuntimeError, "cancelled"):
                self.render(cancelled=lambda: flag["stop"])
        self.assertEqual(self.dest.read_bytes(), b"another-writer")

    def test_deterministic_repeated_render_hash(self):
        one = self.render(points_ms=["0=12.5", "100=37.5", "200=0"])
        first_bytes = self.dest.read_bytes()
        self.dest.unlink()
        two = self.render(points_ms=["0=12.5", "100=37.5", "200=0"])
        self.assertEqual(one["pcm_f32le_sha256"], two["pcm_f32le_sha256"])
        self.assertEqual(first_bytes, self.dest.read_bytes())


class OriginalSavedComposeWetEnvelope(unittest.TestCase):
    def test_real_compose_kit_to_automated_pcm(self):
        root = Path(__file__).resolve().parents[2]
        if not (root / "zaaggenz_runtime" / "nyquismic_offline_audition.py").is_file():
            self.skipTest("genuine saved-Compose renderer requires original repository host")
        from zaaggenz_runtime import nyquismic_production_kit
        from test_nyquismic_compose_delivery import source_document
        with tempfile.TemporaryDirectory() as dirname:
            project = Path(dirname) / "song.zgtimeline.json"
            project.write_text(json.dumps(source_document()), encoding="utf-8")
            kit = Path(dirname) / "listening.zip"
            kit_receipt = nyquismic_production_kit.export_saved_compose_kit(
                project, kit, virtual_rates_hz=["4/1", "5/1"])
            output = Path(dirname) / "wet-envelope.wav"
            receipt = env.bounce_wet_envelope(
                kit, output, virtual_rate_hz="4/1",
                points_ms=["0=0", "150=100", "450=0"],
                project_path=project, expected_zip_sha256=kit_receipt["zip_sha256"])
            self.assertEqual(receipt["frames"], 28800)
            self.assertEqual(receipt["delivery_hz"], 48000)
            self.assertTrue(receipt["trusted_kit_checked"])
            self.assertTrue(receipt["source_project_checked"])
            with zipfile.ZipFile(kit) as archive:
                _, dry = wavfile.read(io.BytesIO(archive.read("original.wav")))
                _, wet = wavfile.read(io.BytesIO(archive.read("nyq-rate-01.wav")))
            rate, pcm = wavfile.read(output)
            self.assertEqual(rate, 48000)
            weights = np.interp(
                np.arange(len(pcm)), [0, 7200, 21600], [0, 1, 0])
            if dry.ndim == 2:
                weights = weights[:, None]
            expected = (dry.astype(np.float64)
                        + (wet.astype(np.float64) - dry.astype(np.float64))
                        * weights).astype(np.float32)
            expected = np.where(weights == 0, dry, expected)
            expected = np.where(weights == 1, wet, expected)
            expected = np.where(dry == wet, dry, expected)
            np.testing.assert_array_equal(pcm, expected)
            self.assertEqual(receipt["pcm_f32le_sha256"],
                             sha(pcm.astype("<f4").tobytes()))
            print("NYQ_WET_ENVELOPE_PCM " + json.dumps({
                "frames": len(pcm), "wav_sha256": receipt["wav_sha256"],
                "pcm_f32le_sha256": receipt["pcm_f32le_sha256"],
                "kit_sha256": receipt["kit_sha256"],
                "dry_wav_sha256": receipt["dry_wav_sha256"],
                "wet_wav_sha256": receipt["wet_wav_sha256"],
            }, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
