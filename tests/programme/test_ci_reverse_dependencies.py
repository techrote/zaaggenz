from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import ci_reverse_dependencies as ci  # noqa: E402


class ReverseDependencyCI(unittest.TestCase):
    def dispatch_names(self, changed: str) -> set[str]:
        result = ci.classify_changed_paths([changed], ROOT)
        return {row["workflow"] for row in result["dispatch"]}

    def native_names(self, changed: str) -> set[str]:
        return set(ci.classify_changed_paths([changed], ROOT)["native"])

    def test_complete_current_workflow_audit(self) -> None:
        _, _, audits = ci.build_audit(ROOT)
        self.assertEqual(37, len(audits))
        self.assertIn("zg001-recovery.yml", audits)
        self.assertTrue(audits["zg002-contracts.yml"].always_native)
        self.assertIn("zg024a-lab.yml", audits)
        self.assertIn("zg024b-strategies.yml", audits)
        self.assertIn("zg024d-staged.yml", audits)
        self.assertIn("zg029-layers.yml", audits)
        self.assertIn("zg030-pockets.yml", audits)
        self.assertIn("zg032-vocal.yml", audits)
        self.assertIn("zg040-studies.yml", audits)
        self.assertIn("zg042-performance.yml", audits)
        self.assertIn("zg045-environment.yml", audits)

    def test_tuning_change_selects_spectral_and_inspector_consumers(self) -> None:
        dispatch = self.dispatch_names("zaaggenz_tuning/core.py")
        native = self.native_names("zaaggenz_tuning/core.py")
        self.assertIn("zg007-tuning.yml", native)
        self.assertIn("zg020-adaptive.yml", native)
        self.assertIn("zg017-spectral.yml", dispatch)
        self.assertIn("zg023-inspector.yml", dispatch)

    def test_spectral_change_selects_inspector_and_inverse_consumers(self) -> None:
        dispatch = self.dispatch_names("zaaggenz_spectral/engine.py")
        native = self.native_names("zaaggenz_spectral/engine.py")
        self.assertIn("zg017-spectral.yml", native)
        self.assertIn("zg018-chordness.yml", native)
        self.assertIn("zg019-placement.yml", native)
        self.assertIn("zg021-band-selective.yml", native)
        self.assertIn("zg024a-lab.yml", native)
        self.assertIn("zg023-inspector.yml", dispatch)
        self.assertIn("zg024b-strategies.yml", dispatch)

    def test_jobs_change_selects_async_consumers(self) -> None:
        dispatch = self.dispatch_names("zaaggenz_jobs/scheduler.py")
        native = self.native_names("zaaggenz_jobs/scheduler.py")
        self.assertIn("zg004-jobs.yml", native)
        self.assertIn("zg024a-lab.yml", native)
        self.assertIn("zg009-timeline.yml", dispatch)
        self.assertIn("zg015-listening.yml", dispatch)
        self.assertIn("zg023-inspector.yml", dispatch)
        self.assertIn("zg024b-strategies.yml", dispatch)

    def test_contract_change_reaches_deep_consumers(self) -> None:
        result = ci.classify_changed_paths(["zaaggenz_contracts/validation.py"], ROOT)
        dispatch = {row["workflow"] for row in result["dispatch"]}
        self.assertEqual(["ZG-002"], result["direct_stable_ids"])
        self.assertIn("zg002-contracts.yml", result["native"])
        self.assertIn("zg016-dsp.yml", dispatch)
        self.assertIn("zg023-inspector.yml", dispatch)
        self.assertIn("zg032-vocal.yml", dispatch)

    def test_broad_consumer_filter_does_not_claim_source_ownership(self) -> None:
        result = ci.classify_changed_paths(["zaaggenz_melody/render.py"], ROOT)
        self.assertEqual(["ZG-008"], result["direct_stable_ids"])
        self.assertNotIn("zg024a-lab.yml", result["impacted"])

    def test_feature_local_change_still_runs_owner_natively(self) -> None:
        result = ci.classify_changed_paths(["zaaggenz_phrase/model.py"], ROOT)
        self.assertEqual(["ZG-025"], result["direct_stable_ids"])
        self.assertIn("zg025-phrase.yml", result["native"])
        dispatch = {row["workflow"] for row in result["dispatch"]}
        self.assertIn("zg026-meter.yml", dispatch)
        self.assertIn("zg027-gesture.yml", dispatch)
        self.assertIn("zg028-linked.yml", dispatch)
        self.assertIn("zg031-textgesture.yml", dispatch)

    def test_persistent_layer_runtime_has_explicit_owner_and_native_gate(self) -> None:
        result = ci.classify_changed_paths(["zaaggenz_layers/runtime.py"], ROOT)
        self.assertEqual(["ZG-029"], result["direct_stable_ids"])
        self.assertIn("zg029-layers.yml", result["native"])

    def test_layer_pockets_preserve_package_owner_and_add_feature_owner(self) -> None:
        result = ci.classify_changed_paths(["zaaggenz_layers/pockets.py"], ROOT)
        self.assertEqual(["ZG-029", "ZG-030"], result["direct_stable_ids"])
        self.assertIn("zg029-layers.yml", result["native"])
        self.assertIn("zg030-pockets.yml", result["native"])
        integration = ci.classify_changed_paths(["zaaggenz_layers/integration.py"], ROOT)
        self.assertEqual(["ZG-029", "ZG-030"], integration["direct_stable_ids"])
        self.assertIn("zg029-layers.yml", integration["native"])
        self.assertIn("zg030-pockets.yml", integration["native"])

    def test_study_package_has_explicit_zg040_owner_and_native_gate(self) -> None:
        result = ci.classify_changed_paths(["zaaggenz_studies/model.py"], ROOT)
        self.assertEqual(["ZG-040"], result["direct_stable_ids"])
        self.assertIn("zg040-studies.yml", result["native"])

    def test_performance_package_has_explicit_zg042_owner_and_native_gate(self) -> None:
        result = ci.classify_changed_paths(["zaaggenz_performance/policy.py"], ROOT)
        self.assertEqual(["ZG-042"], result["direct_stable_ids"])
        self.assertIn("zg042-performance.yml", result["native"])

    def test_packaging_change_runs_zg045_natively_without_inventing_downstream_consumers(self) -> None:
        result = ci.classify_changed_paths(["zaaggenz_environment/runtime.py"], ROOT)
        self.assertEqual(["ZG-045"], result["direct_stable_ids"])
        self.assertIn("zg045-environment.yml", result["native"])
        self.assertEqual([], result["dispatch"])

    def test_docs_only_change_does_not_create_downstream_work(self) -> None:
        result = ci.classify_changed_paths(["docs/spectral/README.md"], ROOT)
        self.assertEqual([], result["dispatch"])
        self.assertEqual([], result["direct_stable_ids"])

    def test_dependency_map_change_is_validation_only(self) -> None:
        result = ci.classify_changed_paths(["programme/dependency_graph.json"], ROOT)
        self.assertEqual([], result["dispatch"])
        self.assertEqual([], result["direct_stable_ids"])

    def test_workflow_definition_change_validates_without_product_fanout(self) -> None:
        result = ci.classify_changed_paths([".github/workflows/zg017-spectral.yml"], ROOT)
        self.assertEqual([], result["dispatch"])
        self.assertEqual([], result["direct_stable_ids"])

    def test_cross_cutting_requirements_have_explicit_owner(self) -> None:
        contract = ci.classify_changed_paths(["requirements-contracts.txt"], ROOT)
        jobs = ci.classify_changed_paths(["requirements-jobs.txt"], ROOT)
        self.assertIn("ZG-002", contract["direct_stable_ids"])
        self.assertIn("zg002-contracts.yml", contract["native"])
        self.assertIn("ZG-004", jobs["direct_stable_ids"])

    def test_dispatch_is_serial_and_watch_is_separate(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "zg000-ci-impact.yml").read_text(encoding="utf-8")
        self.assertIn("Dispatch required downstream workflows serially", workflow)
        self.assertIn("watch_matrix", workflow)
        self.assertIn("workflow dispatch failed after bounded retries", workflow)
        self.assertIn("max-parallel: 4", workflow)
        self.assertIn("--interval 60 --exit-status", workflow)
        self.assertNotIn("matrix.workflow }}\n          STABLE_ID", workflow.split("  dispatch:", 1)[1].split("  watch:", 1)[0])

    def test_dispatch_failure_is_observable_and_discovery_is_bounded(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "zg000-ci-impact.yml").read_text(encoding="utf-8")
        self.assertIn("capture_output=True", workflow)
        self.assertIn("if cp.stderr", workflow)
        self.assertIn("for attempt, delay in enumerate((0, 30, 90)", workflow)
        self.assertIn("for delay in (10, 30, 60)", workflow)
        self.assertNotIn("sleep 2", workflow)


if __name__ == "__main__":
    unittest.main()
