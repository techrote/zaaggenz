from __future__ import annotations
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'app'))
from zaaggenz_gesture import DirectionalGesture,edit_landing,compile_gesture_recipe
from zaaggenz_melody import render_phrase
from zaaggenz_project import Project
from zaaggenz_textgesture import (TextGestureError,TextSyntaxError,MnemonicDictionary,DictionaryRegistry,
    parse_text,format_text,semantic_ast,compile_text,make_render_recipe,TextGestureBundle,make_bundle,starter_registry)

SAMPLE='bu[d=1/2,a=2,p=1,b=0.6] ~1/4 |\nbudu[n=4,c=25] @return[d=1/2]'

class SyntaxTests(unittest.TestCase):
    def test_canonical_roundtrip_preserves_semantics_timing_units_groups_and_return(self):
        a=parse_text(SAMPLE);canonical=format_text(a);b=parse_text(canonical)
        self.assertEqual(semantic_ast(a),semantic_ast(b));self.assertEqual(format_text(b),canonical)
        self.assertEqual(a['group_count'],2);self.assertEqual(a['modifier_units']['d'],'beats');self.assertEqual(a['modifier_units']['b'],'opening-fraction')
        self.assertEqual([x['kind'] for x in a['items']],['token','hold','group','token','return'])
        self.assertEqual(a['items'][-1]['kind'],'return')
    def test_source_spans_include_exact_line_and_column(self):
        ast=parse_text('bu |\n  budu @return')
        budu=next(x for x in ast['items'] if x.get('token')=='budu')
        self.assertEqual((budu['span']['line'],budu['span']['column']),(2,3))
    def test_invalid_modifier_reports_exact_source_location(self):
        with self.assertRaises(TextSyntaxError) as cm:parse_text('bu |\n  budu[x=1] @return')
        self.assertEqual((cm.exception.line,cm.exception.column),(2,8));self.assertIn('unknown modifier',str(cm.exception))
    def test_ambiguous_or_executable_looking_syntax_never_executes(self):
        with tempfile.TemporaryDirectory() as tmp:
            sentinel=Path(tmp)/'should-not-exist'
            payload=f'bu $(touch {sentinel}) @return'
            with self.assertRaises(TextSyntaxError):parse_text(payload)
            self.assertFalse(sentinel.exists())
        for text in ('bu;drop @return','bu `whoami` @return','bu __import__ @return','bu[x=1] @return'):
            with self.subTest(text=text),self.assertRaises(TextSyntaxError):parse_text(text)
    def test_hold_group_and_terminal_return_rules_are_strict(self):
        for text in ('~1/2 bu @return','| bu @return','bu | @return','bu @return budu','bu'):
            with self.subTest(text=text),self.assertRaises(TextSyntaxError):parse_text(text)

class DictionaryTests(unittest.TestCase):
    def setUp(self):self.registry=starter_registry()
    def test_multiple_dictionaries_coexist_and_same_syllable_can_mean_different_things(self):
        self.assertEqual(self.registry.ids,('local-soft','local-bright'))
        soft=self.registry.get('local-soft').mapping('bu');bright=self.registry.get('local-bright').mapping('bu')
        self.assertNotEqual(soft['degree_offset'],bright['degree_offset']);self.assertNotEqual(soft['brightness_fraction'],bright['brightness_fraction'])
        original=self.registry.sha256;copy_doc=self.registry.to_dict();copy_doc['dictionaries'][0]['base_degree']=12
        self.assertEqual(self.registry.sha256,original)
    def test_dictionary_validation_rejects_duplicate_tokens_and_bad_ranges(self):
        data=self.registry.get('local-soft').to_dict();data['entries'].append(deepcopy(data['entries'][0]))
        with self.assertRaisesRegex(TextGestureError,'duplicate'):MnemonicDictionary(data)
        data=self.registry.get('local-soft').to_dict();data['brightness_range_hz']={'closed_hz':5000.,'open_hz':1000.}
        with self.assertRaisesRegex(TextGestureError,'closed_hz < open_hz'):MnemonicDictionary(data)
    def test_registry_is_versioned_and_reopenable(self):
        reopened=DictionaryRegistry.from_document(json.loads(json.dumps(self.registry.to_dict())))
        self.assertEqual(reopened.sha256,self.registry.sha256)
        with self.assertRaisesRegex(TextGestureError,'duplicate dictionary id'):DictionaryRegistry([self.registry.get('local-soft'),self.registry.get('local-soft')])

class CompilationTests(unittest.TestCase):
    def setUp(self):self.registry=starter_registry()
    def test_preview_makes_tuning_source_and_defaults_visible_before_apply(self):
        compiled=compile_text(SAMPLE,self.registry,'local-soft',sample_rate=12000);preview=compiled.preview
        self.assertEqual(preview['apply_state'],'preview-only; export/apply is explicit')
        self.assertEqual(preview['dictionary_id'],'local-soft');self.assertEqual(preview['base_degree'],0)
        self.assertIn('active_tuning',preview);self.assertEqual(preview['active_tuning']['id'],preview['active_tuning_id'])
        self.assertGreater(preview['source_frequency_hz'],0);self.assertEqual(preview['source_id'],compiled.phrase.to_dict()['source_ids'][0])
    def test_hold_and_groups_compile_to_exact_editable_timeline(self):
        compiled=compile_text(SAMPLE,self.registry,'local-soft',sample_rate=12000);events=compiled.preview['events'];timeline=compiled.timeline.to_dict()
        self.assertEqual((events[0]['beat'],events[0]['duration_beats'],events[0]['holds']),('0/1','3/4',['1/4']))
        self.assertEqual(events[1]['beat'],'3/4');self.assertTrue(events[-1]['terminal_return'])
        self.assertEqual((events[-1]['beat'],events[-1]['duration_beats']),('5/4','1/2'))
        self.assertEqual([(c['start_beat'],c['end_beat']) for c in timeline['clips']],[('0/1','3/4'),('3/4','7/4')])
        self.assertEqual([n['beat'] for n in timeline['notes']],['0/1','3/4','5/4'])
    def test_dictionary_choice_changes_mapping_without_mutating_text(self):
        text='bu @return';soft=compile_text(text,self.registry,'local-soft',sample_rate=12000);bright=compile_text(text,self.registry,'local-bright',sample_rate=12000)
        self.assertEqual(format_text(soft.ast),format_text(bright.ast));self.assertEqual(soft.ast,bright.ast)
        self.assertNotEqual(soft.preview['events'][0]['degree'],bright.preview['events'][0]['degree'])
        self.assertNotEqual(soft.gesture.to_dict()['trajectories'][4]['points'][0]['value'],bright.gesture.to_dict()['trajectories'][4]['points'][0]['value'])
    def test_unknown_token_reports_original_line_and_column(self):
        with self.assertRaises(TextSyntaxError) as cm:compile_text('bu |\n  mystery @return',self.registry,'local-soft',sample_rate=12000)
        self.assertEqual((cm.exception.line,cm.exception.column),(2,3));self.assertIn("'mystery'",str(cm.exception))
    def test_compiled_gesture_is_valid_roundtrippable_and_has_return_landmarks(self):
        compiled=compile_text(SAMPLE,self.registry,'local-soft',sample_rate=12000);gesture=compiled.gesture
        reopened=DirectionalGesture.from_json(json.dumps(gesture.to_dict()));self.assertEqual(reopened.sha256,gesture.sha256)
        kinds=[x['kind'] for x in gesture.to_dict()['landmarks']];self.assertIn('landing',kinds);self.assertIn('endpoint',kinds);self.assertIn('turn',kinds)
        self.assertEqual(gesture.to_dict()['landing']['beat'],compiled.preview['events'][-1]['beat'])
    def test_normal_offline_render_is_source_preserving_and_nonzero(self):
        compiled=compile_text(SAMPLE,self.registry,'local-soft',sample_rate=12000);recipe=make_render_recipe(compiled)
        source=Project.from_document(compiled.timeline.to_dict()['project']).head_recipe.to_dict()['source'];self.assertEqual(recipe.to_dict()['source'],source)
        result=render_phrase(recipe);self.assertGreater(np.max(np.abs(result.mix)),0);self.assertEqual(result.diagnostics['notes'],3);self.assertGreater(result.diagnostics['roll_retriggers'],0)
    def test_structured_gesture_remains_manually_editable_without_text(self):
        compiled=compile_text('bu budu @return',self.registry,'local-soft',sample_rate=12000)
        edited=edit_landing(compiled.gesture,degree=2,detune_cents=15.)
        self.assertEqual((edited.to_dict()['landing']['degree'],edited.to_dict()['landing']['detune_cents']),(2,15.))
        bundle=compile_gesture_recipe(edited,compiled.timeline);result=render_phrase(bundle.recipe)
        self.assertGreater(np.max(np.abs(result.mix)),0);self.assertEqual(bundle.recipe.to_dict()['phase_policy'],'source-derived')

class BundleTests(unittest.TestCase):
    def setUp(self):self.registry=starter_registry();self.bundle=make_bundle(SAMPLE,self.registry,'local-soft',sample_rate=12000)
    def test_bundle_roundtrip_recompiles_and_reproduces_all_derived_identity(self):
        reopened=TextGestureBundle.from_json(json.dumps(self.bundle.to_dict()))
        self.assertEqual(reopened.sha256,self.bundle.sha256);self.assertEqual(reopened.compilation.sha256,self.bundle.compilation.sha256)
        self.assertEqual(reopened.timeline.revision_id,self.bundle.timeline.revision_id);self.assertEqual(reopened.gesture.sha256,self.bundle.gesture.sha256)
    def test_tampered_text_dictionary_gesture_or_preview_is_rejected(self):
        for change in ('text','dictionary','gesture','preview'):
            doc=self.bundle.to_dict()
            if change=='text':doc['text']='bu @return'
            elif change=='dictionary':doc['registry']['dictionaries'][0]['entries'][0]['mapping']['degree_offset']=7
            elif change=='gesture':doc['gesture']['landing']['degree']=7
            else:doc['preview']['base_degree']=7
            with self.subTest(change=change),self.assertRaises(TextGestureError):TextGestureBundle(doc)
    def test_bundle_embeds_project_local_registry_and_apply_is_explicit_timeline_data(self):
        doc=self.bundle.to_dict();self.assertEqual(doc['registry'],self.registry.to_dict())
        self.assertEqual(doc['preview']['apply_state'],'preview-only; export/apply is explicit')
        self.assertEqual(self.bundle.timeline.to_dict()['project'],doc['base_timeline']['project'])
        self.assertNotEqual(doc['base_timeline']['notes'],doc['timeline']['notes'])

if __name__=='__main__':unittest.main(verbosity=2)
