from __future__ import annotations

import importlib.metadata
from pathlib import Path
import subprocess
import tempfile
import sys
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from zaaggenz_environment import VERSION, MissingExtraError, external_tool_policy, external_tool_report, installed_asset_report, package_identity, require_extra


class CanonicalEnvironmentTests(unittest.TestCase):
    def test_distribution_identity_matches_source_version(self):
        self.assertEqual(importlib.metadata.version("zaaggenz"), VERSION)
        identity = package_identity()
        self.assertEqual(identity["source_version"], VERSION)
        self.assertEqual(identity["installed_version"], VERSION)

    def test_metadata_separates_runtime_browser_dev_test_and_research(self):
        metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        project = metadata["project"]
        self.assertEqual(project["requires-python"], ">=3.13,<3.14")
        runtime = "\n".join(project["dependencies"]).lower()
        for name in ("numpy", "scipy", "threadpoolctl", "jsonschema", "referencing"):
            self.assertIn(name, runtime)
        self.assertNotIn("playwright", runtime)
        groups = project["optional-dependencies"]
        self.assertIn("playwright", "\n".join(groups["browser"]).lower())
        self.assertIn("playwright", "\n".join(groups["dev"]).lower())
        self.assertIn("build", "\n".join(groups["test"]).lower())
        self.assertIn("numpy", "\n".join(groups["research"]).lower())
        self.assertIn("scipy", "\n".join(groups["research"]).lower())
        packages = metadata["tool"]["setuptools"]["packages"]["find"]
        self.assertTrue(packages["namespaces"])
        self.assertIn("app*", packages["include"])
        self.assertIn("web*", packages["include"])

    def test_generated_views_and_workflow_pins_are_in_sync(self):
        result = subprocess.run(
            [sys.executable, "tools/sync_environment.py", "--check"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_browser_missing_extra_error_is_actionable(self):
        with self.assertRaises(MissingExtraError) as cm:
            require_extra("browser", finder=lambda _name: None)
        text = str(cm.exception)
        self.assertIn("[browser]", text)
        self.assertIn("playwright", text)

    def test_research_missing_extra_error_is_actionable(self):
        with self.assertRaises(MissingExtraError) as cm:
            require_extra("research", finder=lambda _name: None)
        text = str(cm.exception)
        self.assertIn("[research]", text)
        self.assertIn("numpy", text)
        self.assertIn("scipy", text)

    def test_report_records_external_tools_without_making_them_python_dependencies(self):
        report = external_tool_report()
        self.assertEqual(report["format"], "zaaggenz-environment-report")
        self.assertEqual(report["package"]["source_version"], VERSION)
        self.assertEqual(set(report["external_tools"]), {"ffmpeg", "ffprobe", "node"})
        metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        deps = "\n".join(metadata["project"]["dependencies"]).lower()
        self.assertNotIn("ffmpeg", deps)
        self.assertNotIn("ffprobe", deps)
        policy = external_tool_policy()
        self.assertEqual(policy["format"], "zaaggenz-external-tool-policy")
        self.assertEqual(policy["tools"]["node"]["requirement"], "test-dev")
        self.assertEqual(policy["tools"]["node"]["supported_range"], ">=22 <25")
        self.assertEqual(policy["tools"]["ffmpeg"]["requirement"], "optional")
        self.assertEqual(policy["tools"]["ffmpeg"]["version_policy"], "record-only")
        self.assertIsNone(policy["tools"]["ffmpeg"]["supported_range"])
        self.assertEqual(report["external_tool_policy"], policy)

    def test_minimal_runtime_imports_do_not_import_playwright(self):
        code = (
            "import sys;"
            "import zaaggenz_analysis.features;"
            "import zaaggenz_jobs.numeric_runtime;"
            "import zaaggenz_contracts.validation;"
            "import zaaggenz_project;"
            "assert not any(k == 'playwright' or k.startswith('playwright.') for k in sys.modules)"
        )
        result = subprocess.run(
            [sys.executable, "-I", "-c", code],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_installed_asset_validator_fails_on_one_missing_required_file(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            required = (
                "web/timeline/index.html",
                "web/listening/app.mjs",
                "web/inspector/app.mjs",
                "web/vocal/app.mjs",
                "app/webapp.py",
                "app/uptempo_harmony/__init__.py",
            )
            for rel in required:
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"x")
            report = installed_asset_report(root)
            self.assertEqual(set(report["required_files"]), set(required))
            (root / "web/listening/app.mjs").unlink()
            with self.assertRaisesRegex(RuntimeError, "web/listening/app.mjs"):
                installed_asset_report(root)

    def test_canonical_pins_cover_audited_distribution_report(self):
        metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        pins = set(metadata["tool"]["zaaggenz"]["environment"]["ci-pins"])
        report = external_tool_report()
        self.assertEqual(set(report["python_distributions"]), pins)


if __name__ == "__main__":
    unittest.main(verbosity=2)
