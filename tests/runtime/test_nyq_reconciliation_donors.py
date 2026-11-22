"""Source-exact provenance check for recovered NYQ files (NOT a DSP acceptance gate)."""
from __future__ import annotations
import json
import subprocess
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
RECEIPT = ROOT / "docs/dsp/NYQ_RECONCILIATION_DONORS_20261122.json"


class ReconciledDonorIdentityTests(unittest.TestCase):
    def test_all_57_recovered_files_match_frozen_git_blobs(self):
        packet = json.loads(RECEIPT.read_text(encoding="utf-8"))
        self.assertEqual(packet["format"], "nyq.reconciliation-donor-blobs.v1")
        entries = packet["donors"]
        self.assertEqual(packet["count"], 57)
        self.assertEqual(len(entries), 57)
        seen = set()
        for entry in entries:
            path = entry["path"]
            with self.subTest(donor=entry["donor_pr"], path=path):
                relative = Path(path)
                self.assertFalse(relative.is_absolute())
                self.assertNotIn("..", relative.parts)
                self.assertNotIn(path, seen)
                seen.add(path)
                # GitHub Actions Windows may checkout text as CRLF; the
                # immutable repository blob is LF-normalized. Verify both the
                # checked-in object and Git-cleaned worktree content, without
                # misreporting platform line endings as donor source changes.
                committed = subprocess.check_output(
                    ["git", "rev-parse", "HEAD:" + path],
                    cwd=ROOT, text=True
                ).strip()
                self.assertEqual(committed, entry["blob_sha"])
                cleaned = subprocess.check_output(
                    ["git", "hash-object", "--path=" + path, path],
                    cwd=ROOT, text=True
                ).strip()
                self.assertEqual(cleaned, entry["blob_sha"])
                self.assertEqual(len(entry["donor_head"]), 40)


if __name__ == "__main__":
    unittest.main()
