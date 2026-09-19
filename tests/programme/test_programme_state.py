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
        row = self.state["tasks"]["ZG-028"]
        self.assertEqual("accepted", row["implementation"])
        self.assertEqual("accepted", row["evidence"])
        self.assertFalse(row["dependency_satisfied"])
        refs = {b["ref"] for b in row["blockers"]}
        self.assertIn("issue:#118", refs)
        self.assertNotIn("issue:#138", refs)
        self.assertIn("issue:#138:corrective-repair", row["evidence_refs"])

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
        row = candidate["tasks"]["ZG-041"]
        row["github_issue"]["state"] = "closed"
        row["blockers"] = []
        ps.validate_state(candidate, root=ROOT)
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
        # ZG-033 is blocked by unsatisfied ZG-022 and ZG-040 regardless of its own issue state.
        report = ps.readiness_report(self.state, root=ROOT)["ZG-033"]
        self.assertFalse(report["hard_prerequisites_satisfied"])
        self.assertEqual(report["unsatisfied_parents"], ["ZG-022"])

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
