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
    section_transition_manifest,
    transform_inspection,
    validate_section_transition,
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

    def test_role_stem_domains_distinguish_raw_audition_from_pre_master_roles(self):
        manifest = ownership_manifest(self.phrase())
        policies = {row["role"]: row for row in manifest["roles"]}
        self.assertEqual(set(policies), set(CANONICAL_LAYER_ROLES))
        self.assertEqual(len({row["stem"] for row in policies.values()}), len(CANONICAL_LAYER_ROLES))
        for role in CANONICAL_LAYER_ROLES:
            self.assertEqual(policies[role]["stem"], role)
            self.assertEqual(policies[role]["pocket_policy"], "explicit-only-no-makeup")
            self.assertEqual(policies[role]["transform_bypass"], "identity-no-retune-or-reweight")
        for role in ("synthline", "exciter"):
            self.assertEqual(policies[role]["stem_domain"], "raw-source-audition")
            self.assertEqual(policies[role]["audition_policy"], "independent-raw-audition-stem")
            self.assertEqual(policies[role]["mute_scope"], "source-bus-input-before-shared-topology")
            self.assertEqual(policies[role]["nonlinear_owner"], "shared-source-bus-topology")
        for role in ("body", "aux", "sub"):
            self.assertEqual(policies[role]["stem_domain"], "independent-pre-master-role")
            self.assertEqual(policies[role]["audition_policy"], "independent-pre-master-stem")
            self.assertEqual(policies[role]["mute_scope"], "role-stem-only")
        self.assertEqual(
            manifest["source_bus"],
            {
                "stem": "source_bus",
                "position": "post-preserved-synthline-topology-pre-master",
                "inputs": ["synthline", "exciter"],
                "input_domain": "raw-source-audition",
                "topology_owner": "render-recipe.synthline-graph",
                "mute_semantics": "selected-raw-inputs-before-shared-topology",
                "additive_decomposition": "not-guaranteed-through-nonlinear-topology",
            },
        )
        self.assertEqual(manifest["master"]["owner"], "render-recipe.output")
        self.assertEqual(manifest["master"]["position"], "single-final-stage")
        self.assertEqual(manifest["master"]["normalization"], "none")

    def test_policy_revision_is_explicit_for_source_bus_semantics(self):
        self.assertEqual(POLICY_VERSION, "1.1.0")
        manifest = ownership_manifest(self.phrase())
        self.assertEqual(manifest["version"], "1.1.0")
        legacy = section_transition_manifest(manifest, boundary_id="section-a")
        tampered = deepcopy(legacy)
        tampered["version"] = "1.0.0"
        tampered["sha256"] = digest({k: v for k, v in tampered.items() if k != "sha256"})
        with self.assertRaises(OwnershipConflict) as caught:
            validate_section_transition(tampered, ownership=manifest)
        self.assertEqual(caught.exception.diagnostic["code"], "invalid-section-transition")

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
                    self.assertEqual(by[role]["state_lifetime"], "persistent-until-explicit-section-reset")

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
        self.assertEqual(synthline["audition_policy"], "independent-raw-audition-stem")
        self.assertEqual(exciter["audition_policy"], "independent-raw-audition-stem")
        self.assertEqual(synthline["stem_domain"], "raw-source-audition")
        self.assertEqual(exciter["stem_domain"], "raw-source-audition")

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

    def test_single_transform_owner_is_exclusive_and_identity_bypass_is_empty_plan(self):
        self.assertEqual(
            resolve_transform_claims([{"layer": "sub", "quantity": "retune", "owner": "root"}]),
            [{"layer": "sub", "quantity": "retune", "owner": "root", "order": None, "mode": "exclusive-owner"}],
        )
        self.assertEqual(resolve_transform_claims([]), [])
        self.assertEqual(ownership_manifest(self.phrase())["transform_plan"], [])

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

    def test_section_boundary_continue_and_reset_are_explicit_serializable_state(self):
        ownership = ownership_manifest(self.phrase())
        continued = section_transition_manifest(ownership, boundary_id="section-a")
        by = {row["role"]: row for row in continued["roles"]}
        for role in ("body", "aux", "sub"):
            self.assertEqual(by[role]["action"], "continue")
            self.assertEqual(by[role]["phase_state"], "continue-integrated-state")
            self.assertEqual(by[role]["tail_state"], "preserve")
        reset = section_transition_manifest(ownership, boundary_id="section-b", reset_roles=["sub"])
        self.assertEqual(reset["reset_roles"], ["sub"])
        sub = next(row for row in reset["roles"] if row["role"] == "sub")
        self.assertEqual(sub["action"], "reset")
        self.assertEqual(sub["phase_state"], "reset-to-declared-origin")
        self.assertEqual(sub["tail_state"], "reset-with-layer")
        roundtrip = json.loads(json.dumps(reset, allow_nan=False))
        self.assertEqual(validate_section_transition(roundtrip, ownership=ownership), reset)

    def test_section_transition_tampering_and_invalid_reset_scopes_fail_closed(self):
        ownership = ownership_manifest(self.phrase())
        original = section_transition_manifest(ownership, boundary_id="section-a", reset_roles=["body"])
        tampered = deepcopy(original)
        next(row for row in tampered["roles"] if row["role"] == "body")["action"] = "continue"
        tampered["sha256"] = digest({k: v for k, v in tampered.items() if k != "sha256"})
        with self.assertRaises(OwnershipConflict) as caught:
            validate_section_transition(tampered, ownership=ownership)
        self.assertEqual(caught.exception.diagnostic["code"], "invalid-section-transition")
        for reset_roles, code in ((["sub", "sub"], "duplicate-section-reset-role"),
                                  (["synthline"], "nonpersistent-section-reset"),
                                  (["mystery"], "unknown-layer-role")):
            with self.subTest(code=code), self.assertRaises(OwnershipConflict) as invalid:
                section_transition_manifest(ownership, boundary_id="section-a", reset_roles=reset_roles)
            self.assertEqual(invalid.exception.diagnostic["code"], code)

    def test_transform_inspection_exposes_requested_realised_owner_stage_and_abstention(self):
        requested = transform_inspection(
            layer="body", quantity="retune", owner="adaptive", stage="harmony.retune",
            requested_target={"cents": "7/2"},
        )
        self.assertEqual(requested["state"], "requested")
        self.assertIsNone(requested["realised_target"])
        applied = transform_inspection(
            layer="body", quantity="retune", owner="adaptive", stage="harmony.retune",
            requested_target={"cents": "7/2"}, realised_target={"cents": "3/1"}, state="applied",
        )
        self.assertEqual(applied["realised_target"], {"cents": "3/1"})
        abstained = transform_inspection(
            layer="body", quantity="retune", owner="adaptive", stage="harmony.retune",
            requested_target={"cents": "7/2"}, state="abstained", reason="conflicting-exclusive-owner",
        )
        self.assertEqual(abstained["reason"], "conflicting-exclusive-owner")
        for document in (requested, applied, abstained):
            self.assertEqual(document["sha256"], digest({k: v for k, v in document.items() if k != "sha256"}))
            json.dumps(document, allow_nan=False)

    def test_transform_inspection_boundaries_fail_closed(self):
        cases = [
            ({"state": "applied"}, "missing-realised-target"),
            ({"state": "abstained"}, "missing-abstention-reason"),
            ({"state": "requested", "realised_target": {"cents": "1/1"}}, "unexpected-realised-target"),
            ({"state": "future"}, "invalid-inspection-state"),
            ({"stage": "../stage"}, "invalid-transform-stage"),
            ({"requested_target": float("nan")}, "invalid-inspection-target"),
        ]
        base = dict(layer="body", quantity="retune", owner="adaptive", stage="harmony.retune",
                    requested_target={"cents": "7/2"})
        for changes, code in cases:
            kwargs = {**base, **changes}
            with self.subTest(code=code), self.assertRaises(OwnershipConflict) as caught:
                transform_inspection(**kwargs)
            self.assertEqual(caught.exception.diagnostic["code"], code)

    def test_non_octave_tuning_and_upper_transform_do_not_rebind_protected_synthline_or_pedal(self):
        phrase = self.phrase()
        self.assertEqual(phrase["tuning_id"], "tritave")
        phrase["bass_role"] = "pedal"
        manifest = ownership_manifest(
            phrase,
            transform_claims=[{"layer": "body", "quantity": "retune", "owner": "spectral"}],
        )
        by = {row["role"]: row for row in manifest["roles"]}
        self.assertEqual(by["synthline"]["source_identity_owner"], "protected-source")
        self.assertEqual(by["synthline"]["source_policy"], "source-derived-unless-explicit-target-note")
        self.assertEqual(by["sub"]["pitch_mode"], "fixed-pedal")
        self.assertEqual(manifest["transform_plan"][0]["layer"], "body")
        self.assertEqual(manifest["transform_plan"][0]["mode"], "exclusive-owner")


if __name__ == "__main__":
    unittest.main(verbosity=2)
