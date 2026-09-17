import copy
import json
import unittest
from pathlib import Path

from zaaggenz_reference import (
    ANNOTATION_COORDINATE_DOMAIN,
    AnnotationError,
    load_annotation_timing,
    load_registry,
    validate_annotation,
)

ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = ROOT / "references" / "private_registry_v1.json"
TIMING_PATH = ROOT / "references" / "annotation_timing_v1.json"
SUGGESTIONS_PATH = ROOT / "references" / "paired_suggestions_v1.json"


def segment(asset_id="activation", start=0, end=1, segment_id="s"):
    return {
        "id": segment_id,
        "asset_id": asset_id,
        "start_sample": start,
        "end_sample": end,
        "section_function": "unknown",
        "label": "boundary fixture",
        "confidence": 0.5,
        "source": "manual",
        "meter_candidates": [],
        "correspondence_group": None,
    }


def annotation(*segments, relations=()):
    return {"version": "1.0.0", "segments": list(segments), "relations": list(relations)}


class AnnotationTimingTests(unittest.TestCase):
    def setUp(self):
        self.registry = load_registry(REGISTRY_PATH)
        self.timing = load_annotation_timing(TIMING_PATH, self.registry)
        self.rows = {row["id"]: row for row in self.timing["assets"]}

    def test_coordinate_domain_and_exact_current_extents(self):
        self.assertEqual(self.timing["coordinate_domain"], ANNOTATION_COORDINATE_DOMAIN)
        self.assertEqual(self.rows["activation"]["sample_rate_hz"], 48000)
        self.assertEqual(self.rows["activation"]["frame_count"], 8_440_548)
        self.assertEqual(self.rows["zaagtivation"]["frame_count"], 10_781_118)
        self.assertEqual(set(self.rows), {row["id"] for row in self.registry["assets"]})

    def test_existing_suggestions_remain_valid_without_rewriting_annotation_bytes(self):
        raw = SUGGESTIONS_PATH.read_bytes()
        data = json.loads(raw)
        self.assertIs(validate_annotation(data, self.timing), data)
        self.assertEqual(raw, SUGGESTIONS_PATH.read_bytes())
        self.assertTrue(all(row["relation"] == "uncertain" for row in data["relations"]))

    def test_canonical_id_allowlist_is_no_longer_id_only_validation(self):
        data = annotation(segment(end=8_440_548))
        self.assertIs(validate_annotation(data, {"activation"}), data)
        bad = annotation(segment(end=8_440_549))
        with self.assertRaisesRegex(AnnotationError, "invalid segment span"):
            validate_annotation(bad, {"activation"})
        with self.assertRaisesRegex(AnnotationError, "unknown annotated asset"):
            validate_annotation(annotation(segment(asset_id="not_registered")), {"not_registered"})

    def test_interior_and_full_asset_half_open_boundary_succeed(self):
        validate_annotation(annotation(segment(start=100, end=200)), self.timing)
        validate_annotation(annotation(segment(start=0, end=self.rows["activation"]["frame_count"])), self.timing)

    def test_out_of_asset_and_invalid_spans_fail(self):
        frame_count = self.rows["activation"]["frame_count"]
        cases = [
            (-1, 1),
            (0, frame_count + 1),
            (5, 5),
            (6, 5),
            (-2, -1),
        ]
        for start, end in cases:
            with self.subTest(start=start, end=end), self.assertRaisesRegex(AnnotationError, "invalid segment span"):
                validate_annotation(annotation(segment(start=start, end=end)), self.timing)

    def test_missing_timing_metadata_fails_closed(self):
        timing = copy.deepcopy(self.timing)
        timing["assets"] = [row for row in timing["assets"] if row["id"] != "activation"]
        with self.assertRaisesRegex(AnnotationError, "unknown annotated asset"):
            validate_annotation(annotation(segment()), timing)

    def test_same_id_rebound_to_different_content_is_rejected(self):
        registry = copy.deepcopy(self.registry)
        registry["assets"][0]["sha256"] = "f" * 64
        with self.assertRaisesRegex(AnnotationError, "content identity mismatch: activation"):
            load_annotation_timing(TIMING_PATH, registry)

    def test_sample_rate_channel_and_frame_count_drift_are_rejected(self):
        for field, value, message in [
            ("sample_rate_hz", 44100, "sample-rate mismatch"),
            ("channels", 1, "channel mismatch"),
        ]:
            registry = copy.deepcopy(self.registry)
            registry["assets"][0]["native"][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(AnnotationError, message):
                load_annotation_timing(TIMING_PATH, registry)
        registry = copy.deepcopy(self.registry)
        registry["assets"][0]["planning"]["decoded_24k_duration_s"] += 1 / 48000
        with self.assertRaisesRegex(AnnotationError, "frame-count mismatch"):
            load_annotation_timing(TIMING_PATH, registry)

    def test_tampered_timing_catalog_is_rejected_before_segment_validation(self):
        timing = copy.deepcopy(self.timing)
        timing["assets"][0]["frame_count"] += 1
        # validate_annotation accepts only a structurally valid timing context; it
        # must not silently repair or infer a different endpoint.
        data = annotation(segment(end=self.rows["activation"]["frame_count"] + 1))
        self.assertIs(validate_annotation(data, timing), data)
        # Binding that same tampered record back to the authoritative registry is
        # what authenticates its frame count and must fail closed.
        with self.assertRaisesRegex(AnnotationError, "frame-count mismatch"):
            load_annotation_timing(TIMING_PATH, {**self.registry})

    def test_relation_and_ambiguous_meter_semantics_are_unchanged(self):
        left = segment("activation", 0, 48000, "a")
        left["meter_candidates"] = [
            {"numerator": 4, "denominator": 4, "pulse_divisor": 1, "confidence": 0.5},
            {"numerator": 4, "denominator": 4, "pulse_divisor": 2, "confidence": 0.4},
        ]
        right = segment("zaagtivation", 0, 48000, "b")
        relation = {
            "id": "r",
            "left_segment": "a",
            "right_segment": "b",
            "relation": "unrelated",
            "confidence": 0.9,
            "source": "manual",
        }
        data = annotation(left, right, relations=(relation,))
        self.assertIs(validate_annotation(data, self.timing), data)


if __name__ == "__main__":
    unittest.main(verbosity=2)
