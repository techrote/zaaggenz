import unittest

from zaaggenz_contracts import ContractError, validate
from zaaggenz_contracts.examples import examples


class HardeningTests(unittest.TestCase):
    def test_reanchored_partial_requires_preserve(self):
        d = examples()['PartialTrackBundle']
        d['tracks'][0]['continuity'] = 'reanchored'
        d['tracks'][0]['frames'][0]['action'] = 'transform'
        with self.assertRaises(ContractError):
            validate(d)

    def test_duplicate_trial_order_is_rejected(self):
        d = examples()['TrialSpec']
        d['presentation_order'] = ['a', 'b', 'b']
        with self.assertRaises(ContractError):
            validate(d)


if __name__ == '__main__':
    unittest.main(verbosity=2)
