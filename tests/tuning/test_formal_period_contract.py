from copy import deepcopy
import unittest

from jsonschema import Draft202012Validator

from zaaggenz_contracts import ContractError, schema, validate
from zaaggenz_contracts.examples import examples
from zaaggenz_tuning import KeyboardMap, TuningError, load_scala_tuning, parse_kbm, tuning_from_spec, tuning_to_spec
from zaaggenz_tuning.scala import ScalaKBM


TRITAVE_SCL = 'tritave\n3\n3/2\n2/1\n3/1\n'


def formal_spec(value, entries=(0,), reference_key=60, reference_degree=0):
    spec = deepcopy(examples()['TuningSpec'])
    spec['reference_degree'] = reference_degree
    spec['keyboard'].update(
        middle_key=60,
        reference_key=reference_key,
        formal_period_degrees=value,
        entries=list(entries),
    )
    return spec


def kbm_text(formal, entries=('0',), reference_key=60):
    lines = [str(len(entries)), '0', '127', '60', str(reference_key), '48', str(formal), *entries]
    return '\n'.join(lines) + '\n'


def zero_size_kbm_text(formal):
    return f'0\n0\n127\n60\n60\n48\n{formal}\n'


class FormalPeriodConsumerTests(unittest.TestCase):
    def setUp(self):
        self.validator = Draft202012Validator(schema('TuningSpec'))

    def _accepts_shared(self, spec):
        try:
            validate(spec, 'TuningSpec')
            return True
        except ContractError:
            return False

    def _accepts_tuning(self, spec):
        try:
            tuning_from_spec(spec)
            return True
        except (ContractError, TuningError):
            return False

    def _accepts_keyboard(self, value):
        try:
            KeyboardMap(0, 127, 60, 60, value, (0,))
            return True
        except TuningError:
            return False

    def test_schema_shared_and_keyboard_consumers_agree(self):
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
        for value, expected in cases:
            with self.subTest(value=value, expected=expected):
                spec = formal_spec(value)
                observed = (
                    self.validator.is_valid(spec),
                    self._accepts_shared(spec),
                    self._accepts_tuning(spec),
                    self._accepts_keyboard(value),
                )
                self.assertEqual(observed, (expected,) * 4)

    def test_schema_valid_integral_float_stays_executable(self):
        tuning = tuning_from_spec(formal_spec(1.0))
        self.assertEqual(tuning.keyboard_degree(61), 1)
        self.assertGreater(tuning.keyboard_frequency(61), 0)

    def test_negative_period_wraps_explicitly_end_to_end(self):
        spec = formal_spec(-3, entries=(0, 1, 2))
        tuning = tuning_from_spec(spec)
        self.assertEqual(tuning.keyboard_degree(63), -3)
        self.assertEqual(tuning.keyboard_degree(57), 3)
        self.assertAlmostEqual(tuning.keyboard_frequency(63), 16.0, 12)
        self.assertAlmostEqual(tuning.keyboard_frequency(57), 144.0, 12)
        self.assertEqual(tuning_to_spec(tuning), spec)

    def test_negative_period_reference_mapping_roundtrips(self):
        spec = formal_spec(-3, entries=(0, 1, 2), reference_key=63, reference_degree=-3)
        tuning = tuning_from_spec(spec)
        self.assertEqual(tuning.reference_degree, -3)
        self.assertEqual(tuning_to_spec(tuning), spec)

    def test_existing_non_octave_sparse_contract_roundtrips(self):
        spec = examples()['TuningSpec']
        tuning = tuning_from_spec(spec)
        self.assertEqual(tuning_to_spec(tuning), spec)
        self.assertEqual(tuning.period_ratio, 3.0)
        self.assertIsNone(tuning.keyboard_degree(61))


class ScalaFormalPeriodTests(unittest.TestCase):
    def test_nonzero_kbm_boundary_domain_matches_contract(self):
        for formal in (-256, -1, 1, 256):
            with self.subTest(formal=formal):
                parsed = parse_kbm(kbm_text(formal))
                self.assertEqual(parsed.formal_period_degrees, formal)
                self.assertEqual(parsed.to_keyboard_map().formal_period_degrees, formal)
        for formal in (-257, 0, 257):
            with self.subTest(formal=formal), self.assertRaises(TuningError):
                parse_kbm(kbm_text(formal))

    def test_direct_scala_kbm_rejects_hidden_later_failures(self):
        for formal in (0, -257, 257, 12.0, True):
            with self.subTest(formal=formal), self.assertRaises(TuningError):
                ScalaKBM(1, 0, 127, 60, 60, 48.0, formal, (0,))

    def test_negative_explicit_kbm_loads_and_roundtrips_to_contract(self):
        text = kbm_text(-3, entries=('0', '1', '2'))
        tuning = load_scala_tuning(TRITAVE_SCL, text, tuning_id='negative-kbm')
        self.assertEqual(tuning.keyboard_degree(63), -3)
        self.assertEqual(tuning.keyboard_degree(57), 3)
        spec = tuning_to_spec(tuning)
        validate(spec, 'TuningSpec')
        self.assertEqual(spec['keyboard']['formal_period_degrees'], -3)

    def test_zero_size_kbm_has_explicit_positive_representation_rule(self):
        parsed = parse_kbm(zero_size_kbm_text(12))
        self.assertEqual(parsed.to_keyboard_map().degree(72), 12)
        for formal in (0, -1, -12, 129, 256):
            with self.subTest(formal=formal), self.assertRaises(TuningError):
                parse_kbm(zero_size_kbm_text(formal))


if __name__ == '__main__':
    unittest.main(verbosity=2)
