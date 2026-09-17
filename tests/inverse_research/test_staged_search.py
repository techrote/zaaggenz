from dataclasses import replace
import unittest

from zaaggenz_project import Project
from zaaggenz_inverse import prepare_experiment, request_from_project
from zaaggenz_jobs.model import CancellationToken

from research.zg024d.fixtures import (
    DEV_NAMES, CONFIRM_NAMES, DEV_SEEDS, CONFIRM_SEEDS, SAFETY_NAMES,
    research_fixture, safety_fixture,
)
from research.zg024d.staged import (
    StageDefinition, StagedPlan, StagedInterrupted, run_staged,
)


class StagedSearchTests(unittest.TestCase):
    def test_all_frozen_fixture_plans_partition_domain_and_budget_exactly(self):
        for names, seeds in ((DEV_NAMES, DEV_SEEDS), (CONFIRM_NAMES, CONFIRM_SEEDS)):
            for name in names:
                fixture, plan = research_fixture(name, seed=seeds[0])
                with self.subTest(name=name):
                    plan.validate_request(fixture.request)
                    self.assertEqual(
                        sum(stage.evaluations for stage in plan.stages),
                        fixture.budget.max_evaluations,
                    )
                    staged_axes = sorted(path for stage in plan.stages for path in stage.axis_paths)
                    self.assertEqual(staged_axes, [axis.path for axis in fixture.domain.axes])

    def test_plan_rejects_axis_overlap_budget_mismatch_and_wrong_method(self):
        with self.assertRaises(Exception):
            StagedPlan((
                StageDefinition("stage-a-root-envelope", ("/x",), 1, 1, "shifted-halton-v1"),
                StageDefinition("stage-b-spectral", ("/x",), 1, 1, "parented-shifted-halton-v1"),
                StageDefinition("stage-c-texture", (), 0, 1, "parented-coordinate-v1"),
            ))
        with self.assertRaises(Exception):
            StageDefinition("stage-c-texture", ("/x",), 1, 1, "shifted-halton-v1")
        fixture, plan = research_fixture("dev-holdout", seed=DEV_SEEDS[0])
        changed = StagedPlan((
            replace(plan.stages[0], evaluations=8), plan.stages[1], plan.stages[2]
        ))
        with self.assertRaises(Exception):
            changed.validate_request(fixture.request)

    def test_staged_runner_consumes_unique_bounded_logical_budget(self):
        fixture, plan = research_fixture("dev-mixed", seed=DEV_SEEDS[0])
        fit, _ = fixture.experiment()
        result = run_staged(fit, plan)
        self.assertLessEqual(len(result.candidates), fixture.budget.max_evaluations)
        self.assertEqual(len({candidate.id for candidate in result.candidates}), len(result.candidates))
        self.assertEqual(len(result.candidates), len(result.lineage))
        self.assertEqual(result.to_dict()["budget"]["declared_evaluations"], 30)
        for candidate in result.candidates:
            fixture.domain.validate_state(
                __import__("zaaggenz_inverse").ParameterState.from_dict(candidate.to_dict()["parameters"])
            )

    def test_mixed_lineage_records_stage_and_parent_boundaries(self):
        fixture, plan = research_fixture("dev-mixed", seed=DEV_SEEDS[1])
        fit, _ = fixture.experiment()
        result = run_staged(fit, plan)
        stage_a = [row for row in result.lineage if row["stage_id"] == "stage-a-root-envelope"]
        stage_b = [row for row in result.lineage if row["stage_id"] == "stage-b-spectral"]
        stage_c = [row for row in result.lineage if row["stage_id"] == "stage-c-texture"]
        self.assertTrue(stage_a and stage_b and stage_c)
        self.assertTrue(all(not row["parent_candidate_ids"] for row in stage_a))
        # If a predecessor stage had at least one eligible retained candidate, every
        # child must name the exact parent candidate used to construct its proposal.
        if result.promotions[0]["retained_candidate_ids"]:
            self.assertTrue(all(len(row["parent_candidate_ids"]) == 1 for row in stage_b))
        if result.promotions[1]["retained_candidate_ids"]:
            self.assertTrue(all(len(row["parent_candidate_ids"]) == 1 for row in stage_c))
        self.assertEqual([row["stage_id"] for row in result.promotions],
                         [stage.id for stage in plan.stages])

    def test_exact_repeatability_same_environment_and_seed(self):
        fixture, plan = research_fixture("dev-holdout", seed=DEV_SEEDS[0])
        a, _ = fixture.experiment(); b, _ = fixture.experiment()
        ra = run_staged(a, plan); rb = run_staged(b, plan)
        self.assertEqual(ra.to_dict(), rb.to_dict())
        self.assertEqual(ra.sha256, rb.sha256)

    def test_search_seed_changes_proposals_without_changing_protocol(self):
        fa, plan_a = research_fixture("dev-root-envelope", seed=DEV_SEEDS[0])
        fb, plan_b = research_fixture("dev-root-envelope", seed=DEV_SEEDS[1])
        self.assertEqual(plan_a.to_dict(), plan_b.to_dict())
        ea, _ = fa.experiment(); eb, _ = fb.experiment()
        ra = run_staged(ea, plan_a); rb = run_staged(eb, plan_b)
        self.assertNotEqual(
            [c.to_dict()["parameters"] for c in ra.candidates],
            [c.to_dict()["parameters"] for c in rb.candidates],
        )

    def test_truth_and_holdout_are_not_staged_runner_capabilities(self):
        fixture, plan = research_fixture("dev-holdout", seed=DEV_SEEDS[0])
        fit, audit = fixture.experiment()
        self.assertFalse(hasattr(fit, "ground_truth"))
        self.assertFalse(hasattr(fit, "holdout"))
        with self.assertRaises(Exception):
            run_staged(audit, plan)

    def test_holdout_only_mutation_cannot_change_proposals_fit_scores_or_eligibility(self):
        fixture, plan = research_fixture("dev-holdout", seed=DEV_SEEDS[0])
        target = fixture.target.copy()
        target[4000:5600] *= -0.61
        request = request_from_project(
            Project(fixture.base_recipe), target, fixture.plan, fixture.domain,
            objective=fixture.objective, budget=fixture.budget, seed=fixture.seed,
        )
        original_fit, _ = fixture.experiment()
        mutated_fit, _ = prepare_experiment(request, target, fixture.plan)
        original = run_staged(original_fit, plan)
        mutated = run_staged(mutated_fit, plan)
        self.assertNotEqual(original.evaluator_search_id, mutated.evaluator_search_id)
        self.assertEqual(
            [c.to_dict()["parameters"] for c in original.candidates],
            [c.to_dict()["parameters"] for c in mutated.candidates],
        )
        self.assertEqual([c.score for c in original.candidates], [c.score for c in mutated.candidates])
        self.assertEqual([c.eligible for c in original.candidates], [c.eligible for c in mutated.candidates])

    def test_verified_adaptive_prefix_resume_matches_fresh_completion(self):
        fixture, plan = research_fixture("dev-holdout", seed=DEV_SEEDS[2])
        fit, _ = fixture.experiment()
        token = CancellationToken(); checkpoints = []

        def checkpoint(cp):
            checkpoints.append(cp)
            if cp.next_ordinal == 3:
                token.cancel()

        with self.assertRaises(StagedInterrupted) as caught:
            run_staged(fit, plan, check_cancelled=token.check, on_checkpoint=checkpoint)
        self.assertEqual(caught.exception.checkpoint.next_ordinal, 3)
        replay, _ = fixture.experiment(); fresh, _ = fixture.experiment()
        resumed = run_staged(replay, plan, checkpoint=checkpoints[-1])
        complete = run_staged(fresh, plan)
        self.assertEqual(resumed.to_dict(), complete.to_dict())

    def test_confirmation_and_development_seed_roles_do_not_overlap(self):
        self.assertTrue(set(DEV_SEEDS).isdisjoint(CONFIRM_SEEDS))
        self.assertTrue(set(DEV_NAMES).isdisjoint(CONFIRM_NAMES))
        with self.assertRaises(ValueError):
            research_fixture(CONFIRM_NAMES[0], seed=DEV_SEEDS[0])
        with self.assertRaises(ValueError):
            research_fixture(DEV_NAMES[0], seed=CONFIRM_SEEDS[0])

    def test_fresh_safety_probes_are_bounded_and_explicit(self):
        for name in SAFETY_NAMES:
            fixture, state, purpose = safety_fixture(name)
            with self.subTest(name=name):
                fixture.domain.validate_state(state)
                self.assertTrue(purpose)
                self.assertEqual(fixture.budget.max_evaluations, 1)
                fit, _ = fixture.experiment()
                candidate = fit.evaluate(state, 0)
                self.assertIsNotNone(candidate.to_dict()["validation"])
                self.assertTrue(all(__import__("math").isfinite(x) for x in candidate.to_dict()["fit"]["objectives"]["components"].values()))


if __name__ == "__main__":
    unittest.main()
