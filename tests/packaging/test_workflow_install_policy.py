from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("sync_environment", ROOT / "tools" / "sync_environment.py")
sync_environment = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(sync_environment)


def workflow(*commands: str) -> str:
    rows = ["jobs:", "  test:", "    steps:"]
    for index, command in enumerate(commands):
        rows.extend((f"      - name: install-{index}", "        run: >-", f"          {command}"))
    return "\n".join(rows) + "\n"


class WorkflowInstallPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.metadata = sync_environment._metadata()

    def errors(self, *commands, name="example.yml"):
        return sync_environment.workflow_install_errors(
            self.metadata, name, workflow(*commands)
        )

    def test_generated_requirement_and_exact_pin_commands_pass(self):
        self.assertEqual(
            self.errors(
                "python -m pip install numpy==2.3.5 scipy==1.17.0 "
                "-r requirements-contracts.txt -r requirements-jobs.txt"
            ),
            [],
        )

    def test_canonical_editable_extras_pass(self):
        for extra in ("test", "dev", "browser", "research"):
            with self.subTest(extra=extra):
                self.assertEqual(
                    self.errors(
                        f'python -m pip install -c constraints/ci.txt -e ".[{extra}]"'
                    ),
                    [],
                )

    def test_range_and_bare_canonical_dependencies_are_rejected(self):
        cases = (
            "python -m pip install numpy>=2.4 -r requirements-contracts.txt",
            "python -m pip install numpy -r requirements-contracts.txt",
            "pip install scipy<2 -c constraints/ci.txt",
        )
        for command in cases:
            with self.subTest(command=command):
                errors = self.errors(command)
                self.assertTrue(errors, command)
                self.assertTrue(any("canonical exact pin" in row for row in errors), errors)

    def test_undeclared_direct_dependency_is_rejected(self):
        errors = self.errors(
            "python -m pip install some-new-package==1.0 -c constraints/ci.txt"
        )
        self.assertTrue(any("undeclared direct dependency" in row for row in errors), errors)

    def test_one_canonical_command_does_not_authorize_a_rogue_second_command(self):
        errors = self.errors(
            'python -m pip install -c constraints/ci.txt -e ".[test]"',
            "python -m pip install numpy>=2.4",
        )
        self.assertTrue(any("does not consume canonical" in row for row in errors), errors)
        self.assertTrue(any("canonical exact pin" in row for row in errors), errors)

    def test_unsupported_index_or_url_install_fails_closed(self):
        errors = self.errors(
            "python -m pip install --index-url https://example.invalid/simple "
            "numpy==2.3.5 -c constraints/ci.txt"
        )
        self.assertTrue(any("unsupported/ambiguous" in row for row in errors), errors)

    def test_matrix_python_expression_is_audited(self):
        errors = self.errors(
            "\${{ matrix.python }} -m pip install numpy>=2.4 -r requirements-contracts.txt"
        )
        self.assertTrue(any("canonical exact pin" in row for row in errors), errors)

    def test_zg001_exception_is_narrow_and_exact(self):
        self.assertEqual(
            self.errors(
                "python -m pip install numpy==2.3.5 scipy==1.17.0",
                name="zg001-recovery.yml",
            ),
            [],
        )
        bad = self.errors(
            "python -m pip install numpy==2.3.5 build==1.6.1",
            name="zg001-recovery.yml",
        )
        self.assertTrue(any("ZG-001 exception" in row for row in bad), bad)

    def test_noncanonical_requirement_and_constraint_files_are_rejected(self):
        for command in (
            "python -m pip install -r requirements.txt",
            "python -m pip install -c other-constraints.txt numpy==2.3.5",
        ):
            with self.subTest(command=command):
                self.assertTrue(self.errors(command))

    def test_ambiguous_pip_syntax_fails_closed(self):
        errors = self.errors(
            "python -m pip install --find-links local-wheelhouse numpy==2.3.5 "
            "-c constraints/ci.txt"
        )
        self.assertTrue(any("unsupported/ambiguous" in row for row in errors), errors)


if __name__ == "__main__":
    unittest.main(verbosity=2)
