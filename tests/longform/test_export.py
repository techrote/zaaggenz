from __future__ import annotations

import hashlib
import json
import tempfile
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "app")]

from scipy.io import wavfile

from zaaggenz_longform import export_longform, load_longform, render_longform, small_test_example


class LongformExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = small_test_example()
        cls.result = render_longform(cls.document)

    def test_export_bundle_has_aligned_mix_and_owned_stems_with_verified_hashes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = export_longform(self.document, root, result=self.result)
            required = {
                "mix.wav",
                "stem-synthline.wav",
                "stem-exciter.wav",
                "stem-body.wav",
                "stem-aux.wav",
                "stem-sub.wav",
                "stem-source_bus.wav",
                "stem-pre_master.wav",
                "project.zglongform.json",
                "tunings.json",
                "grammars.json",
                "note-events.json",
            }
            self.assertTrue(required <= set(manifest["files"]))
            for name in required:
                payload = (root / name).read_bytes()
                self.assertEqual(
                    hashlib.sha256(payload).hexdigest(),
                    manifest["files"][name]["sha256"],
                )
                self.assertEqual(len(payload), manifest["files"][name]["bytes"])

            frame_counts = {}
            for name in required:
                if name.endswith(".wav"):
                    sr, audio = wavfile.read(root / name)
                    self.assertEqual(sr, self.result.sample_rate_hz)
                    frame_counts[name] = len(audio)
            self.assertEqual(set(frame_counts.values()), {len(self.result.mix)})

            reopened = load_longform(root / "project.zglongform.json")
            self.assertEqual(reopened.sha256, self.document.sha256)
            note_export = json.loads((root / "note-events.json").read_text())
            self.assertTrue(note_export["warnings"])
            self.assertEqual(
                note_export["source_document_sha256"], self.document.sha256
            )
            self.assertEqual(
                manifest["final_master_owner"], "render-recipe.output"
            )
            self.assertEqual(
                manifest["frame_count"], len(self.result.mix)
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
