from __future__ import annotations
from types import SimpleNamespace
import unittest
from zaaggenz_spectral import (ChordnessError,ChordnessCoefficients,ChordnessRequest,CombTemplate,
                               harmonic_comb,templates_from_voicing_frame)

class ChordnessModelTests(unittest.TestCase):
    def test_explicit_inharmonic_local_comb_serialises_without_tuning_assumption(self):
        comb=CombTemplate('local.glass',(437.2,701.3,1003.7),2,'local inharmonic',{'author':'user'})
        d=comb.to_dict();self.assertEqual(d['teeth_hz'],[437.2,701.3,1003.7]);self.assertEqual(d['tooth_capacity'],2)
        self.assertEqual(d['source']['author'],'user')

    def test_request_exposes_candidates_coefficients_and_manual_selection(self):
        a=CombTemplate('a',(440.,880.));b=CombTemplate('b',(660.,1320.))
        coefficients=ChordnessCoefficients(target_fit=2.,roughness=.7,density_penalty=.04,reassignment_cents=.3,gain_motion_db=.2)
        r=ChordnessRequest((a,b),mode='hybrid',selected_template_ids=('a','b'),max_selected_templates=2,coefficients=coefficients)
        d=r.to_dict();self.assertEqual(d['selected_template_ids'],['a','b']);self.assertEqual(len(d['templates']),2)
        self.assertEqual(d['coefficients']['roughness'],.7);self.assertEqual(d['selection_mode'],'manual')

    def test_active_manual_mode_requires_explicit_selection(self):
        with self.assertRaises(ChordnessError):ChordnessRequest((CombTemplate('a',(440.,)),),mode='retune')

    def test_harmonic_helper_is_explicit_and_bounded(self):
        c=harmonic_comb('root',55.,harmonics=5,max_hz=260.)
        self.assertEqual(c.teeth_hz,(55.,110.,165.,220.));self.assertEqual(c.source['root_hz'],55.)

    def test_voicing_adapter_yields_one_comb_per_fundamental(self):
        frame=SimpleNamespace(sonority_id='local',fundamental_targets_hz=(55.,82.5,137.5))
        templates=templates_from_voicing_frame(frame,harmonics=3,max_hz=500.)
        self.assertEqual([x.id for x in templates],['local.v0','local.v1','local.v2'])
        self.assertEqual(templates[1].teeth_hz,(82.5,165.,247.5))

    def test_invalid_capacity_and_unsorted_teeth_rejected(self):
        with self.assertRaises(ChordnessError):CombTemplate('bad',(440.,430.))
        with self.assertRaises(ChordnessError):CombTemplate('bad',(440.,),0)

if __name__=='__main__':unittest.main(verbosity=2)
