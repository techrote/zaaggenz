from __future__ import annotations

from copy import deepcopy
import unittest

from jsonschema import Draft202012Validator

from zaaggenz_contracts import ContractError, digest, schema, validate
from zaaggenz_contracts.examples import examples
from zaaggenz_contracts.model import SAFE_INT
from zaaggenz_contracts.validation import _trial


class TrialExcerptBoundsTests(unittest.TestCase):
    def setUp(self):
        self.trial = examples()['TrialSpec']

    def _schema_accepts(self, trial):
        return Draft202012Validator(schema('TrialSpec')).is_valid(trial)

    def _semantic_accepts(self, trial):
        try:
            _trial(trial)
        except ContractError:
            return False
        return True

    def _set_excerpt(self, start, end, *, frame_count=None):
        trial = deepcopy(self.trial)
        stimulus = trial['stimuli'][0]
        stimulus['start_sample'] = start
        stimulus['end_sample'] = end
        if frame_count is not None:
            stimulus['asset']['frame_count'] = frame_count
        return trial

    def test_negative_start_is_rejected_by_schema_semantics_and_public_validation(self):
        trial = self._set_excerpt(-1, 1)
        self.assertFalse(self._schema_accepts(trial))
        self.assertFalse(self._semantic_accepts(trial))
        with self.assertRaises(ContractError):
            validate(trial, 'TrialSpec')

    def test_negative_end_is_rejected_by_schema_semantics_and_public_validation(self):
        trial = self._set_excerpt(0, -1)
        self.assertFalse(self._schema_accepts(trial))
        self.assertFalse(self._semantic_accepts(trial))
        with self.assertRaises(ContractError):
            validate(trial, 'TrialSpec')

    def test_exact_full_asset_excerpt_is_valid(self):
        frame_count = self.trial['stimuli'][0]['asset']['frame_count']
        trial = self._set_excerpt(0, frame_count)
        self.assertTrue(self._schema_accepts(trial))
        self.assertTrue(self._semantic_accepts(trial))
        validate(trial, 'TrialSpec')

    def test_normal_interior_excerpt_is_valid(self):
        frame_count = self.trial['stimuli'][0]['asset']['frame_count']
        trial = self._set_excerpt(1, frame_count - 1)
        self.assertTrue(self._schema_accepts(trial))
        self.assertTrue(self._semantic_accepts(trial))
        validate(trial, 'TrialSpec')

    def test_zero_length_and_reversed_excerpts_fail_semantics(self):
        for start, end in ((10, 10), (11, 10)):
            with self.subTest(start=start, end=end):
                trial = self._set_excerpt(start, end)
                # Shape alone cannot express this cross-field ordering rule.
                self.assertTrue(self._schema_accepts(trial))
                self.assertFalse(self._semantic_accepts(trial))
                with self.assertRaises(ContractError):
                    validate(trial, 'TrialSpec')

    def test_end_beyond_asset_and_tampered_extent_fail_semantics(self):
        frame_count = self.trial['stimuli'][0]['asset']['frame_count']
        cases = (
            self._set_excerpt(0, frame_count + 1),
            self._set_excerpt(0, frame_count, frame_count=frame_count - 1),
        )
        for trial in cases:
            with self.subTest(trial=trial['stimuli'][0]):
                self.assertTrue(self._schema_accepts(trial))
                self.assertFalse(self._semantic_accepts(trial))
                with self.assertRaises(ContractError):
                    validate(trial, 'TrialSpec')

    def test_safe_integer_endpoint_boundary_is_valid(self):
        trial = self._set_excerpt(SAFE_INT - 1, SAFE_INT, frame_count=SAFE_INT)
        # Both stimuli contain independent asset envelopes; keep the untouched
        # second stimulus valid while exercising the maximum safe endpoint.
        self.assertTrue(self._schema_accepts(trial))
        self.assertTrue(self._semantic_accepts(trial))
        validate(trial, 'TrialSpec')

    def test_valid_v1_identity_is_unchanged_by_validation(self):
        before = digest(self.trial)
        validate(self.trial, 'TrialSpec')
        self.assertEqual(digest(self.trial), before)
        self.assertEqual(self.trial['version'], '1.0.0')


if __name__ == '__main__':
    unittest.main(verbosity=2)
