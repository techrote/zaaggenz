from __future__ import annotations
from copy import deepcopy
from fractions import Fraction
import json
from pathlib import Path
import sys
import unittest
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'app'))
from zaaggenz_melody import render_phrase
from zaaggenz_project import Project
from zaaggenz_timeline import default_document
from zaaggenz_gesture import (GestureError,DirectionalGesture,rise_turn_return,vary_surface,reverse_direction,
                              replace_trajectory_points,edit_landing,trajectory_value,effective_event_gains,
                              compile_gesture,compile_gesture_recipe)


def trajectory(plan,axis): return next(t for t in plan.to_dict()['trajectories'] if t['axis']==axis)
def values(plan,axis): return [p['value'] for p in trajectory(plan,axis)['points']]
def beats(plan,axis): return [p['beat'] for p in trajectory(plan,axis)['points']]
def directions(plan,axis): return [s['direction'] for s in trajectory(plan,axis)['segments']]

class ValidationTests(unittest.TestCase):
    def setUp(self): self.plan=rise_turn_return()
    def bad(self,edit,pattern=None):
        data=self.plan.to_dict();edit(data);ctx=self.assertRaisesRegex(GestureError,pattern) if pattern else self.assertRaises(GestureError)
        with ctx:DirectionalGesture(data)
    def test_roundtrip_snapshot_and_hash(self):
        original=self.plan.sha256;data=self.plan.to_dict();data['base_degree']=4
        self.assertEqual(self.plan.sha256,original);self.assertEqual(DirectionalGesture.from_json(json.dumps(self.plan.to_dict())).sha256,original)
    def test_unknown_version_fields_units_and_nonfinite_rejected(self):
        self.bad(lambda d:d.update(version='2.0.0'));self.bad(lambda d:d.update(extra=True))
        self.bad(lambda d:d['trajectories'][0].update(unit='Hz'),'unit mismatch')
        self.bad(lambda d:d['trajectories'][1]['points'][1].update(value=float('nan')))
    def test_terminal_landing_and_required_landmarks_are_exact(self):
        self.bad(lambda d:d['landing'].update(beat='3/1'),'landing must be terminal')
        self.bad(lambda d:d.update(landmarks=[x for x in d['landmarks'] if x['kind']!='landing']),'entry, landing and endpoint')
    def test_directional_constraints_and_turn_landmarks_are_enforced(self):
        self.bad(lambda d:d['trajectories'][3]['points'][1].update(value=400),'violate rising')
        self.bad(lambda d:d.update(landmarks=[x for x in d['landmarks'] if x['kind']!='turn']),'turn landmark')
        self.bad(lambda d:d['trajectories'][3]['segments'][1].update(start_beat='5/2'),'contiguously')
    def test_density_duration_bounds_and_interpolation_are_explicit(self):
        self.bad(lambda d:d['trajectories'][0]['points'][1].update(value=4.5),'integers')
        self.bad(lambda d:d['trajectories'][0].update(interpolation='linear'),'step interpolation')
        self.bad(lambda d:d['trajectories'][2].update(interpolation='linear'),'step interpolation')
    def test_effective_gain_upper_overflow_is_rejected_at_interpolated_event_start(self):
        data=self.plan.to_dict();data['base_gain_db']=24.
        with self.assertRaisesRegex(GestureError,r'effective event gain at beat 1/2 lies outside -120\.\.24 dB'):
            DirectionalGesture(data)
        accent=next(t for t in data['trajectories'] if t['axis']=='accent_db')
        self.assertEqual(trajectory_value(accent,Fraction(1,2)),.75)
    def test_effective_gain_lower_underflow_is_rejected_before_compilation(self):
        data=self.plan.to_dict();data['base_gain_db']=-120.
        accent=next(t for t in data['trajectories'] if t['axis']=='accent_db')
        for point in accent['points']:point['value']=float(point['value'])-1.
        with self.assertRaisesRegex(GestureError,r'effective event gain at beat 0/1 lies outside -120\.\.24 dB'):
            DirectionalGesture(data)
    def test_effective_gain_exact_phrase_boundaries_are_valid_and_compile_unchanged(self):
        upper=self.plan.to_dict();upper['base_gain_db']=21.;upper_plan=DirectionalGesture(upper)
        upper_rows=effective_event_gains(upper_plan.to_dict());upper_compiled=compile_gesture(upper_plan,'twelve-tet')
        self.assertEqual(max(gain for _,gain in upper_rows),24.)
        self.assertEqual(max(event['gain_db'] for event in upper_compiled.phrase.to_dict()['events'][:-1]),24.)
        lower=self.plan.to_dict();lower['base_gain_db']=-120.;lower_plan=DirectionalGesture(lower)
        lower_rows=effective_event_gains(lower_plan.to_dict());lower_compiled=compile_gesture(lower_plan,'twelve-tet')
        self.assertEqual(min(gain for _,gain in lower_rows),-120.)
        self.assertEqual(min(event['gain_db'] for event in lower_compiled.phrase.to_dict()['events'][:-1]),-120.)
    def test_terminal_landing_gain_is_independent_at_both_boundaries(self):
        for gain in (-120.,24.):
            data=self.plan.to_dict();data['landing']['gain_db']=gain;plan=DirectionalGesture(data)
            compiled=compile_gesture(plan,'twelve-tet')
            self.assertEqual(compiled.phrase.to_dict()['events'][-1]['gain_db'],gain)

class TransformTests(unittest.TestCase):
    def setUp(self): self.plan=rise_turn_return()
    def test_surface_variation_is_deterministic_and_preserves_landmarks_directions_endpoints(self):
        a=vary_surface(self.plan,'42',1.,axes=('pitch_cents','brightness_hz'),source_family='surface-b')
        b=vary_surface(self.plan,'42',1.,axes=('pitch_cents','brightness_hz'),source_family='surface-b')
        self.assertEqual(a.sha256,b.sha256);self.assertNotEqual(a.sha256,self.plan.sha256)
        for axis in ('pitch_cents','brightness_hz'):
            self.assertEqual(values(a,axis),values(self.plan,axis));self.assertEqual(directions(a,axis),directions(self.plan,axis))
            self.assertEqual([beats(a,axis)[i] for i in (0,2,4)],['0/1','2/1','4/1'])
            self.assertNotEqual(beats(a,axis),beats(self.plan,axis))
        self.assertEqual(a.to_dict()['landing'],self.plan.to_dict()['landing']);self.assertEqual(a.to_dict()['source_family'],'surface-b')
    def test_opposite_direction_preserves_surface_inventory_timing_and_landing(self):
        opposite=reverse_direction(self.plan,('pitch_cents','brightness_hz'),source_family='opposite-surface')
        self.assertEqual(beats(opposite,'pitch_cents'),beats(self.plan,'pitch_cents'))
        self.assertEqual(directions(opposite,'pitch_cents'),['falling','rising'])
        for axis in ('onset_density','accent_db','duration_beats'):
            self.assertEqual(trajectory(opposite,axis),trajectory(self.plan,axis))
        self.assertEqual(opposite.to_dict()['landing'],self.plan.to_dict()['landing'])
    def test_manual_correction_and_landing_edit_are_independent(self):
        points=deepcopy(trajectory(self.plan,'pitch_cents')['points']);points[1]['value']=120.
        corrected=replace_trajectory_points(self.plan,'pitch_cents',points)
        self.assertEqual(values(corrected,'pitch_cents')[1],120.)
        bad=deepcopy(points);bad[1]['value']=400.
        with self.assertRaises(GestureError):replace_trajectory_points(self.plan,'pitch_cents',bad)
        landed=edit_landing(self.plan,degree=7,detune_cents=25.)
        self.assertEqual((landed.to_dict()['landing']['degree'],landed.to_dict()['landing']['detune_cents']),(7,25.))
        self.assertEqual(landed.to_dict()['source_family'],self.plan.to_dict()['source_family']);self.assertEqual(landed.to_dict()['trajectories'],self.plan.to_dict()['trajectories'])

class CompilationTests(unittest.TestCase):
    def setUp(self): self.plan=rise_turn_return();self.base=default_document(12000)
    def test_step_controls_switch_at_the_exact_authored_point(self):
        density=trajectory(self.plan,'onset_density');duration=trajectory(self.plan,'duration_beats')
        self.assertEqual(trajectory_value(density,'999/1000'),2.)
        self.assertEqual(trajectory_value(density,'1/1'),4.)
        self.assertEqual(trajectory_value(duration,'999/1000'),.5)
        self.assertEqual(trajectory_value(duration,'1/1'),.375)
    def test_compilation_is_deterministic_and_terminal_landing_is_explicit(self):
        a=compile_gesture(self.plan,'twelve-tet');b=compile_gesture(self.plan,'twelve-tet')
        self.assertEqual(a.sha256,b.sha256);events=a.phrase.to_dict()['events']
        self.assertEqual(events[-1]['id'],'gesture-landing');self.assertEqual((events[-1]['beat'],events[-1]['duration_beats']),('7/2','1/2'))
        self.assertEqual([e['beat'] for e in events],sorted([e['beat'] for e in events],key=lambda x:Fraction(*map(int,x.split('/')))))
    def test_same_direction_surface_variant_holds_event_timing_gain_duration_but_changes_pitch(self):
        variant=vary_surface(self.plan,'42',1.,axes=('pitch_cents',))
        a,b=compile_gesture(self.plan,'twelve-tet'),compile_gesture(variant,'twelve-tet')
        ea,eb=a.phrase.to_dict()['events'],b.phrase.to_dict()['events'];self.assertEqual(len(ea),len(eb))
        for left,right in zip(ea,eb):
            self.assertEqual((left['beat'],left['duration_beats'],left['gain_db']),(right['beat'],right['duration_beats'],right['gain_db']))
        self.assertNotEqual([e['pitch']['detune_cents'] for e in ea[:-1]],[e['pitch']['detune_cents'] for e in eb[:-1]])
        self.assertEqual(ea[-1]['pitch'],eb[-1]['pitch'])
    def test_opposite_pitch_direction_holds_event_inventory_level_and_return(self):
        opposite=reverse_direction(self.plan,('pitch_cents',))
        a,b=compile_gesture(self.plan,'twelve-tet'),compile_gesture(opposite,'twelve-tet')
        ea,eb=a.phrase.to_dict()['events'],b.phrase.to_dict()['events']
        self.assertEqual([(e['beat'],e['duration_beats'],e['gain_db']) for e in ea],[(e['beat'],e['duration_beats'],e['gain_db']) for e in eb])
        self.assertNotEqual([e['pitch']['detune_cents'] for e in ea[:-1]],[e['pitch']['detune_cents'] for e in eb[:-1]])
        self.assertEqual(ea[-1],eb[-1])
    def test_deferred_timbral_automation_is_typed_and_cannot_rewrite_topology(self):
        compiled=compile_gesture(self.plan,'twelve-tet');automation=compiled.automation
        self.assertFalse(automation['protected_topology_rewrite']);self.assertEqual(len(automation['rows']),4)
        self.assertEqual({r['axis'] for r in automation['rows']},{'brightness_hz','roughness_fraction','spectral_occupancy_fraction','spectral_width_fraction'})
        self.assertTrue(all(r['apply_mode']=='deferred-explicit' for r in automation['rows']))
    def test_source_preserving_render_keeps_protected_source_and_no_hidden_dsp(self):
        source=Project.from_document(self.base.to_dict()['project']).head_recipe.to_dict()['source']
        bundle=compile_gesture_recipe(self.plan,self.base);recipe=bundle.recipe.to_dict()
        self.assertEqual(recipe['source'],source);self.assertEqual(recipe['phase_policy'],'source-derived');self.assertEqual(recipe['nodes'],[]);self.assertIsNone(recipe['sculpt'])
        result=render_phrase(bundle.recipe);self.assertGreater(np.max(np.abs(result.mix)),0);self.assertEqual(result.diagnostics['rests'],0)
        self.assertEqual(result.diagnostics['notes'],len(bundle.compilation.phrase.to_dict()['events']))

if __name__=='__main__':unittest.main(verbosity=2)
