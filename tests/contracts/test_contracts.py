from __future__ import annotations
from copy import deepcopy
from dataclasses import FrozenInstanceError
from fractions import Fraction
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator
from zaaggenz_contracts import Contract, ContractError, KINDS, digest, loads, schema, validate, derive_seed
from zaaggenz_contracts.examples import examples
from zaaggenz_contracts.model import canonical_bytes, fraction, seed_value
from zaaggenz_contracts.music import beat_to_seconds, beat_to_sample, sample_to_beat

ROOT = Path(__file__).resolve().parents[2]


def change(value, path, replacement):
    d = deepcopy(value)
    at = d
    for key in path[:-1]:
        at = at[key]
    at[path[-1]] = replacement
    return d


class BoundaryTests(unittest.TestCase):
    def test_duplicate_key(self):
        with self.assertRaises(ContractError): loads('{"a":1,"a":2}')
    def test_nested_duplicate_key(self):
        with self.assertRaises(ContractError): loads('{"o":{"x":0,"x":1}}')
    def test_nonfinite_and_overflow(self):
        for text in ('NaN', 'Infinity', '-Infinity', '1e999'):
            with self.subTest(text=text), self.assertRaises(ContractError): loads(text)
    def test_unsafe_integer(self):
        for x in (2**53, float(2**53), -(2**53), 1e30):
            with self.subTest(x=x), self.assertRaises(ContractError): digest(x)
    def test_invalid_utf8(self):
        with self.assertRaises(ContractError): loads(b'"\xff"')
    def test_unpaired_surrogate(self):
        with self.assertRaises(ContractError): loads('"\\ud800"')
    def test_not_json(self):
        for x in ({1: 'bad'}, (1,2), b'a', {1,2}, object()):
            with self.subTest(type=type(x)), self.assertRaises(ContractError): digest(x)
    def test_cycle(self):
        x = []; x.append(x)
        with self.assertRaises(ContractError): digest(x)
    def test_depth_limit(self):
        x = 0
        for _ in range(34): x = [x]
        with self.assertRaises(ContractError): digest(x)
    def test_very_long_integer_token(self):
        with self.assertRaises(ContractError): loads('9'*5000)
    def test_byte_limit(self):
        with self.assertRaises(ContractError): loads(' ' * 2_000_001)
    def test_node_limit(self):
        with self.assertRaises(ContractError): digest([None]*100001)
    def test_string_limit(self):
        with self.assertRaises(ContractError): digest('a'*65537)
    def test_root_shape(self):
        for v in ([], None, {'kind': []}):
            with self.subTest(v=v), self.assertRaises(ContractError): validate(v)
    def test_unit_confusion(self):
        d = examples()['TimeMap'];d['tempo_segments'][0]['bpm'] = 200
        with self.assertRaises(ContractError): validate(d)
    def test_bool_is_not_integer(self):
        d=examples()['TimeMap'];d['sample_rate_hz']=True
        with self.assertRaises(ContractError): validate(d)


class IdentityTests(unittest.TestCase):
    def test_defensive_snapshot(self):
        d=examples()['TimeMap']; c=Contract(d); before=c.sha256
        d['tempo_segments'][0]['bpm']='20/1'
        c.to_dict()['tempo_segments'][0]['bpm']='21/1'
        self.assertEqual(before,c.sha256)
    def test_frozen(self):
        c=Contract(examples()['TimeMap'])
        with self.assertRaises(FrozenInstanceError): c._json=b'null'
    def test_key_order(self): self.assertEqual(digest({'z':0,'a':1}),digest({'a':1,'z':0}))
    def test_numeric_equivalence(self):
        self.assertEqual(digest(1),digest(1.)); self.assertEqual(digest(-0.),digest(0))
    def test_type_separation(self): self.assertEqual(len({digest(v) for v in (None,False,0,'0',[],{})}),6)
    def test_unicode_not_normalized(self): self.assertNotEqual(digest('é'),digest('e\u0301'))
    def test_stage_order_affects_identity(self): self.assertNotEqual(digest(['drive','tune']),digest(['tune','drive']))
    def test_seed_stable(self):
        s=derive_seed('18446744073709551615','texture')
        self.assertEqual(s,derive_seed('18446744073709551615','texture'))
        self.assertNotEqual(s,derive_seed('18446744073709551615','notes'))
        self.assertLess(int(s),2**64)
    def test_bad_seeds(self):
        for s in ('01','-1','18446744073709551616',1):
            with self.subTest(s=s), self.assertRaises(ContractError): seed_value(s)
    def test_bad_stream(self):
        with self.assertRaises(ContractError): derive_seed('0','../../file')
    def test_cross_language_vectors(self):
        vectors=json.loads((ROOT/'examples/contracts/hash-vectors-v1.json').read_text(encoding='utf-8'))
        text='\n'.join(json.dumps(v['value'],ensure_ascii=False) for v in vectors)+'\n'
        cp=subprocess.run(['node',str(ROOT/'zaaggenz_contracts/canonical.mjs')],input=text,
                          text=True,capture_output=True,check=True,encoding='utf-8',timeout=20)
        self.assertEqual(cp.stdout.splitlines(),[v['sha256'] for v in vectors])
        for v in vectors:self.assertEqual(v['sha256'],digest(v['value']))
    def test_scalar_method_data_not_executed(self):
        d=examples()['FeatureBundle']
        d['method']['configuration']={'kind':'TimeMap','version':'1.0.0','command':'not executable'}
        validate(d)  # metadata is not recursively interpreted as a contract/program


class TimingTests(unittest.TestCase):
    def setUp(self): self.d=examples()['TimeMap'];self.d['origin_sample']=0
    def test_tempo_integral(self): self.assertEqual(beat_to_seconds(self.d,'12/1'),Fraction(17,5))
    def test_boundary(self): self.assertEqual(beat_to_sample(self.d,'8/1'),115200)
    def test_negative_pickup(self): self.assertEqual(beat_to_sample(self.d,'-1/4'),-3600)
    def test_round_trip_integer_samples(self):
        for sample in (-12412,0,12,115200,223123):
            q=sample_to_beat(self.d,sample)
            self.assertEqual(beat_to_sample(self.d,f'{q.numerator}/{q.denominator}'),sample)
    def test_ties_even(self):
        self.d['sample_rate_hz']=44100;self.d['tempo_segments']=[dict(beat='0/1',bpm='360/1')]
        self.assertEqual(beat_to_sample(self.d,'1/12'),612)
        self.assertEqual(beat_to_sample(self.d,'-1/12'),-612)
        self.assertEqual(beat_to_sample(self.d,'1/4'),1838)
    def test_no_accumulated_drift(self):
        self.d['sample_rate_hz']=44100;self.d['tempo_segments']=[dict(beat='0/1',bpm='1997/10')]
        for i in range(3073):
            q=Fraction(i,12);exact=q*60*44100/Fraction(1997,10)
            self.assertLessEqual(abs(beat_to_sample(self.d,f'{q.numerator}/{q.denominator}')-exact),Fraction(1,2))
    def test_bad_rationals(self):
        for v in ('2/4','0/2','1/0','-0/1','1/-2','01/2',.5):
            with self.subTest(v=v), self.assertRaises(ContractError): fraction(v)
    def test_unsorted_tempo(self):
        self.d['tempo_segments'].reverse()
        with self.assertRaises(ContractError):validate(self.d)
    def test_duplicate_segment(self):
        self.d['tempo_segments'][1]['beat']='0/1'
        with self.assertRaises(ContractError):validate(self.d)
    def test_out_of_bounds_tempo(self):
        self.d['tempo_segments'][0]['bpm']='0/1'
        with self.assertRaises(ContractError):validate(self.d)
    def test_integer_spelling_not_float_timing(self):
        self.d['sample_rate_hz']=48000.0
        self.assertEqual(beat_to_sample(self.d,'8/1'),115200)


class SemanticTests(unittest.TestCase):
    def bad(self,kind,path,value):
        with self.assertRaises(ContractError): validate(change(examples()[kind],path,value))
    def test_unmapped_reference(self):self.bad('TuningSpec',['keyboard','reference_key'],61)
    def test_wrong_reference_degree(self):self.bad('TuningSpec',['reference_degree'],2)
    def test_unsorted_degrees(self):self.bad('TuningSpec',['degree_ratios'],[1,2,1.5])
    def test_period_not_a_degree(self):self.bad('TuningSpec',['degree_ratios'],[1,3])
    def test_non_octave_and_sparse_allowed(self):validate(examples()['TuningSpec'])
    def test_channel_layout(self):self.bad('AudioAssetRef',['channels'],1)
    def test_analysis_frequency_units(self):self.bad('FeatureBundle',['observations',0,'unit'],'LUFS')
    def test_unknown_not_zero(self):self.bad('FeatureBundle',['observations',0,'value'],0.)
    def test_unknown_confidence_not_zero(self):self.bad('FeatureBundle',['observations',0,'confidence'],0.)
    def test_valid_needs_value(self):self.bad('FeatureBundle',['observations',0,'validity'],'valid')
    def test_target_has_no_confidence(self):
        d=examples()['FeatureBundle'];o=d['observations'][0]
        o.update(validity='valid',role='target',value=48,confidence=.8)
        with self.assertRaises(ContractError):validate(d)
    def test_above_nyquist_observation(self):
        d=examples()['FeatureBundle'];o=d['observations'][0];o.update(validity='valid',value=25000,confidence=.8)
        with self.assertRaises(ContractError):validate(d)
    def test_support_order(self):self.bad('PartialTrackBundle',['tracks',0,'frames',0,'support','end_sample'],0)
    def test_unpadded_support(self):self.bad('FeatureBundle',['observations',0,'support','start_sample'],-1)
    def test_padded_support(self):
        d=examples()['FeatureBundle'];s=d['observations'][0]['support'];s.update(start_sample=-1024,padding='zero')
        validate(d)
    def test_partial_channel_phase(self):self.bad('PartialTrackBundle',['tracks',0,'frames',0,'phases_radians'],[0.])
    def test_partial_phase_convention(self):self.bad('PartialTrackBundle',['phase_convention'],'radians-somewhere')
    def test_partial_frequency(self):self.bad('PartialTrackBundle',['tracks',0,'frames',0,'frequency_hz'],24000)
    def test_unknown_phase_transform(self):
        d=examples()['PartialTrackBundle'];d['tracks'][0]['continuity']='unknown';d['tracks'][0]['frames'][0]['action']='transform'
        with self.assertRaises(ContractError):validate(d)
    def test_duplicate_partial_identity(self):
        d=examples()['PartialTrackBundle'];d['tracks']*=2
        with self.assertRaises(ContractError):validate(d)
    def test_remainder_alignment(self):
        d=examples()['PartialTrackBundle'];d['residual_asset']=deepcopy(d['asset']);d['residual_asset']['frame_count']-=1
        with self.assertRaises(ContractError):validate(d)
    def test_empty_audio_and_empty_analysis(self):
        d=examples()['FeatureBundle'];d['asset']['frame_count']=0;d['observations']=[];validate(d)
    def test_empty_audio_with_observation(self):self.bad('FeatureBundle',['asset','frame_count'],0)
    def test_wrong_gesture_units(self):self.bad('GestureSpec',['curves',0,'unit'],'Hz')
    def test_gesture_span(self):self.bad('GestureSpec',['curves',0,'points',1,'beat'],'2/1')
    def test_gesture_value(self):self.bad('GestureSpec',['curves',0,'points',1,'value'],100000)
    def test_wrong_tuning_reference(self):self.bad('PhrasePlan',['events',0,'pitch','tuning_id'],'absent')
    def test_wrong_gesture_reference(self):self.bad('PhrasePlan',['events',0,'gesture_id'],'absent')
    def test_unknown_source(self):self.bad('PhrasePlan',['events',0,'source_id'],'absent')
    def test_event_outside_phrase(self):self.bad('PhrasePlan',['events',0,'beat'],'-1/1')
    def test_rest_and_empty_phrase_allowed(self):
        d=examples()['PhrasePlan'];d['events'][0]['pitch']=None;validate(d);d['events']=[];validate(d)
    def test_graph_cycle(self):
        d=examples()['RenderRecipe'];n=examples()['DSPNodeSpec'];n.update(inputs=['trim']);d.update(nodes=[n],output_node='trim')
        with self.assertRaises(ContractError):validate(d)
    def test_graph_valid(self):
        d=examples()['RenderRecipe'];d.update(nodes=[examples()['DSPNodeSpec']],output_node='trim');validate(d)
    def test_disconnected_node(self):self.bad('RenderRecipe',['nodes'],[examples()['DSPNodeSpec']])
    def test_dangling_input(self):
        d=examples()['RenderRecipe'];n=examples()['DSPNodeSpec'];n['inputs']=['absent'];d.update(nodes=[n],output_node='trim')
        with self.assertRaises(ContractError):validate(d)
    def test_unregistered_node(self):self.bad('DSPNodeSpec',['type_id'],'arbitrary.exec')
    def test_unregistered_parameter(self):self.bad('DSPNodeSpec',['params'],{'gain_db':0,'code':'eval()'})
    def test_parameter_bound(self):self.bad('DSPNodeSpec',['params','gain_db'],25)
    def test_automation_bound(self):self.bad('DSPNodeSpec',['automation',0,'points',1,'value'],100)
    def test_automation_units(self):self.bad('DSPNodeSpec',['automation',0,'unit'],'Hz')
    def test_forged_latency(self):self.bad('DSPNodeSpec',['latency_samples'],3)
    def test_recipe_rate_mismatch(self):self.bad('RenderRecipe',['time_map','sample_rate_hz'],96000)
    def test_implicit_upmix(self):self.bad('RenderRecipe',['channels'],2)
    def test_mode_state_mismatch(self):self.bad('RenderRecipe',['render_mode'],'arrange_bass')
    def test_clipping_policy(self):self.bad('RenderRecipe',['output','clipping'],'silent-normalisation')
    def test_trial_order(self):self.bad('TrialSpec',['presentation_order'],['a','missing'])
    def test_trial_excerpt(self):self.bad('TrialSpec',['stimuli',0,'end_sample'],48001)
    def test_preregistration(self):self.bad('TrialSpec',['mode'],'confirmatory')
    def test_success_needs_artifacts(self):self.bad('RunManifest',['status'],'succeeded')
    def test_failure_needs_error(self):self.bad('RunManifest',['status'],'failed')
    def test_cancel_cannot_publish(self):
        d=examples()['RunManifest'];d.update(status='cancelled',artifacts=[{'kind':'audio','sha256':'c'*64}])
        with self.assertRaises(ContractError):validate(d)
    def test_no_network(self):
        with patch('socket.create_connection', side_effect=AssertionError('unexpected network')):
            for d in examples().values():validate(d)


class SchemaTests(unittest.TestCase):
    def test_schema_identifiers_unique(self):
        self.assertEqual(len({schema(k)['$id'] for k in KINDS}),len(KINDS))
    def test_invalid_examples(self):
        rows=json.loads((ROOT/'examples/contracts/invalid-v1.json').read_text(encoding='utf-8'))
        for row in rows:
            with self.subTest(reason=row['reason']), self.assertRaises(ContractError):
                validate(row['contract'])
    def test_newline_id(self):
        d=examples()['TuningSpec'];d['id']+='\n'
        with self.assertRaises(ContractError):validate(d)
    def test_all_metaschemas(self):
        for kind in KINDS:Draft202012Validator.check_schema(schema(kind))
    def test_examples_frozen(self):
        committed=json.loads((ROOT/'examples/contracts/valid-v1.json').read_text(encoding='utf-8'))
        self.assertEqual(committed,examples())
    def test_fragments_only(self):
        def walk(x):
            if type(x)is dict:
                if '$ref' in x:self.assertTrue(x['$ref'].startswith('#/$defs/'))
                for v in x.values():walk(v)
            elif type(x)is list:
                for v in x:walk(v)
        walk(schema())
    def test_export_and_cli(self):
        with tempfile.TemporaryDirectory() as td:
            subprocess.run([sys.executable,'-m','zaaggenz_contracts','export','--out',td],check=True,capture_output=True)
            self.assertEqual(len(list(Path(td).glob('*.schema.json'))),11)
            f=Path(td)/'recipe.json';f.write_text(Contract(examples()['RenderRecipe']).to_json())
            p=subprocess.run([sys.executable,'-m','zaaggenz_contracts','validate',str(f)],check=True,capture_output=True,text=True)
            self.assertEqual(json.loads(p.stdout)['kind'],'RenderRecipe')
    def test_invalid_cli(self):
        with tempfile.TemporaryDirectory() as td:
            f=Path(td)/'bad.json';f.write_text('{"kind":"wrong"}')
            p=subprocess.run([sys.executable,'-m','zaaggenz_contracts','validate',str(f)],capture_output=True,text=True)
            self.assertEqual(p.returncode,2);self.assertNotIn('Traceback',p.stderr)


def per_kind(kind, alteration):
    def run(self):
        d=examples()[kind]
        if alteration=='roundtrip':
            c=Contract(d);self.assertEqual(Contract.from_json(c.to_json()).sha256,c.sha256)
        else:
            if alteration=='version':d['version']='99.0.0'
            else:d['unrecognized']=True
            with self.assertRaises(ContractError):Contract(d)
    return run

for kind in KINDS:
    for alteration in ('roundtrip','version','unknown_field'):
        setattr(SchemaTests,f'test_{kind}_{alteration}',per_kind(kind,alteration))

if __name__=='__main__':unittest.main(verbosity=2)
