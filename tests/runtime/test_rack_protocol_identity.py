"""MBR-001 saved-rack contracts participate in every workspace release identity."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import zaaggenz_web_release as web_release
from test_web_release_protocol_identity import _copy_release_tree, _append

ROOT = Path(__file__).resolve().parents[2]
RACK_PROTOCOL_PATHS = (
    'zaaggenz_contracts/rack.py',
    'zaaggenz_contracts/rack_schema.py',
    'zaaggenz_project/rack_state.py',
)


class RackProtocolIdentityTests(unittest.TestCase):
    def test_saved_rack_modules_are_explicit_protocol_dependencies(self):
        for workspace, paths in web_release._BACKEND_PATHS.items():
            with self.subTest(workspace=workspace):
                self.assertTrue(set(RACK_PROTOCOL_PATHS) <= set(paths))
        self.assertEqual(web_release.protocol_dependency_errors(ROOT, unified_runtime=True), ())

    def test_each_rack_protocol_change_invalidates_all_workspace_releases(self):
        for relative_path in RACK_PROTOCOL_PATHS:
            with self.subTest(path=relative_path), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                _copy_release_tree(root, unified_runtime=True)
                before = web_release.build_web_releases(root, unified_runtime=True)
                _append(root / relative_path, '\n# changed saved rack contract semantics\n')
                after = web_release.build_web_releases(root, unified_runtime=True)
                self.assertEqual(set(before), set(after))
                for workspace in before:
                    self.assertNotEqual(before[workspace].release_id, after[workspace].release_id)

    def test_omitting_a_rack_module_still_fails_closed(self):
        for relative_path in RACK_PROTOCOL_PATHS:
            paths = {
                name: tuple(path for path in values if path != relative_path)
                for name, values in web_release._BACKEND_PATHS.items()
            }
            with self.subTest(path=relative_path), patch.object(web_release, '_BACKEND_PATHS', paths):
                errors = web_release.protocol_dependency_errors(ROOT, unified_runtime=True)
                self.assertTrue(any(relative_path in error for error in errors), errors)
                with self.assertRaisesRegex(RuntimeError, 'protocol dependency audit failed'):
                    web_release.build_web_releases(ROOT, unified_runtime=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
