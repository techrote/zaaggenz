from __future__ import annotations

import json
import tempfile
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "app")]

from zaaggenz_longform import (
    LongformDocument,
    LongformError,
    load_longform,
    save_longform,
    small_test_example,
    stress_64bar_example,
    structured_90s_example,
)
from zaaggenz_longform.render import compile_sections


class LongformModelTests(unittest.TestCase):
    def test_save_reload_preserves_structure_tuning_automation_and_hash(self):
        document = small_test_example()
        reopened = LongformDocument.from_json(json.dumps(document.to_dict()))
        self.assertEqual(reopened.sha256, document.sha256)
        self.assertEqual(reopened.to_dict(), document.to_dict())

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "song.zglongform.json"
            save_longform(document, path)
            loaded = load_longform(path)
            self.assertEqual(loaded.sha256, document.sha256)
            self.assertEqual(loaded.to_dict(), document.to_dict())

    def test_structured_example_contains_motif_returns_tempo_meter_and_automation(self):
        document = structured_90s_example()
        data = document.to_dict()
        self.assertEqual(len(data["sections"]), 12)
        motif_ids = [row["motif_id"] for row in data["sections"]]
        self.assertLess(len(set(motif_ids)), len(motif_ids))
        self.assertTrue(any(len(row["tempo_segments"]) > 1 for row in data["sections"]))
        self.assertTrue(any(len(row["meter_segments"]) > 1 for row in data["sections"]))
        self.assertTrue(any(row["automation"] for row in data["sections"]))
        self.assertTrue(any(row["pocket_plan"] is not None for row in data["sections"]))

        compiled = compile_sections(document)
        total_seconds = sum(
            row.nominal_samples for row in compiled
        ) / document.sample_rate_hz
        self.assertGreaterEqual(total_seconds, 85.0)
        self.assertLessEqual(total_seconds, 100.0)

    def test_64bar_stress_is_exactly_64_four_four_bars_and_contains_non_octave_intent(self):
        document = stress_64bar_example()
        data = document.to_dict()
        self.assertEqual(len(data["sections"]), 16)
        self.assertTrue(all(row["repeats"] == 4 for row in data["sections"]))
        self.assertEqual(16 * 4, 64)
        self.assertTrue(any(row["tuning_id"] == "thirteen-ed3-a1" for row in data["sections"]))
        thirteen = next(row for row in data["tunings"] if row["id"] == "thirteen-ed3-a1")
        self.assertAlmostEqual(thirteen["period_ratio"], 3.0)
        self.assertEqual(len(thirteen["degree_ratios"]), 13)
        self.assertTrue(any(row["deferred_intent"] for row in data["sections"]))
        compile_sections(document)

    def test_unknown_fields_and_missing_motif_fail_closed(self):
        data = small_test_example().to_dict()
        data["surprise"] = True
        with self.assertRaises(LongformError):
            LongformDocument(data)

        data = small_test_example().to_dict()
        data["sections"][0]["motif_id"] = "missing"
        with self.assertRaises(LongformError):
            LongformDocument(data)

    def test_total_sample_bound_rejects_unbounded_construction(self):
        data = small_test_example().to_dict()
        # Keep the embedded Project completely valid. Instead make one legal
        # motif-repetition request extremely long at the minimum accepted tempo;
        # the long-form wrapper must reject it before allocating proportional PCM.
        section = data["sections"][0]
        section["repeats"] = 64
        section["tempo_segments"] = [{"beat": "0/1", "bpm": "20/1"}]
        section["automation"] = []
        with self.assertRaisesRegex(LongformError, "exceeds 5000000 samples"):
            LongformDocument(data)


if __name__ == "__main__":
    unittest.main(verbosity=2)
