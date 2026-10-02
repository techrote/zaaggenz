"""Real portable project persistence, immutable sources and user preset revisions."""
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import tempfile
import unittest
from unittest.mock import patch

from zaaggenz_contracts import Contract, ContractError, digest
from zaaggenz_contracts.rack import RackRecipe, with_rack, empty_rack
from zaaggenz_project import Project, ProjectError, save_project, load_project
from zaaggenz_project.project import _revision_id
from zaaggenz_project.rack_state import MAX_RACK_PRESETS
from helpers import source, rack, retune, insert, external


def other_source():
    data = source().to_dict(); data['source']['params']['seed'] += 1
    return Contract(data)


def factory_records():
    from uptempo_harmony.synth import PRESETS
    from zaaggenz_zaag import product_preset_catalogue
    return json.dumps({'legacy': {k: v.to_dict() for k, v in PRESETS.items()},
                       'approved': product_preset_catalogue()}, sort_keys=True).encode()


class RackPersistenceTests(unittest.TestCase):
    def test_no_rack_projects_keep_old_format_and_exact_identity(self):
        from zaaggenz_contracts.legacy import freeze_legacy
        self.assertEqual(freeze_legacy({}).sha256,
            'd81b094313d0a1de20a2351380c88443ef9b0c9f7f56d3e60b3b76bc48ee332e')
        original = Project(source()); document = original.to_document()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'old.zaag.json'
            save_project(original, path); before = path.read_bytes()
            reopened = load_project(path); save_project(reopened, path)
            self.assertEqual(before, path.read_bytes())
            self.assertEqual(document, reopened.to_document())
            self.assertEqual(original.sha256, reopened.sha256)
            self.assertEqual(reopened.head_recipe.sonic_sha256, original.head_recipe.sha256)
            self.assertEqual(reopened.to_document()['format_version'], '1.0.0')
            self.assertNotIn('rack_presets', reopened.to_document())
            self.assertIsNone(reopened.rack)

    def test_edited_working_copy_and_named_preset_reopen_with_source_provenance(self):
        factory_before = factory_records()
        project = Project(source()); root = project.to_document()['revisions'][0]
        saved = rack(spectral=retune()); project.set_rack(saved)
        entry = project.save_rack_preset('user.first', 'First sound')
        self.assertEqual(entry['source_revision_id'], root['id'])
        data = saved.to_dict(); insert(data)['params']['ratio'] = 8
        project.set_rack(RackRecipe(data)); edited = project.head
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'rack.zaag.json'; save_project(project, path)
            restored = load_project(path)
            self.assertEqual(restored.to_document(), project.to_document())
            self.assertEqual(restored.head, edited)
            self.assertEqual(restored.rack.to_dict(), data)
            restored.apply_rack_preset('user.first')
            self.assertNotEqual(restored.head, edited)
            self.assertEqual(restored.rack.sha256, saved.sha256)
            self.assertEqual(restored.to_document()['revisions'][0], root)
            save_project(restored, path)
            self.assertEqual(load_project(path).sha256, restored.sha256)
        self.assertEqual(factory_records(), factory_before)

    def test_cosmetic_names_do_not_change_audio_but_settings_do(self):
        project = Project(source()); project.set_rack(rack()); project.save_rack_preset('user', 'Before')
        head = project.head; sonic = project.head_recipe.sonic_sha256; snapshot = project.sha256
        project.rename_rack_preset('user', 'After')
        self.assertEqual(head, project.head)
        self.assertEqual(sonic, project.head_recipe.sonic_sha256)
        self.assertNotEqual(snapshot, project.sha256)
        data = project.rack.to_dict(); data['display'][data['id']] = 'Display rack'
        project.set_rack(RackRecipe(data))
        self.assertNotEqual(head, project.head)
        self.assertEqual(sonic, project.head_recipe.sonic_sha256)
        data['wet'] = .5; project.set_rack(RackRecipe(data))
        self.assertNotEqual(sonic, project.head_recipe.sonic_sha256)
        detached = project.rack_presets; detached['user']['name'] = 'Not saved'
        self.assertEqual(project.rack_presets['user']['name'], 'After')

    def test_reset_processing_and_restore_source_are_distinct_explicit_actions(self):
        base = source(); project = Project(base); project.set_rack(rack())
        project.save_rack_preset('mine', 'Mine')
        data = project.head_recipe.to_dict(); data['output']['master_gain_db'] = -7
        project.commit(Contract(data)); project.reset_rack()
        self.assertIsNone(project.rack)
        self.assertEqual(project.head_recipe.to_dict()['output']['master_gain_db'], -7)
        self.assertEqual(project.head_recipe.to_dict()['source'], base.to_dict()['source'])
        project.apply_rack_preset('mine')
        project.restore_source_and_rack()
        self.assertEqual(project.head_recipe.to_json(), base.to_json())
        self.assertIsNone(project.rack)
        project.commit(other_source()); old_head = project.head
        with self.assertRaisesRegex(ContractError, 'binding'): project.apply_rack_preset('mine')
        self.assertEqual(project.head, old_head)
        project.restore_source_and_rack('mine')
        self.assertEqual(project.head_recipe.to_dict()['source'], base.to_dict()['source'])
        self.assertEqual(project.rack.sha256, project.rack_presets['mine']['rack_sha256'])

    def test_unavailable_external_states_round_trip_without_a_host(self):
        project = Project(source()); data = empty_rack(source()).to_dict()
        data['bands'][2]['inserts'] = [external()]; project.set_rack(RackRecipe(data))
        project.save_rack_preset('external', 'Unavailable processor')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'external.json'; save_project(project, path)
            restored = load_project(path)
            self.assertEqual(restored.to_document(), project.to_document())
            self.assertTrue(restored.rack.has_external)

    def test_source_origin_must_be_a_real_retained_no_rack_ancestor(self):
        with self.assertRaisesRegex(ProjectError, 'retained no-rack'): Project(with_rack(source(), rack()))
        project = Project(source()); before = project.to_document()
        data = rack().to_dict(); data['source_binding']['origin_recipe_sha256'] = 'f'*64
        with self.assertRaisesRegex(ProjectError, 'ancestor'): project.set_rack(RackRecipe(data))
        self.assertEqual(project.to_document(), before)
        project.set_rack(rack()); doc = project.to_document()
        # Recompute hashes: a forged but self-consistent revision must still fail ancestry validation.
        row = doc['revisions'][-1]; payload = json.loads(row['recipe_json'])
        payload['rack']['source_binding']['origin_recipe_sha256'] = 'a'*64
        recipe = Contract(payload); row['recipe_json'] = recipe.to_json(); row['recipe_sha256'] = recipe.sha256
        row['id'] = _revision_id(recipe.sha256, row['parent']); doc['head'] = row['id']
        with self.assertRaisesRegex(ProjectError, 'ancestor'): Project.from_document(doc)

    def test_hidden_preset_state_unknown_formats_and_tampering_fail(self):
        project = Project(source()); project.set_rack(rack()); project.save_rack_preset('user', 'User')
        mutations = [lambda d: d.update(format_version='9.0.0'),
            lambda d: d.update(format_version='1.0.0'), lambda d: d.pop('rack_presets'),
            lambda d: d['rack_presets']['user'].update(id='other'),
            lambda d: d['rack_presets']['user'].update(source_revision_id='f'*64),
            lambda d: d['rack_presets']['user'].update(rack_sha256='f'*64),
            lambda d: d['rack_presets']['user'].update(sonic_sha256='f'*64),
            lambda d: d['rack_presets']['user'].update(name='bad\nname'),
            lambda d: insert(d['rack_presets']['user']['rack'])['params'].update(ratio=float('nan'))]
        for mutate in mutations:
            data = project.to_document(); mutate(data)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError): Project.from_document(data)
        data = project.to_document()
        data['rack_presets']['user']['rack']['bypass'] = True
        insert(data['rack_presets']['user']['rack'])['params']['ratio'] = 0
        with self.assertRaises(ProjectError): Project.from_document(data)

    def test_preset_bounds_and_failed_mutations_are_atomic(self):
        project = Project(source()); project.set_rack(empty_rack(source()))
        for i in range(MAX_RACK_PRESETS): project.save_rack_preset('user.'+str(i), 'Preset '+str(i))
        before = project.to_document()
        for action in [lambda: project.save_rack_preset('overflow', 'Overflow'),
                       lambda: project.save_rack_preset('user.0', 'Unconfirmed overwrite'),
                       lambda: project.rename_rack_preset('user.0', 'x'*129),
                       lambda: project.save_rack_preset('invalid/id', 'Invalid id')]:
            with self.assertRaises(ValueError): action()
            self.assertEqual(project.to_document(), before)
        project.save_rack_preset('user.0', 'Explicit replacement', replace=True)
        self.assertEqual(len(project.rack_presets), MAX_RACK_PRESETS)
        before = project.to_document(); data = project.rack.to_dict(); data['wet'] = .7
        # Small injected limit exercises the actual admission path without manufacturing huge histories.
        with patch('zaaggenz_project.rack_state.MAX_BYTES', 10):
            with self.assertRaises(ProjectError): project.set_rack(RackRecipe(data))
        self.assertEqual(project.to_document(), before)


if __name__ == '__main__': unittest.main()
