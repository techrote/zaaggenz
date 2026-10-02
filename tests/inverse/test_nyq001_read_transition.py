"""The NYQ-001 source-read repair gets one exact, fail-closed evidence row."""
from zaaggenz_contracts import digest
import test_nyq001_transition as previous

SUCCESSOR = 'f562faec6d279b090ff0da28b7c73fc24082d875e2fa3d9c87cc50d95072bcd3'


class NYQ001ReadAdmissionTransitionTests(previous.NYQ001TransitionTests):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.transition = next(r for r in cls.validations
                              if r['to_implementation_sha256'] == SUCCESSOR)

    def successor_fixture(self):
        # Reuse the explicitly synthetic comparator fixture, not render evidence.
        actual = super().successor_fixture()
        actual['implementation_sha256'] = SUCCESSOR
        previous.rehash(actual)
        return actual

    def test_exact_identity_and_explicit_changed_paths(self):
        rows = [r for r in self.implementations
                if r['to_implementation_sha256'] == SUCCESSOR]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['from_implementation_sha256'], previous.PREDECESSOR)
        self.assertEqual(rows[0]['issue'], 250)
        self.assertEqual(rows[0]['changed_paths'], ['zaaggenz_contracts/nyquismic_clock.py'])
        self.assertFalse(self.compare(self.successor_fixture()))

    def test_preexisting_registry_rows_are_unchanged(self):
        super().test_preexisting_registry_rows_are_unchanged()
        self.assertEqual(digest(self.implementations[:31]),
                         'da2ca8d0e1d4dcd701d454b8ad5c9c3161ce5f05ca91d8e8fc4017c48bb7214e')
        self.assertEqual(digest(self.validations[:6]),
                         '16ff06fee56318399c69f3c7ddae2706916d05ee170096ef79a5b5a8359dd488')
        predecessor = next(r for r in self.validations
                           if r['to_implementation_sha256'] == previous.SUCCESSOR)
        self.assertEqual(self.transition['changes'], predecessor['changes'])

    # Inherited adversarial tests reject unknown identities, altered numerical
    # scores/recipes, tampered report hashes and unauthorized validation states.
    # Do not assert current engine_identity(): this historical row must survive
    # later independently reviewed implementations rather than freeze the engine.
