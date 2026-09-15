import copy
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from zaaggenz_contracts import digest
from tools.inverse_foundation_report import (build_report, calibration_reference, compare_reports,
                                            read_json, write_json, validate_implementation_transitions)


class EvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch('tools.inverse_foundation_report.NAMES', ('holdout-step',)):
            cls.report, cls.full, cls.telemetry = build_report(include_legacy=False)
        cls.reference = calibration_reference(cls.report)

    def rehash(self, document):
        document['evidence_sha256'] = digest({k:v for k,v in document.items() if k != 'evidence_sha256'})
        return document

    def transition(self, old, new):
        return {'kind':'InverseFoundationImplementationTransitions','version':'1.0.0','transitions':[{
            'from_implementation_sha256':old,'to_implementation_sha256':new,'issue':137,'stable_id':'ZG-016',
            'changed_paths':['zaaggenz_dsp/graph.py'],'reason':'reviewed test transition'}]}

    def test_reference_preserves_identity_bounds_seeds_losses_and_holdouts(self):
        self.assertEqual(compare_reports(self.reference, self.reference), [])
        fixture = self.reference['fixtures'][0]
        self.assertEqual(fixture['seed'], '24')
        self.assertEqual(len(fixture['fixture_id']), 64)
        self.assertEqual(fixture['budget']['consumed_evaluations'], 3)
        self.assertEqual(fixture['domain']['axes'][0]['lower'], -6.)
        self.assertEqual(fixture['domain']['axes'][0]['upper'], 6.)
        self.assertEqual(len(fixture['candidates'][0]['fit']['losses']), 8)
        self.assertEqual(sum(c['overfit_warning'] for c in fixture['candidates']), 2)
        self.assertEqual(len(self.full[0]['audits']), 3)
        self.assertNotIn('total_seconds', self.report)
        self.assertGreater(self.telemetry['total_seconds'], 0.)

    def test_comparison_catches_modified_numeric_results_even_with_rehashed_envelope(self):
        changed = copy.deepcopy(self.reference)
        changed['fixtures'][0]['candidates'][0]['holdout']['score'] = 0.
        self.rehash(changed)
        differences = compare_reports(changed, self.reference)
        self.assertTrue(any('holdout/score' in d for d in differences))

    def test_comparison_catches_unrecorded_identity_tampering(self):
        changed = copy.deepcopy(self.reference)
        changed['fixtures'][0]['fixture_id'] = '0'*64
        self.assertIn('actual: evidence identity mismatch', compare_reports(changed, self.reference))

    def test_implementation_identity_change_fails_without_reviewed_transition(self):
        changed=copy.deepcopy(self.reference);old=changed['implementation_sha256'];new='1'*64
        changed['implementation_sha256']=new;self.rehash(changed)
        differences=compare_reports(changed,self.reference)
        self.assertEqual(differences,[f'/implementation_sha256: unreviewed transition {old}->{new}'])

    def test_exact_reviewed_implementation_transition_preserves_old_calibration(self):
        changed=copy.deepcopy(self.reference);old=changed['implementation_sha256'];new='2'*64
        changed['implementation_sha256']=new;self.rehash(changed)
        transitions=validate_implementation_transitions(self.transition(old,new))
        self.assertEqual(compare_reports(changed,self.reference,implementation_transitions=transitions),[])
        self.assertNotEqual(changed['evidence_sha256'],self.reference['evidence_sha256'])
        self.assertEqual(self.reference['implementation_sha256'],old)

    def test_transition_does_not_authorise_numeric_or_semantic_drift(self):
        changed=copy.deepcopy(self.reference);old=changed['implementation_sha256'];new='3'*64
        changed['implementation_sha256']=new
        changed['fixtures'][0]['candidates'][0]['holdout']['score']=0.
        self.rehash(changed)
        transitions=validate_implementation_transitions(self.transition(old,new))
        differences=compare_reports(changed,self.reference,implementation_transitions=transitions)
        self.assertTrue(any('holdout/score' in d for d in differences))

    def test_transition_direction_and_shape_are_strict(self):
        old=self.reference['implementation_sha256'];new='4'*64
        changed=copy.deepcopy(self.reference);changed['implementation_sha256']=new;self.rehash(changed)
        wrong=validate_implementation_transitions(self.transition(new,old))
        self.assertTrue(any('unreviewed transition' in d for d in compare_reports(changed,self.reference,implementation_transitions=wrong)))
        invalid=self.transition(old,new);invalid['transitions'][0]['changed_paths']=['zaaggenz_dsp/**']
        with self.assertRaises(ValueError):validate_implementation_transitions(invalid)

    def test_gzip_evidence_is_deterministic_and_roundtrips(self):
        with tempfile.TemporaryDirectory() as directory:
            a, b = (Path(directory)/n for n in ('a.json.gz','b.json.gz'))
            write_json(a,self.reference,compact=True); write_json(b,self.reference,compact=True)
            self.assertEqual(a.read_bytes(),b.read_bytes())
            self.assertEqual(read_json(a),self.reference)


if __name__ == '__main__': unittest.main()
