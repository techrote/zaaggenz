from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import check_programme_docs as pd  # noqa: E402


class ProgrammeDocsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.docs, self.baseline = pd._load_texts(ROOT)
        self.state = json.loads((ROOT / "programme" / "task_state.json").read_text(encoding="utf-8"))

    def test_repository_documents_are_reconciled(self) -> None:
        self.assertEqual([], pd.audit_texts(self.docs, self.baseline, self.state))
        pd.check(ROOT)

    def test_root_readme_stale_zg001_gate_is_rejected(self) -> None:
        docs = dict(self.docs)
        docs["readme"] += (\n            "\nThe first implementation gate is **ZG-001**: recover and provenance-check the source.\n"\n        )
        errors = pd.audit_texts(docs, self.baseline, self.state)
        self.assertTrue(any("readme: stale live ZG-001" in error for error in errors))

    def test_deployment_stale_zg001_gate_is_rejected(self) -> None:
        docs = dict(self.docs)
        docs["deployment"] += (
            "\nThe actual v1.2.1 source/archive still has to be recovered before implementation.\n"
        )
        errors = pd.audit_texts(docs, self.baseline, self.state)
        self.assertTrue(any("deployment: stale live ZG-001" in error for error in errors))

    def test_historical_status_documents_require_explicit_non_live_boundary(self) -> None:
        docs = dict(self.docs)
        docs["research_scratchpad"] = docs["research_scratchpad"].replace(
            "Historical pre-G0 research workpad", "Pre-G0 research workpad"
        ).replace(
            "It is superseded as a live programme-status source; ", ""
        )
        errors = pd.audit_texts(docs, self.baseline, self.state)
        self.assertIn(
            "research_scratchpad: missing explicit historical/non-live-status boundary",
            errors,
        )

    def test_zg040_current_blocker_claim_is_rejected_when_reaccepted(self) -> None:
        docs = dict(self.docs)
        docs["overview"] += "\nZG-040 currently blocks confirmatory study-family work.\n"
        errors = pd.audit_texts(docs, self.baseline, self.state)
        self.assertIn(
            "overview: ZG-040 is dependency-satisfying but prose calls it a current blocker",
            errors,
        )

    def test_zg042_current_blocker_claim_is_rejected_when_reaccepted(self) -> None:
        docs = dict(self.docs)
        docs["overview"] += "\nZG-042 currently blocks release-validation work.\n"
        errors = pd.audit_texts(docs, self.baseline, self.state)
        self.assertIn(
            "overview: ZG-042 is dependency-satisfying but prose calls it a current blocker",
            errors,
        )

    def test_status_authority_pointer_is_required_where_status_is_reported(self) -> None:
        docs = dict(self.docs)
        docs["deployment"] = docs["deployment"].replace("task_state.json", "task-status.json")
        errors = pd.audit_texts(docs, self.baseline, self.state)
        self.assertIn("deployment: missing task_state.json authority pointer", errors)

    def test_current_inverse_terminal_evidence_is_required(self) -> None:
        for required in pd.ZG024_REQUIRED_RAG:
            with self.subTest(required=required):
                docs = dict(self.docs)
                docs["rag"] = docs["rag"].replace(required, f"OLD-{required}")
                errors = pd.audit_texts(docs, self.baseline, self.state)
                self.assertIn(f"rag: missing current inverse authority pointer {required}", errors)

    def test_rag_cannot_revert_to_handoff_1_2_as_terminal_current_state(self) -> None:
        docs = dict(self.docs)
        docs["rag"] += (
            "\nThe latest accepted serial ZG-024 handoffs are "
            "ZG024_RESEARCH_HANDOFF_1.md and ZG024_RESEARCH_HANDOFF_2.md.\n"
        )
        errors = pd.audit_texts(docs, self.baseline, self.state)
        self.assertIn("rag: stale Handoff-1/2-only terminal research claim present", errors)

    def test_rag_must_preserve_parent_incomplete_and_no_promotion_interpretation(self) -> None:
        docs = dict(self.docs)
        docs["rag"] = docs["rag"].replace(
            "**no production optimizer was promoted**", "a production optimizer was selected"
        )
        docs["rag"] = docs["rag"].replace(
            "Parent ZG-024 / #25 remains research-active",
            "Parent ZG-024 / #25 is complete",
        )
        errors = pd.audit_texts(docs, self.baseline, self.state)
        self.assertIn("rag: missing no-production-optimizer interpretation for ZG-024", errors)
        self.assertIn("rag: missing current parent ZG-024 research-active interpretation", errors)

    def test_runtime_requires_research_hub_and_single_session_authority(self) -> None:
        docs = dict(self.docs)
        docs["runtime"] = docs["runtime"].replace("`/research`", "`/experiment`")
        errors = pd.audit_texts(docs, self.baseline, self.state)
        self.assertIn("runtime: missing accepted non-destructive Research hub", errors)

        docs = dict(self.docs)
        docs["runtime"] = docs["runtime"].replace(
            "exactly one `RuntimeSession`", "several `RuntimeSession` instances"
        )
        errors = pd.audit_texts(docs, self.baseline, self.state)
        self.assertIn("runtime: missing single authoritative RuntimeSession ownership", errors)

    def test_runtime_requires_separate_trusted_listening_capability(self) -> None:
        docs = dict(self.docs)
        docs["runtime"] = docs["runtime"].replace(
            "Trusted Listening authority remains a separate server-held capability",
            "Trusted Listening authority shares the ordinary session capability",
        )
        errors = pd.audit_texts(docs, self.baseline, self.state)
        self.assertIn("runtime: missing separate trusted Listening capability boundary", errors)

    def test_baseline_hash_disagreement_is_rejected(self) -> None:
        docs = dict(self.docs)
        docs["context"] = docs["context"].replace(pd.RUNTIME_SHA, "0" * 64)
        errors = pd.audit_texts(docs, self.baseline, self.state)
        self.assertTrue(any("context missing accepted runtime payload" in error for error in errors))

    def test_zg001_must_remain_accepted_in_live_state(self) -> None:
        state = copy.deepcopy(self.state)
        state["tasks"]["ZG-001"]["dependency_satisfied"] = False
        errors = pd.audit_texts(self.docs, self.baseline, state)
        self.assertIn("live state no longer records accepted/satisfied ZG-001 recovery", errors)

    def test_owner_gate_and_research_state_are_not_erased(self) -> None:
        state = copy.deepcopy(self.state)
        state["tasks"]["ZG-022"]["owner_gate"] = "satisfied"
        state["tasks"]["ZG-024"]["research"] = "accepted"
        errors = pd.audit_texts(self.docs, self.baseline, state)
        self.assertIn("live state no longer records ZG-022 owner gate as pending/unsatisfied", errors)
        self.assertIn("live state no longer records ZG-024 as active research/unsatisfied", errors)


if __name__ == "__main__":
    unittest.main()
