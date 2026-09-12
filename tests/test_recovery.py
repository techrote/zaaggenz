from pathlib import Path
import importlib.util
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = ROOT / 'baseline/recovered_source'
spec = importlib.util.spec_from_file_location('recovery', PAYLOAD / 'materialize_v2.py')
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.parts = self.root / 'parts'
        shutil.copytree(PAYLOAD, self.parts)
        self.dest = self.root / 'output'

    def test_exact_payload_and_idempotence(self):
        self.assertEqual(recovery.materialize(self.parts, self.dest), (34, recovery.EXPECTED_SHA256))
        self.assertEqual(len([p for p in (self.dest / 'app').rglob('*') if p.is_file()]), 34)
        self.assertIn('1.2.1-earth-ui', (self.dest / 'app/webapp.py').read_text())
        self.assertEqual(recovery.materialize(self.parts, self.dest)[0], 34)

    def test_corruption_is_not_silently_repaired(self):
        p = self.parts / (recovery.PREFIX + '14')
        text = p.read_text(); p.write_text(('A' if text[0] != 'A' else 'B') + text[1:])
        with self.assertRaisesRegex(RuntimeError, 'SHA-256 mismatch'):
            recovery.materialize(self.parts, self.dest)
        self.assertFalse(self.dest.exists())

    def test_extra_suffix_rejected(self):
        p = self.parts / (recovery.PREFIX + '14')
        p.write_text(p.read_text() + 'AAAA')
        with self.assertRaisesRegex(RuntimeError, 'expected 7000'):
            recovery.materialize(self.parts, self.dest)
        self.assertFalse(self.dest.exists())

    def test_truncated_part_rejected(self):
        p = self.parts / (recovery.PREFIX + '16')
        p.write_text(p.read_text()[:-4])
        with self.assertRaises(RuntimeError):
            recovery.materialize(self.parts, self.dest)

    def test_missing_part_rejected(self):
        (self.parts / (recovery.PREFIX + '00')).unlink()
        with self.assertRaises(RuntimeError):
            recovery.materialize(self.parts, self.dest)

    def test_output_conflict_fails_before_other_writes(self):
        p = self.dest / 'app/webapp.py'; p.parent.mkdir(parents=True); p.write_text('local edit')
        with self.assertRaises(RuntimeError):
            recovery.materialize(self.parts, self.dest)
        self.assertEqual(list((self.dest / 'app').iterdir()), [p])
        self.assertEqual(p.read_text(), 'local edit')
        recovery.materialize(self.parts, self.dest, replace=True)
        self.assertIn('1.2.1-earth-ui', p.read_text())

    def test_output_symlink_rejected_even_with_replace(self):
        actual = self.root / 'actual'; actual.mkdir()
        try:
            self.dest.symlink_to(actual, target_is_directory=True)
        except OSError:
            self.skipTest('symlink creation unavailable')
        with self.assertRaisesRegex(RuntimeError, 'symlink'):
            recovery.materialize(self.parts, self.dest, replace=True)
        self.assertEqual(list(actual.iterdir()), [])

    def test_file_ancestor_rejected_before_writes(self):
        p = self.dest / 'app/uptempo_harmony'; p.parent.mkdir(parents=True); p.write_text('keep')
        with self.assertRaisesRegex(RuntimeError, 'ancestor'):
            recovery.materialize(self.parts, self.dest)
        self.assertEqual(list(p.parent.iterdir()), [p])


if __name__ == '__main__':
    unittest.main()
