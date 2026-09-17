from __future__ import annotations
import sys, unittest
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'app'))
from zaaggenz_contracts import validate
from zaaggenz_melody import render_phrase
from zaaggenz_project import Project
from zaaggenz_timeline import TimelineDocument
from zaaggenz_tuning import fixture_pack,tuning_to_spec,ratio_to_cents
from zaaggenz_linked import *
NAMES=('baseline','violation-only','recovery-only','both-linked','both-unrelated')
def event_signature(exp):return [(e['beat'],e['duration_beats'],e['gain_db'],e['source_id']) for e in exp.phrase.to_dict()['events']]
def bridge_dist(exp):return [r['distance_to_return_cents'] for r in exp.trace if r['phase']=='bridge']
def physical_distance(tuning,row,ret):return abs(ratio_to_cents(tuning.frequency(row['degree'],row['detune_cents'])/tuning.frequency(ret['degree'],ret['detune_cents'])))
class ValidationTests(unittest.TestCase):
 def setUp(self):self.plan=linked_fakeout_return()
 def bad(self,edit):
  d=self.plan.to_dict();edit(d)
  with self.assertRaises(Exception):LinkedEventPlan(d)
 def test_roundtrip_snapshot_and_hash(self):
  h=self.plan.sha256;d=self.plan.to_dict();d['local_expectation']['expected_degree']=4;self.assertEqual(self.plan.sha256,h);self.assertEqual(LinkedEventPlan.from_json(self.plan._json).sha256,h)
 def test_phase_order_contiguity_role_and_layer_contracts(self):
  self.bad(lambda d:d['phases'][1].update(start_beat='9/1'));self.bad(lambda d:d['phases'][1].update(role='transition'));self.bad(lambda d:d['phases'][1].update(layers=['synthline','synthline']));self.bad(lambda d:d['phases'].reverse())
 def test_local_expectation_and_bridge_are_bounded(self):
  self.bad(lambda d:d['local_expectation'].update(beat='10/1'));self.bad(lambda d:d['local_expectation'].update(substitute_degree=7));self.bad(lambda d:d['bridge']['neutral_degree_offsets'].pop());self.bad(lambda d:d['bridge'].update(duration_beats='2/1'))
 def test_return_must_be_final_and_in_declared_sonority(self):
  self.bad(lambda d:d['return_destination'].update(beat='14/1'));self.bad(lambda d:d['return_destination'].update(degree=2));self.bad(lambda d:d['return_sonority']['tones'][0].update(degree_offset=5000))
 def test_meter_must_span_phrase_and_use_same_stable_clock(self):
  self.bad(lambda d:d.update(stable_clock_id='bounce'))
  def shorten(d):
   d['meter_plan']['end_beat']='15/1'
   for clock in d['meter_plan']['clocks']:clock['active_windows'][-1]['end_beat']='15/1'
  self.bad(shorten)
 def test_all_transform_families_and_explicit_policies_required(self):self.bad(lambda d:d['transforms'].pop());self.bad(lambda d:d['transforms'][0].update(apply_policy='applied-source-derived'))
 def test_engine_model_state_is_explicitly_not_listener_outcome(self):self.bad(lambda d:d['engine_model'].update(uncertainty=1.1));self.bad(lambda d:d['engine_model'].update(semantics='listener-certainty'))
 def test_variant_vocabulary_is_closed(self):
  for name in NAMES:self.assertEqual(ControlledVariant(name).name,name)
  with self.assertRaises(LinkedEventError):ControlledVariant('invalid-condition')
class ExpansionTests(unittest.TestCase):
 def setUp(self):self.plan=linked_fakeout_return();self.bundles={n:compile_linked_recipe(self.plan,n,sample_rate=12000) for n in NAMES}
 def test_all_controls_preserve_source_timing_duration_gain_and_final_destination(self):
  signatures=[event_signature(b.expansion) for b in self.bundles.values()];self.assertTrue(all(s==signatures[0] for s in signatures[1:]));returns=[b.expansion.phrase.to_dict()['events'][-1] for b in self.bundles.values()];self.assertTrue(all(r==returns[0] for r in returns[1:]));self.assertEqual(returns[0]['id'],'linked-return');self.assertEqual(returns[0]['pitch']['degree'],0);sources=[b.recipe.to_dict()['source'] for b in self.bundles.values()];self.assertTrue(all(s==sources[0] for s in sources[1:]))
 def test_local_violation_is_only_expected_substitution(self):
  degree=lambda b:next(r['degree'] for r in b.expansion.trace if r['event_id']=='linked-local-event');self.assertEqual(degree(self.bundles['baseline']),7);self.assertEqual(degree(self.bundles['recovery-only']),7);self.assertEqual(degree(self.bundles['violation-only']),9);self.assertEqual(degree(self.bundles['both-linked']),9)
 def test_linked_bridge_strictly_converges_to_shared_return(self):
  for name in ('recovery-only','both-linked'):
   d=bridge_dist(self.bundles[name].expansion);self.assertTrue(all(b<a for a,b in zip(d,d[1:])),d);rows=[r for r in self.bundles[name].expansion.trace if r['phase']=='bridge'];self.assertEqual([round(r['link_progress'],6) for r in rows],[round((i+1)/6,6) for i in range(5)])
 def test_unrelated_recovery_is_not_hidden_linked_convergence(self):
  d=bridge_dist(self.bundles['both-unrelated'].expansion);self.assertFalse(all(b<a for a,b in zip(d,d[1:])));self.assertEqual([r['link_progress'] for r in self.bundles['both-unrelated'].expansion.trace if r['phase']=='bridge'],[0.0]*5)
 def test_bridge_distance_uses_active_tuning_for_linked_and_unrelated(self):
  ret=self.plan.to_dict()['return_destination']
  for fixture_name in ('synthetic-ratio-7','synthetic-13ed3'):
   tuning=fixture_pack()[fixture_name];spec=tuning_to_spec(tuning)
   with self.subTest(tuning=fixture_name):
    for variant in ('both-linked','both-unrelated'):
     exp=expand_linked(self.plan,variant,spec);events={e['id']:e for e in exp.phrase.to_dict()['events']}
     for row in (r for r in exp.trace if r['phase']=='bridge'):
      self.assertAlmostEqual(row['distance_to_return_cents'],physical_distance(tuning,row,ret),9)
      self.assertEqual(events[row['event_id']]['pitch']['degree'],row['degree']);self.assertAlmostEqual(events[row['event_id']]['pitch']['detune_cents'],row['detune_cents'],12)
    unrelated=[r for r in expand_linked(self.plan,'both-unrelated',spec).trace if r['phase']=='bridge']
    self.assertTrue(any(abs(r['distance_to_return_cents']-abs((r['degree']-ret['degree'])*100.0))>1e-4 for r in unrelated))
 def test_12tet_distance_control_matches_100_cents_per_integer_degree(self):
  tuning=fixture_pack()['12tet-a440'];ret=self.plan.to_dict()['return_destination'];exp=expand_linked(self.plan,'both-unrelated',tuning_to_spec(tuning))
  for row in (r for r in exp.trace if r['phase']=='bridge'):
   self.assertAlmostEqual(row['distance_to_return_cents'],abs((row['degree']-ret['degree'])*100.0),9)
   self.assertAlmostEqual(row['distance_to_return_cents'],physical_distance(tuning,row,ret),9)
 def test_tuning_distance_handles_negative_and_positive_bridge_degrees(self):
  d=self.plan.to_dict();d['bridge']['unrelated_degree_offsets']=[-8,-5,-7,-4,-6];plan=LinkedEventPlan(d);tuning=fixture_pack()['synthetic-ratio-7'];ret=d['return_destination'];exp=expand_linked(plan,'both-unrelated',tuning_to_spec(tuning));rows=[r for r in exp.trace if r['phase']=='bridge']
  self.assertLess(min(r['degree'] for r in rows),0);self.assertGreater(max(r['degree'] for r in rows),0)
  for row in rows:self.assertAlmostEqual(row['distance_to_return_cents'],physical_distance(tuning,row,ret),9)
 def test_return_distance_is_exactly_zero_under_active_tuning(self):
  for tuning in fixture_pack().values():
   exp=expand_linked(self.plan,'both-linked',tuning_to_spec(tuning));row=next(r for r in exp.trace if r['phase']=='return');self.assertEqual(row['distance_to_return_cents'],0.0)
 def test_slower_sway_anchor_is_identical_through_all_conditions(self):
  anchors=[b.expansion.anchor_trace for b in self.bundles.values()];self.assertTrue(all(a==anchors[0] for a in anchors[1:]));self.assertEqual([r['beat'] for r in anchors[0]],['0/1','2/1','4/1','6/1','8/1','10/1','12/1','14/1'])
 def test_transform_activation_distinguishes_violation_and_recovery(self):
  by=lambda name:{r['kind']:r for r in self.bundles[name].expansion.automation};self.assertFalse(any(r['active'] for r in by('baseline').values()));self.assertTrue(by('violation-only')['withheld-low-band-arrival']['active']);self.assertFalse(by('violation-only')['motif-completion']['active']);self.assertTrue(by('recovery-only')['motif-completion']['active']);self.assertTrue(all(r['active'] for r in by('both-linked').values()));self.assertTrue(all(r['protected_topology_rewrite'] is False for r in by('both-linked').values()))
 def test_engine_probabilities_remain_generator_state(self):
  state=self.bundles['both-linked'].expansion.model_state;self.assertEqual(state['semantics'],'generator-state-not-listener-outcome');self.assertEqual(state['local_prediction_probability'],.85);self.assertTrue(state['actual_local_violation']);self.assertTrue(state['recovery_present'])
 def test_phrase_has_four_nonoverlapping_roles_and_valid_contract(self):
  phrase=self.bundles['both-linked'].expansion.phrase.to_dict();validate(phrase,'PhrasePlan');self.assertEqual([(r['beat'],r['duration_beats'],r['role']) for r in phrase['roles']],[('0/1','8/1','establish'),('8/1','2/1','fakeout'),('10/1','5/1','transition'),('15/1','1/1','return')])
class ComposeIntegrationTests(unittest.TestCase):
 def setUp(self):self.plan=linked_fakeout_return()
 def test_timeline_export_retains_project_and_phase_clips(self):
  b=compile_linked_recipe(self.plan,'both-linked',sample_rate=12000);td=b.timeline.to_dict();self.assertEqual([c['name'] for c in td['clips']],['preparation: establish','violation: fakeout','bridge: transition','return: return']);retained=Project.from_document(td['project']).head_recipe.to_dict();self.assertTrue(all(retained[k] is not None for k in ('arrangement','reversebass','sculpt')));self.assertEqual(b.recipe.to_dict()['source'],retained['source']);self.assertIsNone(b.recipe.to_dict()['arrangement']);self.assertIsNone(b.recipe.to_dict()['sculpt'])
 def test_source_derived_render_is_useful_without_research_or_deferred_dsp(self):
  b=compile_linked_recipe(self.plan,'both-linked',sample_rate=12000);result=render_phrase(b.recipe);self.assertGreater(np.max(np.abs(result.mix)),0);self.assertEqual(result.diagnostics['clipped_fraction'],0);self.assertEqual(len(result.mix),57600)
 def test_save_reopen_authoring_timeline_is_deterministic(self):
  a=compile_linked_recipe(self.plan,'both-linked',sample_rate=12000);b=TimelineDocument.from_json(a.timeline._json);self.assertEqual(a.timeline.revision_id,b.revision_id);self.assertEqual(a.timeline.to_dict(),b.to_dict())
if __name__=='__main__':unittest.main(verbosity=2)
