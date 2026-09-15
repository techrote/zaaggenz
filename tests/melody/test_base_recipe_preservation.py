from __future__ import annotations
from copy import deepcopy
from pathlib import Path
import sys
import unittest
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'app'))

from zaaggenz_contracts import Contract,ContractError
from zaaggenz_contracts.legacy import envelope
from zaaggenz_gesture import rise_turn_return,compile_gesture_recipe
from zaaggenz_linked import linked_fakeout_return,compile_linked_recipe
from zaaggenz_melody import (MelodyError,make_melodic_recipe,make_phrase_plan,note_event,
                             render_phrase,transform_melodic_recipe)
from zaaggenz_phrase import template_1234_5555,compile_role_recipe
from zaaggenz_project import Project
from zaaggenz_textgesture import compile_text,starter_registry
from zaaggenz_textgesture.compile import make_render_recipe as make_text_recipe
from zaaggenz_timeline import TimelineDocument,default_document
from zaaggenz_vocal.edit import VocalCompilation,make_render_recipe as make_vocal_recipe


def _node(identifier,type_id,input_id,params,automation=()):
    return envelope('DSPNodeSpec',id=identifier,type_id=type_id,inputs=[input_id],channels=1,
                    params=deepcopy(params),state_policy='stateless',phase_policy='source-derived',
                    latency_samples=0,lookahead_samples=0,bypass='identity',automation=[deepcopy(x) for x in automation])


def _phrase(recipe):
    return make_phrase_plan(recipe['tuning']['id'],[
        note_event('probe','0/1','1/2',recipe['tuning']['id'],0,gain_db=-12.,source_id=recipe['source']['id'])
    ],end_beat='1/1',source_id=recipe['source']['id'])


def _synth_recipe(sample_rate=12000,*,with_graph=True,with_sculpt=False):
    retained=Project.from_document(default_document(sample_rate).to_dict()['project']).head_recipe.to_dict()
    d=deepcopy(retained)
    d.update(render_mode='synth',arrangement=None,reversebass=None,phrase=None,phase_policy='source-derived',
             tail={'mode':'preserve','maximum_samples':321},quality='high')
    d['output']=deepcopy(d['output']);d['output'].update(master_gain_db=-3.,clipping='unbounded_float')
    if with_graph:
        lane={'parameter':'gain_db','unit':'dB','interpolation':'linear',
              'points':[{'sample':0,'value':-6.},{'sample':128,'value':-6.}]}
        d['nodes']=[
            _node('a-output','core.gain.v1','z-shaper',{'gain_db':-6.},[lane]),
            _node('z-shaper','core.tanh.v1',d['source']['id'],{'drive_db':0.,'mix':0.})]
        d['output_node']='a-output';d['sculpt']=None
    else:
        d['nodes']=[];d['output_node']=d['source']['id'];d['sculpt']=deepcopy(retained['sculpt']) if with_sculpt else None
    return Contract(d)


def _timeline_from_recipe(recipe,*,second_head=None):
    td=default_document(recipe.to_dict()['time_map']['sample_rate_hz']).to_dict()
    project=Project(recipe)
    if second_head is not None:project.commit(second_head)
    td['project']=project.to_document();td['master_gain_db']=-3.
    return TimelineDocument(td)


def _protected(recipe):
    d=recipe.to_dict() if isinstance(recipe,Contract) else recipe
    return {k:deepcopy(d[k]) for k in ('source','time_map','tuning','nodes','output_node','sculpt','channels','state_policy','tail','quality','random','output')}


class BaseRecipeTransformTests(unittest.TestCase):
    def test_explicit_synth_graph_automation_routing_tail_quality_and_output_policy_survive(self):
        base=_synth_recipe();bd=base.to_dict();compiled=transform_melodic_recipe(base,_phrase(bd))
        self.assertEqual(_protected(compiled),_protected(base))
        self.assertEqual(compiled.to_dict()['phrase'],_phrase(bd).to_dict())
        self.assertEqual(compiled.to_dict()['nodes'][0]['automation'],bd['nodes'][0]['automation'])
        self.assertEqual(compiled.to_dict()['output_node'],'a-output')

        processed=render_phrase(compiled)
        plain=compiled.to_dict();plain['nodes']=[];plain['output_node']=plain['source']['id']
        unprocessed=render_phrase(Contract(plain))
        gain=10**(-6./20.)
        np.testing.assert_allclose(processed.mix,unprocessed.mix*gain,rtol=2e-6,atol=2e-7)
        self.assertEqual(processed.diagnostics['clipped_fraction'],0.)
        self.assertEqual(compiled.to_dict()['output'],bd['output'])

    def test_supported_legacy_sculpt_is_preserved_and_executed_before_master(self):
        base=_synth_recipe(with_graph=False,with_sculpt=True);compiled=transform_melodic_recipe(base,_phrase(base.to_dict()))
        self.assertEqual(compiled.to_dict()['sculpt'],base.to_dict()['sculpt'])
        sculpted=render_phrase(compiled)
        plain=compiled.to_dict();plain['sculpt']=None
        dry=render_phrase(Contract(plain))
        self.assertGreater(np.max(np.abs(sculpted.mix)),0.)
        self.assertFalse(np.array_equal(sculpted.mix,dry.mix))
        self.assertEqual(compiled.to_dict()['output'],base.to_dict()['output'])

    def test_non_synth_explicit_topology_fails_instead_of_being_rebound_or_stripped(self):
        original=Project.from_document(default_document(12000).to_dict()['project']).head_recipe.to_dict()
        d=deepcopy(original);d['sculpt']=None
        d['nodes']=[_node('gain','core.gain.v1',d['source']['id'],{'gain_db':-6.})];d['output_node']='gain'
        base=Contract(d)
        with self.assertRaisesRegex(MelodyError,'ambiguous layer ownership'):
            transform_melodic_recipe(base,_phrase(d))

    def test_ambiguous_or_invalid_synth_topology_fails_before_recipe_publication(self):
        graph=_synth_recipe().to_dict();legacy=Project.from_document(default_document(12000).to_dict()['project']).head_recipe.to_dict()['sculpt']
        graph['sculpt']=legacy
        with self.assertRaisesRegex(MelodyError,'combines legacy SCULPT'):
            transform_melodic_recipe(Contract(graph),_phrase(graph))

        bad=_synth_recipe().to_dict();bad['nodes'].append(_node('orphan','core.identity.v1',bad['source']['id'],{}))
        with self.assertRaisesRegex(ContractError,'disconnected'):
            Contract(bad)

    def test_zero_one_and_maximum_graph_depth_boundaries(self):
        zero=_synth_recipe(with_graph=False);z=transform_melodic_recipe(zero,_phrase(zero.to_dict()))
        self.assertEqual(z.to_dict()['nodes'],[]);self.assertEqual(z.to_dict()['output_node'],z.to_dict()['source']['id'])

        one=zero.to_dict();one['nodes']=[_node('identity','core.identity.v1',one['source']['id'],{})];one['output_node']='identity';one=Contract(one)
        self.assertEqual(transform_melodic_recipe(one,_phrase(one.to_dict())).to_dict()['nodes'],one.to_dict()['nodes'])

        maximum=zero.to_dict();nodes=[];parent=maximum['source']['id']
        for i in range(128):
            identifier=f'n{i:03d}';nodes.append(_node(identifier,'core.identity.v1',parent,{}));parent=identifier
        maximum['nodes']=nodes;maximum['output_node']=parent;maximum=Contract(maximum)
        preserved=transform_melodic_recipe(maximum,_phrase(maximum.to_dict()))
        self.assertEqual(len(preserved.to_dict()['nodes']),128);self.assertEqual(preserved.to_dict()['output_node'],'n127')

    def test_tail_change_is_only_applied_when_explicitly_requested(self):
        base=_synth_recipe();phrase=_phrase(base.to_dict())
        kept=transform_melodic_recipe(base,phrase);changed=transform_melodic_recipe(base,phrase,tail_mode='truncate')
        self.assertEqual(kept.to_dict()['tail'],{'mode':'preserve','maximum_samples':321})
        self.assertEqual(changed.to_dict()['tail'],{'mode':'truncate','maximum_samples':321})
        a=kept.to_dict();b=changed.to_dict();a['tail']=b['tail'];self.assertEqual(a,b)

    def test_default_full_project_projection_matches_pre_repair_fresh_melodic_recipe(self):
        document=default_document(12000);source=Project.from_document(document.to_dict()['project']).head_recipe.to_dict()
        bundle=compile_gesture_recipe(rise_turn_return(),document)
        expected=make_melodic_recipe(source['source']['params'],source['time_map'],source['tuning'],bundle.compilation.phrase,
                                     quality='standard',tail_mode='truncate',master_gain_db=document.to_dict()['master_gain_db'])
        self.assertEqual(bundle.recipe.to_dict(),expected.to_dict())


class CompilerSurfacePreservationTests(unittest.TestCase):
    def setUp(self):
        self.base_recipe=_synth_recipe();self.base=_timeline_from_recipe(self.base_recipe);self.expected=_protected(self.base_recipe)

    def assertPreserved(self,recipe):
        self.assertEqual(_protected(recipe),self.expected)
        self.assertEqual(recipe.to_dict()['phase_policy'],'source-derived')
        self.assertIsNotNone(recipe.to_dict()['phrase'])

    def test_gesture_phrase_linked_text_and_vocal_compilers_share_one_preservation_rule(self):
        self.assertPreserved(compile_gesture_recipe(rise_turn_return(),self.base).recipe)
        self.assertPreserved(compile_role_recipe(template_1234_5555(content_seed='7',placement_seed='11'),self.base).recipe)
        self.assertPreserved(compile_linked_recipe(linked_fakeout_return(),'both-linked',self.base).recipe)

        text=compile_text('bu @return',starter_registry(),'local-soft',base=self.base)
        self.assertPreserved(make_text_recipe(text))

        vocal=VocalCompilation(_phrase(self.base_recipe.to_dict()),self.base,{}, {},'0'*64)
        self.assertPreserved(make_vocal_recipe(vocal))

    def test_actual_immutable_project_head_is_transformed_not_an_earlier_revision(self):
        first=_synth_recipe(with_graph=False)
        latest=_synth_recipe();latest_data=latest.to_dict();latest_data['nodes'][0]['params']['gain_db']=-9.;latest=Contract(latest_data)
        timeline=_timeline_from_recipe(first,second_head=latest)
        bundle=compile_gesture_recipe(rise_turn_return(),timeline)
        self.assertEqual(bundle.recipe.to_dict()['nodes'],latest.to_dict()['nodes'])
        self.assertNotEqual(bundle.recipe.to_dict()['nodes'],first.to_dict()['nodes'])
        self.assertEqual(bundle.source_project,timeline.to_dict()['project'])


if __name__=='__main__':unittest.main(verbosity=2)
