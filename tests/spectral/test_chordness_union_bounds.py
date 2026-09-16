from __future__ import annotations
import unittest
from unittest.mock import patch

from zaaggenz_spectral import ChordnessError,ChordnessRequest,CombTemplate
from zaaggenz_spectral.chordness_descriptors import (
    MAX_SELECTED_UNION_TEETH,combined_usable_teeth,select_templates,usable_teeth,
)

SR=48000
BUNDLE={'asset':{'sample_rate_hz':SR}}


def comb(name,start,count):
    return CombTemplate(name,tuple(float(x) for x in range(start,start+count)))


def fake_evaluation(scores):
    def evaluate(bundle,template,*,tolerance_cents=35.):
        teeth=usable_teeth(template,bundle['asset']['sample_rate_hz'])
        return {'template_id':template.id,'usable_teeth_hz':list(teeth),
                'metrics':{'target_comb_fit':{'value':scores.get(template.id,1.)},
                           'target_comb_density':{'value':float(len(teeth))}}}
    return evaluate


class ChordnessUnionBudgetTests(unittest.TestCase):
    def test_manual_exact_128_unique_teeth_is_admitted(self):
        a=comb('a',100,64);b=comb('b',164,64)
        request=ChordnessRequest((a,b),mode='retune',selected_template_ids=('a','b'),max_selected_templates=2)
        with patch('zaaggenz_spectral.chordness_descriptors.evaluate_template',side_effect=fake_evaluation({})):
            selected,evaluations=select_templates(BUNDLE,request)
        self.assertEqual(tuple(x.id for x in selected),('a','b'))
        self.assertEqual(len(combined_usable_teeth(selected,SR)),MAX_SELECTED_UNION_TEETH)
        self.assertTrue(all(x['selection_budget']['selected'] for x in evaluations))
        self.assertTrue(all(x['selection_budget']['selected_union_teeth']==MAX_SELECTED_UNION_TEETH for x in evaluations))

    def test_manual_129_unique_teeth_fails_before_descriptor_or_transform_work(self):
        a=comb('a',100,128);b=CombTemplate('b',(228.,))
        request=ChordnessRequest((a,b),mode='retune',selected_template_ids=('a','b'),max_selected_templates=2)
        with patch('zaaggenz_spectral.chordness_descriptors.evaluate_template') as evaluate:
            with self.assertRaisesRegex(ChordnessError,r'129 unique teeth.*maximum is 128'):
                select_templates(BUNDLE,request)
            evaluate.assert_not_called()

    def test_overlapping_teeth_deduplicate_before_budgeting(self):
        a=comb('a',100,100);b=comb('b',150,78)
        request=ChordnessRequest((a,b),mode='retune',selected_template_ids=('a','b'),max_selected_templates=2)
        with patch('zaaggenz_spectral.chordness_descriptors.evaluate_template',side_effect=fake_evaluation({})):
            selected,_=select_templates(BUNDLE,request)
        teeth=combined_usable_teeth(selected,SR)
        self.assertEqual(len(teeth),128)
        self.assertEqual(teeth[0],100.);self.assertEqual(teeth[-1],227.)

    def test_nyquist_filtering_precedes_union_cardinality(self):
        a=comb('a',100,128)
        b=CombTemplate('b',(227.,24000.,30000.))
        request=ChordnessRequest((a,b),mode='retune',selected_template_ids=('a','b'),max_selected_templates=2)
        with patch('zaaggenz_spectral.chordness_descriptors.evaluate_template',side_effect=fake_evaluation({})):
            selected,_=select_templates(BUNDLE,request)
        teeth=combined_usable_teeth(selected,SR)
        self.assertEqual(len(teeth),128)
        self.assertNotIn(24000.,teeth);self.assertNotIn(30000.,teeth)

    def test_descriptor_selection_skips_whole_over_budget_comb_and_continues(self):
        a=comb('a',100,80);b=comb('b',180,80);c=comb('c',120,60)
        request=ChordnessRequest((a,b,c),mode='retune',selection_mode='descriptor',max_selected_templates=2)
        scores={'a':3.,'b':2.,'c':1.}
        with patch('zaaggenz_spectral.chordness_descriptors.evaluate_template',side_effect=fake_evaluation(scores)):
            selected,evaluations=select_templates(BUNDLE,request)
        self.assertEqual(tuple(x.id for x in selected),('a','c'))
        rows={x['template_id']:x for x in evaluations}
        self.assertEqual(rows['b']['selection_budget']['reason'],'combined_target_teeth_limit')
        self.assertEqual(rows['b']['selection_budget']['union_teeth_if_selected'],160)
        self.assertEqual(len(rows['b']['usable_teeth_hz']),80)
        self.assertEqual(len(combined_usable_teeth(selected,SR)),80)

    def test_descriptor_selection_can_fill_to_exact_union_limit(self):
        a=comb('a',100,64);b=comb('b',164,64);c=CombTemplate('c',(228.,))
        request=ChordnessRequest((a,b,c),mode='retune',selection_mode='descriptor',max_selected_templates=3)
        scores={'a':3.,'b':2.,'c':1.}
        with patch('zaaggenz_spectral.chordness_descriptors.evaluate_template',side_effect=fake_evaluation(scores)):
            selected,evaluations=select_templates(BUNDLE,request)
        self.assertEqual(tuple(x.id for x in selected),('a','b'))
        self.assertEqual(len(combined_usable_teeth(selected,SR)),128)
        rows={x['template_id']:x for x in evaluations}
        self.assertEqual(rows['c']['selection_budget']['reason'],'combined_target_teeth_limit')
        self.assertEqual(rows['c']['selection_budget']['union_teeth_if_selected'],129)


if __name__=='__main__':unittest.main(verbosity=2)
