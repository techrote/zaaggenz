from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))

from zaaggenz_contracts import Contract, ownership_manifest, section_transition_manifest
from zaaggenz_contracts.legacy import adapt_parameters, freeze_legacy
from zaaggenz_harmony import SonoritySpec, SonorityTone, VoiceSpec, VoicingConstraints, solve_progression
from zaaggenz_layers import (
    LayerGeneratorSpec, LayerRuntimeError, LayerRuntimeSpec, LayerRuntimeState,
    LayerTransformTarget, render_coordinated_layers,
)
from zaaggenz_melody import make_melodic_recipe, make_phrase_plan, note_event, render_phrase
from zaaggenz_tuning import fixture_pack, tuning_to_spec


def _legacy(sr=8000, bpm=240.0):
    params = adapt_parameters("synth", {"sr": sr, "bpm": bpm, "beats": 1, "f0_hz": 48.0})
    frozen = freeze_legacy(params).to_dict()
    return params, frozen["time_map"], frozen["tuning"]


def _sonority(root, name):
    return SonoritySpec(name, root, (
        SonorityTone("root", degree_offset=0), SonorityTone("third", degree_offset=4), SonorityTone("fifth", degree_offset=7),
    ))


def _voices(sub_policy="hold-first"):
    return VoicingConstraints((
        VoiceSpec("sub", "sub", 20, 60, 34, max_leap_cents=1600, anchor_policy=sub_policy),
        VoiceSpec("body", "body", 36, 90, 56, max_leap_cents=1800),
        VoiceSpec("aux", "aux", 70, 150, 102, max_leap_cents=1800),
        VoiceSpec("lead", "synthline", 105, 240, 160, max_leap_cents=1800),
    ))


def _spec(*, claims=(), targets=(), release=32, glide=16):
    return LayerRuntimeSpec(
        generators=tuple(LayerGeneratorSpec(role, "sine", -30.0, glide, release, 0.125) for role in ("body", "aux", "sub")),
        transform_claims=tuple(claims), transform_targets=tuple(targets),
    )


def _fixture(*, bass_role="pedal", sub_policy="hold-first", tuning=None, master_gain_db=0.0):
    params, time_map, legacy_tuning = _legacy()
    tuning = legacy_tuning if tuning is None else tuning
    phrase = make_phrase_plan(
        tuning["id"], [note_event("lead-source", "0/1", "1/2", tuning["id"], 12, gain_db=-18.0)],
        start_beat="0/1", end_beat="1/1", bass_role=bass_role,
    )
    recipe = make_melodic_recipe(params, time_map, tuning, phrase, quality="standard", tail_mode="truncate", master_gain_db=master_gain_db)
    progression = solve_progression(tuning, [_sonority(0, "a"), _sonority(5, "b")], _voices(sub_policy))
    return recipe, progression, ["0/1", "1/2"], "1/2"


class PersistentLayerRuntimeTests(unittest.TestCase):
    def test_source_synthline_and_exciter_are_not_resynthesized_by_harmony(self):
        recipe, progression, beats, durations = _fixture()
        source = render_phrase(recipe)
        coordinated = render_coordinated_layers(recipe, progression, beats, durations, _spec())
        np.testing.assert_array_equal(coordinated.stems["synthline"][:len(source.stems["synthline"])], source.stems["synthline"])
        np.testing.assert_array_equal(coordinated.stems["exciter"][:len(source.stems["exciter"])], source.stems["exciter"])
        lead = next(row for row in coordinated.diagnostics["voice_trace"] if row["voice_id"] == "lead")
        self.assertEqual(lead["action"], "source-owned-not-resynthesized")
        self.assertEqual(coordinated.diagnostics["recipe_sha256"], recipe.sha256)

    def test_full_role_stems_exist_and_muting_one_role_does_not_erase_other_stems(self):
        recipe, progression, beats, durations = _fixture()
        full = render_coordinated_layers(recipe, progression, beats, durations, _spec())
        no_body = render_coordinated_layers(recipe, progression, beats, durations, _spec(), muted_roles=("body",))
        self.assertEqual(set(full.stems), {"synthline", "exciter", "source_bus", "body", "aux", "sub", "pre_master"})
        reconstructed = (
            np.asarray(full.stems["source_bus"], dtype=np.float64)
            + np.asarray(full.stems["body"], dtype=np.float64)
            + np.asarray(full.stems["aux"], dtype=np.float64)
            + np.asarray(full.stems["sub"], dtype=np.float64)
        ).astype(np.float32)
        np.testing.assert_allclose(full.stems["pre_master"], reconstructed, rtol=0, atol=3e-7)
        self.assertGreater(float(np.max(np.abs(full.stems["body"]), initial=0)), 0.0)
        np.testing.assert_array_equal(full.stems["sub"], no_body.stems["sub"])
        np.testing.assert_array_equal(full.stems["synthline"], no_body.stems["synthline"])
        self.assertFalse(np.array_equal(full.mix, no_body.mix))

    def test_fixed_pedal_stays_fixed_while_upper_sonority_moves(self):
        recipe, progression, beats, durations = _fixture(bass_role="pedal", sub_policy="hold-first")
        sub_hz = [next(v.frequency_hz for v in frame.voices if v.voice_id == "sub") for frame in progression.frames]
        body_hz = [next(v.frequency_hz for v in frame.voices if v.voice_id == "body") for frame in progression.frames]
        self.assertAlmostEqual(sub_hz[0], sub_hz[1], places=12)
        self.assertNotAlmostEqual(body_hz[0], body_hz[1], places=6)
        result = render_coordinated_layers(recipe, progression, beats, durations, _spec())
        self.assertAlmostEqual(result.state.voices["sub:sub"]["last_frequency_hz"], sub_hz[-1], places=12)

    def test_moving_sub_follows_declared_harmony_and_is_rejected_under_pedal_contract(self):
        moving_recipe, moving, beats, durations = _fixture(bass_role="moving", sub_policy="moving")
        hz = [next(v.frequency_hz for v in frame.voices if v.voice_id == "sub") for frame in moving.frames]
        self.assertGreater(max(hz) - min(hz), 1.0)
        result = render_coordinated_layers(moving_recipe, moving, beats, durations, _spec())
        self.assertAlmostEqual(result.state.voices["sub:sub"]["last_frequency_hz"], hz[-1], places=12)
        bad = moving_recipe.to_dict(); bad["phrase"]["bass_role"] = "pedal"
        with self.assertRaises(LayerRuntimeError) as caught:
            render_coordinated_layers(Contract(bad), moving, beats, durations, _spec())
        self.assertEqual(caught.exception.diagnostic["code"], "pedal-sub-moved")

    def test_upper_retune_is_layer_scoped_and_cannot_drag_locked_sub(self):
        recipe, progression, beats, durations = _fixture()
        plain = render_coordinated_layers(recipe, progression, beats, durations, _spec())
        transformed = _spec(
            claims=({"layer": "body", "quantity": "retune", "owner": "adaptive"},),
            targets=(LayerTransformTarget("body", "retune", "adaptive", 37.0),),
        )
        shifted = render_coordinated_layers(recipe, progression, beats, durations, transformed)
        self.assertFalse(np.array_equal(plain.stems["body"], shifted.stems["body"]))
        np.testing.assert_array_equal(plain.stems["sub"], shifted.stems["sub"])
        self.assertEqual(plain.state.voices["sub:sub"], shifted.state.voices["sub:sub"])

    def test_competing_transform_owners_fail_closed_and_explicit_order_is_recorded(self):
        recipe, progression, beats, durations = _fixture()
        claims = ({"layer": "body", "quantity": "retune", "owner": "adaptive"}, {"layer": "body", "quantity": "retune", "owner": "spectral"})
        with self.assertRaises(LayerRuntimeError) as caught:
            render_coordinated_layers(recipe, progression, beats, durations, _spec(claims=claims))
        self.assertEqual(caught.exception.diagnostic["code"], "competing-transform-owners")
        ordered = (
            {"layer": "body", "quantity": "retune", "owner": "adaptive", "order": 0},
            {"layer": "body", "quantity": "retune", "owner": "spectral", "order": 1},
        )
        targets = (LayerTransformTarget("body", "retune", "adaptive", 10.0, "body"), LayerTransformTarget("body", "retune", "spectral", -3.0, "body"))
        result = render_coordinated_layers(recipe, progression, beats, durations, _spec(claims=ordered, targets=targets))
        row = next(row for row in result.diagnostics["voice_trace"] if row["voice_id"] == "body")
        self.assertEqual([item["owner"] for item in row["retune_trace"]], ["adaptive", "spectral"])
        self.assertEqual([item["order"] for item in row["retune_trace"]], [0, 1])
        self.assertAlmostEqual(row["retune_cents"], 7.0)

    def test_save_reload_continue_is_bit_identical_and_explicit_reset_changes_phase(self):
        recipe, progression, beats, durations = _fixture(); spec = _spec(release=64, glide=8)
        first = render_coordinated_layers(recipe, progression, beats, durations, spec)
        reloaded = LayerRuntimeState.from_dict(json.loads(json.dumps(first.state.to_dict(), allow_nan=False)))
        ownership = ownership_manifest(recipe.to_dict()["phrase"], phase_policy=recipe.to_dict()["phase_policy"])
        continued_transition = section_transition_manifest(ownership, boundary_id="section-two")
        direct = render_coordinated_layers(recipe, progression, beats, durations, spec, state=first.state, section_transition=continued_transition)
        roundtrip = render_coordinated_layers(recipe, progression, beats, durations, spec, state=reloaded, section_transition=continued_transition)
        np.testing.assert_array_equal(direct.mix, roundtrip.mix)
        self.assertEqual(direct.state.to_dict(), roundtrip.state.to_dict())
        reset_transition = section_transition_manifest(ownership, boundary_id="section-reset", reset_roles=("sub",))
        reset = render_coordinated_layers(recipe, progression, beats, durations, spec, state=reloaded, section_transition=reset_transition)
        self.assertFalse(np.array_equal(direct.stems["sub"], reset.stems["sub"]))
        self.assertNotEqual(direct.state.voices["sub:sub"]["phase_cycles"], reset.state.voices["sub:sub"]["phase_cycles"])

    def test_continuing_nonempty_state_without_transition_fails_closed(self):
        recipe, progression, beats, durations = _fixture(); first = render_coordinated_layers(recipe, progression, beats, durations, _spec())
        with self.assertRaises(LayerRuntimeError) as caught:
            render_coordinated_layers(recipe, progression, beats, durations, _spec(), state=first.state)
        self.assertEqual(caught.exception.diagnostic["code"], "missing-section-transition")

    def test_final_master_is_applied_once_without_hidden_normalisation(self):
        recipe, progression, beats, durations = _fixture(master_gain_db=-12.0)
        result = render_coordinated_layers(recipe, progression, beats, durations, _spec())
        expected = np.clip(np.asarray(result.stems["pre_master"], dtype=np.float64) * (10.0 ** (-12.0 / 20.0)), -1.0, 1.0).astype(np.float32)
        np.testing.assert_allclose(result.mix, expected, rtol=0, atol=2e-7)
        self.assertEqual(result.diagnostics["final_master_owner"], "render-recipe.output")
        self.assertEqual(result.diagnostics["normalization"], "none")

    def test_missing_generator_and_unowned_transform_are_structured_diagnostics(self):
        recipe, progression, beats, durations = _fixture()
        missing = LayerRuntimeSpec((LayerGeneratorSpec("body", "sine", -30.0, 0, 0),))
        with self.assertRaises(LayerRuntimeError) as caught:
            render_coordinated_layers(recipe, progression, beats, durations, missing)
        self.assertEqual(caught.exception.diagnostic["code"], "missing-persistent-generator")
        self.assertEqual(caught.exception.diagnostic["missing_roles"], ["aux", "sub"])
        unowned = _spec(targets=(LayerTransformTarget("body", "retune", "adaptive", 10.0),))
        with self.assertRaises(LayerRuntimeError) as target:
            render_coordinated_layers(recipe, progression, beats, durations, unowned)
        self.assertEqual(target.exception.diagnostic["code"], "unowned-transform-target")

    def test_non_octave_tuning_runs_through_real_source_and_persistent_stems(self):
        tuning = tuning_to_spec(fixture_pack()["synthetic-13ed3"]); params, time_map, _ = _legacy()
        phrase = make_phrase_plan(tuning["id"], [note_event("lead-source", "0/1", "1/2", tuning["id"], 5, gain_db=-21.0)], start_beat="0/1", end_beat="1/1", bass_role="moving")
        recipe = make_melodic_recipe(params, time_map, tuning, phrase, quality="standard", tail_mode="truncate")
        voices = VoicingConstraints((
            VoiceSpec("sub", "sub", 20, 60, 34, anchor_policy="moving"), VoiceSpec("body", "body", 36, 90, 56),
            VoiceSpec("aux", "aux", 70, 150, 102), VoiceSpec("lead", "synthline", 105, 260, 165),
        ))
        sonority = lambda root, name: SonoritySpec(name, root, (SonorityTone("root", degree_offset=0), SonorityTone("d4", degree_offset=4), SonorityTone("ratio", ratio=3/2)))
        progression = solve_progression(tuning, [sonority(0, "a"), sonority(3, "b")], voices)
        result = render_coordinated_layers(recipe, progression, ["0/1", "1/2"], "1/2", _spec())
        self.assertGreater(float(np.max(np.abs(result.stems["sub"]), initial=0)), 0.0)
        self.assertEqual(result.diagnostics["bass_role"], "moving")
        self.assertEqual(result.diagnostics["progression_sha256"], progression.sha256)

    def test_runtime_state_tamper_is_rejected(self):
        recipe, progression, beats, durations = _fixture(); first = render_coordinated_layers(recipe, progression, beats, durations, _spec())
        bad = first.state.to_dict(); bad["voices"]["sub:sub"]["phase_cycles"] = 0.75
        with self.assertRaises(LayerRuntimeError) as caught: LayerRuntimeState.from_dict(bad)
        self.assertEqual(caught.exception.diagnostic["code"], "invalid-runtime-state")


if __name__ == "__main__": unittest.main(verbosity=2)
