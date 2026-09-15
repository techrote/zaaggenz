from __future__ import annotations

import hashlib
import io
from pathlib import Path
import sys
import unittest

import numpy as np
from scipy.io import wavfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "app"))

from zaaggenz_vocal import (  # noqa: E402
    SessionAudioStore,
    VocalCaptureError,
    analyse_vocal,
    decode_wav_bytes,
)

SR = 12_000


def wav_bytes(samples, sample_rate=SR):
    out = io.BytesIO()
    wavfile.write(out, sample_rate, np.asarray(samples))
    return out.getvalue()


class WavDecodeTests(unittest.TestCase):
    def test_uint8_midpoint_endpoints_and_known_amplitudes(self):
        codes = np.array([0, 64, 96, 112, 127, 128, 129, 144, 160, 192, 255], dtype=np.uint8)
        sr, decoded = decode_wav_bytes(wav_bytes(codes))
        expected = (codes.astype(np.float32) - np.float32(128.0)) / np.float32(128.0)

        self.assertEqual(sr, SR)
        self.assertEqual(decoded.dtype, np.float32)
        np.testing.assert_array_equal(decoded, expected)
        self.assertEqual(float(decoded[codes.tolist().index(128)]), 0.0)
        self.assertEqual(float(decoded[0]), -1.0)
        self.assertEqual(float(decoded[-1]), 127.0 / 128.0)
        self.assertEqual(float(decoded[codes.tolist().index(96)]), -0.25)
        self.assertEqual(float(decoded[codes.tolist().index(160)]), 0.25)

    def test_uint8_digital_silence_is_exact_zero_mono_and_stereo(self):
        mono = np.full(257, 128, dtype=np.uint8)
        stereo = np.full((257, 2), 128, dtype=np.uint8)

        _, decoded_mono = decode_wav_bytes(wav_bytes(mono))
        _, decoded_stereo = decode_wav_bytes(wav_bytes(stereo))

        self.assertTrue(np.array_equal(decoded_mono, np.zeros_like(decoded_mono)))
        self.assertTrue(np.array_equal(decoded_stereo, np.zeros_like(decoded_stereo)))

    def test_signed_integer_and_float_controls_keep_existing_normalisation(self):
        int16 = np.array([np.iinfo(np.int16).min, -16384, 0, 16384, np.iinfo(np.int16).max], dtype=np.int16)
        int32 = np.array([np.iinfo(np.int32).min, -(2**30), 0, 2**30, np.iinfo(np.int32).max], dtype=np.int32)
        floating = np.array([-1.25, -0.5, 0.0, 0.5, 1.25], dtype=np.float32)

        _, got16 = decode_wav_bytes(wav_bytes(int16))
        _, got32 = decode_wav_bytes(wav_bytes(int32))
        _, got_float = decode_wav_bytes(wav_bytes(floating))

        np.testing.assert_array_equal(got16, int16.astype(np.float32) / np.float32(32768.0))
        np.testing.assert_array_equal(got32, int32.astype(np.float32) / np.float32(2147483648.0))
        np.testing.assert_array_equal(got_float, floating)

    def test_non_finite_float_wav_remains_rejected(self):
        for bad in (np.nan, np.inf, -np.inf):
            with self.subTest(value=bad):
                payload = wav_bytes(np.array([0.0, bad, 0.0], dtype=np.float32))
                with self.assertRaisesRegex(VocalCaptureError, "non-finite"):
                    decode_wav_bytes(payload)

    def test_corrected_uint8_pcm_drives_capture_and_analysis_identity(self):
        t = np.arange(SR // 2, dtype=np.float64) / SR
        source = 0.25 * np.sin(2.0 * np.pi * 120.0 * t)
        codes = np.clip(np.rint(source * 128.0 + 128.0), 0, 255).astype(np.uint8)
        sr, decoded = decode_wav_bytes(wav_bytes(codes))

        canonical = np.asarray(decoded[:, None], dtype="<f4", order="C").tobytes(order="C")
        sha = hashlib.sha256(canonical).hexdigest()

        store = SessionAudioStore()
        self.assertEqual(store.put(decoded, sr), "capture-" + sha[:16])
        analysis = analyse_vocal(decoded, sr, origin="local-import").to_dict()
        self.assertEqual(analysis["source"]["content_sha256"], sha)
        self.assertEqual(analysis["source"]["identity_domain"], "pcm-f32le-interleaved-v1")


if __name__ == "__main__":
    unittest.main(verbosity=2)
