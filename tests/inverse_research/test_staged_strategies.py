import unittest

from zaaggenz_jobs import JobCancelled
from zaaggenz_project import Project
from zaaggenz_inverse import prepare_experiment, request_from_project
from research.zg024d import (
    DESIGN_MANIFEST, METHODS, StagedInterrupted, StagedResumeDivergence, StagedSpec,
    development_fixture, run_staged, sentinel_renderer,
)


class StagedStrategyV2Tests(unittest.TestCase):
    def run_fixture(self, name='dev-mixed', method='zg024d.staged-balanced.v2', seed='41'):
        fixture = development_fixture(name, seed=seed)
        fit, audit = fixture.experiment()
        return fixture, fit, audit, run_staged(fit, StagedSpec(method))

    def test_all_frozen_allocations_consume_exact_budget_and_retain_lineage(self):
        for method in METHODS:
            with self.subTest(method=method):
                fixture, fit, _, result = self.run_fixture(method=method)
                expected = dict(zip(('A', 'B', 'C'), StagedSpec(method).allocation))
                self.assertEqual(len(result.candidates), 24)
                self.assertEqual(dict(result.stage_consumption), expected)
                self.assertEqual(len({candidate.id for candidate in result.candidates}), 24)
                self.assertEqual(len(result.lineage), 24)
                self.assertEqual(fit.render_calls, 48)
                self.assertIsNone(result.stop_reason)
                self.assertEqual([row['stage'] for row in result.promotions], ['A', 'B', 'C-final'])
                eligible = {candidate.id for candidate in result.candidates if candidate.eligible}
                for promotion in result.promotions:
                    self.assertLessEqual(len(promotion['retained_candidate_ids']), 4)
                    self.assertTrue(set(promotion['retained_candidate_ids']) <= eligible)
                self.assertTrue(result.final_retained_candidate_ids)

    def test_parameter_families_are_isolated_by_stage_and_parent(self):
        fixture, _, _, result = self.run_fixture()
        base = dict(__import__('zaaggenz_inverse.recipes', fromlist=['state_from_recipe']).state_from_recipe(
            fixture.base_recipe, fixture.domain).values)
        states = {candidate.id: dict(candidate.to_dict()['parameters']['values']) for candidate in result.candidates}
        families = {stage: set(names) for stage, names in DESIGN_MANIFEST['families'].items()}
        for row in result.lineage:
            state = states[row['candidate_id']]
            if row['stage'] == 'A':
                anchor = base
                self.assertEqual(row['parent_candidate_ids'], [])
                family = families['A']
            else:
                self.assertEqual(len(row['parent_candidate_ids']), 1)
                anchor = states[row['parent_candidate_ids'][0]]
                family = families[row['stage']]
            for path, value in state.items():
                if path.rsplit('/', 1)[-1] not in family:
                    self.assertEqual(value, anchor[path], (row, path))

    def test_exact_replay_resume_and_stale_method_rejection(self):
        fixture = development_fixture('dev-mixed')
        fit, _ = fixture.experiment()
        interrupted = None

        def cancel_after_five(checkpoint):
            if checkpoint.next_ordinal == 5:
                raise JobCancelled('test cancellation')

        try:
            run_staged(fit, StagedSpec(METHODS[0]), on_checkpoint=cancel_after_five)
        except StagedInterrupted as exc:
            interrupted = exc
        self.assertIsNotNone(interrupted)
        self.assertEqual(interrupted.checkpoint.next_ordinal, 5)

        resumed_fit, _ = fixture.experiment()
        resumed = run_staged(resumed_fit, StagedSpec(METHODS[0]), checkpoint=interrupted.checkpoint)
        clean_fit, _ = fixture.experiment()
        clean = run_staged(clean_fit, StagedSpec(METHODS[0]))
        self.assertEqual(resumed.to_dict(), clean.to_dict())
        self.assertEqual(resumed.sha256, clean.sha256)

        stale_fit, _ = fixture.experiment()
        with self.assertRaises(StagedResumeDivergence):
            run_staged(stale_fit, StagedSpec(METHODS[1]), checkpoint=interrupted.checkpoint)

    def test_render_cache_is_reused_without_collapsing_strategy_identity(self):
        fixture = development_fixture('dev-mixed')
        fit, _ = fixture.experiment()
        first = run_staged(fit, StagedSpec(METHODS[0]))
        calls = fit.render_calls
        hits = fit.render_hits
        replay = run_staged(fit, StagedSpec(METHODS[0]))
        self.assertEqual(first.to_dict(), replay.to_dict())
        self.assertEqual(fit.render_calls, calls)
        self.assertGreater(fit.render_hits, hits)

        other_fit, _ = fixture.experiment(render_cache=fit.render_cache)
        other = run_staged(other_fit, StagedSpec(METHODS[1]))
        self.assertNotEqual(first.run_id, other.run_id)
        self.assertNotEqual(first.strategy.sha256, other.strategy.sha256)

    def test_same_environment_is_byte_exact_and_seed_changes_coverage(self):
        a = development_fixture('dev-structure', seed='41'); b = development_fixture('dev-structure', seed='41')
        af, _ = a.experiment(); bf, _ = b.experiment()
        ra = run_staged(af, StagedSpec(METHODS[0])); rb = run_staged(bf, StagedSpec(METHODS[0]))
        self.assertEqual(ra.to_dict(), rb.to_dict())
        c = development_fixture('dev-structure', seed='211'); cf, _ = c.experiment()
        rc = run_staged(cf, StagedSpec(METHODS[0]))
        self.assertNotEqual([x.to_dict()['parameters'] for x in ra.candidates[:8]],
                            [x.to_dict()['parameters'] for x in rc.candidates[:8]])

    def test_holdout_mutation_cannot_change_proposals_fit_scores_or_eligibility(self):
        fixture = development_fixture('dev-mixed')
        target = fixture.target.copy(); target[3900:5600] *= -0.73
        request = request_from_project(Project(fixture.base_recipe), target, fixture.plan, fixture.domain,
            objective=fixture.objective, budget=fixture.budget, seed=fixture.seed)
        original_fit, _ = fixture.experiment()
        changed_fit, _ = prepare_experiment(request, target, fixture.plan)
        a = run_staged(original_fit, StagedSpec(METHODS[0]))
        b = run_staged(changed_fit, StagedSpec(METHODS[0]))
        self.assertNotEqual(a.evaluator_search_id, b.evaluator_search_id)
        self.assertEqual([c.to_dict()['parameters'] for c in a.candidates],
                         [c.to_dict()['parameters'] for c in b.candidates])
        self.assertEqual([c.score for c in a.candidates], [c.score for c in b.candidates])
        self.assertEqual([c.eligible for c in a.candidates], [c.eligible for c in b.candidates])

    def test_adversarial_sentinels_are_owned_by_existing_gates_and_never_promoted(self):
        expected = {
            'sentinel-transient': {'transient_loss', 'silence_collapse'},
            'sentinel-silence': {'silence_collapse', 'transient_loss', 'energy_collapse'},
            'sentinel-clipping': {'pathological_clipping', 'destructive_output_clipping'},
        }
        for name, expected_any in expected.items():
            with self.subTest(name=name):
                fixture = development_fixture(name)
                renderer, renderer_id = sentinel_renderer(name)
                fit, _ = fixture.experiment(renderer=renderer, renderer_id=renderer_id)
                result = run_staged(fit, StagedSpec(METHODS[0]))
                eligible = {candidate.id for candidate in result.candidates if candidate.eligible}
                promoted = {candidate_id for record in result.promotions for candidate_id in record['retained_candidate_ids']}
                self.assertTrue(promoted <= eligible)
                reasons = set()
                for candidate in result.candidates:
                    for window in candidate.to_dict()['fit']['windows']:
                        reasons.update(window['validation']['rejected_reasons'])
                self.assertTrue(reasons & expected_any, (name, reasons))
                self.assertTrue(any(not candidate.eligible for candidate in result.candidates))

    def test_audit_capability_is_rejected_at_strategy_boundary(self):
        fixture = development_fixture('dev-mixed'); _, audit = fixture.experiment()
        with self.assertRaises(Exception):
            run_staged(audit, StagedSpec(METHODS[0]))


if __name__ == '__main__':
    unittest.main()
