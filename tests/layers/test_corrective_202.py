from __future__ import annotations

import hashlib
import json
import unittest

import numpy as np

from tests.layers.test_pockets import CROSSOVERS
from tests.layers.test_runtime import _fixture as runtime_fixture, _spec
from zaaggenz_contracts import ownership_manifest, section_transition_manifest
from zaaggenz_layers import (
    LayerGeneratorSpec,
    LayerPocketPlan,
    LayerRuntimeError,
    LayerRuntimeSpec,
    LayerRuntimeState,
    LayerTransformTarget,
    PocketAutomationPoint,
    StaticPocketSpec,
    render_coordinated_layers,
    render_coordinated_pockets,
)
from zaaggenz_melody import render_phrase


def _sha_f32le(audio):
    return hashlib.sha256(np.asarray(audio, dtype="<f4").tobytes()).hexdigest()


class Corrective202RuntimeEvidenceTests(unittest.TestCase):
    def test_source_stems_are_independent_pcm_and_remain_hash_bound_through_pockets(self):
        recipe, progression, beats, durations = runtime_fixture(master_gain_db=-6.0)
        runtime = _spec()
        source = render_phrase(recipe)
        full = render_coordinated_layers(recipe, progression, beats, durations, runtime)

        # Real PCM comparisons: coordinated rendering keeps the accepted source
        # renderer authoritative rather than inferring preservation from role labels.
        np.testing.assert_array_equal(
            full.stems["synthline"][: len(source.stems["synthline"])],
            source.stems["synthline"],
        )
        np.testing.assert_array_equal(
            full.stems["exciter"][: len(source.stems["exciter"])],
            source.stems["exciter"],
        )

        without_exciter = render_coordinated_layers(
            recipe, progression, beats, durations, runtime, muted_roles=("exciter",)
        )
        without_synthline = render_coordinated_layers(
            recipe, progression, beats, durations, runtime, muted_roles=("synthline",)
        )
        # Exciter removal cannot remove or replace full SYNTHLINE.
        np.testing.assert_array_equal(
            without_exciter.stems["synthline"], full.stems["synthline"]
        )
        np.testing.assert_array_equal(
            without_exciter.stems["exciter"], np.zeros_like(full.stems["exciter"])
        )
        # SYNTHLINE muting occurs before its preserved topology.  The processed
        # synthline-named stem need not be numerically zero because an independently
        # retained exciter may still traverse that topology, but the mute must alter
        # SYNTHLINE while leaving the exciter stem itself byte-identical.
        self.assertFalse(
            np.array_equal(without_synthline.stems["synthline"], full.stems["synthline"])
        )
        np.testing.assert_array_equal(
            without_synthline.stems["exciter"], full.stems["exciter"]
        )

        synth_sha = _sha_f32le(full.stems["synthline"])
        exciter_sha = _sha_f32le(full.stems["exciter"])
        self.assertEqual(full.diagnostics["recipe_sha256"], recipe.sha256)
        self.assertEqual(full.diagnostics["stem_sha256"]["synthline"], synth_sha)
        self.assertEqual(full.diagnostics["stem_sha256"]["exciter"], exciter_sha)

        plan = LayerPocketPlan(
            CROSSOVERS,
            static_pockets=(
                StaticPocketSpec("body", "lowmid", (PocketAutomationPoint(0, 6.0),)),
            ),
        )
        pocketed = render_coordinated_pockets(
            recipe, progression, beats, durations, runtime, plan
        )
        self.assertFalse(np.array_equal(pocketed.stems["body"], full.stems["body"]))
        np.testing.assert_array_equal(
            pocketed.stems["synthline"], full.stems["synthline"]
        )
        np.testing.assert_array_equal(
            pocketed.stems["exciter"], full.stems["exciter"]
        )
        self.assertEqual(pocketed.diagnostics["recipe_sha256"], recipe.sha256)
        self.assertEqual(pocketed.diagnostics["stem_sha256"]["synthline"], synth_sha)
        self.assertEqual(pocketed.diagnostics["stem_sha256"]["exciter"], exciter_sha)
        self.assertEqual(pocketed.diagnostics["pockets"]["makeup_gain_db"], 0.0)

    def test_pocketed_save_reload_continue_preserves_state_and_one_final_master(self):
        recipe, progression, beats, durations = runtime_fixture(master_gain_db=-9.0)
        runtime = _spec(release=64, glide=8)
        plan = LayerPocketPlan(
            CROSSOVERS,
            static_pockets=(
                StaticPocketSpec("body", "lowmid", (PocketAutomationPoint(0, 9.0),)),
            ),
        )
        first = render_coordinated_pockets(
            recipe, progression, beats, durations, runtime, plan
        )
        reloaded = LayerRuntimeState.from_dict(
            json.loads(json.dumps(first.state.to_dict(), allow_nan=False))
        )
        ownership = ownership_manifest(
            recipe.to_dict()["phrase"], phase_policy=recipe.to_dict()["phase_policy"]
        )
        transition = section_transition_manifest(
            ownership, boundary_id="corrective-202-next"
        )

        direct = render_coordinated_pockets(
            recipe,
            progression,
            beats,
            durations,
            runtime,
            plan,
            state=first.state,
            section_transition=transition,
        )
        roundtrip = render_coordinated_pockets(
            recipe,
            progression,
            beats,
            durations,
            runtime,
            plan,
            state=reloaded,
            section_transition=transition,
        )
        np.testing.assert_array_equal(direct.mix, roundtrip.mix)
        for name in direct.stems:
            np.testing.assert_array_equal(direct.stems[name], roundtrip.stems[name])
        self.assertEqual(direct.state.to_dict(), roundtrip.state.to_dict())

        unpocketed = render_coordinated_layers(
            recipe,
            progression,
            beats,
            durations,
            runtime,
            state=first.state,
            section_transition=transition,
        )
        np.testing.assert_array_equal(direct.stems["sub"], unpocketed.stems["sub"])
        np.testing.assert_array_equal(
            direct.stems["synthline"], unpocketed.stems["synthline"]
        )
        self.assertEqual(direct.state.to_dict(), unpocketed.state.to_dict())

        expected = np.clip(
            np.asarray(direct.stems["pre_master"], dtype=np.float64)
            * (10.0 ** (-9.0 / 20.0)),
            -1.0,
            1.0,
        ).astype(np.float32)
        np.testing.assert_allclose(direct.mix, expected, rtol=0, atol=2e-7)
        self.assertEqual(
            direct.diagnostics["final_master_owner"], "render-recipe.output"
        )
        self.assertEqual(direct.diagnostics["normalization"], "none")
        self.assertEqual(direct.diagnostics["pockets"]["makeup_gain_db"], 0.0)
        self.assertIn(
            "RenderRecipe.output once", direct.diagnostics["pocket_master_path"]
        )

    def test_transform_conflict_and_infeasible_runtime_inputs_fail_closed(self):
        recipe, progression, beats, durations = runtime_fixture()
        competing = (
            {"layer": "body", "quantity": "retune", "owner": "adaptive"},
            {"layer": "body", "quantity": "retune", "owner": "spectral"},
        )
        with self.assertRaises(LayerRuntimeError) as conflict:
            render_coordinated_layers(
                recipe, progression, beats, durations, _spec(claims=competing)
            )
        self.assertEqual(
            conflict.exception.diagnostic["code"], "competing-transform-owners"
        )

        ordered = (
            {"layer": "body", "quantity": "retune", "owner": "adaptive", "order": 0},
            {"layer": "body", "quantity": "retune", "owner": "spectral", "order": 1},
        )
        targets = (
            LayerTransformTarget("body", "retune", "adaptive", 10.0, "body"),
            LayerTransformTarget("body", "retune", "spectral", -3.0, "body"),
        )
        result = render_coordinated_layers(
            recipe,
            progression,
            beats,
            durations,
            _spec(claims=ordered, targets=targets),
        )
        row = next(
            item
            for item in result.diagnostics["voice_trace"]
            if item["voice_id"] == "body"
        )
        self.assertEqual(
            [
                (item["owner"], item["order"], item["state"])
                for item in row["retune_trace"]
            ],
            [("adaptive", 0, "applied"), ("spectral", 1, "applied")],
        )
        self.assertAlmostEqual(row["retune_cents"], 7.0)

        missing = LayerRuntimeSpec(
            (LayerGeneratorSpec("body", "sine", -30.0, 0, 0),)
        )
        with self.assertRaises(LayerRuntimeError) as infeasible:
            render_coordinated_layers(recipe, progression, beats, durations, missing)
        self.assertEqual(
            infeasible.exception.diagnostic["code"], "missing-persistent-generator"
        )
        self.assertEqual(
            infeasible.exception.diagnostic["missing_roles"], ["aux", "sub"]
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
