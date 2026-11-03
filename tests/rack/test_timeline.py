"""Authoritative Compose saved-contract handoff; runtime execution is MBR-002."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from zaaggenz_contracts import Contract, ContractError, digest
from zaaggenz_contracts.legacy import freeze_legacy
from zaaggenz_contracts.rack import RackRecipe, empty_rack, PLACEMENT
from zaaggenz_project import Project
from zaaggenz_timeline.model import (TimelineDocument, default_document, compile_recipe,
                                   source_preset_id, apply_source_preset, OWNERSHIP)
from zaaggenz_melody import render_phrase, MelodyError
from zaaggenz_dsp.legacy import _node
from helpers import rack, source


def one_note(document=None):
    document = default_document(12000) if document is None else document
    data = document.to_dict(); data['end_beat'] = '1/1'
    data['notes'] = [{'id': 'n1', 'beat': '0/1', 'duration_beats': '1/1', 'degree': 0,
                     'detune_cents': 0., 'gain_db': 0., 'muted': False, 'roll_density': 0}]
    data['next_id'] = 1
    return TimelineDocument(data)


class RackTimelineTests(unittest.TestCase):
    def test_no_rack_default_source_and_recipe_match_accepted_main_golden(self):
        # Captured by executing the accepted b62ffb1 source tree, not the new code.
        doc = default_document(12000)
        self.assertEqual(doc.revision_id, 'dd9762df9ee61ee6bca5ad7afa529fa230dacfe07e494d95407c4688c5f95f5b')
        doc = one_note(doc)
        self.assertEqual(doc.revision_id, '3d4233a3dee96bcef4d75f25716c063db4db7a72398b288af7db0b8e0628059e')
        self.assertEqual(compile_recipe(doc).sha256, '2d5ac375ead853ead55ef6fd30f947f60faa0c8c3009f1d3ffaae48d4fe9e220')
        self.assertEqual(source_preset_id(doc), 'locked_bloom')
        from uptempo_harmony.synth import PRESETS
        from zaaggenz_zaag import product_preset_catalogue
        self.assertEqual(digest({'legacy': {k: v.to_dict() for k, v in PRESETS.items()},
                                'approved': product_preset_catalogue()}),
                         'f4aaa0c1bc495e01e237f8f448071d2ce28a8d4851f3826237eaa1f1372fc8cf')
        self.assertGreater(render_phrase(compile_recipe(doc)).mix.size, 0)

    def test_saved_working_copy_survives_compose_reopen_and_compilation(self):
        data = one_note().to_dict(); project = Project.from_document(data['project'])
        origin = project.head_recipe; original_record = project.to_document()['revisions'][0]
        saved = rack(origin); project.set_rack(saved); project.save_rack_preset('my.rack', 'My rack')
        data['project'] = project.to_document(); data['master_gain_db'] = -4
        document = TimelineDocument.from_json(json.dumps(data))
        recipe = compile_recipe(document).to_dict()
        self.assertEqual(recipe['version'], '1.1.0')
        self.assertEqual(recipe['rack'], saved.to_dict())
        self.assertEqual(recipe['source'], origin.to_dict()['source'])
        self.assertEqual(recipe['output']['master_gain_db'], -4)
        self.assertEqual(recipe['rack']['policy']['master_gain_db'], 0)
        self.assertEqual(recipe['rack']['placement'], PLACEMENT)
        self.assertEqual(document.to_dict()['layer_ownership'], OWNERSHIP)
        retained = Project.from_document(document.to_dict()['project'])
        self.assertEqual(retained.to_document()['revisions'][0], original_record)
        for key in ('arrangement', 'reversebass', 'sculpt'):
            self.assertEqual(retained.head_recipe.to_dict()[key], origin.to_dict()[key])
            self.assertIsNone(recipe[key])  # full-mix ownership is not rebound to SYNTHLINE
        self.assertEqual(source_preset_id(document), 'locked_bloom')
        self.assertEqual(retained.rack_presets['my.rack']['rack'], recipe['rack'])

    def test_synth_owned_sculpt_and_graph_are_not_dropped_by_rack_compilation(self):
        from uptempo_harmony.multiband import SCULPT_PRESETS
        for graph in (False, True):
            base = freeze_legacy({'sr': 12000}, sculpt=SCULPT_PRESETS['gentle_separation'].to_dict())
            if graph:
                from zaaggenz_dsp.legacy import graphify_legacy_recipe
                base = graphify_legacy_recipe(base)
            project = Project(base); project.set_rack(empty_rack(base))
            data = one_note().to_dict(); data['project'] = project.to_document()
            compiled = compile_recipe(TimelineDocument(data)).to_dict()
            self.assertEqual(compiled['sculpt'], base.to_dict()['sculpt'])
            self.assertEqual(compiled['nodes'], base.to_dict()['nodes'])
            self.assertEqual(compiled['output_node'], base.to_dict()['output_node'])

    def test_ambiguous_full_mix_graph_is_rejected_not_reassigned(self):
        data = one_note().to_dict(); project = Project.from_document(data['project'])
        base = project.head_recipe.to_dict()
        base['nodes'] = [_node('gain', 'core.gain.v1', base['source']['id'], {'gain_db': -3})]
        base['output_node'] = 'gain'; origin = Contract(base)
        project.commit(origin); project.set_rack(empty_rack(origin)); data['project'] = project.to_document()
        with self.assertRaisesRegex(MelodyError, 'ambiguous layer ownership'):
            compile_recipe(TimelineDocument(data))

    def test_runtime_execution_is_real_and_bypass_is_exact(self):
        import numpy as np
        dry = render_phrase(compile_recipe(one_note()))
        for bypass in (False, True):
            data = one_note().to_dict(); project = Project.from_document(data['project'])
            saved = rack(project.head_recipe).to_dict(); saved['bypass'] = bypass
            project.set_rack(RackRecipe(saved)); data['project'] = project.to_document()
            compiled = compile_recipe(TimelineDocument(data))
            actual = render_phrase(compiled)
            self.assertIn('rack', actual.diagnostics)
            if bypass:
                np.testing.assert_array_equal(actual.mix, dry.mix)
            else:
                self.assertFalse(np.array_equal(actual.mix, dry.mix))
                self.assertGreater(actual.diagnostics['rack']['bands'][1]['input']['rms'], 0)

    def test_factory_selection_cannot_silently_rebind_a_saved_rack(self):
        data = one_note().to_dict(); project = Project.from_document(data['project'])
        project.set_rack(rack(project.head_recipe)); data['project'] = project.to_document()
        document = TimelineDocument(data); before = document.revision_id
        from zaaggenz_zaag import PRODUCTION_PRESET_IDS
        with self.assertRaisesRegex(ContractError, 'binding'):
            apply_source_preset(document, PRODUCTION_PRESET_IDS[0])
        self.assertEqual(document.revision_id, before)


if __name__ == '__main__': unittest.main()
