import unittest

from zaaggenz_jobs import JobCancelled
from zaaggenz_project import Project
from zaaggenz_inverse import prepare_experiment, request_from_project
from zaaggenz_inverse.recipes import state_from_recipe
from research.zg024e import (
    DESIGN_MANIFEST,
    METHODS,
    DiagnosticInterrupted,
    DiagnosticResumeDivergence,
    DiagnosticSpec,
    development_fixture,
    run_diagnostic,
    sentinel_renderer,
)
from tools.inverse_feasibility_report import _budget_accounting_ok


class ZG024eDiagnosticTests(unittest.TestCase):
    def run_fixture(self, name="dev2-mixed-texture",
                    method="zg024e.factorized-36-balanced.v1", seed="53"):
        spec = DiagnosticSpec(method)
        fixture = development_fixture(name, seed=seed, budget_evaluations=spec.budget)
        fit, audit = fixture.experiment()
        return fixture, fit, audit, run_diagnostic(fit, spec)

    def test_frozen_method_budgets_allocations_and_parent_caps(self):
        expected = {
            "zg024e.factorized-24-control.v1": (24, {"A": 10, "B": 7, "C": 7}, 4),
            "zg024e.factorized-36-balanced.v1": (36, {"A": 12, "B": 12, "C": 12}, 4),
            "zg024e.factorized-36-a-heavy.v1": (36, {"A": 16, "B": 10, "C": 10}, 4),
            "zg024e.factorized-36-b-heavy.v1": (36, {"A": 10, "B": 16, "C": 10}, 4),
            "zg024e.factorized-36-wide-parents.v1": (36, {"A": 12, "B": 12, "C": 12}, 8),
            "zg024e.coupled-ab-36.v1": (36, {"AB": 24, "C": 12}, 4),
        }
        self.assertEqual(set(METHODS), set(expected))
        for method, (budget, allocation, retain) in expected.items():
            with self.subTest(method=method):
                spec = DiagnosticSpec(method)
                self.assertEqual(spec.budget, budget)
                self.assertEqual(spec.allocation, allocation)
                self.assertEqual(spec.retain, retain)

    def test_all_methods_preserve_budget_and_never_promote_ineligible(self):
        for method in METHODS:
            with self.subTest(method=method):
                fixture, fit, _, result = self.run_fixture(method=method)
                spec = DiagnosticSpec(method)
                self.assertLessEqual(len(result.candidates), spec.budget)
                self.assertEqual(
                    sum(dict(result.stage_consumption).values()), len(result.candidates)
                )
                self.assertEqual(
                    len({candidate.id for candidate in result.candidates}),
                    len(result.candidates),
                )
                self.assertEqual(fit.render_calls, 2 * len(result.candidates))
                eligible = {
                    candidate.id for candidate in result.candidates if candidate.eligible
                }
                for record in result.promotions:
                    self.assertTrue(set(record["retained_candidate_ids"]) <= eligible)
                    self.assertLessEqual(
                        len(record["retained_candidate_ids"]), spec.retain
                    )

                row = {
                    "family": "diagnostic",
                    "method_id": method,
                    "declared_budget": spec.budget,
                    "consumed_evaluations": len(result.candidates),
                    "stage_consumption": dict(result.stage_consumption),
                    "stop_reason": result.stop_reason,
                    "final_retained_count": len(result.final_retained_candidate_ids),
                }
                self.assertTrue(_budget_accounting_ok(row))

    def test_factorized_stages_change_only_their_family_relative_to_parent(self):
        fixture, _, _, result = self.run_fixture(
            method="zg024e.factorized-36-balanced.v1"
        )
        base = dict(state_from_recipe(fixture.base_recipe, fixture.domain).values)
        states = {
            candidate.id: dict(candidate.to_dict()["parameters"]["values"])
            for candidate in result.candidates
        }
        families = {
            stage: set(names)
            for stage, names in DESIGN_MANIFEST["families"].items()
        }
        for row in result.lineage:
            state = states[row["candidate_id"]]
            if row["stage"] == "A":
                anchor = base
                family = families["A"]
                self.assertEqual(row["parent_candidate_ids"], [])
            else:
                self.assertEqual(len(row["parent_candidate_ids"]), 1)
                anchor = states[row["parent_candidate_ids"][0]]
                family = families[row["stage"]]
            for path, value in state.items():
                if path.rsplit("/", 1)[-1] not in family:
                    self.assertEqual(value, anchor[path], (row, path))

    def test_coupled_ab_removes_a_only_promotion_boundary(self):
        fixture, _, _, result = self.run_fixture(
            name="dev2-structure-spectral-starvation",
            method="zg024e.coupled-ab-36.v1",
        )
        self.assertNotIn("A", [row["stage"] for row in result.lineage])
        self.assertNotIn("B", [row["stage"] for row in result.lineage])
        self.assertEqual(result.promotions[0]["stage"], "AB")

        base = dict(state_from_recipe(fixture.base_recipe, fixture.domain).values)
        states = {
            candidate.id: dict(candidate.to_dict()["parameters"]["values"])
            for candidate in result.candidates
        }
        allowed_ab = set(DESIGN_MANIFEST["families"]["A"]) | set(
            DESIGN_MANIFEST["families"]["B"]
        )
        allowed_c = set(DESIGN_MANIFEST["families"]["C"])
        for row in result.lineage:
            state = states[row["candidate_id"]]
            if row["stage"] == "AB":
                self.assertEqual(row["parent_candidate_ids"], [])
                anchor = base
                allowed = allowed_ab
            else:
                self.assertEqual(row["stage"], "C")
                self.assertEqual(len(row["parent_candidate_ids"]), 1)
                anchor = states[row["parent_candidate_ids"][0]]
                allowed = allowed_c
            for path, value in state.items():
                if path.rsplit("/", 1)[-1] not in allowed:
                    self.assertEqual(value, anchor[path], (row, path))

    def test_wide_parent_method_retains_only_eligible_up_to_eight(self):
        _, _, _, result = self.run_fixture(
            method="zg024e.factorized-36-wide-parents.v1"
        )
        eligible = {candidate.id for candidate in result.candidates if candidate.eligible}
        for record in result.promotions:
            self.assertLessEqual(len(record["retained_candidate_ids"]), 8)
            self.assertTrue(set(record["retained_candidate_ids"]) <= eligible)

    def test_exact_resume_and_changed_method_fail_closed(self):
        method = "zg024e.factorized-36-balanced.v1"
        spec = DiagnosticSpec(method)
        fixture = development_fixture(
            "dev2-mixed-texture", budget_evaluations=spec.budget
        )
        fit, _ = fixture.experiment()
        interrupted = None

        def cancel_after_five(checkpoint):
            if checkpoint.next_ordinal == 5:
                raise JobCancelled("test cancellation")

        try:
            run_diagnostic(fit, spec, on_checkpoint=cancel_after_five)
        except DiagnosticInterrupted as exc:
            interrupted = exc
        self.assertIsNotNone(interrupted)
        self.assertEqual(interrupted.checkpoint.next_ordinal, 5)

        resumed_fit, _ = fixture.experiment()
        resumed = run_diagnostic(
            resumed_fit, spec, checkpoint=interrupted.checkpoint
        )
        clean_fit, _ = fixture.experiment()
        clean = run_diagnostic(clean_fit, spec)
        self.assertEqual(resumed.to_dict(), clean.to_dict())
        self.assertEqual(resumed.sha256, clean.sha256)

        other_spec = DiagnosticSpec("zg024e.factorized-36-a-heavy.v1")
        stale_fit, _ = fixture.experiment()
        with self.assertRaises(DiagnosticResumeDivergence):
            run_diagnostic(
                stale_fit, other_spec, checkpoint=interrupted.checkpoint
            )

    def test_holdout_mutation_cannot_change_proposals_fit_or_eligibility(self):
        spec = DiagnosticSpec("zg024e.factorized-36-balanced.v1")
        fixture = development_fixture(
            "dev2-mixed-texture", budget_evaluations=spec.budget
        )
        changed_target = fixture.target.copy()
        changed_target[4200:5750] *= -0.61
        request = request_from_project(
            Project(fixture.base_recipe),
            changed_target,
            fixture.plan,
            fixture.domain,
            objective=fixture.objective,
            budget=fixture.budget,
            seed=fixture.seed,
        )
        original_fit, _ = fixture.experiment()
        changed_fit, _ = prepare_experiment(request, changed_target, fixture.plan)
        original = run_diagnostic(original_fit, spec)
        changed = run_diagnostic(changed_fit, spec)

        self.assertNotEqual(original.evaluator_search_id, changed.evaluator_search_id)
        self.assertEqual(
            [candidate.to_dict()["parameters"] for candidate in original.candidates],
            [candidate.to_dict()["parameters"] for candidate in changed.candidates],
        )
        self.assertEqual(
            [candidate.score for candidate in original.candidates],
            [candidate.score for candidate in changed.candidates],
        )
        self.assertEqual(
            [candidate.eligible for candidate in original.candidates],
            [candidate.eligible for candidate in changed.candidates],
        )

    def test_cache_reuse_within_capacity_and_strategy_identity_separation(self):
        # The accepted bounded render cache is intentionally smaller than the
        # 36-evaluation diagnostic working set. Verify full replay reuse using the
        # preregistered 24-evaluation control (the inherited supported case), rather
        # than requiring an unbounded cache merely to make this test pass.
        control_spec = DiagnosticSpec("zg024e.factorized-24-control.v1")
        control_fixture = development_fixture(
            "dev2-mixed-texture", budget_evaluations=control_spec.budget
        )
        fit, _ = control_fixture.experiment()
        first = run_diagnostic(fit, control_spec)
        calls = fit.render_calls
        hits = fit.render_hits
        replay = run_diagnostic(fit, control_spec)
        self.assertEqual(first.to_dict(), replay.to_dict())
        self.assertEqual(fit.render_calls, calls)
        self.assertGreater(fit.render_hits, hits)

        # Strategy/run identity separation is checked independently at the new
        # 36-evaluation budget; cache capacity is not widened for the experiment.
        fixture36 = development_fixture(
            "dev2-mixed-texture", budget_evaluations=36
        )
        balanced_fit, _ = fixture36.experiment()
        balanced = run_diagnostic(
            balanced_fit, DiagnosticSpec("zg024e.factorized-36-balanced.v1")
        )
        other_fit, _ = fixture36.experiment(render_cache=balanced_fit.render_cache)
        other = run_diagnostic(
            other_fit, DiagnosticSpec("zg024e.factorized-36-a-heavy.v1")
        )
        self.assertNotEqual(balanced.run_id, other.run_id)
        self.assertNotEqual(balanced.strategy.sha256, other.strategy.sha256)

    def test_safety_sentinels_remain_hard_gated_and_unpromoted(self):
        expected = {
            "sentinel2-transient": {"transient_loss", "silence_collapse"},
            "sentinel2-silence": {
                "silence_collapse", "energy_collapse", "transient_loss"
            },
            "sentinel2-clipping": {
                "pathological_clipping", "destructive_output_clipping"
            },
        }
        spec = DiagnosticSpec("zg024e.factorized-36-balanced.v1")
        for name, expected_any in expected.items():
            with self.subTest(name=name):
                fixture = development_fixture(
                    name, budget_evaluations=spec.budget
                )
                renderer, renderer_id = sentinel_renderer(name)
                fit, _ = fixture.experiment(
                    renderer=renderer, renderer_id=renderer_id
                )
                result = run_diagnostic(fit, spec)
                eligible = {
                    candidate.id
                    for candidate in result.candidates
                    if candidate.eligible
                }
                promoted = {
                    candidate_id
                    for record in result.promotions
                    for candidate_id in record["retained_candidate_ids"]
                }
                self.assertTrue(promoted <= eligible)
                reasons = set()
                for candidate in result.candidates:
                    for window in candidate.to_dict()["fit"]["windows"]:
                        reasons.update(window["validation"]["rejected_reasons"])
                self.assertTrue(reasons & expected_any, (name, reasons))
                self.assertFalse(result.final_retained_candidate_ids)

    def test_audit_capability_is_rejected_at_search_boundary(self):
        spec = DiagnosticSpec("zg024e.factorized-36-balanced.v1")
        fixture = development_fixture(
            "dev2-mixed-texture", budget_evaluations=spec.budget
        )
        _, audit = fixture.experiment()
        with self.assertRaises(Exception):
            run_diagnostic(audit, spec)


class ZG024eBudgetAccountingTests(unittest.TestCase):
    def test_flat_controls_require_exact_declared_budget(self):
        row = {
            "family": "baseline",
            "method_id": "zg024b.halton-shifted.v1",
            "declared_budget": 36,
            "consumed_evaluations": 36,
            "stage_consumption": None,
            "stop_reason": None,
        }
        self.assertTrue(_budget_accounting_ok(row))
        row["consumed_evaluations"] = 35
        self.assertFalse(_budget_accounting_ok(row))

    def test_fail_closed_prefix_cannot_smuggle_downstream_work(self):
        row = {
            "family": "diagnostic",
            "method_id": "zg024e.factorized-36-balanced.v1",
            "declared_budget": 36,
            "consumed_evaluations": 13,
            "stage_consumption": {"A": 12, "B": 1, "C": 0},
            "stop_reason": "stage-A-no-eligible-parent",
            "final_retained_count": 0,
        }
        self.assertFalse(_budget_accounting_ok(row))


if __name__ == "__main__":
    unittest.main()
