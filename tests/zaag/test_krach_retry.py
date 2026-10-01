"""V2 retry tests verify execution, not subjective success or owner approval."""
from __future__ import annotations
from dataclasses import replace
import hashlib
import json
import tempfile
import unittest
import wave
from pathlib import Path
import numpy as np
from zaaggenz_zaag.krach_retry import (
    RECIPES, REVISION, RetryRecipe, render_retry_source,
    render_retry_phrase, build_retry_pack, _level_match,
)
from zaaggenz_zaag import family, production_presets, render_family_source
from zaaggenz_zaag.model import ZaagFamilyError


class KrachRetryTests(unittest.TestCase):
    def test_four_versioned_candidate_ids_never_enter_production(self):
        self.assertEqual(len(RECIPES), 4)
        self.assertEqual(len({r.id for r in RECIPES}), 4)
        self.assertEqual({r.mechanism for r in RECIPES}, {"pressure", "bounce", "vowel", "motor"})
        self.assertTrue({r.id for r in RECIPES}.isdisjoint(r.id for r in production_presets()))
        self.assertTrue(all(r.classification == "krach-candidate" for r in RECIPES))

    def test_determinism_boundaries_and_no_added_noise_for_all_four(self):
        hashes = []
        for r in RECIPES:
            a, info = render_retry_source(r, 12000)
            b, other = render_retry_source(r, 12000)
            np.testing.assert_array_equal(a, b)
            self.assertEqual(info, other)
            self.assertEqual(len(a), round(12000*60/190*.985))
            self.assertEqual(float(a[0]), 0.)
            self.assertEqual(float(a[-1]), 0.)
            self.assertTrue(np.isfinite(a).all())
            for key in ("noise_level", "roughness", "pitch_jitter_cents", "harmonic_lock_cents", "transient_click"):
                self.assertEqual(info["source_parameters"][key], 0.)
            self.assertEqual(info["oversampling"], 4)
            self.assertFalse(info["production_promoted"])
            hashes.append(info["source_pcm_sha256"])
        self.assertEqual(len(set(hashes)), 4)

    def test_fullrate_is_finite_deterministic_and_does_not_modify_accepted_source(self):
        before = {r.id: (r.to_dict(), render_family_source(r, 12000).diagnostics["output_pcm_sha256"]) for r in production_presets()}
        for r in RECIPES:
            a, info = render_retry_source(r, 48000)
            b, _ = render_retry_source(r, 48000)
            np.testing.assert_array_equal(a, b)
            self.assertTrue(np.isfinite(a).all())
            self.assertEqual(info["internal_rate_hz"], 192000)
        after = {r.id: (r.to_dict(), render_family_source(r, 12000).diagnostics["output_pcm_sha256"]) for r in production_presets()}
        self.assertEqual(before, after)

    def test_bad_rates_bpm_and_controls_fail_closed(self):
        for value in (True, 0, 44100, 96000, "48000"):
            with self.subTest(rate=value), self.assertRaises(ZaagFamilyError):
                render_retry_source(RECIPES[0], value)
        for value in (True, float("nan"), float("inf"), 59.99, 260.01, "190"):
            with self.subTest(bpm=value), self.assertRaises(ZaagFamilyError):
                render_retry_source(RECIPES[0], bpm=value)
        for key, value in (("motion", 1.01), ("drive", float("inf")), ("body_gain", -1.), ("classification", "approved")):
            with self.subTest(key=key), self.assertRaises(ZaagFamilyError):
                replace(RECIPES[0], **{key: value})
        with self.assertRaises(ZaagFamilyError):
            render_retry_source({})

    def test_tempo_boundaries_and_parameter_identity(self):
        for bpm in (60., 260.):
            audio, _ = render_retry_source(RECIPES[0], 12000, bpm=bpm)
            self.assertEqual(len(audio), round(12000*60./bpm*.985))
        a = RECIPES[0]
        b = replace(a, motion=.2)
        self.assertNotEqual(a.sha256, b.sha256)
        self.assertFalse(np.array_equal(render_retry_source(a, 12000)[0], render_retry_source(b, 12000)[0]))

    def test_loop_reproduction_empty_and_bounds(self):
        source, _ = render_retry_source(RECIPES[1], 12000)
        for melodic in (False, True):
            a = render_retry_phrase(source, 12000, bars=2, melodic=melodic)
            b = render_retry_phrase(source, 12000, bars=2, melodic=melodic)
            np.testing.assert_array_equal(a, b)
            self.assertEqual(len(a), round(8*12000*60/190))
            self.assertEqual(float(a[0]), 0.)
            self.assertEqual(float(a[-1]), 0.)
        for bad in (0, 17, True):
            with self.assertRaises(ZaagFamilyError):
                render_retry_phrase(source, 12000, bars=bad)
        for bad in ([], [float("nan")]*64):
            with self.assertRaises(ZaagFamilyError):
                render_retry_phrase(bad, 12000)

    def test_matching_is_single_scalar_with_headroom_not_a_limiter(self):
        x = np.asarray([0., .2, -2., 5., -.8, 0.])
        y, meta = _level_match(x)
        np.testing.assert_allclose(y, x*10**(meta["gain_db"]/20.), rtol=1e-6, atol=1e-8)
        self.assertLessEqual(np.max(np.abs(y)), .920001)
        for bad in ([0.]*64, [float("nan")]*64, []):
            with self.assertRaises(ZaagFamilyError):
                _level_match(bad)

    def test_pack_wavs_manifest_hashes_and_approval_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)/"pack"
            report = build_retry_pack(out, 12000)
            self.assertEqual(report["revision"], REVISION)
            self.assertEqual(report["owner_status"], "pending-owner")
            self.assertEqual(report["owner_decisions"], [])
            self.assertEqual(len(list(out.rglob("*.wav"))), 17)
            for candidate in report["candidates"]:
                self.assertEqual(len(candidate["exports"]), 4)
                for item in candidate["exports"]:
                    p = out/item["path"]
                    self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(), item["sha256"])
                    with wave.open(str(p)) as handle:
                        self.assertEqual((handle.getframerate(), handle.getnchannels(), handle.getsampwidth()), (12000, 1, 3))
            with self.assertRaises(ZaagFamilyError):
                build_retry_pack(out, 12000)
            saved = json.loads((out/"manifest.json").read_text())
            self.assertEqual(report, saved)

if __name__ == "__main__":
    unittest.main(verbosity=2)
