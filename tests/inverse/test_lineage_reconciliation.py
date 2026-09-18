"""Regression guards for issue #90's non-destructive ZG-024 reconciliation."""
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
LINEAGE = ROOT / "docs" / "inverse" / "ZG024_LINEAGE_RECONCILIATION.md"
RAG = ROOT / "docs" / "zaaggenz" / "RAG_INDEX.md"
HANDOFFS = (
    ROOT / "docs" / "inverse" / "ZG024_RESEARCH_HANDOFF_1.md",
    ROOT / "docs" / "inverse" / "ZG024_RESEARCH_HANDOFF_2.md",
)


class ZG024LineageReconciliationTests(unittest.TestCase):
    def test_authoritative_and_superseded_prs_are_unambiguous(self):
        text = LINEAGE.read_text(encoding="utf-8")
        expected = {
            "#84": "ff6a5400df802b21e18395a0657d1a17f9ddccff",
            "#85": "6ae987eb12fa56307afddfc379d1374a87c02911",
            "#86": "44db98add56a00a317554064b3c672de79cd21bd",
            "#187": "ea79fbff0050f6534738f7428de8d5f0cc3d138d",
            "#194": "4bcdbf4a0fa2d37b2af777f12cd7e87bd1160f89",
            "#195": "a5e3c814a1bafdecbeb055d284e4e1a375e7103f",
            "#196": "c9f6b77730a1b1f9b19202e14b2f3f95b5f31bb4",
        }
        for pr, sha in expected.items():
            with self.subTest(pr=pr):
                self.assertIn(pr, text)
                self.assertIn(sha, text)
        self.assertIn("Authoritative ZG-024a foundation", text)
        self.assertIn("Accepted ZG-024b strategy-research pass", text)
        self.assertRegex(text, r"#85[^\n]+closed unmerged[^\n]+superseded")
        self.assertRegex(text, r"#196[^\n]+closed unmerged[^\n]+superseded")

    def test_every_audited_ref_has_exact_head_and_explicit_disposition(self):
        text = LINEAGE.read_text(encoding="utf-8")
        refs = {
            "work/zg024a-association-stability": "20cfce5c67b017ed647f0794d1a8d04c4df25450",
            "work/zg024a-inverse-foundations": "ff6a5400df802b21e18395a0657d1a17f9ddccff",
            "work/zg024a-lab-20260914": "6ae987eb12fa56307afddfc379d1374a87c02911",
            "work/zg024b-strategy-research": "44db98add56a00a317554064b3c672de79cd21bd",
            "zg024/provenance-binding-134": "ea79fbff0050f6534738f7428de8d5f0cc3d138d",
            "zg024/issue-87-transient-gate": "4bcdbf4a0fa2d37b2af777f12cd7e87bd1160f89",
            "repair/zg024-staged-strategy-92": "a5e3c814a1bafdecbeb055d284e4e1a375e7103f",
            "repair/zg024-staged-confirmation-92": "c9f6b77730a1b1f9b19202e14b2f3f95b5f31bb4",
        }
        for ref, sha in refs.items():
            with self.subTest(ref=ref):
                self.assertIn(f"`{ref}`", text)
                self.assertIn(f"`{sha}`", text)
        self.assertGreaterEqual(text.count("Safe to delete after this reconciliation record is merged."), 7)

    def test_unique_association_finding_is_preserved_without_false_promotion(self):
        text = LINEAGE.read_text(encoding="utf-8")
        self.assertIn("0fa1ec97fe18cc1f8a1208d45a53c65cfcae1f80", text)
        self.assertIn("34889037449", text)
        self.assertIn("1e-10 Hz", text)
        self.assertIn("Windows verification of that repaired variant was not established", text)
        self.assertIn("do not silently copy the old integer-microcent code into production", text)

    def test_temporary_snapshot_workflow_is_not_on_accepted_tree(self):
        self.assertFalse((ROOT / ".github" / "workflows" / "zg024a-reconcile-source.yml").exists())

    def test_rag_points_to_lineage_and_handoffs_do_not_instruct_old_branches(self):
        rag = RAG.read_text(encoding="utf-8")
        self.assertIn("ZG024_LINEAGE_RECONCILIATION.md", rag)
        stale_refs = (
            "work/zg024a-association-stability",
            "work/zg024a-inverse-foundations",
            "work/zg024a-lab-20260914",
            "work/zg024b-strategy-research",
        )
        for handoff in HANDOFFS:
            text = handoff.read_text(encoding="utf-8")
            for ref in stale_refs:
                with self.subTest(handoff=handoff.name, ref=ref):
                    self.assertNotIn(ref, text)

    def test_accidental_issues_are_not_programme_dependencies(self):
        pattern = re.compile(r"(?<!\d)#(?:81|82)\b")
        for path in (ROOT / "programme").rglob("*"):
            if not path.is_file() or path.suffix not in {".json", ".md"}:
                continue
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertIsNone(pattern.search(path.read_text(encoding="utf-8")))

    def test_frozen_zg024_evidence_files_remain_present(self):
        required = (
            ROOT / "examples" / "zg024a_inverse_calibration.json.gz",
            ROOT / "examples" / "zg024b_strategy_calibration.json",
            ROOT / "examples" / "zg024a_implementation_transitions.json",
            ROOT / "examples" / "zg024a_validation_transitions.json",
        )
        for path in required:
            with self.subTest(path=path.name):
                self.assertTrue(path.is_file())
                self.assertGreater(path.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
