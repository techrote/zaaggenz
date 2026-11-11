"""Real Compose and adversarial regressions for opt-in two-rate timbre morph."""
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
from zaaggenz_runtime import nyquismic_rate_morph as morph


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def wav(pcm):
    out = io.BytesIO()
    wavfile.write(out, 48000, np.asarray(pcm, np.float32))
    return out.getvalue()


class TwoRateMorphIsolated(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.project = self.root / "song.zgtimeline.json"
        self.project.write_bytes(b'{"saved":"compose"}')
        self.kit = self.root / "kit.zip"
        self.output = self.root / "out.wav"
        self.a = np.full(12000, .25, np.float32)
        self.b = np.full(12000, .75, np.float32)
        self.dry = np.full(12000, -.25, np.float32)
        self.build()

    def build(self):
        self.wavs = [wav(x) for x in (self.dry, self.a, self.b)]
        with zipfile.ZipFile(self.kit, "w", compression=zipfile.ZIP_STORED) as z:
            for path, raw in zip(("original.wav", "nyq-rate-01.wav", "nyq-rate-02.wav"), self.wavs):
                z.writestr(path, raw)
        self.receipt = {
            "zip_sha256": sha(self.kit.read_bytes()),
            "virtual_rates_hz": ["4/1", "5/1"],
            "frames": len(self.a),
            "channels": 1 if self.a.ndim == 1 else 2,
            "tracks": [
                {"wav_sha256": sha(w), "pcm_f32le_sha256": sha(np.asarray(x, dtype="<f4").tobytes())}
                for w, x in zip(self.wavs, (self.dry, self.a, self.b))
            ],
            "source_project_sha256": sha(self.project.read_bytes()),
            "trusted_zip_sha_checked": True,
            "original_project_checked": True,
        }

    def bounce(self, **overrides):
        kwargs = dict(rate_a_hz="4/1", rate_b_hz="5/1",
                      points_ms=["0=0", "200=100"], curve="linear",
                      project_path=self.project,
                      expected_zip_sha256=self.receipt["zip_sha256"])
        kwargs.update(overrides)
        output = kwargs.pop("output_wav", self.output)
        with mock.patch.object(morph, "verify_production_kit", return_value=self.receipt):
            return morph.bounce_rate_morph(self.kit, output, **kwargs)

    def pcm(self):
        hz, pcm = wavfile.read(self.output)
        self.assertEqual(hz, 48000)
        self.assertEqual(pcm.dtype, np.float32)
        return pcm

    def test_linear_morph_physical_frame_oracle_and_source_identity(self):
        receipt = self.bounce()
        result = self.pcm()
        self.assertEqual(receipt["frames"], 12000)
        self.assertEqual(result[0], self.a[0])
        self.assertEqual(result[9600], self.b[9600])
        self.assertEqual(result[-1], self.b[-1])
        self.assertAlmostEqual(float(result[4800]), .5, places=7)
        self.assertEqual(receipt["pcm_f32le_sha256"], sha(result.astype("<f4").tobytes()))
        self.assertTrue(receipt["trusted_kit_checked"])
        self.assertEqual(receipt["rate_a_wav_sha256"], sha(self.wavs[1]))

    def test_equal_power_intentionally_increases_correlated_level(self):
        self.a.fill(.75)
        self.b.fill(.75)
        self.build()
        receipt = self.bounce(curve="equal-power")
        self.assertAlmostEqual(float(self.pcm()[4800]), .75 * (2 ** .5), places=6)
        self.assertTrue(receipt["exceeds_unity_peak"])
        self.assertEqual(self.pcm()[0], self.a[0])
        self.assertEqual(self.pcm()[-1], self.b[-1])

    def test_linear_equal_sources_preserve_exact_signed_zero(self):
        self.a = np.tile(np.asarray([0.0, .25, -.0], np.float32), 4000)
        self.b = self.a.copy()
        self.b[2::3] = 0.0
        self.build()
        self.bounce()
        out = self.pcm()
        np.testing.assert_array_equal(out[:1].view(np.uint32), self.a[:1].view(np.uint32))
        self.assertEqual(out[2].view(np.uint32), self.a[2].view(np.uint32))
        self.assertEqual(out[9602].view(np.uint32), self.b[9602].view(np.uint32))

    def test_stereo_and_chunk_boundaries(self):
        frames = 70003
        t = np.arange(frames, dtype=np.float64)
        self.a = np.stack((.1 + .01 * np.sin(t / 50), .3 + .01 * np.cos(t / 30)), axis=1).astype(np.float32)
        self.b = np.stack((.7 + .01 * np.cos(t / 18), -.4 + .01 * np.sin(t / 12)), axis=1).astype(np.float32)
        self.dry = np.zeros_like(self.a)
        self.build()
        self.bounce(points_ms=["0=0", "500=100"])
        out = self.pcm()
        self.assertEqual(out.shape, (frames, 2))
        np.testing.assert_array_equal(out[0], self.a[0])
        np.testing.assert_array_equal(out[24000:], self.b[24000:])
        idx = np.array([1, 5000, 65535, 65536, 65537, 23999])
        w = np.minimum(idx.astype(np.float64) / 24000, 1.)
        expected = (self.a[idx].astype(np.float64) * (1 - w[:, None])
                    + self.b[idx].astype(np.float64) * w[:, None]).astype(np.float32)
        np.testing.assert_allclose(out[idx], expected, atol=1e-7, rtol=0)

    def test_replay_same_pcm_and_file_hash(self):
        first = self.bounce()
        initial = self.output.read_bytes()
        self.output.rename(self.root / "first.wav")
        second = self.bounce()
        self.assertEqual(self.output.read_bytes(), initial)
        self.assertEqual(first["pcm_f32le_sha256"], second["pcm_f32le_sha256"])

    def test_wrong_rates_or_bad_curve_rejected(self):
        for extra in ({"rate_a_hz": "4"}, {"rate_b_hz": "4/1"},
                      {"rate_b_hz": "6/1"}, {"curve": "unbounded"}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                self.bounce(**extra)
        self.assertFalse(self.output.exists())

    def test_malformed_and_non_monotone_keyframes_rejected(self):
        invalid = [
            ["0=0"], ["0=0"] * 65, ["1=0", "2=10"],
            ["0=0", "0=50"], ["0=0", "0.001=10"],
            ["0=0", "200=NaN"], ["0=0", "200=Infinity"],
            ["0=0", "200=-1"], ["0=0", "200=101"],
            ["0=0", "200=0.1234567"], ["0=0", "200.0001=100"],
            ["0=0", "500=100"], ["0", "200=100"],
        ]
        for points in invalid:
            with self.subTest(points=points), self.assertRaises(ValueError):
                self.bounce(points_ms=points)
        self.assertFalse(self.output.exists())

    def test_output_collision_and_non_wav_rejected(self):
        self.output.write_bytes(b"someone-else")
        with self.assertRaises(FileExistsError):
            self.bounce()
        self.assertEqual(self.output.read_bytes(), b"someone-else")
        self.output.unlink()
        with self.assertRaises(ValueError):
            self.bounce(output_wav=self.root / "oops.zip")
        self.assertFalse(self.output.exists())

    def test_kit_mutation_between_verify_and_audio_open_rejected(self):
        old = self.receipt["zip_sha256"]
        def verifier(*args, **kwargs):
            self.kit.write_bytes(b"changed")
            return self.receipt
        with mock.patch.object(morph, "verify_production_kit", side_effect=verifier):
            with self.assertRaisesRegex(RuntimeError, "changed after verification"):
                morph.bounce_rate_morph(self.kit, self.output, rate_a_hz="4/1",
                                       rate_b_hz="5/1", points_ms=["0=0", "200=100"])
        self.assertFalse(self.output.exists())
        self.assertNotEqual(sha(self.kit.read_bytes()), old)

    def test_invalid_cancel_hook_and_cancel_mid_chunk(self):
        with self.assertRaises(ValueError):
            self.bounce(cancelled=1)
        calls = [0]
        def cancelled():
            calls[0] += 1
            return calls[0] >= 4
        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            self.bounce(cancelled=cancelled)
        self.assertFalse(self.output.exists())

    def test_kit_and_project_change_inside_final_link_roll_back(self):
        original = os.link
        for target in ("kit", "project"):
            with self.subTest(target=target):
                def mutate(src, dest):
                    original(src, dest)
                    if target == "kit":
                        self.kit.write_bytes(b"modified")
                    else:
                        self.project.write_bytes(b"changed")
                with mock.patch.object(morph.os, "link", side_effect=mutate):
                    with self.assertRaisesRegex(RuntimeError, "changed"):
                        self.bounce()
                self.assertFalse(self.output.exists())
                self.project.write_bytes(b'{"saved":"compose"}')
                self.build()

    def test_cancellation_after_hardlink_rolls_back(self):
        signal = [False]
        original = os.link
        def late(src, dst):
            original(src, dst)
            signal[0] = True
        with mock.patch.object(morph.os, "link", side_effect=late):
            with self.assertRaisesRegex(RuntimeError, "cancelled"):
                self.bounce(cancelled=lambda: signal[0])
        self.assertFalse(self.output.exists())

    def test_competitor_and_foreign_replacement_survive(self):
        def competitor(src, dst):
            Path(dst).write_bytes(b"another-writer")
            raise FileExistsError(dst)
        with mock.patch.object(morph.os, "link", side_effect=competitor):
            with self.assertRaises(FileExistsError):
                self.bounce()
        self.assertEqual(self.output.read_bytes(), b"another-writer")
        self.output.unlink()
        original = os.link
        cancelled = [False]
        def replacement(src, dst):
            original(src, dst)
            foreign = self.root / "foreign.wav"
            foreign.write_bytes(b"replacement")
            foreign.replace(dst)
            cancelled[0] = True
        with mock.patch.object(morph.os, "link", side_effect=replacement):
            with self.assertRaisesRegex(RuntimeError, "cancelled"):
                self.bounce(cancelled=lambda: cancelled[0])
        self.assertEqual(self.output.read_bytes(), b"replacement")

    def test_negative_wet_peaks_not_auto_limited(self):
        self.a.fill(-1.5)
        self.b.fill(1.5)
        self.build()
        receipt = self.bounce()
        self.assertTrue(receipt["exceeds_unity_peak"])
        self.assertEqual(float(self.pcm()[0]), -1.5)
        self.assertEqual(float(self.pcm()[-1]), 1.5)


class OriginalComposeTwoRateMorph(unittest.TestCase):
    def test_real_saved_compose_two_rate_numerical_pcm(self):
        root = Path(__file__).resolve().parents[2]
        if not (root / "zaaggenz_runtime" / "nyquismic_offline_audition.py").is_file():
            self.skipTest("requires full original-source Compose renderer")
        from zaaggenz_runtime import nyquismic_production_kit
        from test_nyquismic_compose_delivery import source_document
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            project = folder / "song.zgtimeline.json"
            project.write_text(json.dumps(source_document()), encoding="utf-8")
            kit = folder / "listen-and-daw.zip"
            kr = nyquismic_production_kit.export_saved_compose_kit(
                project, kit, virtual_rates_hz=["4/1", "5/1"])
            out = folder / "rate-morph.wav"
            receipt = morph.bounce_rate_morph(
                kit, out, rate_a_hz="4/1", rate_b_hz="5/1",
                points_ms=["0=0", "150=100"], project_path=project,
                expected_zip_sha256=kr["zip_sha256"])
            with zipfile.ZipFile(kit) as z:
                _, a = wavfile.read(io.BytesIO(z.read("nyq-rate-01.wav")))
                _, b = wavfile.read(io.BytesIO(z.read("nyq-rate-02.wav")))
            hz, actual = wavfile.read(out)
            self.assertEqual((hz, len(actual), receipt["channels"]), (48000, 28800, 1))
            weights = np.minimum(np.arange(len(a), dtype=np.float64) / 7200., 1.)
            oracle = (a.astype(np.float64) + (b.astype(np.float64) - a.astype(np.float64)) * weights).astype(np.float32)
            oracle = np.where(a == b, a, oracle)
            oracle = np.where(weights == 0, a, oracle)
            oracle = np.where(weights == 1, b, oracle)
            np.testing.assert_array_equal(actual, oracle)
            self.assertEqual(receipt["pcm_f32le_sha256"], sha(actual.astype("<f4").tobytes()))
            self.assertEqual(receipt["wav_sha256"], sha(out.read_bytes()))
            self.assertTrue(receipt["trusted_kit_checked"])
            self.assertTrue(receipt["source_project_checked"])
            print("NYQ_TWO_RATE_MORPH_PCM " + json.dumps({
                "source_kit_sha256": receipt["kit_sha256"],
                "frames": receipt["frames"], "delivery_hz": hz,
                "rate_a_pcm_sha256": sha(a.astype("<f4").tobytes()),
                "rate_b_pcm_sha256": sha(b.astype("<f4").tobytes()),
                "morph_pcm_sha256": receipt["pcm_f32le_sha256"],
                "morph_wav_sha256": receipt["wav_sha256"],
            }, sort_keys=True))


if __name__ == "__main__":
    unittest.main(verbosity=2)
