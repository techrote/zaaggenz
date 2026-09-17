from dataclasses import replace
import unittest

from zaaggenz_project import Project
from zaaggenz_inverse import SearchBudget, prepare_experiment, request_from_project
from research.zg024d import METHODS, StagedSpec, run_staged, research_fixture


class StagedStrategyTests(unittest.TestCase):
    def fixture(self, name='staged-calibration-nonlinear', seed='41', budget=12):
        return replace(research_fixture(name, seed=seed), budget=SearchBudget(budget, 5, 2))

    def test_exact_budget_uniqueness_bounds_and_stage_accounting(self):
        for method in METHODS:
            with self.subTest(method=method):
                fixture = self.fixture(budget=12); fit, _ = fixture.experiment()
                result = run_staged(fit, StagedSpec(method))
                self.assertEqual(len(result.candidates), 12)
                self.assertEqual(len({c.id for c in result.candidates}), 12)
                self.assertEqual(result.global_evaluations + result.local_evaluations, 12)
                self.assertEqual(fit.render_calls, 24)
                self.assertEqual(result.lineage[0]['proposal']['stage'], 'global')
                self.assertTrue(any(row['proposal']['stage'] in ('broad-local','fine-local') for row in result.lineage))
                for candidate in result.candidates:
                    fixture.domain.validate_state(__import__('zaaggenz_inverse').ParameterState.from_dict(
                        candidate.to_dict()['parameters']))

    def test_preregistered_fraction_boundaries_are_exact(self):
        expected = {
            'zg024d.staged-h33.v1': 4,
            'zg024d.staged-h50.v1': 6,
            'zg024d.staged-h67.v1': 8,
        }
        for method, count in expected.items():
            fit, _ = self.fixture(budget=12).experiment()
            self.assertEqual(run_staged(fit, StagedSpec(method)).global_evaluations, count)

    def test_same_environment_is_byte_for_byte_repeatable(self):
        for method in METHODS:
            a, _ = self.fixture(budget=8).experiment(); b, _ = self.fixture(budget=8).experiment()
            ra = run_staged(a, StagedSpec(method)); rb = run_staged(b, StagedSpec(method))
            self.assertEqual(ra.to_dict(), rb.to_dict())
            self.assertEqual(ra.sha256, rb.sha256)

    def test_seed_changes_global_path_without_truth_initialization(self):
        a, _ = self.fixture(seed='41', budget=8).experiment()
        b, _ = self.fixture(seed='211', budget=8).experiment()
        pa = [c.to_dict()['parameters'] for c in run_staged(a, StagedSpec(METHODS[1])).candidates]
        pb = [c.to_dict()['parameters'] for c in run_staged(b, StagedSpec(METHODS[1])).candidates]
        self.assertNotEqual(pa, pb)

    def test_local_lineage_names_fit_selected_parent(self):
        fit, _ = self.fixture(budget=10).experiment()
        result = run_staged(fit, StagedSpec('zg024d.staged-h50.v1'))
        local = [row for row in result.lineage if row['proposal']['stage'] in ('broad-local','fine-local')]
        self.assertTrue(local)
        self.assertTrue(all(len(row['parent_candidate_ids']) == 1 for row in local))
        self.assertTrue(all(row['proposal']['center_candidate_id'] == row['parent_candidate_ids'][0] for row in local))

    def test_holdout_mutation_cannot_change_fit_search(self):
        fixture = self.fixture('staged-audit-envelope', budget=8)
        target = fixture.target.copy(); target[4000:5600] *= -0.73
        request = request_from_project(Project(fixture.base_recipe), target, fixture.plan,
            fixture.domain, objective=fixture.objective, budget=fixture.budget, seed=fixture.seed)
        for method in METHODS:
            a, _ = fixture.experiment(); b, _ = prepare_experiment(request, target, fixture.plan)
            ra = run_staged(a, StagedSpec(method)); rb = run_staged(b, StagedSpec(method))
            self.assertNotEqual(ra.evaluator_search_id, rb.evaluator_search_id)
            self.assertEqual([c.to_dict()['parameters'] for c in ra.candidates],
                             [c.to_dict()['parameters'] for c in rb.candidates])
            self.assertEqual([c.score for c in ra.candidates], [c.score for c in rb.candidates])
            self.assertEqual([c.eligible for c in ra.candidates], [c.eligible for c in rb.candidates])

    def test_runner_rejects_audit_capability(self):
        fixture = self.fixture(budget=4); _, audit = fixture.experiment()
        with self.assertRaises(Exception):
            run_staged(audit, StagedSpec(METHODS[0]))


if __name__ == '__main__':
    unittest.main()
