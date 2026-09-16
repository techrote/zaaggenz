from __future__ import annotations
import json
from pathlib import Path
import re
import unittest

from tools.inverse_foundation_report import validate_implementation_transitions

ROOT=Path(__file__).resolve().parents[2]
SHA256_RE=re.compile(r'^[0-9a-f]{64}$')


def identity_diagnostic(value):
    if not isinstance(value,str):
        return repr(value)
    return f'{value!r} length={len(value)} codepoints={[hex(ord(c)) for c in value]}'


class CheckedTransitionRegistryTests(unittest.TestCase):
    def test_checked_in_registry_has_exact_distinct_sha256_identities(self):
        document=json.loads((ROOT/'examples'/'zg024a_implementation_transitions.json').read_text(encoding='utf-8'))
        for i,row in enumerate(document['transitions']):
            old=row.get('from_implementation_sha256');new=row.get('to_implementation_sha256')
            self.assertIsInstance(old,str,f'transition {i} old identity is not text')
            self.assertIsInstance(new,str,f'transition {i} new identity is not text')
            self.assertRegex(old,SHA256_RE,f'transition {i} old identity {identity_diagnostic(old)}')
            self.assertRegex(new,SHA256_RE,f'transition {i} new identity {identity_diagnostic(new)}')
            self.assertNotEqual(old,new,f'transition {i} identities are equal')
        self.assertEqual(validate_implementation_transitions(document),document['transitions'])


if __name__=='__main__':
    unittest.main(verbosity=2)
