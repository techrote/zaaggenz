from __future__ import annotations
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'app'))
from uptempo_harmony.arrangement import make_arrangement_template
from zaaggenz_melody import render_phrase
from zaaggenz_project import Project
from zaaggenz_phrase import (PhraseRoleError, PhraseRolePlan, template_1234_5555,
                             expand_role_plan, plan_to_timeline, compile_role_recipe)
from zaaggenz_timeline import TimelineDocument, default_document


def mutate(plan, **updates):
    data = plan.to_dict(); data.update(updates); return PhraseRolePlan(data)


def bar4(expansion):
    return expansion.trace[3]


def find_changed_seed(plan, field, selector, limit=2000):
    baseline = selector(expand_role_plan(plan, 'twelve-tet'))
    for seed in range(1, limit + 1):
        candidate = mutate(plan, **{field: str(seed)})
        result = expand_role_plan(candidate, 'twelve-tet')
        if selector(result) != baseline:
            return candidate, result
    raise AssertionError(f'no changed {field} found in bounded search')


def event_inventory(expansion, ids):
    by_id = {e['id']: e for e in expansion.phrase.to_dict()['events']}
    out = []
    for event_id in ids:
        e = by_id[event_id]
        out.append((None if e['pitch'] is None else e['pitch']['degree'],
                    None if e['pitch'] is None else e['pitch']['detune_cents'],
                    e['duration_beats'], e['gain_db'], e['source_id'], e['gesture_id'] is not None))
    return out


class PlanValidationTests(unittest.TestCase):
    def setUp(self): self.plan = template_1234_5555()

    def bad(self, edit, pattern=None):
        data = self.plan.to_dict(); edit(data)
        ctx = self.assertRaisesRegex(PhraseRoleError, pattern) if pattern else self.assertRaises(PhraseRoleError)
        with ctx: PhraseRolePlan(data)

    def test_roundtrip_snapshot_and_hash(self):
        original = self.plan.sha256; data = self.plan.to_dict(); data['windows'][0]['role'] = 'repeat'
        self.assertEqual(self.plan.sha256, original)
        reopened = PhraseRolePlan.from_json(json.dumps(self.plan.to_dict()))
        self.assertEqual(reopened.sha256, original)

    def test_unknown_version_fields_and_invalid_seeds_rejected(self):
        self.bad(lambda d: d.update(version='2.0.0'))
        self.bad(lambda d: d.update(extra=True))
        self.bad(lambda d: d.update(content_seed='01'))
        self.bad(lambda d: d.update(placement_seed='-1'))

    def test_windows_are_ordered_non_overlapping_and_bounded(self):
        self.bad(lambda d: d['windows'][1].update(start_beat='3/1'), 'ordered')
        self.bad(lambda d: d['windows'][-1].update(end_beat='17/1'), 'ordered')
        self.bad(lambda d: d.update(end_beat='0/1'))

    def test_infeasible_placement_and_return_constraints_fail(self):
        self.bad(lambda d: d['windows'][-1]['placements'].append({'offset': '7/2', 'weight': 1}), 'cannot fit')
        self.bad(lambda d: d['windows'][-1]['destination'].update(beat='16/1'), 'destination')
        data = self.plan.to_dict(); data['windows'][-1]['role'] = 'return'; data['windows'][-1]['destination'] = None
        with self.assertRaisesRegex(PhraseRoleError, 'return role'): PhraseRolePlan(data)

    def test_no_fill_only_allowed_in_variation_family_roles(self):
        data = self.plan.to_dict(); data['windows'][0]['variants'][0]['events'] = []
        with self.assertRaisesRegex(PhraseRoleError, 'no-fill'): PhraseRolePlan(data)

    def test_duplicate_ids_offsets_and_nonfinite_values_rejected(self):
        self.bad(lambda d: d['windows'].append(deepcopy(d['windows'][-1])))
        self.bad(lambda d: d['windows'][-1]['placements'].append(deepcopy(d['windows'][-1]['placements'][0])))
        self.bad(lambda d: d['windows'][-1]['variants'][0].update(weight=True))
        self.bad(lambda d: d['windows'][-1]['variants'][0]['events'][0].update(gain_db=float('nan')))


class ExpansionTests(unittest.TestCase):
    def setUp(self): self.plan = template_1234_5555()

    def test_template_is_three_stable_bars_plus_fourth_bar_permission_window(self):
        expansion = expand_role_plan(self.plan, 'twelve-tet')
        phrase = expansion.phrase.to_dict(); events = phrase['events']
        stable = [e['pitch']['degree'] for e in events if float(e['beat'].split('/')[0]) / float(e['beat'].split('/')[1]) < 12]
        self.assertEqual(stable, [0,2,4,7] * 3)
        self.assertEqual(self.plan.to_dict()['end_beat'], '16/1')
        self.assertEqual([w['role'] for w in self.plan.to_dict()['windows']], ['establish','repeat','reinforce','vary'])
        self.assertEqual(bar4(expansion)['window_start_beat'], '12/1')
        destination = next(e for e in events if e['id'] == bar4(expansion)['destination_event_id'])
        self.assertEqual((destination['beat'], destination['pitch']['degree']), ('15/1', 0))
        self.assertEqual([r['role'] for r in phrase['roles']], ['establish','repeat','repeat','variation','return'])

    def test_repeated_expansion_is_identical_and_trace_is_defensive(self):
        a = expand_role_plan(self.plan, 'twelve-tet'); b = expand_role_plan(self.plan, 'twelve-tet')
        self.assertEqual(a.sha256, b.sha256)
        trace = a.trace; trace[3]['variant_id'] = 'tampered'
        self.assertNotEqual(a.trace[3]['variant_id'], 'tampered')

    def test_content_seed_changes_fill_not_permission_window_or_placement(self):
        changed, result = find_changed_seed(self.plan, 'content_seed', lambda x: bar4(x)['variant_id'])
        base = expand_role_plan(self.plan, 'twelve-tet')
        self.assertNotEqual(bar4(base)['variant_id'], bar4(result)['variant_id'])
        self.assertEqual(bar4(base)['placement_offset'], bar4(result)['placement_offset'])
        self.assertEqual((bar4(base)['window_start_beat'], bar4(base)['window_end_beat']), ('12/1','16/1'))
        self.assertEqual((bar4(result)['window_start_beat'], bar4(result)['window_end_beat']), ('12/1','16/1'))
        self.assertNotEqual(changed.to_dict()['content_seed'], self.plan.to_dict()['content_seed'])

    def test_placement_seed_changes_location_without_inventory_or_gain_profile(self):
        changed, result = find_changed_seed(self.plan, 'placement_seed', lambda x: bar4(x)['placement_offset'])
        base = expand_role_plan(self.plan, 'twelve-tet')
        self.assertEqual(bar4(base)['variant_id'], bar4(result)['variant_id'])
        self.assertNotEqual(bar4(base)['placement_offset'], bar4(result)['placement_offset'])
        self.assertEqual(event_inventory(base, bar4(base)['event_ids']), event_inventory(result, bar4(result)['event_ids']))
        by_a = {e['id']: e for e in base.phrase.to_dict()['events']}; by_b = {e['id']: e for e in result.phrase.to_dict()['events']}
        self.assertNotEqual([by_a[x]['beat'] for x in bar4(base)['event_ids']], [by_b[x]['beat'] for x in bar4(result)['event_ids']])
        self.assertNotEqual(changed.to_dict()['placement_seed'], self.plan.to_dict()['placement_seed'])

    def test_no_fill_is_valid_and_return_time_survives(self):
        nofill, result = find_changed_seed(self.plan, 'content_seed', lambda x: bar4(x)['variant_id'] == 'no-fill')
        if bar4(result)['variant_id'] != 'no-fill':
            for seed in range(1, 5000):
                candidate = mutate(self.plan, content_seed=str(seed)); candidate_result = expand_role_plan(candidate, 'twelve-tet')
                if bar4(candidate_result)['variant_id'] == 'no-fill': nofill, result = candidate, candidate_result; break
        self.assertEqual(bar4(result)['variant_id'], 'no-fill')
        self.assertEqual(bar4(result)['event_ids'], [])
        destination = next(e for e in result.phrase.to_dict()['events'] if e['id'] == bar4(result)['destination_event_id'])
        self.assertEqual(destination['beat'], '15/1')
        self.assertEqual(destination['pitch']['degree'], 0)
        self.assertTrue(nofill.to_dict()['content_seed'].isdigit())

    def test_probabilities_are_engine_outputs_not_listener_certainty(self):
        row = bar4(expand_role_plan(self.plan, 'twelve-tet'))
        self.assertGreater(row['declared_content_probability'], 0)
        self.assertGreater(row['declared_placement_probability'], 0)
        self.assertAlmostEqual(row['joint_generator_probability'], row['declared_content_probability'] * row['declared_placement_probability'])
        self.assertIn('not-listener-certainty', row['generator_semantics'])
        self.assertNotIn('listener_probability', row)

    def test_source_family_and_named_streams_survive_contract(self):
        expansion = expand_role_plan(self.plan, 'twelve-tet'); phrase = expansion.phrase.to_dict()
        self.assertIn(bar4(expansion)['source_family'], phrase['source_ids'])
        self.assertIn('placement.bar4-permission-window', phrase['random']['streams'])
        self.assertIn('content.bar4-permission-window', phrase['random']['streams'])


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.plan = template_1234_5555(content_seed='7', placement_seed='11')
        self.base = default_document(12000)

    def test_timeline_export_retains_full_project_and_role_regions(self):
        before = self.base.to_dict()['project']
        timeline, expansion = plan_to_timeline(self.plan, self.base)
        data = timeline.to_dict()
        self.assertEqual(data['project'], before)
        self.assertEqual(data['end_beat'], '16/1')
        self.assertEqual(len(data['clips']), 4)
        self.assertEqual([c['start_beat'] for c in data['clips']], ['0/1','4/1','8/1','12/1'])
        self.assertEqual(len(data['notes']), len(expansion.phrase.to_dict()['events']))
        self.assertTrue(any(n['roll_density'] > 1 for n in data['notes']))
        self.assertEqual(TimelineDocument.from_json(json.dumps(data)).revision_id, timeline.revision_id)

    def test_source_preserving_render_is_nonzero_and_protected_source_is_unchanged(self):
        source = Project.from_document(self.base.to_dict()['project']).head_recipe.to_dict()['source']
        bundle = compile_role_recipe(self.plan, self.base)
        recipe = bundle.recipe.to_dict()
        self.assertEqual(recipe['source'], source)
        self.assertEqual(recipe['phase_policy'], 'source-derived')
        result = render_phrase(bundle.recipe)
        self.assertGreater(np.max(np.abs(result.mix)), 0)
        self.assertEqual(result.diagnostics['notes'], sum(n['degree'] is not None for n in bundle.timeline.to_dict()['notes']))
        self.assertGreater(result.diagnostics['roll_retriggers'], 0)

    def test_existing_simple_arrangement_template_remains_available(self):
        arrangement = make_arrangement_template('flat_test', bpm=200., bars=4, seed=1337).to_dict()
        self.assertEqual(arrangement['bars'], 4)

    def test_cli_template_timeline_and_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp); plan = tmp/'plan.json'; timeline = tmp/'timeline.json'; wave = tmp/'phrase.wav'
            commands = [
                ['template', str(plan), '--content-seed', '7', '--placement-seed', '11'],
                ['timeline', str(plan), str(timeline), '--sample-rate', '12000'],
                ['render', str(plan), str(wave), '--sample-rate', '12000']]
            for command in commands:
                completed = subprocess.run([sys.executable, '-m', 'zaaggenz_phrase', *command], cwd=ROOT, capture_output=True, text=True)
                self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIsInstance(TimelineDocument.from_json(timeline.read_text(encoding='utf-8')), TimelineDocument)
            self.assertGreater(wave.stat().st_size, 44)


if __name__ == '__main__': unittest.main(verbosity=2)
