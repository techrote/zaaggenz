from __future__ import annotations
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'app'))
from zaaggenz_contracts import Contract, ContractError
from zaaggenz_contracts.legacy import adapt_parameters, freeze_legacy
from zaaggenz_contracts.music import beat_to_sample
from zaaggenz_grammar import *
from zaaggenz_jobs import JobScheduler, JobClass, SchedulerLimits
from zaaggenz_melody import (render_phrase, MelodicRenderSpec, make_render_executor,
                            note_event, rest_event, make_phrase_plan)
from zaaggenz_tuning import fixture_pack, tuning_to_spec


def base(sr=12000):
    p = adapt_parameters('synth', {'sr': sr, 'bpm': 200., 'beats': 1, 'f0_hz': 48.})
    d = freeze_legacy(p).to_dict()
    return p, d['time_map'], d['tuning']


def degrees(expansion):
    return [e['pitch']['degree'] if e['pitch'] else None for e in expansion.phrase.to_dict()['events']]


class GrammarValidationTests(unittest.TestCase):
    def setUp(self):
        self.g = starter_grammars()['step-return'].to_dict()

    def bad(self, change):
        data = deepcopy(self.g)
        change(data)
        with self.assertRaises((GrammarError, ContractError)):
            GrammarSpec(data)

    def test_version_unknown_fields_and_bool_weights_rejected(self):
        self.bad(lambda d: d.update(version='2.0.0'))
        self.bad(lambda d: d.update(extra=1))
        self.bad(lambda d: d['degrees'][0].update(weight=True))
        self.bad(lambda d: d['degrees'][0].update(weight=float('nan')))

    def test_directional_contradictions_rejected(self):
        self.bad(lambda d: d.update(ascending_steps=[{'step': -1, 'weight': 1}]))
        self.bad(lambda d: d.update(descending_steps=[{'step': 0, 'weight': 1}]))
        self.bad(lambda d: d['motifs'][0].update(steps=[0, -1]))

    def test_register_and_return_fail_clearly(self):
        self.bad(lambda d: d.update(register={'minimum': 0, 'maximum': 0}))
        self.bad(lambda d: d.update(return_path=[4, 3, 0]))
        self.bad(lambda d: d.update(return_path=[4, 2]))
        self.bad(lambda d: d.update(resting_degrees=[1]))
        self.bad(lambda d: d['motifs'][0].update(steps=[0, 32]))

    def test_duplicate_degrees_patterns_and_steps_rejected(self):
        self.bad(lambda d: d['degrees'].append(d['degrees'][-1]))
        self.bad(lambda d: d['motifs'].append(d['motifs'][0]))
        self.bad(lambda d: d['ascending_steps'].append(d['ascending_steps'][0]))

    def test_source_description_and_license_required(self):
        self.bad(lambda d: d.update(description=''))
        self.bad(lambda d: d['provenance'].update(source=''))
        self.bad(lambda d: d['provenance'].update(license=''))

    def test_grammar_is_defensive_snapshot(self):
        grammar = GrammarSpec(self.g)
        original = grammar.sha256
        self.g['return_path'][0] = 7
        output = grammar.to_dict()
        output['return_path'][0] = 9
        self.assertEqual(grammar.sha256, original)
        self.assertEqual(GrammarSpec.from_json(json.dumps(grammar.to_dict())).sha256, original)

    def test_request_bounds_and_strict_rationals(self):
        for kwargs in ({'event_count': 0}, {'event_count': True}, {'event_count': 2049},
                       {'step_beats': '2/4'}, {'step_beats': '-1/2'}, {'start_beat': '-1/1'},
                       {'seed': '01'}, {'enabled': 1}, {'directions': ()}, {'gain_db': float('inf')}):
            with self.subTest(kwargs=kwargs), self.assertRaises((ValueError, TypeError)):
                ExpansionRequest(**kwargs)


class ExpansionTests(unittest.TestCase):
    def setUp(self):
        _, _, self.tuning = base()
        self.g = starter_grammars()['step-return']

    def test_reproducible_and_trace_for_every_event(self):
        request = ExpansionRequest(seed='987654321', event_count=32)
        a = expand_grammar(self.g, request, self.tuning)
        b = expand_grammar(self.g, request, self.tuning)
        self.assertEqual(a.sha256, b.sha256)
        self.assertEqual(len(a.trace), 32)
        self.assertEqual([x['event_id'] for x in a.trace], [e['id'] for e in a.phrase.to_dict()['events']])
        self.assertTrue(all('rule' in row for row in a.trace))
        trace = a.trace
        trace[0]['degree'] = 400
        self.assertEqual(a.trace[0]['degree'], 0)

    def test_same_allowed_pitches_different_direction_and_return(self):
        g1, g2 = starter_grammars().values()
        self.assertEqual(g1.to_dict()['degrees'], g2.to_dict()['degrees'])
        request = ExpansionRequest(event_count=32, seed='42')
        a, b = [expand_grammar(g, request, self.tuning) for g in (g1, g2)]
        self.assertNotEqual(degrees(a)[:-3], degrees(b)[:-3])
        self.assertNotEqual(degrees(a)[-3:], degrees(b)[-3:])
        self.assertEqual(degrees(a)[-1], degrees(b)[-1])

    def test_actual_directions_and_register_with_explicit_reflection(self):
        for direction in ('up', 'down'):
            a = expand_grammar(self.g, ExpansionRequest(event_count=64, directions=(direction,)), self.tuning)
            for i, row in enumerate(a.trace):
                self.assertTrue(0 <= row['degree'] <= 12)
                if row['rule'] == 'directional-step':
                    delta = row['degree'] - a.trace[i-1]['degree']
                    self.assertEqual(delta > 0, row['realised_direction'] == 'up')
            self.assertTrue(any(row.get('reflected') for row in a.trace))

    def test_no_reflection_policy_reports_infeasible_step(self):
        d = self.g.to_dict()
        d['boundary'] = 'error'
        with self.assertRaisesRegex(GrammarError, 'no legal down'):
            expand_grammar(GrammarSpec(d), ExpansionRequest(directions=('down',)), self.tuning)

    def test_motif_reuse_and_return_not_truncated(self):
        d = self.g.to_dict()
        d['register'] = {'minimum': 0, 'maximum': 24}
        d['motifs'] = [{'id': 'turn', 'kind': 'motif', 'direction': 'any', 'steps': [0, 1, 0], 'weight': 1},
                       {'id': 'lower', 'kind': 'motif', 'direction': 'any', 'steps': [0, -1, 0], 'weight': 1}]
        a = expand_grammar(GrammarSpec(d), ExpansionRequest(event_count=32, motif_every=4, directions=('hold',)), self.tuning)
        patterns = [row for row in a.trace if row['rule'] == 'motif']
        self.assertGreater(len(patterns), 6)
        self.assertEqual(len(patterns) % 3, 0)
        self.assertEqual(degrees(a)[-3:], [4, 2, 0])
        self.assertEqual([r['rule'] for r in a.trace[-3:]], ['return-path'] * 3)

    def test_ornaments_close_to_their_entry_pitch(self):
        a = expand_grammar(self.g, ExpansionRequest(event_count=32, ornament_every=4, directions=('hold',)), self.tuning)
        positions = [i for i, row in enumerate(a.trace) if row['rule'] == 'ornament' and row['pattern_position'] == 0]
        self.assertGreater(len(positions), 2)
        for i in positions:
            self.assertEqual(a.trace[i]['degree'], a.trace[i+2]['degree'])
            self.assertNotEqual(a.trace[i]['degree'], a.trace[i+1]['degree'])

    def test_infeasible_motif_is_not_silently_replaced(self):
        d = self.g.to_dict()
        d['motifs'] = [{'id': 'fall', 'kind': 'motif', 'direction': 'any', 'steps': [0, -1, -2], 'weight': 1}]
        with self.assertRaisesRegex(GrammarError, 'no motif fits'):
            expand_grammar(GrammarSpec(d), ExpansionRequest(motif_every=1, directions=('hold',)), self.tuning)

    def test_rest_schedule_and_full_phrase_extent(self):
        a = expand_grammar(self.g, ExpansionRequest(event_count=128, step_beats='1/2', rest_every=4), self.tuning)
        p = a.phrase.to_dict()
        self.assertEqual(p['end_beat'], '64/1')
        self.assertIsNone(p['events'][4]['pitch'])
        self.assertEqual(p['events'][-1]['pitch']['degree'], 0)

    def test_short_return_rejected(self):
        with self.assertRaisesRegex(GrammarError, 'full return path'):
            expand_grammar(self.g, ExpansionRequest(event_count=3), self.tuning)

    def test_non_octave_and_negative_tonic_coordinates(self):
        d = self.g.to_dict()
        d['period_degrees'] = 13
        d['register'] = {'minimum': -13, 'maximum': 13}
        tuning = tuning_to_spec(fixture_pack()['synthetic-13ed3'])
        a = expand_grammar(GrammarSpec(d), ExpansionRequest(tonic_degree=-1), tuning)
        self.assertEqual(degrees(a)[-1], -1)
        for row in a.trace:
            self.assertTrue(np.isfinite(row['target_hz']))
        with self.assertRaisesRegex(GrammarError, 'period_degrees'):
            expand_grammar(self.g, ExpansionRequest(), tuning)

    def test_disabled_grammar_preserves_manual_notes_and_rests_exactly(self):
        phrase = make_phrase_plan(self.tuning['id'], [note_event('manual', '0/1', '1/2', self.tuning['id'], 3),
                                 rest_event('silence', '1/2', '1/2')], end_beat='1/1')
        a = expand_grammar(self.g, ExpansionRequest(enabled=False), self.tuning, manual_phrase=phrase)
        self.assertIs(a.phrase, phrase)
        self.assertEqual(a.phrase.sha256, phrase.sha256)
        self.assertTrue(all(row['rule'] == 'manual-bypass' for row in a.trace))
        with self.assertRaises(GrammarError):
            expand_grammar(self.g, ExpansionRequest(enabled=False), self.tuning)

    def test_named_randomness_does_not_depend_on_global_random(self):
        import random
        r = ExpansionRequest(seed='2026')
        a = expand_grammar(self.g, r, self.tuning)
        random.seed(53)
        for _ in range(100):
            random.random()
        self.assertEqual(a.sha256, expand_grammar(self.g, r, self.tuning).sha256)
        self.assertNotEqual(degrees(a), degrees(expand_grammar(self.g, replace(r, seed='2027'), self.tuning)))


class RecipeAndRenderTests(unittest.TestCase):
    def setUp(self):
        self.p, self.tm, self.tu = base()
        self.g = starter_grammars()['step-return']
        self.request = ExpansionRequest(event_count=8, step_beats='1/4', rest_every=3)
        self.bundle = make_grammar_recipe(self.g, self.request, self.p, self.tm, self.tu,
                                         quality='standard', tail_mode='truncate')

    def test_save_load_contains_generator_and_project_recipe(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'phrase.zggrammar.json'
            save_grammar_recipe(self.bundle, path)
            b = load_grammar_recipe(path)
        self.assertEqual(b.sha256, self.bundle.sha256)
        self.assertEqual(b.to_dict()['grammar'], self.g.to_dict())
        self.assertEqual(b.to_dict()['request'], self.request.to_dict())
        self.assertEqual(b.project.head, self.bundle.project.head)
        self.assertEqual(b.render_recipe.to_dict()['phase_policy'], 'source-derived')

    def test_changed_authoring_state_cannot_claim_old_audio_recipe(self):
        d = self.bundle.to_dict()
        d['request']['tonic_degree'] = 1
        with self.assertRaisesRegex(GrammarError, 'identity mismatch'):
            GrammarRecipe(d)
        d = self.bundle.to_dict()
        d['expansion_sha256'] = '0' * 64
        with self.assertRaisesRegex(GrammarError, 'identity mismatch'):
            GrammarRecipe(d)

    def test_ordinary_frozen_recipe_remains_unchanged_and_valid(self):
        recipe = self.bundle.render_recipe
        self.assertEqual(Contract.from_json(recipe.to_json()).sha256, recipe.sha256)
        self.assertNotIn('grammar', recipe.to_dict())
        self.assertEqual(recipe.to_dict()['source']['params'], freeze_legacy(self.p).to_dict()['source']['params'])

    def test_real_render_reopens_sample_identically_and_keeps_timing(self):
        result = render_phrase(self.bundle.render_recipe)
        reopened = GrammarRecipe.from_json(json.dumps(self.bundle.to_dict()))
        again = render_phrase(reopened.render_recipe)
        np.testing.assert_array_equal(result.mix, again.mix)
        self.assertGreater(np.max(np.abs(result.mix)), 0)
        self.assertEqual(result.diagnostics['clipped_fraction'], 0)
        for index, event in enumerate(result.events):
            self.assertEqual(event['onset_sample'], beat_to_sample(self.tm, f'{Fraction(index, 4).numerator}/{Fraction(index, 4).denominator}'))

    def test_existing_async_job_binds_revision_and_grammar_audio(self):
        recipe = self.bundle.render_recipe
        revision = self.bundle.project.head
        scheduler = JobScheduler(SchedulerLimits(), apply_numeric_limit=False)
        try:
            job = scheduler.submit(JobClass.RENDER, revision, make_render_executor(recipe, MelodicRenderSpec(), revision),
                                   estimated_memory_bytes=4_000_000)
            self.assertEqual(scheduler.wait(job, 10).state, 'completed')
            result = scheduler.result(job)
            self.assertEqual(result.recipe_sha256, recipe.sha256)
            self.assertEqual(result.revision_id, revision)
        finally:
            scheduler.shutdown(cancel=True, timeout=2)

    def test_render_memory_is_admitted_before_large_allocation(self):
        from zaaggenz_jobs import JobError
        request = ExpansionRequest(event_count=128, step_beats='16/1')
        bundle = make_grammar_recipe(self.g, request, self.p, self.tm, self.tu, quality='standard', tail_mode='truncate')
        scheduler = JobScheduler(SchedulerLimits(), apply_numeric_limit=False)
        try:
            with self.assertRaises(JobError):
                submit_grammar_render(bundle, scheduler)
        finally:
            scheduler.shutdown(cancel=True, timeout=2)

    def test_oversized_bundle_rejected_before_unreopenable_save(self):
        with self.assertRaisesRegex(GrammarError, 'frozen JSON bounds'):
            make_grammar_recipe(self.g, ExpansionRequest(event_count=2048), self.p,
                                self.tm, self.tu, quality='standard', tail_mode='truncate')

    def test_cli_create_and_reopen_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            for args in (['create', str(p / 'phrase.json'), '--events', '8', '--sample-rate', '12000'],
                         ['render', str(p / 'phrase.json'), str(p / 'phrase.wav')]):
                result = subprocess.run([sys.executable, '-m', 'zaaggenz_grammar', *args], cwd=ROOT, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertGreater((p / 'phrase.wav').stat().st_size, 44)


if __name__ == '__main__':
    unittest.main(verbosity=2)
