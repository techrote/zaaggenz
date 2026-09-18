from __future__ import annotations

import shutil
from pathlib import Path
import tempfile
import unittest

import zaaggenz_web_release as web_release
from zaaggenz_web_release import build_web_releases, protocol_dependency_errors

ROOT = Path(__file__).resolve().parents[2]

_LEGACY_BACKEND_PATHS = {
    "timeline": ("zaaggenz_timeline/server.py",),
    "listening": ("zaaggenz_timeline/server.py", "zaaggenz_listening/server.py"),
    "inspector": ("zaaggenz_timeline/server.py", "zaaggenz_inspector/server.py"),
    "vocal": ("zaaggenz_timeline/server.py", "zaaggenz_vocal/server.py"),
}


def _copy_release_tree(destination: Path, *, unified_runtime: bool = False) -> None:
    needed = {web_release._HELPER_PATH}
    for paths in web_release._FRONTEND_PATHS.values():
        needed.update(paths)
    for paths in web_release._BACKEND_PATHS.values():
        needed.update(paths)
    if unified_runtime:
        needed.update(web_release._UNIFIED_RUNTIME_PATHS)
    for rel in sorted(needed):
        target = destination / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, target)


def _append(path: Path, text: str) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(text)


class WebProtocolIdentityTests(unittest.TestCase):
    def _case(self, relative_path: str, expected_changed: set[str]) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _copy_release_tree(root)
            before = build_web_releases(root)
            _append(root / relative_path, "\n# protocol-identity-test\n")
            after = build_web_releases(root)
            changed = {
                name for name in before
                if before[name].release_id != after[name].release_id
            }
            self.assertEqual(changed, expected_changed)

    def test_pre_fix_server_only_identity_missed_service_semantics(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _copy_release_tree(root)
            legacy_before = {
                name: web_release._digest_paths(
                    root, tuple(paths) + (web_release._HELPER_PATH,)
                )
                for name, paths in _LEGACY_BACKEND_PATHS.items()
            }
            current_before = build_web_releases(root)
            _append(root / "zaaggenz_timeline/service.py", "\n# changed service semantics\n")
            legacy_after = {
                name: web_release._digest_paths(
                    root, tuple(paths) + (web_release._HELPER_PATH,)
                )
                for name, paths in _LEGACY_BACKEND_PATHS.items()
            }
            current_after = build_web_releases(root)

            self.assertEqual(legacy_before, legacy_after)
            for name in ("timeline", "listening", "inspector", "vocal"):
                self.assertNotEqual(
                    current_before[name].release_id,
                    current_after[name].release_id,
                )

    def test_workspace_semantic_dependencies_invalidate_only_affected_release_domains(self):
        cases = (
            ("zaaggenz_timeline/service.py", {"timeline", "listening", "inspector", "vocal"}),
            ("zaaggenz_listening/service.py", {"listening"}),
            ("zaaggenz_inspector/service.py", {"inspector"}),
            ("zaaggenz_vocal/service.py", {"vocal"}),
            ("zaaggenz_contracts/validation.py", {"timeline", "listening", "inspector", "vocal"}),
        )
        for path, expected in cases:
            with self.subTest(path=path):
                self._case(path, expected)

    def test_unrelated_dsp_and_documentation_bytes_do_not_churn_web_releases(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _copy_release_tree(root)
            before = build_web_releases(root)

            dsp = root / "zaaggenz_dsp" / "__init__.py"
            dsp.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / "zaaggenz_dsp" / "__init__.py", dsp)
            _append(dsp, "\n# unrelated DSP implementation change\n")
            docs = root / "docs" / "note.md"
            docs.parent.mkdir(parents=True, exist_ok=True)
            docs.write_text("documentation-only change\n", encoding="utf-8")

            after = build_web_releases(root)
            self.assertEqual(
                {name: release.release_id for name, release in before.items()},
                {name: release.release_id for name, release in after.items()},
            )

    def test_unclassified_first_party_protocol_dependency_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _copy_release_tree(root)
            service = root / "zaaggenz_timeline" / "service.py"
            _append(service, "\nfrom zaaggenz_future_protocol import protocol_value\n")
            errors = protocol_dependency_errors(root, workspace="timeline")
            self.assertTrue(
                any("unclassified first-party dependency zaaggenz_future_protocol" in row for row in errors),
                errors,
            )
            with self.assertRaisesRegex(RuntimeError, "protocol dependency audit failed"):
                build_web_releases(root)

    def test_missing_declared_protocol_module_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _copy_release_tree(root)
            (root / "zaaggenz_listening" / "service.py").unlink()
            errors = protocol_dependency_errors(root, workspace="listening")
            self.assertTrue(
                any("missing protocol dependency zaaggenz_listening/service.py" in row for row in errors),
                errors,
            )
            with self.assertRaisesRegex(RuntimeError, "protocol dependency audit failed"):
                build_web_releases(root)

    def test_unified_runtime_session_semantics_invalidate_every_workspace(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _copy_release_tree(root, unified_runtime=True)
            before = build_web_releases(root, unified_runtime=True)
            _append(root / "zaaggenz_runtime" / "session.py", "\n# runtime session semantic change\n")
            after = build_web_releases(root, unified_runtime=True)
            for name in before:
                self.assertNotEqual(before[name].release_id, after[name].release_id)

    def test_current_repository_protocol_manifest_is_complete(self):
        self.assertEqual(protocol_dependency_errors(ROOT), ())
        self.assertEqual(protocol_dependency_errors(ROOT, unified_runtime=True), ())


if __name__ == "__main__":
    unittest.main(verbosity=2)
