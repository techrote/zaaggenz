from __future__ import annotations

from copy import deepcopy
import unittest

import numpy as np

from zaaggenz_longform import LongformDocument, render_longform, small_test_example
from zaaggenz_longform.export import simple_note_export
from zaaggenz_longform.render import compile_sections


class LongformRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = small_test_example()
        cls.result = render_longform(cls.document)

    def test_mix_and_all_stems_are_sample_aligned(self):
        result = self.result
        self.assertGreater(len(result.mix), 0)
        for name in (
            "synthline",
            "exciter",
            "source_bus",
            "body",
            "aux",
            "sub",
            "pre_master",
        ):
            with self.subTest(stem=name):
                self.assertEqual(len(result.stems[name]), len(result.mix))
        self.assertGreater(float(np.max(np.abs(result.stems["synthline"]))), 0.0)
        self.assertGreater(float(np.max(np.abs(result.stems["exciter"]))), 0.0)
        self.assertGreater(float(np.max(np.abs(result.stems["body"]))), 0.0)
        self.assertGreater(float(np.max(np.abs(result.stems["aux"]))), 0.0)
        self.assertGreater(float(np.max(np.abs(result.stems["sub"]))), 0.0)

    def test_pre_master_ownership_and_one_final_master_are_explicit(self):
        result = self.result
        expected_pre = (
            np.asarray(result.stems["source_bus"], dtype=np.float64)
            + np.asarray(result.stems["body"], dtype=np.float64)
            + np.asarray(result.stems["aux"], dtype=np.float64)
            + np.asarray(result.stems["sub"], dtype=np.float64)
        ).astype(np.float32)
        np.testing.assert_allclose(
            result.stems["pre_master"], expected_pre, rtol=0, atol=4e-7
        )
        expected_mix = np.clip(
            np.asarray(result.stems["pre_master"], dtype=np.float64)
            * (10.0 ** (-6.0 / 20.0)),
            -1.0,
            1.0,
        ).astype(np.float32)
        np.testing.assert_allclose(result.mix, expected_mix, rtol=0, atol=4e-7)
        self.assertEqual(result.diagnostics["final_master_owner"], "render-recipe.output")
        self.assertEqual(result.diagnostics["normalization"], "none")
        self.assertIn("post-source-topology", result.diagnostics["automation_stage"])

    def test_save_reload_render_is_deterministic(self):
        reopened = LongformDocument.from_json(
            __import__("json").dumps(self.document.to_dict())
        )
        again = render_longform(reopened)
        self.assertEqual(again.diagnostics["mix_sha256"], self.result.diagnostics["mix_sha256"])
        self.assertEqual(
            again.diagnostics["stem_sha256"],
            self.result.diagnostics["stem_sha256"],
        )
        self.assertEqual(again.final_runtime_state, self.result.final_runtime_state)
        self.assertEqual(again.section_ranges, self.result.section_ranges)

    def test_persistent_release_tail_crosses_section_boundary_without_shifting_stems(self):
        data = self.document.to_dict()
        # Leave one beat empty at the start of section B. ZG-042 state should
        # continue the prior BODY/AUX/SUB release rather than reset at the file
        # concatenation boundary.
        second = data["sections"][1]
        second["harmony_frames"] = [
            {"beat": "1/1", "duration_beats": "1/1", "root_degree": 0},
            {"beat": "2/1", "duration_beats": "2/1", "root_degree": 4},
        ]
        document = LongformDocument(data)
        result = render_longform(document)
        boundary = result.section_ranges[0]["end_sample"]
        body = np.asarray(result.stems["body"], dtype=np.float64)
        self.assertGreater(float(np.max(np.abs(body[boundary:boundary + 128]))), 0.0)
        self.assertEqual(result.section_ranges[1]["start_sample"], boundary)
        self.assertEqual(len(result.stems["body"]), len(result.mix))

    def test_simple_note_export_warns_instead_of_silently_collapsing_intent(self):
        payload = simple_note_export(self.document, self.result)
        codes = {row["code"] for row in payload["warnings"]}
        self.assertIn("non-12tet-tuning", codes)
        self.assertIn("microtonal-static-offset", codes)
        self.assertIn("timbral-gesture-not-note-exportable", codes)
        self.assertIn("pre-master-automation-not-note-exportable", codes)
        self.assertIn("no-exact-midi-note", codes)
        self.assertEqual(
            payload["layer_ownership"]["source_bus"],
            "processed shared source contribution after preserved source topology",
        )
        self.assertEqual(
            payload["layer_ownership"]["mix"],
            "single final RenderRecipe.output owner",
        )
        exact = [
            row
            for row in payload["events"]
            if not row["rest"] and row["midi_note_12tet"] is not None
        ]
        self.assertTrue(exact)
        self.assertTrue(all("frequency_hz" in row for row in payload["events"] if not row["rest"]))

    def test_section_ranges_are_contiguous_and_cover_mix(self):
        cursor = 0
        for row in self.result.section_ranges:
            self.assertEqual(row["start_sample"], cursor)
            self.assertGreater(row["end_sample"], row["start_sample"])
            cursor = row["end_sample"]
        self.assertEqual(cursor, len(self.result.mix))


if __name__ == "__main__":
    unittest.main(verbosity=2)
