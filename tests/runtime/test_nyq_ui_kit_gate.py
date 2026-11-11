"""Adversarial provenance checks for the real Compose-to-NYQ original-host gate."""
from __future__ import annotations

import copy
import unittest

from tools.nyq_ui_kit_gate import assert_kit_source_matches_ui


class UiKitSourceAnchorTests(unittest.TestCase):
    def setUp(self):
        self.project_sha = "1" * 64
        self.export = {
            "revision_id": "2" * 64,
            "recipe_sha256": "3" * 64,
            "pcm_sha256": "4" * 64,
            "frames": 57600,
            "channels": 1,
        }
        self.manifest = {"source": {
            "project_file_sha256": self.project_sha,
            "source_revision_sha256": self.export["revision_id"],
            "compose_recipe_sha256": self.export["recipe_sha256"],
            "dry_pcm_f32le_sha256": self.export["pcm_sha256"],
            "frames": 57600,
            "channels": 1,
        }}

    def test_actual_ui_source_anchor_passes(self):
        assert_kit_source_matches_ui(self.manifest, self.export, self.project_sha)

    def test_self_consistent_foreign_kit_identity_is_rejected(self):
        for key in ("project_file_sha256", "source_revision_sha256",
                    "compose_recipe_sha256", "dry_pcm_f32le_sha256"):
            with self.subTest(key=key):
                foreign = copy.deepcopy(self.manifest)
                foreign["source"][key] = "f" * 64
                with self.assertRaisesRegex(RuntimeError, key):
                    assert_kit_source_matches_ui(foreign, self.export, self.project_sha)

    def test_missing_or_invalid_ui_evidence_is_rejected(self):
        for key in ("revision_id", "recipe_sha256", "pcm_sha256"):
            with self.subTest(key=key):
                ui = dict(self.export)
                ui.pop(key)
                with self.assertRaisesRegex(RuntimeError, "differs"):
                    assert_kit_source_matches_ui(self.manifest, ui, self.project_sha)
        with self.assertRaisesRegex(RuntimeError, "source-authentication"):
            assert_kit_source_matches_ui({}, self.export, self.project_sha)

    def test_extent_mismatch_is_rejected(self):
        for key in ("frames", "channels"):
            with self.subTest(key=key):
                foreign = copy.deepcopy(self.manifest)
                foreign["source"][key] += 1
                with self.assertRaisesRegex(RuntimeError, key):
                    assert_kit_source_matches_ui(foreign, self.export, self.project_sha)


if __name__ == "__main__":
    unittest.main()
