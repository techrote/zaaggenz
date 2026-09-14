"""Synthetic recovery, leakage, cache, budget and exact-resume acceptance."""
import copy
import dataclasses
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import numpy as np

from zaaggenz_contracts import ContractError, derive_seed
from zaaggenz_inverse import *
from zaaggenz_inverse.engine import FitProblem, AuditTarget, DivergenceError, dominates, _trace_id
from zaaggenz_inverse.contracts import Snapshot
from zaaggenz_inverse.render import finish_render, execution_identity
from zaaggenz_inverse.fixtures import make_fixture, CATALOGUE
from zaaggenz_inverse.objectives import AXES
from zaaggenz_inverse.jobs import submit_inverse_job
from zaaggenz_jobs import JobScheduler, JobClass, JobCancelled
from zaaggenz_project import ArtifactCache
from zaaggenz_project.project import ProjectError


def winner(result):
    d = result.to_dict()
    return next(c for c in d['retained'] if c['id'] == d['best_candidate_id'])


class SearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = {n: make_fixture(n) for n in CATALOGUE if n != 'rich-nonlinear-48k'}
        cls.problems = {n: f.problem() for n, f in cls.cases.items()}
        cls.results = {n: run_baseline(p) for n, (p, _) in cls.problems.items()}

    def test_known_parameter_generation_and_witness_not_passed_to_search(self):
        for name, f in self.cases.items():
            state = ParameterState.from_mapping(f.witness.to_dict()['parameters'])
            rendered = f.renderer.render(state, derive_seed(f.request.to_dict()['seed'], 'inverse-render'), lambda: None)
            self.assertEqual(rendered.output.pcm, f.target.pcm)
            p, _ = self.problems[name]
            self.assertFalse(hasattr(p, 'witness'))
            self.assertFalse(hasattr(p.renderer, 'target'))
            self.assertFalse(hasattr(p.renderer, 'truth'))
            self.assertTrue(all(len(t.audio) < len(f.target.audio) for _, t in p.fitting_targets))
            self.assertEqual(make_fixture(name).fixture_id, f.fixture_id)

    def test_unique_identifiable_recovery(self):
        r = self.results['identifiable-bands']
        c = winner(r)
        self.assertEqual(c['parameters'], self.cases['identifiable-bands'].witness.to_dict()['parameters'])
        self.assertEqual(c['fit']['aggregate']['search_score'], 0.)
        self.assertEqual(len(r.to_dict()['frontier_candidate_ids']), 1)
        p, vault = self.problems['identifiable-bands']
        a = audit_result(r, vault, p.renderer, store=p._store).to_dict()
        best = next(v for v in a['candidates'] if v['candidate_id'] == c['id'])
        self.assertEqual(best['held_out']['aggregate']['search_score'], 0.)

    def test_exact_nonidentifiability_keeps_distinct_recipes(self):
        d = self.results['nonidentifiable-gains'].to_dict()
        zero = [c for c in d['retained'] if c['fit']['aggregate']['search_score'] == 0]
        self.assertEqual(len(zero), 3)
        self.assertEqual(len({c['id'] for c in zero}), 3)
        self.assertEqual(len({c['render']['output']['content_sha256'] for c in zero}), 1)
        self.assertEqual(len(d['frontier_candidate_ids']), 3)
        self.assertNotEqual(zero[0]['parameters'], zero[1]['parameters'])

    def test_weak_identifiability_is_quantified_not_claimed_as_recovery(self):
        d = self.results['weakly-identifiable-gains'].to_dict()
        reciprocal = [c for c in d['retained'] if abs(sum(c['parameters'].values())) < 1e-9]
        self.assertEqual(len(reciprocal), 3)
        errors = [c['fit']['aggregate']['components']['waveform']['raw'] for c in reciprocal]
        self.assertEqual(min(errors), 0.)
        self.assertGreater(max(errors), 1e-7)
        self.assertLess(max(errors), 1e-3)
        self.assertEqual(len({c['render']['output']['content_sha256'] for c in reciprocal}), 3)

    def test_feature_and_waveform_agreement_can_disagree(self):
        d = self.results['polarity-feature-conflict'].to_dict()
        negative = next(c for c in d['retained'] if c['parameters']['polarity'] == -1)
        a = negative['fit']['aggregate']
        self.assertEqual(a['components']['waveform']['raw'], 2.)
        self.assertEqual(a['search_score'], 0.)
        self.assertTrue(all(c['raw'] == 0 for k, c in a['components'].items() if k != 'waveform'))
        self.assertEqual(len(a['vector']), len(AXES))

    def test_intentional_overfit_is_exposed_only_after_freeze(self):
        r = self.results['fit-only-tail']; before = r.to_json()
        c = winner(r)
        self.assertEqual(c['parameters'], {'tail_gain_db': -12.})
        self.assertTrue(c['validation']['eligible'])
        self.assertEqual(c['fit']['aggregate']['search_score'], 0.)
        p, v = self.problems['fit-only-tail']
        a = audit_result(r, v, p.renderer, store=p._store).to_dict()
        rows = {x['candidate_id']: x for x in a['candidates']}
        held = rows[c['id']]['held_out']
        self.assertGreater(held['aggregate']['components']['waveform']['raw'], .7)
        self.assertGreater(held['aggregate']['components']['level']['raw'], 11.99)
        self.assertTrue(all('level_mismatch' in w['validation']['codes'] for w in held['windows']))
        self.assertEqual(r.to_json(), before)
        self.assertEqual([c['id'] for c in r.to_dict()['retained']], [c['candidate_id'] for c in a['candidates']])

    def test_changed_holdout_does_not_change_fit_scores_or_selection(self):
        f = self.cases['fit-only-tail']; original = self.results['fit-only-tail']
        x = f.target.audio.copy(); x[len(x)//2:] *= .7
        target = AudioBuffer(x, f.target.rate, 'post_master')
        data = f.request.to_dict(); data['target'] = target.asset.to_dict()
        request = SearchRequest.from_dict(data)
        p, _ = prepare_problem(request, f.renderer, target)
        actual = run_baseline(p)
        self.assertNotEqual(original.to_dict()['search_id'], actual.to_dict()['search_id'])
        self.assertEqual(winner(original)['parameters'], winner(actual)['parameters'])
        self.assertEqual([r['vector'] for r in original.to_dict()['ledger']], [r['vector'] for r in actual.to_dict()['ledger']])
        # Instrumentation proves no feature extraction of the full target or holdouts during fit.
        lengths = []
        store = FeatureStore(request.to_dict()['execution'])
        measure = store.measure
        def capture(buffer, plan): lengths.append(len(buffer.audio)); return measure(buffer, plan)
        with patch.object(store, 'measure', side_effect=capture):
            p, _ = prepare_problem(request, f.renderer, target, store=store)
            run_baseline(p)
        self.assertEqual(set(lengths), {2048})

    def test_exact_repeated_results_and_multiple_retention(self):
        for name in ('fit-only-tail', 'nonidentifiable-gains'):
            p, _ = self.cases[name].problem()
            r = run_baseline(p)
            self.assertEqual(r.sha256, self.results[name].sha256)
            self.assertGreater(len(r.to_dict()['retained']), 1)
            self.assertEqual(r.to_dict()['evaluations'], p.request.budget.evaluations)
            self.assertEqual(r.to_dict()['render_calls'], 2*p.request.budget.evaluations)
            self.assertTrue(all(len(e['vector']) == len(AXES) for e in r.to_dict()['ledger']))

    def test_bound_violation_never_reaches_renderer(self):
        p, _ = self.problems['fit-only-tail']
        with patch.object(type(p.renderer), 'render', side_effect=AssertionError('render must not run')):
            with self.assertRaises(ContractError): p.evaluate(ParameterState.from_mapping({'tail_gain_db': -13.}), 0)
            with self.assertRaises(ContractError): p.evaluate(ParameterState.from_mapping({'tail_gain_db': 0.}), 0)

    def test_pause_resume_replays_identity_and_keeps_lineage(self):
        f = self.cases['fit-only-tail']; p, _ = f.problem()
        paused = run_baseline(p, pause_after=1)
        checkpoint = Checkpoint.from_dict(paused.to_dict()['checkpoint'])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'checkpoint.json'; checkpoint.save(path)
            loaded = Checkpoint.load(path)
            self.assertEqual(loaded.sha256, checkpoint.sha256)
            resumed = run_baseline(p, resume=loaded, checkpoint_path=path)
            self.assertEqual(Checkpoint.load(path).to_dict()['status'], 'completed')
        full = self.results['fit-only-tail'].to_dict(); actual = resumed.to_dict()
        for key in ('ledger', 'retained', 'candidate_set_sha256'):
            self.assertEqual(actual[key], full[key])
        self.assertEqual(actual['lineage']['resumed_from_checkpoint_sha256'], checkpoint.sha256)
        self.assertEqual(actual['lineage']['replayed_evaluations'], 1)

    def test_checkpoint_tamper_wrong_search_and_replay_divergence(self):
        p, _ = self.problems['fit-only-tail']
        c = Checkpoint.from_dict(run_baseline(p, pause_after=1).to_dict()['checkpoint'])
        d = c.to_dict(); d['ledger'][0]['score'] = 999
        with self.assertRaises(ContractError): Checkpoint.from_dict(d)
        d['trace_sha256'] = _trace_id(d['search_id'], d['ledger'])
        tampered = Checkpoint.from_dict(d)
        with self.assertRaises(DivergenceError): run_baseline(p, resume=tampered)
        other, _ = make_fixture('fit-only-tail', search_seed='3').problem()
        with self.assertRaises(ContractError): run_baseline(other, resume=c)
        data = p.request.to_dict(); data['execution']['implementation_sha256'] = 'a'*64
        with self.assertRaises(ContractError): prepare_problem(SearchRequest.from_dict(data), p.renderer, self.cases['fit-only-tail'].target)

    def test_cancellation_preserves_completed_prefix(self):
        p, _ = self.problems['fit-only-tail']; saved = []; stop = [False]
        def on_checkpoint(c):
            saved.append(c)
            if c.to_dict()['next_index'] == 1: stop[0] = True
        def check():
            if stop[0]: raise JobCancelled('test cancellation')
        with self.assertRaises(JobCancelled): run_baseline(p, on_checkpoint=on_checkpoint, check_cancelled=check)
        self.assertEqual(saved[-1].to_dict()['status'], 'cancelled')
        self.assertEqual(saved[-1].to_dict()['next_index'], 1)
        resumed = run_baseline(p, resume=saved[-1])
        self.assertEqual(resumed.to_dict()['ledger'], self.results['fit-only-tail'].to_dict()['ledger'])

    def test_invalid_outputs_consume_budget_but_never_become_best(self):
        p, _ = self.problems['fit-only-tail']
        with patch.object(type(p.renderer), 'render', side_effect=ValueError('NaN is not audio')):
            r = run_baseline(p).to_dict()
        self.assertEqual(r['evaluations'], 3)
        self.assertEqual(r['render_calls'], 3)
        self.assertIsNone(r['best_candidate_id'])
        self.assertTrue(all(not c['validation']['eligible'] for c in r['retained']))

    def test_nondeterministic_render_is_explicitly_divergent(self):
        p, _ = self.problems['fit-only-tail']; count = [0]
        real = type(p.renderer).render
        def alternating(renderer, state, seed, check):
            count[0] += 1
            r = real(renderer, state, seed, check)
            return r if count[0] % 2 else finish_render(r.before_gain.audio*.9, r.output.rate, r.recipe.to_dict(), r.policy.to_dict())
        with patch.object(type(p.renderer), 'render', new=alternating):
            r = run_baseline(p).to_dict()
        self.assertIsNone(r['best_candidate_id'])
        self.assertTrue(all(c['validation']['state'] == 'divergent' for c in r['retained']))

    def test_audit_rejects_window_and_target_swaps(self):
        r = self.results['fit-only-tail']; p, v = self.problems['fit-only-tail']
        wrong = AuditTarget(v.request_id, v.target, p.request.windows.fitting)
        with self.assertRaises(ContractError): audit_result(r, wrong, p.renderer)
        with self.assertRaises(ContractError): audit_result(r, self.problems['polarity-feature-conflict'][1], p.renderer)
        real = type(p.renderer).render
        def changed(renderer, state, seed, check):
            out = real(renderer, state, seed, check)
            return finish_render(out.before_gain.audio*.5, out.output.rate, out.recipe.to_dict())
        with patch.object(type(p.renderer), 'render', new=changed):
            a = audit_result(r, v, p.renderer).to_dict()
        self.assertTrue(all(c['reproducibility'] == 'divergent' and c['held_out'] is None for c in a['candidates']))

    def test_disk_cache_reuse_and_integrity(self):
        f = self.cases['fit-only-tail']
        with tempfile.TemporaryDirectory() as tmp:
            cache = ArtifactCache(tmp, 16*1024*1024)
            first = FeatureStore(f.request.to_dict()['execution'], artifact_cache=cache)
            p, _ = f.problem(store=first); a = run_baseline(p)
            second = FeatureStore(f.request.to_dict()['execution'], artifact_cache=ArtifactCache(tmp))
            p, _ = f.problem(store=second); b = run_baseline(p)
            self.assertEqual(a.sha256, b.sha256)
            self.assertEqual(second.misses, 0)
            self.assertGreater(second.hits, 0)
            for file in Path(tmp).glob('*.bin'): file.write_bytes(b'corrupt')
            third = FeatureStore(f.request.to_dict()['execution'], artifact_cache=ArtifactCache(tmp))
            p, _ = f.problem(store=third)
            with self.assertRaises(ProjectError): run_baseline(p)

    def test_feature_cache_can_reuse_when_only_search_weights_change(self):
        f = self.cases['fit-only-tail']; store = FeatureStore(f.request.to_dict()['execution'])
        b = f.target.excerpt(f.request.windows.fitting[0])
        a = store.measure(b, ObjectivePlan())
        c = store.measure(b, ObjectivePlan(weights={'waveform': 2.}))
        self.assertEqual(a.sha256, c.sha256)
        self.assertEqual(store.misses, 1)
        self.assertEqual(store.hits, 1)

    def test_pareto_comparison_preserves_ties_and_masks(self):
        a = {'eligible': True, 'vector': [0., 1.], 'applicable': [True, True]}
        b = {**a, 'vector': [1., 0.]}
        self.assertFalse(dominates(a, b)); self.assertFalse(dominates(b, a))
        self.assertFalse(dominates(a, a))
        self.assertTrue(dominates(a, {**a, 'vector': [1., 2.]}))
        self.assertFalse(dominates(a, {**b, 'applicable': [False, True]}))
        self.assertFalse(dominates({**a, 'eligible': False}, b))

    def test_retention_cap_cannot_drop_the_scalar_winner_record(self):
        f = self.cases['polarity-feature-conflict']
        d = f.request.to_dict(); d['budget']['retain'] = 1
        p, vault = prepare_problem(SearchRequest.from_dict(d), f.renderer, f.target)
        r = run_baseline(p)
        self.assertEqual(winner(r)['parameters'], {'polarity': -1.})
        self.assertEqual(len(r.to_dict()['retained']), 1)
        audit = audit_result(r, vault, f.renderer)
        self.assertEqual(audit.to_dict()['candidates'][0]['candidate_id'], r.to_dict()['best_candidate_id'])

    def test_rich_fixture_uses_accepted_48k_antialias_path(self):
        f = make_fixture('rich-nonlinear-48k', budget=3)
        self.assertEqual(f.target.rate, 48000)
        self.assertIn('tanh_aa', f.renderer.method['configuration']['recipe_json'])
        p, v = f.problem(); r = run_baseline(p)
        self.assertEqual(r.to_dict()['evaluations'], 3)
        self.assertTrue(all(c['error'] is None for c in r.to_dict()['retained']))

    def test_scheduler_adapter_preserves_research_lane_and_cancel_checkpoint(self):
        p, _ = self.cases['fit-only-tail'].problem()
        entered = threading.Event(); release = threading.Event(); saved = []
        def checkpoint(c):
            saved.append(c)
            if c.to_dict()['status'] == 'running': entered.set(); release.wait(10)
        scheduler = JobScheduler()
        try:
            j = submit_inverse_job(scheduler, 'a'*64, p, on_checkpoint=checkpoint)
            self.assertTrue(entered.wait(10))
            preview = scheduler.submit(JobClass.PREVIEW, 'a'*64, lambda ctx: 'responsive', estimated_memory_bytes=1)
            self.assertEqual(scheduler.wait(preview, 5).state, 'completed')
            scheduler.cancel(j); release.set()
            self.assertEqual(scheduler.wait(j, 10).state, 'cancelled')
            self.assertEqual(saved[-1].to_dict()['status'], 'cancelled')
        finally:
            release.set(); scheduler.shutdown(cancel=True, timeout=10)


if __name__ == '__main__': unittest.main()
