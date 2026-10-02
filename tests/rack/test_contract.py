"""Shape, semantic/resource admission, identity and extension-boundary tests."""
from copy import deepcopy
import math
import unittest

from jsonschema import Draft202012Validator
from zaaggenz_contracts import Contract, ContractError, schema, digest
from zaaggenz_contracts.rack import (RackRecipe, RackError, RACK_VERSION, with_rack,
    without_rack, empty_rack, state_blob, processor_definition, MAX_RACK_BYTES,
    MAX_PLUGIN_STATE_BYTES, MAX_RETUNE_SEGMENTS, MAX_INSERTS_PER_BAND,
    COMPRESSION, BITCRUSH, PLACEMENT)
from zaaggenz_dsp import CompressionSpec, BitcrushSpec
from helpers import source, rack, insert, retune, chordness, external


class RackContractTests(unittest.TestCase):
    def test_explicit_recipe_version_and_frozen_schema(self):
        old = source()
        previous = old.to_json()
        schema_before = schema()
        new = with_rack(old, rack(old, retune(old)))
        exported = schema('RenderRecipe', version='1.1.0')
        Draft202012Validator.check_schema(exported)
        Draft202012Validator(exported).validate(new.to_dict())
        self.assertEqual(Contract.from_json(new.to_json()).sha256, new.sha256)
        self.assertEqual(without_rack(new).to_json(), previous)
        self.assertEqual(old.to_json(), previous)
        self.assertEqual(schema(), schema_before)
        self.assertNotIn('rack', schema_before['$defs']['RenderRecipe']['properties'])
        self.assertEqual(old.sonic_sha256, old.sha256)
        for kind, version in [('TimeMap', '1.1.0'), ('RenderRecipe', '9.0.0'), (None, '1.1.0')]:
            with self.subTest(kind=kind, version=version), self.assertRaises(ValueError):
                schema(kind, version=version)
        for version, remove_rack in [('1.0.0', False), ('1.1.0', True), ('9.0.0', False)]:
            data = new.to_dict(); data['version'] = version
            if remove_rack: del data['rack']
            with self.assertRaises(ContractError): Contract(data)

    def test_defaults_are_original_spec_defaults_and_defensive(self):
        for type_id, definitions, spec in [('zg.compression', COMPRESSION, CompressionSpec()),
                                            ('zg.bitcrush', BITCRUSH, BitcrushSpec())]:
            for key, definition in definitions.items():
                self.assertEqual(definition['default'], getattr(spec, key))
            metadata = processor_definition(type_id)
            metadata['parameters'].clear()
            self.assertTrue(processor_definition(type_id)['parameters'])

    def test_snapshot_and_sonic_identity_are_distinct(self):
        saved = rack(spectral=retune()); data = saved.to_dict()
        data['display'][data['id']] = 'User label'
        spectral = insert(data, 'spectral')['params']
        spectral['voices'][0]['label'] = 'Renamed root'
        spectral['segments'][0]['label'] = 'Renamed passage'
        spectral['segments'][0]['voices'][0]['label'] = 'Renamed bass'
        renamed = RackRecipe(data)
        self.assertNotEqual(renamed.sha256, saved.sha256)
        self.assertEqual(renamed.sonic_sha256, saved.sonic_sha256)
        self.assertEqual(with_rack(source(), renamed).sonic_sha256,
                         with_rack(source(), saved).sonic_sha256)
        data['display'].clear()
        self.assertIn('User label', renamed.to_json())  # defensive, not a live dict
        chord = rack(spectral=chordness()); data = chord.to_dict()
        insert(data, 'spectral')['params']['templates'][0]['label'] = 'Display only'
        self.assertEqual(chord.sonic_sha256, RackRecipe(data).sonic_sha256)

    def test_sonic_fields_and_instance_preserving_reorder(self):
        saved = rack(spectral=retune()); data = saved.to_dict()
        original = {i['id']: i for i in data['bands'][1]['inserts']}
        moved = saved.move_insert(data['bands'][1]['id'], original[next(iter(original))]['id'], 3)
        self.assertEqual({i['id']: i for i in moved.to_dict()['bands'][1]['inserts']}, original)
        self.assertNotEqual(moved.sonic_sha256, saved.sonic_sha256)
        self.assertEqual(saved.move_insert(data['bands'][1]['id'], data['bands'][1]['inserts'][0]['id'], 0).sha256,
                         saved.sha256)
        mutations = [lambda d: d.update(bypass=True), lambda d: d.update(wet=.5),
                     lambda d: d['bands'][1].update(bypass=True), lambda d: d['bands'][1].update(wet=.5),
                     lambda d: d['bands'][1].update(confine_delta=True),
                     lambda d: insert(d).update(bypass=True), lambda d: insert(d).update(wet=.5),
                     lambda d: insert(d)['params'].update(ratio=5),
                     lambda d: d['crossovers']['frequencies_hz'].__setitem__(0, 100.),
                     lambda d: insert(d, 'spectral')['params'].update(amount=.5),
                     lambda d: d['source_binding'].update(origin_recipe_sha256='f' * 64)]
        for mutate in mutations:
            value = saved.to_dict(); mutate(value)
            self.assertNotEqual(saved.sonic_sha256, RackRecipe(value).sonic_sha256)

    def test_cross_band_move_preserves_instance_and_its_label(self):
        saved = rack(); data = saved.to_dict(); moved = data['bands'][1]['inserts'].pop(0)
        data['display'][moved['id']] = 'My processor'
        before_move = RackRecipe(saved.to_dict() | {'display': data['display']})
        data['bands'][2]['inserts'].append(moved)
        after_move = RackRecipe.from_json(RackRecipe(data).to_json())
        self.assertEqual(after_move.to_dict()['bands'][2]['inserts'][0], moved)
        self.assertEqual(after_move.to_dict()['display'][moved['id']], 'My processor')
        self.assertNotEqual(after_move.sonic_sha256, before_move.sonic_sha256)

    def test_source_and_rate_binding_cannot_be_relaxed(self):
        saved = rack()
        foreign = source(24000)
        for base in [foreign, source().to_dict() | {'channels': 2}]:
            with self.assertRaises(ContractError): with_rack(base, saved)
        changed = source().to_dict(); changed['source']['params']['seed'] += 1
        with self.assertRaises(ContractError): with_rack(Contract(changed), saved)
        changed = source().to_dict(); changed['source']['id'] = 'another'; changed['output_node'] = 'another'
        with self.assertRaises(ContractError): with_rack(Contract(changed), saved)

    def test_invalid_hidden_state_is_rejected_at_all_bypass_levels(self):
        bad = [lambda d: insert(d)['params'].update(ratio=0),
               lambda d: insert(d)['params'].update(ratio=float('nan')),
               lambda d: insert(d)['params'].update(attack_ms=float('inf')),
               lambda d: insert(d)['params'].update(wet=True),
               lambda d: insert(d)['params'].update(surprise=1),
               lambda d: insert(d).update(type_id='untrusted.native'),
               lambda d: insert(d).update(version='2.0.0'),
               lambda d: insert(d).pop('id'),
               lambda d: insert(d).update(automation=[{'parameter': 'ratio', 'value': 8}]),
               lambda d: d['crossovers'].update(frequencies_hz=[520., 105., 3600.]),
               lambda d: d['crossovers'].update(frequencies_hz=[105., 520., 5880.]),
               lambda d: d['crossovers'].update(frequencies_hz=[0., 520., 3600.]),
               lambda d: d['crossovers'].update(method='other.filter'),
               lambda d: d.update(version='99.0.0'),
               lambda d: d.update(sample_rate_hz=True),
               lambda d: d.update(sample_rate_hz=7999),
               lambda d: d['policy'].update(master_gain_db=6),
               lambda d: d['placement'].update(bus='SUB'),
               lambda d: d['display'].update(missing='Dangling label'),
               lambda d: d.update(monitor_solo='lowmid')]
        for bypass_level in ['rack', 'band', 'insert']:
            for number, mutate in enumerate(bad):
                with self.subTest(bypass=bypass_level, case=number):
                    value = rack().to_dict()
                    if bypass_level == 'rack': value['bypass'] = True
                    elif bypass_level == 'band': value['bands'][1]['bypass'] = True
                    else: insert(value)['bypass'] = True
                    mutate(value)
                    with self.assertRaises(ContractError): RackRecipe(value)

    def test_duplicate_ids_types_and_fixed_band_partition(self):
        saved = rack().to_dict()
        modifications = [lambda d: insert(d).update(id=d['id']),
            lambda d: d['bands'][0].update(id=d['bands'][1]['id']),
            lambda d: insert(d).update(id=d['bands'][1]['inserts'][0]['id']),
            lambda d: d['bands'][0]['inserts'].append(deepcopy(insert(d))),
            lambda d: d['bands'][0].update(band='lowmid'),
            lambda d: d['bands'].reverse(),
            lambda d: d['bands'][1]['inserts'].append(insert(d) | {'id': 'compression.second'})]
        for mutate in modifications:
            data = deepcopy(saved); mutate(data)
            with self.assertRaises(ContractError): RackRecipe(data)

    def test_spectral_bounds_and_method_validation_behind_bypass(self):
        bad = [lambda p: p.update(version='9.0.0'), lambda p: p.update(kind='ExternalSpectral'),
               lambda p: p.update(amount=-.1), lambda p: p.update(max_hz=6000.1),
               lambda p: p.update(voices=[]), lambda p: p.update(segments=p['segments'] * 65),
               lambda p: p['voices'][0].update(partial_ratios=[1., 1.]),
               lambda p: p['voices'][0].update(partial_ratios=[1.] * 129),
               lambda p: p['voices'][0].update(degree=4097),
               lambda p: p['segments'][0].update(start_sample=0),
               lambda p: p['tuning_spec'].update(version='2.0.0'),
               lambda p: p.update(max_displacement_cents=1e100)]
        for mutate in bad:
            data = rack(spectral=retune()).to_dict(); data['bypass'] = True
            mutate(insert(data, 'spectral')['params'])
            with self.assertRaises(ContractError): RackRecipe(data)
        for mutate in [lambda p: p.update(selected_template_ids=['missing']),
                       lambda p: p.update(max_displacement_cents=2400, max_assignment_cents=100),
                       lambda p: p['templates'][0].update(teeth_hz=[6001.]),
                       lambda p: p['templates'][0].update(tooth_capacity=17),
                       lambda p: p['coefficients'].update(target_fit=float('nan'))]:
            data = rack(spectral=chordness()).to_dict(); data['bypass'] = True
            mutate(insert(data, 'spectral')['params'])
            with self.assertRaises(ContractError): RackRecipe(data)

    def test_unavailable_external_descriptor_is_only_preserved_data(self):
        data = rack().to_dict(); data['bands'][1]['inserts'].insert(2, external())
        saved = RackRecipe(data)
        self.assertTrue(saved.has_external)
        self.assertFalse(processor_definition('external.vst3')['executable'])
        self.assertEqual(RackRecipe.from_json(saved.to_json()).sha256, saved.sha256)
        data['bands'][1]['inserts'][2]['params']['component_state'] = state_blob(b'changed')
        self.assertNotEqual(saved.sonic_sha256, RackRecipe(data).sonic_sha256)
        for mutate in [lambda p: p.update(path='C:\\evil.dll'),
                       lambda p: p.update(format='VST2'), lambda p: p.update(platform='linux-x64'),
                       lambda p: p.update(class_id='x' * 32),
                       lambda p: p['component_state'].update(sha256='0' * 64),
                       lambda p: p['component_state'].update(data='@@@@'),
                       lambda p: p['component_state'].update(encoding='pickle'),
                       lambda p: p.update(execution_contract='executable')]:
            changed = saved.to_dict(); mutate(changed['bands'][1]['inserts'][2]['params'])
            with self.assertRaises(ContractError): RackRecipe(changed)

    def test_serialized_state_and_insert_count_limits(self):
        self.assertEqual(len(state_blob(b'x' * MAX_PLUGIN_STATE_BYTES)['data']), 10924)
        with self.assertRaises(ContractError): state_blob(b'x' * (MAX_PLUGIN_STATE_BYTES + 1))
        data = empty_rack(source()).to_dict()
        data['bands'][0]['inserts'] = [external('ext.' + str(i), b'') for i in range(MAX_INSERTS_PER_BAND)]
        self.assertEqual(len(RackRecipe(data).to_dict()['bands'][0]['inserts']), MAX_INSERTS_PER_BAND)
        data['bands'][0]['inserts'].append(external('too.many', b''))
        with self.assertRaises(ContractError): RackRecipe(data)
        data = empty_rack(source()).to_dict()
        data['bands'][0]['inserts'] = [external('ext.' + str(i), b'x' * 8192) for i in range(5)]
        with self.assertRaises(ContractError): RackRecipe(data)
        with self.assertRaises(ContractError): RackRecipe.from_json(' ' * (MAX_RACK_BYTES + 1))
        with self.assertRaises(ContractError): RackRecipe.from_json('{"kind":0,"kind":1}')

    def test_numeric_boundaries_and_disabled_rate_preflight(self):
        # Generic rack admission supports 192 kHz; the legacy synth source caps 96 kHz.
        for rate in (8000, 96000, 192000):
            data = empty_rack(source(min(rate, 96000))).to_dict()
            data['sample_rate_hz'] = rate; data['bypass'] = True
            data['crossovers']['frequencies_hz'] = [20., 520., math.nextafter(.49 * rate, 0.)]
            RackRecipe(data)
            data['crossovers']['frequencies_hz'][2] = .49 * rate
            with self.assertRaises(ContractError): RackRecipe(data)
        data = rack().to_dict(); insert(data)['params'].update(threshold_db=-120, ratio=100,
            attack_ms=.01, release_ms=10000, knee_db=48, makeup_db=-36, wet=0)
        RackRecipe(data)
        insert(data)['params']['ratio'] = math.nextafter(100., math.inf)
        with self.assertRaises(ContractError): RackRecipe(data)


if __name__ == '__main__': unittest.main()
