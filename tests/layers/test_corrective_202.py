from __future__ import annotations

import hashlib
import json
import unittest

import numpy as np

from tests.layers.test_pockets import CROSSOVERS
from tests.layers.test_runtime import _fixture as runtime_fixture, _spec
from zaaggenz_contracts import Contract, ownership_manifest, section_transition_manifest
from zaaggenz_contracts.legacy import envelope
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


def _with_nonzero_exciter(recipe):
    """Add an explicit source-owned roll gesture without changing layer semantics."""
    data = recipe.to_dict()
    gesture = envelope(
        "GestureSpec",
        id="corrective-202-roll",
        duration_beats="1/2",
        curves=[
            {
                "axis": "density_per_beat",
                "unit": "events/beat",
                "interpolation": "step",
                "points": [
                    {"beat": "0/1", "value": 4.0},
                    {"beat": "1/2", "value": 4.0},
                ],
            }
        ],
    )
    data["phrase"]["gestures"] = [gesture]
    data["phrase"]["events"][0]["gesture_id"] = "corrective-202-roll"
    return Contract(data)


def _with_topology(recipe, type_id, params):
    """Attach one preserved source-bus topology node without changing source identity."""
    data = recipe.to_dict()
    node_id = "corrective-202-source-topology"
    data["nodes"] = [
        envelope(
            "DSPNodeSpec",
            id=node_id,
            type_id=type_id,
            inputs=[data["source"]["id"]],
            channels=1,
            params=dict(params),
            state_policy="stateless",
            phase_policy="source-derived",
            latency_samples=0,
            lookahead_samples=0,
            bypass="identity",
            automation=[],
        )
    ]
    data["output_node"] = node_id
    data["sculpt"] = None
    return Contract(data)


class Corrective202RuntimeEvidenceTests(unittest.TestCase):
    def test_source_stems_are_independent_pcm_and_remain_hash_bound_through_pockets(self):
        recipe, progression, beats, durations = runtime_fixture(master_gain_db=-6.0)
        recipe = _with_nonzero_exciter(recipe)
        runtime = _spec()
        source = render_phrase(recipe)
        self.assertGreater(float(np.max(np.abs(source.stems["exciter"]), initial=0)), 0.0)
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
        # Mute is an assembly decision: first-class raw audition stems are retained
        # for inspection/null tests while the returned audible mix changes. Muting
        # one source role must never delete, substitute, or rewrite either stem.
        for muted_result in (without_exciter, without_synthline):
            np.testing.assert_array_equal(
                muted_result.stems["synthline"], full.stems["synthline"]
            )
            np.testing.assert_array_equal(
                muted_result.stems["exciter"], full.stems["exciter"]
            )
        self.assertFalse(np.array_equal(without_exciter.mix, full.mix))
        self.assertFalse(np.array_equal(without_synthline.mix, full.mix))
        self.assertFalse(np.array_equal(without_exciter.mix, without_synthline.mix))

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
        np.testing.assert_array_equal(
            pocketed.stems["source_bus"], full.stems["source_bus"]
        )
        self.assertEqual(pocketed.diagnostics["recipe_sha256"], recipe.sha256)
        self.assertEqual(pocketed.diagnostics["stem_sha256"]["synthline"], synth_sha)
        self.assertEqual(pocketed.diagnostics["stem_sha256"]["exciter"], exciter_sha)
        self.assertEqual(pocketed.diagnostics["pockets"]["makeup_gain_db"], 0.0)

    def test_linear_topology_exposes_raw_audition_stems_and_exact_processed_source_bus(self):
        recipe, progression, beats, durations = runtime_fixture(master_gain_db=0.0)
        recipe = _with_topology(
            _with_nonzero_exciter(recipe), "core.gain.v1", {"gain_db": -9.0}
        )
        runtime = _spec()
        source = render_phrase(recipe)
        result = render_coordinated_layers(
            recipe, progression, beats, durations, runtime
        )

        # Raw audition/null stems remain the accepted ZG-008 source evidence.
        np.testing.assert_array_equal(
            result.stems["synthline"][: len(source.stems["synthline"])],
            source.stems["synthline"],
        )
        np.testing.assert_array_equal(
            result.stems["exciter"][: len(source.stems["exciter"])],
            source.stems["exciter"],
        )
        # With no source-role mute, the source bus is exactly the accepted ZG-008
        # post-topology pre-master source contribution.
        np.testing.assert_array_equal(
            result.stems["source_bus"][: len(source.stems["pre_master"])],
            source.stems["pre_master"],
        )

        gain = 10.0 ** (-9.0 / 20.0)
        expected_bus = (
            np.asarray(result.stems["synthline"], dtype=np.float64)
            + np.asarray(result.stems["exciter"], dtype=np.float64)
        ) * gain
        np.testing.assert_allclose(
            result.stems["source_bus"], expected_bus, rtol=2e-6, atol=3e-7
        )

        reconstructed = (
            np.asarray(result.stems["source_bus"], dtype=np.float64)
            + np.asarray(result.stems["body"], dtype=np.float64)
            + np.asarray(result.stems["aux"], dtype=np.float64)
            + np.asarray(result.stems["sub"], dtype=np.float64)
        )
        np.testing.assert_allclose(
            result.stems["pre_master"], reconstructed, rtol=0, atol=3e-7
        )
        self.assertEqual(
            result.diagnostics["source_bus"]["position"],
            "post-preserved-synthline-topology-pre-master",
        )
        self.assertEqual(
            result.diagnostics["source_bus"]["input_domain"], "raw-source-audition"
        )

    def test_nonlinear_topology_mutes_before_shared_bus_and_is_not_additively_decomposed(self):
        recipe, progression, beats, durations = runtime_fixture(master_gain_db=0.0)
        recipe = _with_topology(
            _with_nonzero_exciter(recipe),
            "core.tanh.v1",
            {"drive_db": 36.0, "mix": 1.0},
        )
        runtime = _spec()
        source = render_phrase(recipe)
        full = render_coordinated_layers(
            recipe, progression, beats, durations, runtime
        )
        synth_solo = render_coordinated_layers(
            recipe,
            progression,
            beats,
            durations,
            runtime,
            muted_roles=("exciter", "body", "aux", "sub"),
        )
        exciter_solo = render_coordinated_layers(
            recipe,
            progression,
            beats,
            durations,
            runtime,
            muted_roles=("synthline", "body", "aux", "sub"),
        )
        source_silence = render_coordinated_layers(
            recipe,
            progression,
            beats,
            durations,
            runtime,
            muted_roles=("synthline", "exciter", "body", "aux", "sub"),
        )

        # Full unmuted coordination keeps the accepted protected source output exact.
        np.testing.assert_array_equal(
            full.stems["source_bus"][: len(source.stems["pre_master"])],
            source.stems["pre_master"],
        )
        # Mute/solo is an assembly choice before the shared nonlinear topology; it
        # never rewrites the retained raw audition/null evidence.
        for result in (synth_solo, exciter_solo, source_silence):
            np.testing.assert_array_equal(
                result.stems["synthline"], full.stems["synthline"]
            )
            np.testing.assert_array_equal(
                result.stems["exciter"], full.stems["exciter"]
            )
        np.testing.assert_allclose(
            synth_solo.stems["pre_master"],
            synth_solo.stems["source_bus"],
            rtol=0,
            atol=3e-7,
        )
        np.testing.assert_allclose(
            exciter_solo.stems["pre_master"],
            exciter_solo.stems["source_bus"],
            rtol=0,
            atol=3e-7,
        )
        self.assertEqual(float(np.max(np.abs(source_silence.stems["source_bus"]))), 0.0)
        self.assertEqual(float(np.max(np.abs(source_silence.stems["pre_master"]))), 0.0)

        # This is the regression that the old "two independent pre-master source
        # stems" wording could not represent: shared nonlinear processing is not
        # additively decomposable into separately processed solo buses.
        solo_sum = (
            np.asarray(synth_solo.stems["source_bus"], dtype=np.float64)
            + np.asarray(exciter_solo.stems["source_bus"], dtype=np.float64)
        )
        nonadditivity = float(
            np.max(
                np.abs(
                    np.asarray(full.stems["source_bus"], dtype=np.float64)
                    - solo_sum
                )
            )
        )
        self.assertGreater(nonadditivity, 1e-4)

        reconstructed = (
            np.asarray(full.stems["source_bus"], dtype=np.float64)
            + np.asarray(full.stems["body"], dtype=np.float64)
            + np.asarray(full.stems["aux"], dtype=np.float64)
            + np.asarray(full.stems["sub"], dtype=np.float64)
        )
        np.testing.assert_allclose(
            full.stems["pre_master"], reconstructed, rtol=0, atol=3e-7
        )
        self.assertEqual(
            full.diagnostics["source_bus"]["additive_decomposition"],
            "not-guaranteed-through-nonlinear-topology",
        )

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
