import subprocess
import unittest
from pathlib import Path
from unittest import mock

import zaaggenz_reference.analysis as analysis


class LoudnessBoundTests(unittest.TestCase):
    def test_loudness_diagnostics_are_spooled_and_tail_bounded(self):
        seen = {}

        def fake_run(args, stdout=None, stderr=None, timeout=None, **kwargs):
            seen["args"] = args
            seen["stdout"] = stdout
            seen["stderr"] = stderr
            seen["timeout"] = timeout
            stderr.write(b"x" * (analysis.LOUDNESS_TAIL_BYTES * 3))
            stderr.write(
                b"\nSummary:\n"
                b"  Integrated loudness:\n"
                b"    I:         -17.2 LUFS\n"
                b"  Loudness range:\n"
                b"    LRA:         5.4 LU\n"
                b"  True peak:\n"
                b"    Peak:       -0.7 dBFS\n"
            )
            return subprocess.CompletedProcess(args, 0)

        with mock.patch.object(analysis.subprocess, "run", side_effect=fake_run):
            result = analysis._loudness(Path("private-reference.flac"))

        self.assertEqual(
            result,
            {
                "integrated_lufs": -17.2,
                "loudness_range_lu": 5.4,
                "true_peak_dbtp": -0.7,
            },
        )
        self.assertEqual(seen["stdout"], subprocess.DEVNULL)
        self.assertIsNot(seen["stderr"], subprocess.PIPE)
        self.assertTrue(hasattr(seen["stderr"], "fileno"))
        self.assertEqual(seen["timeout"], 180)

    def test_loudness_failure_is_transactional(self):
        def fake_run(args, stdout=None, stderr=None, timeout=None, **kwargs):
            stderr.write(b"decoder/filter failure")
            return subprocess.CompletedProcess(args, 1)

        with mock.patch.object(analysis.subprocess, "run", side_effect=fake_run):
            with self.assertRaisesRegex(RuntimeError, "ffmpeg loudness failed"):
                analysis._loudness(Path("private-reference.flac"))

    def test_missing_loudness_summary_fails_closed(self):
        def fake_run(args, stdout=None, stderr=None, timeout=None, **kwargs):
            stderr.write(b"ffmpeg exited successfully without a summary")
            return subprocess.CompletedProcess(args, 0)

        with mock.patch.object(analysis.subprocess, "run", side_effect=fake_run):
            with self.assertRaisesRegex(RuntimeError, "summary missing"):
                analysis._loudness(Path("private-reference.flac"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
