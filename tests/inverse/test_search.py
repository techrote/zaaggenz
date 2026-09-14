from dataclasses import replace
import copy
import json
import unittest
import numpy as np

from zaaggenz_analysis import AnalysisCache
from zaaggenz_contracts import digest
from zaaggenz_inverse import *
from zaaggenz_inverse.fixtures import NAMES, synthetic_fixture
from zaaggenz_inverse.recipes import apply_state, state_from_recipe, render_trace, RenderTrace
from zaaggenz_inverse.results import validate_vector


class FixtureSearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases={}
        for name in NAMES:
            fixture=synthetic_fixture(name);fit,audit=fixture.experiment();result=run_grid(fit)
            cls.cases[name]=(fixture,fit,audit,result)

    def test_fixture_generation_is_repeatable_and_ground_truth_recorded(self):
        for name,(fixture,_,_,_) in self.cases.items():
            with self.subTest(name=name):
                repeated=synthetic_fixture(name)
                self.assertEqual(fixture.catalogue_record(),repeated.catalogue_record())
                np.testing.assert_array_equal(fixture.target,repeated.target)
                self.assertIn('ground_truth_parameters',fixture.catalogue_record()['definition'])
                self.assertIn('generation',fixture.catalogue_record()['definition'])

    def test_identifiable_known_parameter_recovery(self):
        f,_,_,result=self.cases['identifiable']
        best=next(c for c in result.candidates if c.id==result.ranked_candidate_ids[0])
        self.assertEqual(best.score,0.)
        self.assertEqual(best.recipe.sha256,f.ground_truth_recipe.sha256)
        self.assertEqual(best.to_dict()['parameters'],f.ground_truth_state.to_dict())
        self.assertEqual(len(result.pareto_candidate_ids),1)

    def test_weak_residual_has_small_but_nonzero_alternative_errors(self):
        f,_,_,result=self.cases['weak-residual']
        scores=sorted(c.score for c in result.candidates if c.eligible)
        self.assertEqual(scores[0],0.)
        self.assertGreater(scores[1],0.)
        self.assertLess(scores[1],.01)
        noise_zero=[c for c in result.candidates if dict(ParameterState.from_dict(c.to_dict()['parameters']).values)['/source/params/noise_level']==0.]
        self.assertEqual(len(noise_zero),3)
        self.assertEqual(len({c.to_dict()['provenance']['render_sha256'] for c in noise_zero}),3) # recipes differ
        self.assertEqual(len({c.to_dict()['render']['signals']['output']['asset']['content_sha256'] for c in noise_zero}),1)

    def test_materially_distinct_recipes_can_be_exactly_nonidentifiable(self):
        _,_,_,result=self.cases['drive-trim-equivalence']
        perfect=[c for c in result.candidates if c.eligible and c.score==0.]
        self.assertEqual(len(perfect),3)
        self.assertEqual(len({c.id for c in perfect}),3)
        self.assertEqual(len({c.recipe.sha256 for c in perfect}),3)
        self.assertEqual(len({c.to_dict()['render']['signals']['output']['asset']['content_sha256'] for c in perfect}),1)
        self.assertEqual(set(result.pareto_candidate_ids),{c.id for c in perfect})

    def test_feature_success_does_not_hide_waveform_disagreement(self):
        _,_,_,result=self.cases['polarity-feature-conflict']
        best=next(c for c in result.candidates if c.id==result.ranked_candidate_ids[0])
        self.assertEqual(best.score,0.)
        self.assertAlmostEqual(best.to_dict()['fit']['objectives']['components']['waveform'],2.,places=12)
        self.assertGreaterEqual(len(result.pareto_candidate_ids),2)

    def test_intentional_overfit_is_detected_only_in_independent_audit(self):
        _,_,audit,result=self.cases['holdout-step']
        selection=result.audit_selection(all_candidates=True)
        before=result.sha256
        scores=[]
        for candidate in result.candidates:
            report=audit.evaluate(candidate,selection)
            gain=dict(ParameterState.from_dict(candidate.to_dict()['parameters']).values)['/nodes/0/automation/0/points/1/value']
            self.assertEqual(candidate.score,0.)
            self.assertEqual(report['reproducibility'],'repeat-verified')
            self.assertEqual(report['overfit_warning'],gain!=6.)
            scores.append(report['holdout']['objectives']['score'])
            self.assertIn('whole_signal',report)
        self.assertGreater(max(scores),1.)
        self.assertEqual(min(scores),0.)
        self.assertEqual(result.sha256,before,'post-selection audit must not alter fitted candidates')
        self.assertEqual(len(result.pareto_candidate_ids),3,'fit frontier must retain ambiguity, not use audit to pick a winner')

    def test_audit_requires_explicit_selection_for_same_search(self):
        _,_,audit,result=self.cases['holdout-step']
        candidate=result.candidates[0]
        with self.assertRaises(InverseError):audit.evaluate(candidate,AuditSelection('a'*64,(candidate.id,)))
        with self.assertRaises(InverseError):audit.evaluate(candidate,AuditSelection(result.search_id,(result.candidates[1].id,)))

    def test_rich_path_reuses_accepted_components_chordness_and_tuning(self):
        _,_,audit,result=self.cases['sonority-nonlinear']
        best=next(c for c in result.candidates if c.score==0.)
        window=best.to_dict()['fit']['windows'][0]
        sonority=window['measurements']['candidate_features']['sonority']
        self.assertEqual(sonority['chordness']['target']['target_comb_fit']['method_id'],'zg.target_comb.v1')
        self.assertEqual(sonority['chordness']['roughness']['method_id'],'zg.components.roughness.v1')
        self.assertEqual(sonority['interaction']['validity'],'valid')
        self.assertEqual(len(sonority['partial_bundle_sha256']),64)
        self.assertEqual(best.recipe.to_dict()['nodes'][0]['type_id'],'core.tanh_aa.v1')
        report=audit.evaluate(best,result.audit_selection())
        self.assertEqual(report['holdout']['objectives']['score'],0.)

    def test_budget_bounds_multi_candidate_retention_and_pareto_records(self):
        for name,(fixture,fit,_,result) in self.cases.items():
            with self.subTest(name=name):
                self.assertEqual(len(result.candidates),fixture.budget.max_evaluations)
                self.assertLessEqual(fit.render_calls,2*fixture.budget.max_evaluations)
                self.assertGreaterEqual(len(result.candidates),3)
                self.assertEqual(len({c.id for c in result.candidates}),len(result.candidates))
                for c in result.candidates:
                    fixture.domain.validate_state(ParameterState.from_dict(c.to_dict()['parameters']))
                    self.assertEqual(c.to_dict()['reproducibility'],'repeat-verified')
                    validate_vector(c.to_dict()['fit']['objectives'])
                    self.assertIn('never identification',c.to_dict()['provenance']['claim'])

    def test_candidate_records_are_immutable_and_detect_tampering(self):
        c=self.cases['identifiable'][3].candidates[0]
        self.assertEqual(Candidate.from_dict(c.to_dict()).sha256,c.sha256)
        d=c.to_dict();d['candidate_id']='0'*64
        with self.assertRaises(InverseError):Candidate.from_dict(d)
        d=c.to_dict();d['provenance']['render_sha256']='0'*64
        with self.assertRaises(InverseError):Candidate.from_dict(d)
        d=c.to_dict();d['reproducibility']='divergent';d['eligible']=True
        with self.assertRaises(InverseError):Candidate.from_dict(d)
        d=c.to_dict();d['made_up_extra_field']=1
        with self.assertRaises(InverseError):Candidate.from_dict(d)


class DeterminismTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture=synthetic_fixture('holdout-step')

    def test_cold_runs_have_identical_ids_components_lineage_and_results(self):
        f=self.fixture
        a,_=f.experiment();b,_=f.experiment()
        ra,rb=run_grid(a),run_grid(b)
        self.assertEqual(ra.to_dict(),rb.to_dict())
        self.assertEqual(ra.sha256,rb.sha256)
        self.assertEqual(a.render_calls,b.render_calls)

    def test_warm_cache_does_not_change_logical_budget_or_identity(self):
        fit,_=self.fixture.experiment(render_cache=AnalysisCache(16),feature_cache=AnalysisCache(32))
        first=run_grid(fit);calls=fit.render_calls
        second=run_grid(fit)
        self.assertEqual(first.to_dict(),second.to_dict())
        self.assertEqual(fit.render_calls,calls)
        self.assertEqual(fit.render_hits,3)
        self.assertEqual(second.to_dict()['budget']['consumed_evaluations'],3)

    def test_full_target_and_truth_are_not_in_fit_capability(self):
        f=self.fixture;fit,_=f.experiment()
        self.assertFalse(hasattr(fit,'holdout'))
        self.assertFalse(hasattr(fit,'ground_truth'))
        self.assertFalse(hasattr(fit,'target'))
        self.assertFalse(hasattr(fit,'audit'))
        for a,w in zip(fit._fit,f.plan.fit):
            self.assertEqual(a.nbytes,4*(w.end_sample-w.start_sample))
            self.assertFalse(np.shares_memory(a,f.target))
            self.assertEqual(a.base.nbytes,a.nbytes,'slice backing storage must not contain held-out samples')
        self.assertNotIn('ground_truth',json.dumps(fit.request.to_dict()))
        with self.assertRaises(InverseError):run_grid(f.experiment()[1])

    def test_holdout_or_adjacent_padding_changes_cannot_change_optimization(self):
        from zaaggenz_project import Project
        f=self.fixture;target=f.target.copy()
        target[1600:2200]=.7 # immediately adjacent to fit: STFT cannot peek across slice boundary
        target[3400:]=-.9   # includes held-out target
        request=request_from_project(Project(f.base_recipe),target,f.plan,f.domain,budget=f.budget)
        a,_=f.experiment();b,_=prepare_experiment(request,target,f.plan)
        self.assertNotEqual(a.search_id,b.search_id,'full target hash is still honest provenance')
        ra,rb=run_grid(a),run_grid(b)
        for ca,cb in zip(ra.candidates,rb.candidates):
            self.assertEqual(ca.to_dict()['parameters'],cb.to_dict()['parameters'])
            self.assertEqual(ca.to_dict()['fit'],cb.to_dict()['fit'])
            self.assertEqual(ca.eligible,cb.eligible)
        self.assertEqual([c.to_dict()['ordinal'] for c in sorted(ra.candidates,key=lambda c:c.score)],
                         [c.to_dict()['ordinal'] for c in sorted(rb.candidates,key=lambda c:c.score)])

    def test_relevant_request_inputs_change_identity(self):
        f=self.fixture;request=f.request;original=f.experiment()[0].search_id
        variants=[replace(request,seed='7'),replace(request,budget=SearchBudget(2)),
                  replace(request,stage=SearchStage(id='second-pass',parent_search_sha256='a'*64)),
                  replace(request,validation=ValidationPolicy(max_level_delta_db=5.)),
                  replace(request,objective=ObjectivePolicy((ObjectiveTerm('waveform'),)))]
        for r in variants:
            with self.subTest(request=r.sha256):
                fit,_=prepare_experiment(r,f.target,f.plan)
                self.assertNotEqual(original,fit.search_id)
        custom,_=f.experiment(renderer=lambda recipe:render_trace(recipe),renderer_id='declared-other-render.v1')
        self.assertNotEqual(original,custom.search_id)

    def test_explicit_smaller_budget_is_bounded_prefix_not_new_heuristic(self):
        f=self.fixture
        small=replace(f,budget=SearchBudget(2));a,_=f.experiment();b,_=small.experiment()
        ra,rb=run_grid(a),run_grid(b)
        self.assertEqual(len(rb.candidates),2)
        self.assertEqual([c.to_dict()['parameters'] for c in ra.candidates[:2]],[c.to_dict()['parameters'] for c in rb.candidates])
        self.assertEqual(rb.to_dict()['budget']['termination'],'budget-exhausted')

    def test_singleton_domain_does_not_duplicate_candidates(self):
        f=self.fixture;axis=f.domain.axes[0]
        domain=ParameterDomain((replace(axis,lower=0.,upper=0.),))
        request=replace(f.request,domain=domain,budget=SearchBudget(9))
        fit,_=prepare_experiment(request,f.target,f.plan);result=run_grid(fit)
        self.assertEqual(len(result.candidates),1)
        self.assertEqual(result.to_dict()['budget']['unspent_evaluations'],8)
        self.assertEqual(result.to_dict()['budget']['termination'],'grid-exhausted')

    def test_divergent_renderer_cannot_appear_successful(self):
        f=self.fixture;calls=[]
        def varying(recipe):
            trace=render_trace(recipe);calls.append(1)
            gain=1. if len(calls)%2 else .5
            return RenderTrace(recipe,trace.source,trace.pre_master*gain,trace.output*gain)
        fit,_=f.experiment(renderer=varying,renderer_id='deliberately-divergent.v1')
        result=run_grid(fit)
        self.assertFalse(result.ranked_candidate_ids)
        self.assertTrue(all(not c.eligible and c.to_dict()['reproducibility']=='divergent' for c in result.candidates))

    def test_invalid_output_in_unobserved_region_is_structurally_rejected(self):
        f=self.fixture
        def nonfinite(recipe):
            trace=render_trace(recipe);a=trace.output.copy();a[-1]=np.nan
            return RenderTrace(recipe,trace.source,trace.pre_master,a)
        fit,_=f.experiment(renderer=nonfinite,renderer_id='invalid-tail.v1')
        candidate=fit.evaluate(f.ground_truth_state)
        self.assertFalse(candidate.eligible)
        self.assertIn('non_finite_render',candidate.to_dict()['structural_rejections'])
        json.dumps(candidate.to_dict(),allow_nan=False)

if __name__=='__main__':unittest.main()
