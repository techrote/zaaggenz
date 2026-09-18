from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))

from zaaggenz_contracts.legacy import adapt_parameters, freeze_legacy
from zaaggenz_harmony import SonoritySpec, SonorityTone, VoiceSpec, VoicingConstraints, solve_progression
from zaaggenz_layers import (
    LayerGeneratorSpec,
    LayerPocketError,
    LayerPocketPlan,
    LayerRuntimeSpec,
    PocketAutomationPoint,
    SidechainPocketSpec,
    StaticPocketSpec,
    apply_layer_pockets,
    render_coordinated_layers,
    render_coordinated_pockets,
)
from zaaggenz_melody import make_melodic_recipe, make_phrase_plan, note_event


CROSSOVERS = (60.0, 500.0, 1800.0)


def _sonority(root, name):
    return SonoritySpec(name, root, (
        SonorityTone("root", degree_offset=0),
        SonorityTone("third", degree_offset=4),
        SonorityTone("fifth", degree_offset=7),
    ))


def _fixture(master_gain_db=-6.0):
    params = adapt_parameters("synth", {"sr": 8000, "bpm": 240.0, "beats": 1, "f0_hz": 48.0})
    frozen = freeze_legacy(params).to_dict()
    tuning, time_map = frozen["tuning"], frozen["time_map"]
    phrase = make_phrase_plan(
        tuning["id"],
        [note_event("lead-source", "0/1", "1/1", tuning["id"], 12, gain_db=-18.0)],
        start_beat="0/1", end_beat="1/1", bass_role="pedal",
    )
    recipe = make_melodic_recipe(
        params, time_map, tuning, phrase, quality="standard", tail_mode="truncate",
        master_gain_db=master_gain_db,
    )
    voices = VoicingConstraints((
        VoiceSpec("sub", "sub", 20, 60, 34, anchor_policy="hold-first"),
        VoiceSpec("body", "body", 36, 90, 56),
        VoiceSpec("aux", "aux", 70, 150, 102),
        VoiceSpec("lead", "synthline", 105, 240, 160),
    ))
    progression = solve_progression(tuning, [_sonority(0, "home")], voices)
    runtime = LayerRuntimeSpec(tuple(
        LayerGeneratorSpec(role, "sine", -24.0, 8, 16, 0.125)
        for role in ("body", "aux", "sub")
    ))
    return recipe, progression, runtime


def _synthetic_stems(n=2048, sr=8000):
    t = np.arange(n, dtype=np.float64) / float(sr)
    body = 0.25 * np.sin(2.0 * np.pi * 240.0 * t)
    detector = np.zeros(n, dtype=np.float64)
    detector[512:1024] = 0.5 * np.sin(2.0 * np.pi * 240.0 * t[512:1024])
    return {
        "synthline": detector,
        "exciter": np.zeros(n, dtype=np.float64),
        "body": body,
        "aux": 0.1 * np.sin(2.0 * np.pi * 900.0 * t),
        "sub": 0.1 * np.sin(2.0 * np.pi * 45.0 * t),
    }


class LayerPocketTests(unittest.TestCase):
    def test_empty_plan_is_bit_exact_runtime_identity(self):
        recipe, progression, runtime = _fixture()
        base = render_coordinated_layers(recipe, progression, ["0/1"], "1/1", runtime)
        result = render_coordinated_pockets(
            recipe, progression, ["0/1"], "1/1", runtime, LayerPocketPlan(CROSSOVERS),
        )
        np.testing.assert_array_equal(result.mix, base.mix)
        for name in base.stems:
            np.testing.assert_array_equal(result.stems[name], base.stems[name])
        self.assertEqual(result.state.to_dict(), base.state.to_dict())
        self.assertEqual(result.diagnostics["pockets"]["normalization"], "none")
        self.assertEqual(result.diagnostics["pockets"]["makeup_gain_db"], 0.0)

    def test_static_pocket_changes_only_declared_persistent_role_and_survives_master(self):
        recipe, progression, runtime = _fixture(master_gain_db=-6.0)
        base = render_coordinated_layers(recipe, progression, ["0/1"], "1/1", runtime)
        plan = LayerPocketPlan(CROSSOVERS, static_pockets=(
            StaticPocketSpec("body", "lowmid", (
                PocketAutomationPoint(0, 12.0),
                PocketAutomationPoint(10000, 12.0),
            )),
        ))
        result = render_coordinated_pockets(recipe, progression, ["0/1"], "1/1", runtime, plan)
        self.assertFalse(np.array_equal(result.stems["body"], base.stems["body"]))
        np.testing.assert_array_equal(result.stems["sub"], base.stems["sub"])
        np.testing.assert_array_equal(result.stems["aux"], base.stems["aux"])
        np.testing.assert_array_equal(result.stems["synthline"], base.stems["synthline"])
        np.testing.assert_array_equal(result.stems["exciter"], base.stems["exciter"])
        self.assertEqual(result.state.to_dict(), base.state.to_dict())
        operation = result.diagnostics["pockets"]["operations"][0]
        self.assertGreater(operation["before_rms"], operation["after_rms"])
        self.assertAlmostEqual(operation["observed_max_attenuation_db"], 12.0, places=9)
        self.assertEqual(operation["makeup_gain_db"], 0.0)
        expected = np.clip(
            np.asarray(result.stems["pre_master"], dtype=np.float64) * (10.0 ** (-6.0 / 20.0)),
            -1.0, 1.0,
        ).astype(np.float32)
        np.testing.assert_allclose(result.mix, expected, rtol=0, atol=2e-7)
        self.assertEqual(result.diagnostics["final_master_owner"], "render-recipe.output")
        self.assertEqual(result.diagnostics["normalization"], "none")

    def test_sidechain_is_bounded_band_limited_and_detector_timed(self):
        stems = _synthetic_stems()
        spec = SidechainPocketSpec(
            "body", "synthline", "lowmid", threshold_dbfs=-36.0,
            attack_samples=4, release_samples=48, lookahead_samples=12,
            max_attenuation_db=9.0,
        )
        output, diagnostics = apply_layer_pockets(
            stems, 8000, LayerPocketPlan(CROSSOVERS, sidechains=(spec,)),
        )
        self.assertFalse(np.array_equal(output["body"], stems["body"]))
        for role in ("synthline", "exciter", "aux", "sub"):
            np.testing.assert_array_equal(output[role], stems[role])
        row = diagnostics["operations"][0]
        self.assertGreater(row["active_samples"], 0)
        self.assertLessEqual(row["observed_max_attenuation_db"], 9.0 + 1e-12)
        self.assertGreater(row["last_active_sample"], 1023)
        self.assertLess(row["first_active_sample"], 512)
        self.assertEqual(row["makeup_gain_db"], 0.0)
        self.assertEqual(diagnostics["filter"]["reconstruction"], "dry + sum(projected effect deltas); dry path never split/recombined")
        leakage = row["band_delta"]["leakage_rms_by_band"]
        self.assertGreater(leakage["lowmid"], leakage["air"])

    def test_muted_detector_disables_sidechain_without_touching_yielding_stem(self):
        stems = _synthetic_stems()
        spec = SidechainPocketSpec(
            "body", "synthline", "lowmid", threshold_dbfs=-80.0,
            attack_samples=0, release_samples=0, lookahead_samples=0,
            max_attenuation_db=12.0,
        )
        output, diagnostics = apply_layer_pockets(
            stems, 8000, LayerPocketPlan(CROSSOVERS, sidechains=(spec,)), muted_roles=("synthline",),
        )
        np.testing.assert_array_equal(output["body"], stems["body"])
        row = diagnostics["operations"][0]
        self.assertTrue(row["detector_muted"])
        self.assertEqual(row["active_samples"], 0)
        self.assertEqual(row["observed_max_attenuation_db"], 0.0)
        self.assertIsNone(row["band_delta"])

    def test_zero_max_sidechain_is_exact_bypass(self):
        stems = _synthetic_stems()
        spec = SidechainPocketSpec(
            "body", "synthline", "lowmid", threshold_dbfs=-80.0,
            attack_samples=0, release_samples=0, lookahead_samples=0,
            max_attenuation_db=0.0,
        )
        output, diagnostics = apply_layer_pockets(stems, 8000, LayerPocketPlan(CROSSOVERS, sidechains=(spec,)))
        np.testing.assert_array_equal(output["body"], stems["body"])
        self.assertEqual(diagnostics["operations"][0]["active_samples"], 0)

    def test_static_automation_is_sample_bounded_and_never_adds_gain(self):
        stems = _synthetic_stems()
        spec = StaticPocketSpec("body", "lowmid", (
            PocketAutomationPoint(0, 0.0),
            PocketAutomationPoint(511, 0.0),
            PocketAutomationPoint(512, 10.0),
            PocketAutomationPoint(1023, 10.0),
            PocketAutomationPoint(1024, 0.0),
            PocketAutomationPoint(2047, 0.0),
        ))
        output, diagnostics = apply_layer_pockets(stems, 8000, LayerPocketPlan(CROSSOVERS, static_pockets=(spec,)))
        row = diagnostics["operations"][0]
        self.assertEqual(row["active_samples"], 512)
        self.assertAlmostEqual(row["observed_max_attenuation_db"], 10.0, places=9)
        self.assertLess(row["after_rms"], row["before_rms"])
        self.assertEqual(diagnostics["makeup_gain_db"], 0.0)
        self.assertTrue(np.isfinite(output["body"]).all())

    def test_ambiguous_duplicate_owner_and_self_sidechain_fail_closed(self):
        static = StaticPocketSpec("body", "lowmid", (PocketAutomationPoint(0, 3.0),))
        dynamic = SidechainPocketSpec("body", "aux", "lowmid", -30.0, 1, 8, 0, 6.0)
        with self.assertRaises(LayerPocketError) as duplicate:
            LayerPocketPlan(CROSSOVERS, static_pockets=(static,), sidechains=(dynamic,))
        self.assertEqual(duplicate.exception.diagnostic["code"], "ambiguous-pocket-order")
        with self.assertRaises(LayerPocketError) as self_chain:
            SidechainPocketSpec("body", "body", "lowmid", -30.0, 1, 8, 0, 6.0)
        self.assertEqual(self_chain.exception.diagnostic["code"], "self-sidechain")

    def test_invalid_crossovers_and_attenuation_fail_before_processing(self):
        stems = _synthetic_stems()
        with self.assertRaises(LayerPocketError):
            PocketAutomationPoint(0, 36.0001)
        bad = LayerPocketPlan((60.0, 500.0, 5000.0), static_pockets=(
            StaticPocketSpec("body", "lowmid", (PocketAutomationPoint(0, 3.0),)),
        ))
        with self.assertRaises(LayerPocketError) as caught:
            apply_layer_pockets(stems, 8000, bad)
        self.assertEqual(caught.exception.diagnostic["code"], "invalid-crossovers")


if __name__ == "__main__":
    unittest.main(verbosity=2)
