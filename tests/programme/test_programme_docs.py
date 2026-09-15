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

    def test_stale_bootstrap_live_claim_is_rejected(self) -> None:
        docs = dict(self.docs)
        docs["overview"] += "\nThe **actual v1.2.1 source/archive still has to be recovered before work.\n"
        errors = pd.audit_texts(docs, self.baseline, self.state)
        self.assertTrue(any("stale live bootstrap claim" in e for e in errors))

    def test_missing_state_authority_pointer_is_rejected(self) -> None:
        docs = dict(self.docs)
        docs["requirements"] = docs["requirements"].replace("task_state.json", "task-status.json")
        errors = pd.audit_texts(docs, self.baseline, self.state)
        self.assertIn("requirements: missing task_state.json authority pointer", errors)

    def test_latest_inverse_handoff_pointer_is_required(self) -> None:
        docs = dict(self.docs)
        docs["rag"] = docs["rag"].replace("ZG024_RESEARCH_HANDOFF_2.md", "ZG024_RESEARCH_HANDOFF_OLD.md")
        errors = pd.audit_texts(docs, self.baseline, self.state)
        self.assertTrue(any("ZG024_RESEARCH_HANDOFF_2.md" in e for e in errors))

    def test_baseline_hash_disagreement_is_rejected(self) -> None:
        docs = dict(self.docs)
        docs["context"] = docs["context"].replace(pd.RUNTIME_SHA, "0" * 64)
        errors = pd.audit_texts(docs, self.baseline, self.state)
        self.assertTrue(any("context missing accepted runtime payload" in e for e in errors))

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
