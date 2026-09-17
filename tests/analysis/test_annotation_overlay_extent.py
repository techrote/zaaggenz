import unittest

import numpy as np

from zaaggenz_analysis import analyse_multiresolution, overlay_landmarks
from zaaggenz_analysis.stft import AnalysisError


def annotation(start, end, asset_id="activation"):
    return {
        "segments": [
            {
                "id": "s",
                "asset_id": asset_id,
                "start_sample": start,
                "end_sample": end,
                "label": "turn",
                "section_function": "variation",
                "source": "manual",
                "confidence": 0.8,
            }
        ]
    }


class AnnotationOverlayExtentTests(unittest.TestCase):
    def setUp(self):
        sr = 12000
        t = np.arange(sr // 2) / sr
        self.timeline = analyse_multiresolution(np.sin(2 * np.pi * 440 * t), sr)["short"]
        self.assertEqual(self.timeline.source_frames, 6000)

    def test_valid_48k_source_landmark_resamples_identically(self):
        rows = overlay_landmarks(self.timeline, annotation(4800, 9600), "activation", 48000, 24000)
        self.assertEqual(rows[0]["start_sample"], 1200)
        self.assertEqual(rows[0]["end_sample"], 2400)
        self.assertTrue(rows[0]["frame_indices"])

    def test_exact_source_endpoint_is_allowed(self):
        rows = overlay_landmarks(self.timeline, annotation(19200, 24000), "activation", 48000, 24000)
        self.assertEqual(rows[0]["end_sample"], self.timeline.source_frames)

    def test_one_frame_beyond_source_is_rejected_before_projection(self):
        with self.assertRaisesRegex(AnalysisError, "outside source extent"):
            overlay_landmarks(self.timeline, annotation(19200, 24001), "activation", 48000, 24000)

    def test_negative_reversed_and_zero_length_source_spans_are_rejected(self):
        for start, end in [(-1, 1), (4, 4), (5, 4)]:
            with self.subTest(start=start, end=end), self.assertRaisesRegex(AnalysisError, "outside source extent"):
                overlay_landmarks(self.timeline, annotation(start, end), "activation", 48000, 24000)

    def test_sample_rate_extent_mismatch_is_rejected(self):
        with self.assertRaisesRegex(AnalysisError, "timing metadata does not match"):
            overlay_landmarks(self.timeline, annotation(100, 200), "activation", 44100, 24000)

    def test_legacy_four_argument_surface_derives_a_bounded_extent(self):
        rows = overlay_landmarks(self.timeline, annotation(4800, 9600), "activation", 48000)
        self.assertEqual((rows[0]["start_sample"], rows[0]["end_sample"]), (1200, 2400))
        with self.assertRaisesRegex(AnalysisError, "outside source extent"):
            overlay_landmarks(self.timeline, annotation(0, 24001), "activation", 48000)


if __name__ == "__main__":
    unittest.main(verbosity=2)
