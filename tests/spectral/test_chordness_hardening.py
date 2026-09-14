from __future__ import annotations
import unittest
import numpy as np
from scipy import signal
from zaaggenz_components import analyse_components
from zaaggenz_spectral import ChordnessError,ChordnessRequest,CombTemplate,apply_chordness

SR=12000

def tone(f,duration=1.,amp=.45):
    t=np.arange(round(SR*duration),dtype=np.float64)/SR
    return (amp*np.cos(2*np.pi*f*t+.2)).astype(np.float32)

def request(template,**kwargs):
    values=dict(mode='retune',selected_template_ids=(template.id,),min_confidence=.4,
                max_assignment_cents=500.,max_displacement_cents=300.)
    values.update(kwargs);return ChordnessRequest((template,),**values)

class ChordnessHardeningTests(unittest.TestCase):
    def test_zero_amount_active_mode_still_uses_exact_identity_path(self):
        x=tone(445.);analysis=analyse_components(x,SR);template=CombTemplate('a',(440.,))
        result=apply_chordness(analysis,request(template,retune_amount=0.))
        self.assertTrue(result.diagnostics['identity_path']);self.assertEqual(result.diagnostics['changed_frames'],0)
        self.assertTrue(np.array_equal(result.audio,x))

    def test_ambiguous_crossing_tracks_remain_explicit_preserves(self):
        n=round(SR*1.4);t=np.arange(n)/SR
        x=(.35*signal.chirp(t,280,t[-1],620)+.35*signal.chirp(t,620,t[-1],280,phi=80)).astype(np.float32)
        analysis=analyse_components(x,SR);ambiguous={tr['id'] for tr in analysis.bundle.to_dict()['tracks'] if tr['continuity']!='continuous'}
        self.assertTrue(ambiguous)
        result=apply_chordness(analysis,request(CombTemplate('wide',(300.,400.,500.,600.)),max_assignment_cents=700.,max_displacement_cents=400.))
        rows=[d for d in result.decisions if d.track_id in ambiguous]
        self.assertTrue(rows);self.assertTrue(all(d.decision=='preserve' for d in rows))
        self.assertTrue(all(d.reason in ('ambiguous-or-reanchored-track','component-policy-preserve') for d in rows))

    def test_assignment_confidence_is_bounded_and_visible(self):
        result=apply_chordness(analyse_components(tone(445.),SR),request(CombTemplate('a',(440.,))))
        assigned=[d for d in result.decisions if d.template_id is not None]
        self.assertTrue(assigned);self.assertTrue(all(d.assignment_confidence is not None and 0<=d.assignment_confidence<=1 for d in assigned))
        self.assertIn('assignment_confidence',assigned[0].to_dict())

    def test_comb_source_metadata_must_be_bounded_json(self):
        with self.assertRaises(ChordnessError):CombTemplate('bad',(440.,),source={'x':object()})
        with self.assertRaises(ChordnessError):CombTemplate('bad',(440.,),source={'x':float('nan')})
        with self.assertRaises(ChordnessError):CombTemplate('bad',(440.,),source={'x':'a'*9000})

if __name__=='__main__':unittest.main(verbosity=2)
