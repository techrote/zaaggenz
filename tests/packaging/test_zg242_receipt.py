"""Synthetic verifier tests only: never evidence of physical Windows acceptance."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from scipy.io import wavfile

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("zg242_receipt", ROOT / "tools" / "zg242_receipt.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class PhysicalReceiptVerifierTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.p = Path(self.temp.name)
        (self.p / "project.json").write_text('{"saved":true}')
        (self.p / "rack.json").write_text('{"preset":true}')
        (self.p / "wheel.whl").write_bytes(b"built-wheel-fixture")
        (self.p / "first.png").write_bytes(PNG_SIGNATURE + b"first-session-fixture")
        (self.p / "second.png").write_bytes(PNG_SIGNATURE + b"reopen-session-fixture")
        pcm = (0.2 * np.sin(np.arange(480, dtype=np.float64) * 0.08)).astype(np.float32)
        for name in ("before.wav", "after.wav", "dry.wav", "bypass.wav"):
            wavfile.write(self.p / name, 48000, pcm)
        self.kw = {k: str(self.p / fname) for k, fname in {
            "project": "project.json", "preset": "rack.json", "before": "before.wav",
            "after": "after.wav", "dry": "dry.wav", "bypass": "bypass.wav",
            "screenshot_first": "first.png", "screenshot_second": "second.png",
            "wheel": "wheel.whl", "snapshot": "snapshot.json", "sessions": "sessions.json",
            "identity": "identity.json", "output": "report.json"}.items()}
        self._json("identity.json", {"schema": "zg242-installed-identity-v1",
                                     "release_ids": {"timeline": "f" * 64}, "package_version": "0.1.0.dev0"})
        self._json("sessions.json", {"schema": "zg242-physical-session-v1", "stages": [{
            "ready": True, "process_exited": True, "exit_code": 0,
            "operator_attested_ctrl_c": True, "operator_attested_workflow": True,
            "startup_utc": "2026-11-09T12:00:00Z", "shutdown_utc": "2026-11-09T12:20:00Z",
            "console_log_sha256": "a" * 64} for _ in range(2)]})

    def _json(self, file, obj):
        (self.p / file).write_text(json.dumps(obj))

    def run_snapshot(self):
        fields = ["project", "preset", "before", "dry", "bypass", "screenshot_first", "wheel"]
        args = ["snapshot"] + sum(([f"--{k.replace('_', '-')}", self.kw[k]] for k in fields), [])
        return mod.main(args + ["--accepted-main-sha", "d" * 40,
                                "--harness-sha", "e" * 40, "--output", self.kw["snapshot"]])

    def run_finalize(self):
        fields = ["project", "preset", "before", "after", "dry", "bypass",
                  "screenshot_second", "wheel", "snapshot", "sessions", "identity", "output"]
        return mod.main(["finalize"] + sum(([f"--{k.replace('_', '-')}", self.kw[k]] for k in fields), []))

    def test_snapshot_and_receipt_are_explicitly_not_admission(self):
        self.assertEqual(self.run_snapshot(), 0)
        self.assertEqual(self.run_finalize(), 0)
        receipt = json.loads(Path(self.kw["output"]).read_text())
        self.assertFalse(receipt["admission"])
        self.assertTrue(receipt["checks"]["same_host_cold_reopen_pcm_exact"])
        self.assertNotIn(str(self.p), json.dumps(receipt))
        self.assertEqual(receipt["artifacts"]["before"]["rate"], 48000)

    def test_missing_or_counterfeit_screenshot_fails(self):
        (self.p / "first.png").write_bytes(b"not a real png")
        self.assertEqual(self.run_snapshot(), 2)
        (self.p / "first.png").unlink()
        self.assertEqual(self.run_snapshot(), 2)

    def test_wrong_rate_and_sample_format_fail(self):
        wavfile.write(self.p / "before.wav", 44100, np.zeros(16, np.float32))
        self.assertEqual(self.run_snapshot(), 2)
        wavfile.write(self.p / "before.wav", 48000, np.zeros(16, np.int16))
        self.assertEqual(self.run_snapshot(), 2)

    def test_bypass_mismatch_fails(self):
        wavfile.write(self.p / "bypass.wav", 48000, np.ones(480, np.float32))
        self.assertEqual(self.run_snapshot(), 2)

    def test_changed_preset_and_reopen_audio_fail(self):
        self.assertEqual(self.run_snapshot(), 0)
        (self.p / "rack.json").write_text('{"preset":false}')
        self.assertEqual(self.run_finalize(), 2)
        (self.p / "rack.json").write_text('{"preset":true}')
        wavfile.write(self.p / "after.wav", 48000, np.zeros(480, np.float32))
        self.assertEqual(self.run_finalize(), 2)

    def test_windows_powershell_bom_metadata(self):
        self.assertEqual(self.run_snapshot(), 0)
        for filename in ("identity.json", "sessions.json"):
            path = self.p / filename
            path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
        self.assertEqual(self.run_finalize(), 0)

    def test_bad_process_attestation_and_missing_release_id_fail(self):
        self.assertEqual(self.run_snapshot(), 0)
        sessions = json.loads((self.p / "sessions.json").read_text())
        sessions["stages"][1]["operator_attested_ctrl_c"] = False
        self._json("sessions.json", sessions)
        self.assertEqual(self.run_finalize(), 2)
        sessions["stages"][1]["operator_attested_ctrl_c"] = True
        self._json("sessions.json", sessions)
        self._json("identity.json", {"schema": "zg242-installed-identity-v1", "package_version": "0.1.0.dev0"})
        self.assertEqual(self.run_finalize(), 2)


if __name__ == "__main__":
    unittest.main()
