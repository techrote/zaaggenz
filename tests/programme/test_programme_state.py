from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import validate_programme_state as ps  # noqa: E402


class ProgrammeStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = ps.load(ROOT / "programme" / "task_state.json")

    def test_repository_state_validates(self) -> None:
        ps.validate_state(self.state, root=ROOT)
        self.assertEqual(45, len(self.state["tasks"]))

    def test_completed_task_has_accepted_evidence(self) -> None:
        row = self.state["tasks"]["ZG-023"]
        self.assertEqual("accepted", row["implementation"])
        self.assertEqual("accepted", row["evidence"])
        self.assertTrue(row["dependency_satisfied"])

    def test_owner_gated_task_is_not_dependency_satisfied(self) -> None:
        row = self.state["tasks"]["ZG-022"]
        self.assertEqual("accepted", row["implementation"])
        self.assertEqual("accepted", row["evidence"])
        self.assertEqual("pending", row["owner_gate"])
        self.assertFalse(row["dependency_satisfied"])

    def test_serial_research_task_is_not_dependency_satisfied(self) -> None:
        row = self.state["tasks"]["ZG-024"]
        self.assertEqual("partial", row["evidence"])
        self.assertEqual("active", row["research"])
        self.assertFalse(row["dependency_satisfied"])

    def test_accepted_implementation_can_be_blocked_from_completion(self) -> None:
        candidate = copy.deepcopy(self.state)
        row = candidate["tasks"]["ZG-028"]
        self.assertEqual("accepted", row["implementation"])
        self.assertEqual("accepted", row["evidence"])
        # Reproduce the historical corrective-blocker state synthetically.  The
        # live row is now reaccepted after #118/#138; this test is about the
        # evidence-state rule, not about keeping a repaired task stale forever.
        row["dependency_satisfied"] = False
        row["blockers"] = [{"ref": "corrective:ZG-028-issue-118-repair", "kind": "corrective"}]
        ps.validate_state(candidate, root=ROOT)
        self.assertFalse(row["dependency_satisfied"])
        refs = {b["ref"] for b in row["blockers"]}
        self.assertIn("corrective:ZG-028-issue-118-repair", refs)
        self.assertIn("issue:#138:corrective-repair", row["evidence_refs"])
        self.assertIn("issue:#118:corrective-repair", row["evidence_refs"])

    def test_blocked_task_requires_a_blocker(self) -> None:
        bad = copy.deepcopy(self.state)
        row = bad["tasks"]["ZG-030"]
        row["implementation"] = "blocked"
        row["dependency_satisfied"] = False
        row["blockers"] = []
        with self.assertRaises(ps.StateError):
            ps.validate_state(bad, root=ROOT)

    def test_pending_owner_gate_cannot_be_forced_satisfied(self) -> None:
        bad = copy.deepcopy(self.state)
        bad["tasks"]["ZG-022"]["dependency_satisfied"] = True
        with self.assertRaises(ps.StateError):
            ps.validate_state(bad, root=ROOT)

    def test_active_research_cannot_be_forced_satisfied(self) -> None:
        bad = copy.deepcopy(self.state)
        bad["tasks"]["ZG-024"]["implementation"] = "accepted"
        bad["tasks"]["ZG-024"]["evidence"] = "accepted"
        bad["tasks"]["ZG-024"]["dependency_satisfied"] = True
        with self.assertRaises(ps.StateError):
            ps.validate_state(bad, root=ROOT)

    def test_closed_issue_without_evidence_does_not_become_satisfied(self) -> None:
        candidate = copy.deepcopy(self.state)
        # ZG-044 is intentionally not started and has no accepted evidence.
        # Closing its GitHub mirror must not manufacture dependency readiness.
        row = candidate["tasks"]["ZG-044"]
        row["github_issue"]["state"] = "closed"
        ps.validate_state(candidate, root=ROOT)
        self.assertEqual("none", row["evidence"])
        self.assertFalse(row["dependency_satisfied"])

    def test_open_issue_can_carry_accepted_dependency_evidence(self) -> None:
        candidate = copy.deepcopy(self.state)
        row = candidate["tasks"]["ZG-023"]
        row["github_issue"]["state"] = "open"
        ps.validate_state(candidate, root=ROOT)
        self.assertTrue(row["dependency_satisfied"])

    def test_issue_close_reopen_does_not_change_dependency_readiness(self) -> None:
        before = ps.hard_prerequisites_satisfied("ZG-025", self.state, root=ROOT)
        closed = ps.with_issue_state(self.state, "ZG-008", "closed")
        opened = ps.with_issue_state(self.state, "ZG-008", "open")
        self.assertEqual(before, ps.hard_prerequisites_satisfied("ZG-025", closed, root=ROOT))
        self.assertEqual(before, ps.hard_prerequisites_satisfied("ZG-025", opened, root=ROOT))

    def test_readiness_follows_parent_evidence_not_child_issue_state(self) -> None:
        # ZG-033 remains blocked by the unsatisfied ZG-022 owner gate; repaired
        # ZG-040 is now accepted prerequisite evidence.
        report = ps.readiness_report(self.state, root=ROOT)["ZG-033"]
        self.assertFalse(report["hard_prerequisites_satisfied"])
        self.assertEqual(report["unsatisfied_parents"], ["ZG-022"])

    def test_post_merge_corrective_reacceptance_is_scoped_to_repaired_task(self) -> None:
        study = self.state["tasks"]["ZG-040"]
        performance = self.state["tasks"]["ZG-042"]
        self.assertEqual(
            (study["implementation"], study["evidence"], study["research"]),
            ("accepted", "accepted", "accepted"),
        )
        self.assertTrue(study["dependency_satisfied"])
        self.assertEqual(study["github_issue"]["state"], "closed")
        self.assertEqual(study["blockers"], [])
        self.assertIn("pr:#214", study["evidence_refs"])
        self.assertIn("issue:#41:corrective-reacceptance", study["evidence_refs"])
        self.assertEqual((performance["implementation"], performance["evidence"]), ("accepted", "accepted"))
        self.assertTrue(performance["dependency_satisfied"])
        self.assertEqual(performance["github_issue"]["state"], "closed")
        self.assertEqual(performance["blockers"], [])
        self.assertIn("pr:#213", performance["evidence_refs"])
        self.assertIn("issue:#43:corrective-reacceptance", performance["evidence_refs"])

    def test_repaired_zg028_and_integrated_zg041_are_dependency_satisfying(self) -> None:
        linked = self.state["tasks"]["ZG-028"]
        integrated = self.state["tasks"]["ZG-041"]
        self.assertTrue(linked["dependency_satisfied"])
        self.assertEqual(linked["blockers"], [])
        self.assertIn("issue:#118:corrective-repair", linked["evidence_refs"])
        self.assertTrue(integrated["dependency_satisfied"])
        self.assertEqual(integrated["blockers"], [])
        self.assertIn("pr:#215", integrated["evidence_refs"])

    def test_zg024_uses_semantic_research_blocker_and_current_evidence(self) -> None:
        row = self.state["tasks"]["ZG-024"]
        self.assertEqual(
            [{"ref": "research:ZG-024-coupled-search-heldout-generalisation", "kind": "research"}],
            row["blockers"],
        )
        for ref in (
            "pr:#187",
            "pr:#194",
            "pr:#195",
            "docs:docs/inverse/CANDIDATE_PROVENANCE.md",
            "docs:docs/inverse/TRANSIENT_PRESERVATION_GATE.md",
            "docs:docs/inverse/TRANSIENT_V4_EVIDENCE_MIGRATION.md",
            "docs:docs/inverse/ZG024_STAGED_PROTOCOL_V2.md",
            "docs:docs/inverse/ZG024_STAGED_RESULT.md",
            "docs:docs/inverse/ZG024_LINEAGE_RECONCILIATION.md",
            "issue:#227:diagnostic-mixed-no-go",
            "pr:#228",
            "docs:docs/inverse/ZG024E_DIAGNOSTIC_PROTOCOL_V1.md",
            "docs:docs/inverse/ZG024E_DIAGNOSTIC_RESULT.md",
            "docs:docs/inverse/ZG024_RESEARCH_HANDOFF_3.md",
            "issue:#25:remaining-research-blocker",
        ):
            self.assertIn(ref, row["evidence_refs"])

    def test_issue_number_cannot_be_live_research_blocker_identity(self) -> None:
        bad = copy.deepcopy(self.state)
        bad["tasks"]["ZG-024"]["blockers"] = [{"ref": "issue:#92", "kind": "research"}]
        with self.assertRaises(ps.StateError):
            ps.validate_state(bad, root=ROOT)

    def test_zg024_issue_mirror_does_not_change_zg039_readiness(self) -> None:
        opened = ps.with_issue_state(self.state, "ZG-024", "open")
        closed = ps.with_issue_state(self.state, "ZG-024", "closed")
        self.assertFalse(ps.hard_prerequisites_satisfied("ZG-039", opened, root=ROOT))
        self.assertFalse(ps.hard_prerequisites_satisfied("ZG-039", closed, root=ROOT))

    def test_zg029_points_directly_to_final_policy_1_1_evidence(self) -> None:
        row = self.state["tasks"]["ZG-029"]
        self.assertTrue(row["dependency_satisfied"])
        self.assertIn("pr:#209", row["evidence_refs"])
        self.assertIn("issue:#202:final-completion", row["evidence_refs"])
        self.assertIn("docs:docs/zaaggenz/ZG029_LAYER_OWNERSHIP_ADR.md", row["evidence_refs"])

    def test_zg045_has_no_completed_prerequisite_issue_blocker(self) -> None:
        row = self.state["tasks"]["ZG-045"]
        self.assertFalse(row["dependency_satisfied"])
        self.assertEqual([], row["blockers"])

    def test_unknown_dependency_blocker_fails(self) -> None:
        bad = copy.deepcopy(self.state)
        bad["tasks"]["ZG-043"]["blockers"] = [{"ref": "task:ZG-999", "kind": "dependency"}]
        with self.assertRaises(ps.StateError):
            ps.validate_state(bad, root=ROOT)

    def test_missing_docs_evidence_ref_fails(self) -> None:
        bad = copy.deepcopy(self.state)
        bad["tasks"]["ZG-023"]["evidence_refs"].append("docs:docs/does-not-exist.md")
        with self.assertRaises(ps.StateError):
            ps.validate_state(bad, root=ROOT)

    def test_duplicate_and_malformed_blocker_identities_fail(self) -> None:
        bad = copy.deepcopy(self.state)
        blocker = {"ref": "owner-gate:ZG-022-listening-default-approval", "kind": "owner_gate"}
        bad["tasks"]["ZG-022"]["blockers"] = [blocker, copy.deepcopy(blocker)]
        with self.assertRaises(ps.StateError):
            ps.validate_state(bad, root=ROOT)

        bad = copy.deepcopy(self.state)
        bad["tasks"]["ZG-022"]["blockers"] = [{"ref": "owner-gate:", "kind": "owner_gate"}]
        with self.assertRaises(ps.StateError):
            ps.validate_state(bad, root=ROOT)

    def test_readiness_table_matches_authority_reconciliation_contract(self) -> None:
        report = ps.readiness_report(self.state, root=ROOT)
        expected = {
            "ZG-033": ["ZG-022"],
            "ZG-034": ["ZG-022"],
            "ZG-035": [],
            "ZG-036": [],
            "ZG-037": [],
            "ZG-038": [],
            "ZG-039": ["ZG-024"],
            "ZG-043": [],
            "ZG-044": ["ZG-022", "ZG-024"],
            "ZG-045": ["ZG-044"],
        }
        for sid, unsatisfied in expected.items():
            self.assertEqual(unsatisfied, report[sid]["unsatisfied_parents"])
            self.assertEqual(not unsatisfied, report[sid]["hard_prerequisites_satisfied"])

    def test_zg043_longform_export_is_accepted_dependency_evidence(self) -> None:
        row = self.state["tasks"]["ZG-043"]
        self.assertEqual((row["implementation"], row["evidence"]), ("accepted", "accepted"))
        self.assertTrue(row["dependency_satisfied"])
        self.assertEqual(row["blockers"], [])
        self.assertEqual(row["github_issue"], {"number": 44, "state": "closed"})
        self.assertIn("pr:#226", row["evidence_refs"])
        self.assertIn("issue:#44:implementation-evidence", row["evidence_refs"])
        self.assertIn("docs:docs/longform/README.md", row["evidence_refs"])
        self.assertIn("docs:docs/longform/VERIFICATION.md", row["evidence_refs"])
        report = ps.readiness_report(self.state, root=ROOT)
        self.assertEqual(report["ZG-044"]["unsatisfied_parents"], ["ZG-022", "ZG-024"])
        self.assertEqual(report["ZG-045"]["unsatisfied_parents"], ["ZG-044"])

    def test_unknown_task_and_wrong_issue_mapping_fail(self) -> None:
        bad = copy.deepcopy(self.state)
        bad["tasks"]["ZG-999"] = copy.deepcopy(bad["tasks"]["ZG-001"])
        with self.assertRaises(ps.StateError):
            ps.validate_state(bad, root=ROOT)
        bad = copy.deepcopy(self.state)
        bad["tasks"]["ZG-001"]["github_issue"]["number"] = 999
        with self.assertRaises(ps.StateError):
            ps.validate_state(bad, root=ROOT)


if __name__ == "__main__":
    unittest.main()
