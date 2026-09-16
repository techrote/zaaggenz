from copy import deepcopy
import unittest

from jsonschema import Draft202012Validator

from zaaggenz_contracts import ContractError, schema, validate
from zaaggenz_contracts.examples import examples


def formal_spec(value):
    spec = deepcopy(examples()['TuningSpec'])
    spec['reference_degree'] = 0
    spec['keyboard'].update(
        middle_key=60,
        reference_key=60,
        formal_period_degrees=value,
        entries=[0],
    )
    return spec


class FormalPeriodContractTests(unittest.TestCase):
    def setUp(self):
        self.validator = Draft202012Validator(schema('TuningSpec'))

    def test_schema_and_shared_validation_agree_at_boundaries(self):
        cases = [
            (-257, False),
            (-256, True),
            (-1, True),
            (0, False),
            (1, True),
            (256, True),
            (257, False),
            (-1.0, True),
            (0.0, False),
            (1.0, True),
            (256.5, False),
            (True, False),
        ]
        for value, accepted in cases:
            with self.subTest(value=value, accepted=accepted):
                spec = formal_spec(value)
                self.assertEqual(self.validator.is_valid(spec), accepted)
                if accepted:
                    validate(spec, 'TuningSpec')
                else:
                    with self.assertRaises(ContractError):
                        validate(spec, 'TuningSpec')

    def test_negative_period_reference_mapping_is_explicit(self):
        spec = formal_spec(-3)
        spec['keyboard'].update(reference_key=63, entries=[0, 1, 2])
        spec['reference_degree'] = -3
        validate(spec, 'TuningSpec')

    def test_negative_period_unmapped_reference_still_fails(self):
        spec = formal_spec(-3)
        spec['keyboard'].update(reference_key=61, entries=[0, None, 2])
        with self.assertRaises(ContractError):
            validate(spec, 'TuningSpec')

    def test_existing_non_octave_sparse_example_remains_valid(self):
        spec = examples()['TuningSpec']
        self.assertEqual(spec['period_ratio'], 3.0)
        self.assertIn(None, spec['keyboard']['entries'])
        validate(spec, 'TuningSpec')


if __name__ == '__main__':
    unittest.main(verbosity=2)
