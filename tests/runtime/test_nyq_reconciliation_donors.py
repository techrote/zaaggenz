"""Source-exact provenance check for recovered NYQ files (NOT a DSP acceptance gate)."""
from __future__ import annotations
import hashlib
import json
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
                raw = (ROOT / relative).read_bytes()
                header = b"blob " + str(len(raw)).encode("ascii") + b"\0"
                self.assertEqual(hashlib.sha1(header + raw).hexdigest(), entry["blob_sha"])
                self.assertEqual(len(entry["donor_head"]), 40)


if __name__ == "__main__":
    unittest.main()
