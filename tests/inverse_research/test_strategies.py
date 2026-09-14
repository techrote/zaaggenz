from dataclasses import replace
import unittest

from zaaggenz_project import Project
from zaaggenz_inverse import SearchBudget, prepare_experiment, request_from_project
from zaaggenz_inverse.search import grid_state
from zaaggenz_jobs.model import CancellationToken
from research.zg024b import (METHODS, StrategySpec, ResearchInterrupted,
    run_strategy, research_fixture, normalized_parameter_error,
    nonidentifiable_manifold_error)


class StrategyTests(unittest.TestCase):
    def small_fixture(self, name='offgrid-envelope', seed='24', budget=5):
        fixture = research_fixture(name, seed=seed)
        return replace(fixture, budget=SearchBudget(budget, 5, 2))

    def test_all_methods_obey_same_logical_budget_and_bounds(self):
        fixture = self.small_fixture(budget=5)
        for method in METHODS:
            with self.subTest(method=method):
                fit, _ = fixture.experiment()
                result = run_strategy(fit, StrategySpec(method))
                self.assertEqual(len(result.candidates), 5)
                self.assertEqual(result.to_dict()['budget']['declared_evaluations'], 5)
                self.assertEqual(result.to_dict()['budget']['consumed_evaluations'], 5)
                self.assertEqual(fit.render_calls, 10)
                self.assertEqual(len({c.id for c in result.candidates}), 5)
                for candidate in result.candidates:
                    fixture.domain.validate_state(
                        __import__('zaaggenz_inverse').ParameterState.from_dict(candidate.to_dict()['parameters']))

    def test_each_method_is_exactly_repeatable_in_same_environment(self):
        fixture = self.small_fixture(budget=4)
        for method in METHODS:
            with self.subTest(method=method):
                a, _ = fixture.experiment(); b, _ = fixture.experiment()
                ra = run_strategy(a, StrategySpec(method)); rb = run_strategy(b, StrategySpec(method))
                self.assertEqual(ra.to_dict(), rb.to_dict())
                self.assertEqual(ra.sha256, rb.sha256)

    def test_grid_wrapper_matches_frozen_foundation_proposals(self):
        fixture = self.small_fixture(budget=5)
        fit, _ = fixture.experiment()
        result = run_strategy(fit, StrategySpec('zg024b.grid-prefix.v1'))
        for ordinal, candidate in enumerate(result.candidates):
            self.assertEqual(candidate.to_dict()['parameters'], grid_state(fit.request, ordinal).to_dict())

    def test_search_seed_changes_seeded_research_paths(self):
        for method in ('zg024b.uniform-splitmix.v1', 'zg024b.halton-shifted.v1', 'zg024b.coordinate-refine.v1'):
            with self.subTest(method=method):
                a = self.small_fixture(seed='24', budget=4); b = self.small_fixture(seed='97', budget=4)
                fa, _ = a.experiment(); fb, _ = b.experiment()
                pa = [c.to_dict()['parameters'] for c in run_strategy(fa, StrategySpec(method)).candidates]
                pb = [c.to_dict()['parameters'] for c in run_strategy(fb, StrategySpec(method)).candidates]
                self.assertNotEqual(pa, pb)

    def test_coordinate_lineage_names_parents_and_adaptive_round(self):
        fixture = self.small_fixture(budget=6)
        fit, _ = fixture.experiment()
        result = run_strategy(fit, StrategySpec('zg024b.coordinate-refine.v1'))
        self.assertEqual(result.lineage[0]['proposal']['phase'], 'initial-halton')
        self.assertFalse(result.lineage[0]['parent_candidate_ids'])
        self.assertTrue(all(row['parent_candidate_ids'] for row in result.lineage[1:]))
        self.assertTrue(any(row['proposal'].get('round') == 0 for row in result.lineage[1:]))

    def test_truth_and_holdouts_are_not_capabilities_of_strategy_runner(self):
        fixture = self.small_fixture(budget=3)
        fit, audit = fixture.experiment()
        self.assertFalse(hasattr(fit, 'ground_truth'))
        self.assertFalse(hasattr(fit, 'holdout'))
        with self.assertRaises(Exception):
            run_strategy(audit, StrategySpec(METHODS[0]))

    def test_holdout_mutation_cannot_change_proposals_or_fit_results(self):
        fixture = self.small_fixture('offgrid-envelope', budget=4)
        target = fixture.target.copy()
        target[4000:5600] *= -0.7
        request = request_from_project(Project(fixture.base_recipe), target, fixture.plan,
            fixture.domain, objective=fixture.objective, budget=fixture.budget, seed=fixture.seed)
        for method in METHODS:
            with self.subTest(method=method):
                a, _ = fixture.experiment(); b, _ = prepare_experiment(request, target, fixture.plan)
                ra = run_strategy(a, StrategySpec(method)); rb = run_strategy(b, StrategySpec(method))
                self.assertNotEqual(ra.evaluator_search_id, rb.evaluator_search_id)
                self.assertEqual([c.to_dict()['parameters'] for c in ra.candidates],
                                 [c.to_dict()['parameters'] for c in rb.candidates])
                self.assertEqual([c.score for c in ra.candidates], [c.score for c in rb.candidates])
                self.assertEqual([c.eligible for c in ra.candidates], [c.eligible for c in rb.candidates])

    def test_verified_prefix_resume_replays_and_matches(self):
        fixture = self.small_fixture(budget=5)
        for method in ('zg024b.halton-shifted.v1', 'zg024b.coordinate-refine.v1'):
            with self.subTest(method=method):
                fit, _ = fixture.experiment(); token = CancellationToken(); checkpoints = []
                def checkpoint(cp):
                    checkpoints.append(cp)
                    if cp.next_ordinal == 2:
                        token.cancel()
                with self.assertRaises(ResearchInterrupted) as caught:
                    run_strategy(fit, StrategySpec(method), check_cancelled=token.check, on_checkpoint=checkpoint)
                self.assertEqual(caught.exception.checkpoint.next_ordinal, 2)
                replay, _ = fixture.experiment(); fresh, _ = fixture.experiment()
                resumed = run_strategy(replay, StrategySpec(method), checkpoint=checkpoints[-1])
                complete = run_strategy(fresh, StrategySpec(method))
                self.assertEqual(resumed.to_dict(), complete.to_dict())

    def test_post_search_truth_metrics_are_explicit_and_identifiability_aware(self):
        fixture = self.small_fixture('offgrid-envelope', budget=4)
        fit, _ = fixture.experiment(); result = run_strategy(fit, StrategySpec(METHODS[1]))
        best = next(c for c in result.candidates if c.id == result.ranked_candidate_ids[0])
        self.assertIsNotNone(normalized_parameter_error(fixture, best))
        self.assertIsNone(nonidentifiable_manifold_error(fixture, best))
        nonid = self.small_fixture('offgrid-nonidentifiable', budget=4)
        fit, _ = nonid.experiment(); result = run_strategy(fit, StrategySpec(METHODS[1]))
        best = next(c for c in result.candidates if c.id == result.ranked_candidate_ids[0])
        self.assertIsNone(normalized_parameter_error(nonid, best))
        self.assertIsNotNone(nonidentifiable_manifold_error(nonid, best))


if __name__ == '__main__':
    unittest.main()
