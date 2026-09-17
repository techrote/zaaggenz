from __future__ import annotations

from copy import deepcopy
import json
import unittest

from zaaggenz_contracts import digest, schema
from zaaggenz_contracts.examples import examples
from zaaggenz_contracts.ownership import (
    CANONICAL_LAYER_ROLES,
    POLICY_ID,
    POLICY_VERSION,
    OwnershipConflict,
    ownership_manifest,
    require_renderer_roles,
    resolve_transform_claims,
    role_policy,
)


class LayerOwnershipPolicyTests(unittest.TestCase):
    def phrase(self):
        return examples()["PhrasePlan"]

    def test_policy_role_vocabulary_is_exact_phraseplan_wire_vocabulary(self):
        event_schema = schema("PhrasePlan")["$defs"]["PhrasePlan"]["properties"]["events"]["items"]
        self.assertEqual(tuple(event_schema["properties"]["layer_role"]["enum"]), CANONICAL_LAYER_ROLES)

    def test_manifest_is_versioned_strict_json_and_deterministic(self):
        phrase = self.phrase()
        a = ownership_manifest(phrase, phase_policy="source-derived")
        b = ownership_manifest(deepcopy(phrase), phase_policy="source-derived")
        self.assertEqual(a, b)
        self.assertEqual(a["kind"], "LayerOwnershipManifest")
        self.assertEqual(a["policy_id"], POLICY_ID)
        self.assertEqual(a["version"], POLICY_VERSION)
        self.assertEqual(a["phrase_sha256"], digest(phrase))
        self.assertEqual(a["sha256"], digest({k: v for k, v in a.items() if k != "sha256"}))
        json.dumps(a, allow_nan=False)

    def test_all_canonical_roles_have_one_same_named_pre_master_stem(self):
        manifest = ownership_manifest(self.phrase())
        policies = {row["role"]: row for row in manifest["roles"]}
        self.assertEqual(set(policies), set(CANONICAL_LAYER_ROLES))
        for role in CANONICAL_LAYER_ROLES:
            self.assertEqual(policies[role]["stem"], role)
            self.assertEqual(policies[role]["pocket_policy"], "explicit-only-no-makeup")
        self.assertEqual(manifest["master"]["owner"], "render-recipe.output")
        self.assertEqual(manifest["master"]["position"], "single-final-stage")
        self.assertEqual(manifest["master"]["normalization"], "none")

    def test_synthline_and_exciter_follow_declared_note_phase_but_persistent_layers_do_not(self):
        for phase in ("source-derived", "reset-event"):
            with self.subTest(phase=phase):
                manifest = ownership_manifest(self.phrase(), phase_policy=phase)
                by = {row["role"]: row for row in manifest["roles"]}
                self.assertEqual(by["synthline"]["phase_policy"], phase)
                self.assertEqual(by["exciter"]["phase_policy"], phase)
                for role in ("body", "aux", "sub"):
                    self.assertEqual(by[role]["phase_policy"], "continuous-integrated")
                    self.assertEqual(by[role]["reset_scope"], "explicit-section-policy")

    def test_sub_pedal_and_moving_root_are_independent_serialized_modes(self):
        expected = {"none": "inactive", "pedal": "fixed-pedal", "moving": "follow-declared-root"}
        for bass_role, mode in expected.items():
            with self.subTest(bass_role=bass_role):
                phrase = self.phrase()
                phrase["bass_role"] = bass_role
                manifest = ownership_manifest(phrase)
                sub = next(row for row in manifest["roles"] if row["role"] == "sub")
                self.assertEqual(sub["pitch_mode"], mode)
                self.assertEqual(sub["pitch_owner"], "phrase-bass-role")

    def test_exciter_cannot_substitute_for_synthline(self):
        exciter = role_policy("exciter")
        synthline = role_policy("synthline")
        self.assertEqual(exciter["source_policy"], "derived-transient-never-synthline-substitute")
        self.assertEqual(synthline["source_identity_owner"], "protected-source")
        self.assertNotEqual(exciter["stem"], synthline["stem"])

    def test_legacy_projection_is_explicit_and_body_subcomponents_do_not_fake_new_wire_roles(self):
        manifest = ownership_manifest(self.phrase())
        self.assertEqual(
            manifest["legacy_projection"],
            {"click": "exciter", "body": "body", "sub": "sub", "synthline": "synthline", "aux": "aux"},
        )
        self.assertEqual(manifest["body_subcomponents"]["low"], "body")
        self.assertEqual(manifest["body_subcomponents"]["upper"], "body")
        self.assertFalse(manifest["body_subcomponents"]["independently_addressable_in_renderrecipe_v1"])

    def test_competing_retune_or_reweight_fails_without_explicit_total_order(self):
        for quantity in ("retune", "reweight"):
            with self.subTest(quantity=quantity), self.assertRaises(OwnershipConflict) as caught:
                resolve_transform_claims([
                    {"layer": "body", "quantity": quantity, "owner": "adaptive"},
                    {"layer": "body", "quantity": quantity, "owner": "spectral"},
                ])
            diag = caught.exception.diagnostic
            self.assertEqual(diag["code"], "competing-transform-owners")
            self.assertEqual(diag["layer"], "body")
            self.assertEqual(diag["quantity"], quantity)
            self.assertEqual(len(diag["claims"]), 2)

    def test_explicit_order_is_the_only_competing_transform_escape_hatch(self):
        plan = resolve_transform_claims([
            {"layer": "body", "quantity": "retune", "owner": "spectral", "order": 1},
            {"layer": "body", "quantity": "retune", "owner": "adaptive", "order": 0},
        ])
        self.assertEqual([row["owner"] for row in plan], ["adaptive", "spectral"])
        self.assertTrue(all(row["mode"] == "ordered-chain" for row in plan))
        with self.assertRaises(OwnershipConflict) as caught:
            resolve_transform_claims([
                {"layer": "body", "quantity": "retune", "owner": "adaptive", "order": 0},
                {"layer": "body", "quantity": "retune", "owner": "spectral", "order": 0},
            ])
        self.assertEqual(caught.exception.diagnostic["code"], "competing-transform-owners")

    def test_single_transform_owner_is_exclusive_and_does_not_need_order(self):
        self.assertEqual(
            resolve_transform_claims([{"layer": "sub", "quantity": "retune", "owner": "root"}]),
            [{"layer": "sub", "quantity": "retune", "owner": "root", "order": None, "mode": "exclusive-owner"}],
        )

    def test_unknown_layer_quantity_owner_and_order_fail_closed_with_structured_diagnostics(self):
        bad = [
            ([{"layer": "mystery", "quantity": "retune", "owner": "x"}], "unknown-layer-role"),
            ([{"layer": "body", "quantity": "pitchish", "owner": "x"}], "unknown-transform-quantity"),
            ([{"layer": "body", "quantity": "retune", "owner": "../x"}], "invalid-transform-owner"),
            ([{"layer": "body", "quantity": "retune", "owner": "x", "order": -1}], "invalid-transform-order"),
        ]
        for claims, code in bad:
            with self.subTest(code=code), self.assertRaises(OwnershipConflict) as caught:
                resolve_transform_claims(claims)
            self.assertEqual(caught.exception.diagnostic["code"], code)
            json.dumps(caught.exception.diagnostic, allow_nan=False)

    def test_renderer_ownership_is_fail_closed_not_silent_stem_rebinding(self):
        phrase = self.phrase()
        require_renderer_roles(phrase, {"synthline"}, owner="zg008.melody")
        phrase["events"][0]["layer_role"] = "body"
        with self.assertRaises(OwnershipConflict) as caught:
            require_renderer_roles(phrase, {"synthline"}, owner="zg008.melody")
        self.assertEqual(caught.exception.diagnostic["code"], "role-not-owned-by-renderer")
        self.assertEqual(caught.exception.diagnostic["rejected_roles"], ["body"])

    def test_phase_and_bass_boundaries_fail_closed(self):
        with self.assertRaises(OwnershipConflict) as phase:
            ownership_manifest(self.phrase(), phase_policy="future-maybe")
        self.assertEqual(phase.exception.diagnostic["code"], "unknown-phase-policy")
        phrase = self.phrase()
        phrase["bass_role"] = "maybe"
        with self.assertRaises(OwnershipConflict) as bass:
            ownership_manifest(phrase)
        self.assertEqual(bass.exception.diagnostic["code"], "unknown-bass-role")


if __name__ == "__main__":
    unittest.main(verbosity=2)
