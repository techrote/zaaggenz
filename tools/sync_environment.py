from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"

_NAME = re.compile(r"^\s*([A-Za-z0-9_.-]+)")
_EXACT_PIN = re.compile(
    r"\b(numpy|scipy|threadpoolctl|jsonschema|referencing|playwright)==([A-Za-z0-9_.+-]+)\b",
    re.IGNORECASE,
)
_PYTHON_VERSION = re.compile(r"python-version:\s*['\"]?([0-9]+\.[0-9]+)")
_NODE_VERSION = re.compile(r"node-version:\s*['\"]?([0-9]+)")
_CONSTRAINT_EXEMPT_WORKFLOWS = {
    "zg001-recovery.yml",  # authenticated recovered-baseline environment evidence
}


def _metadata() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def _requirements(rows: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in rows:
        match = _NAME.match(row)
        if not match:
            raise ValueError(f"cannot parse requirement {row!r}")
        out[match.group(1).lower().replace("_", "-")] = row
    return out


def _generated(metadata: dict) -> dict[Path, str]:
    project = metadata["project"]
    env = metadata["tool"]["zaaggenz"]["environment"]
    pins = env["ci-pins"]
    runtime = _requirements(project["dependencies"])
    header = "# Generated from pyproject.toml by tools/sync_environment.py; do not edit by hand.\n"
    constraints = header + "".join(f"{name}=={pins[name]}\n" for name in sorted(pins))

    def view(names: tuple[str, ...], constraint: str) -> str:
        return header + f"-c {constraint}\n" + "".join(runtime[name] + "\n" for name in names)

    package_json = {
        "name": "zaaggenz-local-tooling",
        "private": True,
        "engines": {"node": env["node-supported"]},
    }
    return {
        ROOT / "constraints" / "ci.txt": constraints,
        ROOT / "requirements-contracts.txt": view(
            ("jsonschema", "referencing"), "constraints/ci.txt"
        ),
        ROOT / "requirements-jobs.txt": view(
            ("threadpoolctl",), "constraints/ci.txt"
        ),
        ROOT / "package.json": json.dumps(package_json, indent=2, sort_keys=True) + "\n",
    }


def _workflow_errors(metadata: dict) -> list[str]:
    env = metadata["tool"]["zaaggenz"]["environment"]
    pins = {k.lower(): str(v) for k, v in env["ci-pins"].items()}
    expected_python = str(env["ci-python"])
    node_range = str(env["node-supported"])
    node_match = re.fullmatch(r">=([0-9]+)\s+<([0-9]+)", node_range)
    if node_match is None:
        raise ValueError("node-supported must use the auditable '>=MAJOR <MAJOR' form")
    node_low, node_high = map(int, node_match.groups())
    errors: list[str] = []
    for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        for name, actual in _EXACT_PIN.findall(text):
            expected = pins[name.lower()]
            if actual != expected:
                errors.append(f"{path.relative_to(ROOT)}: {name}=={actual} != canonical {expected}")
            if (
                path.name not in _CONSTRAINT_EXEMPT_WORKFLOWS
                and not any(
                    marker in text
                    for marker in (
                        "constraints/ci.txt",
                        "requirements-contracts.txt",
                        "requirements-jobs.txt",
                        "-e \".[",
                        "-e '.[",
                    )
                )
            ):
                errors.append(
                    f"{path.relative_to(ROOT)}: pinned dependency does not consume canonical constraints/metadata"
                )
        for actual in _PYTHON_VERSION.findall(text):
            if actual != expected_python:
                errors.append(
                    f"{path.relative_to(ROOT)}: Python {actual} != canonical CI Python {expected_python}"
                )
        for actual in _NODE_VERSION.findall(text):
            major = int(actual)
            if not node_low <= major < node_high:
                errors.append(
                    f"{path.relative_to(ROOT)}: Node {major} outside supported {node_range}"
                )
    return errors


def _historical_requirement_errors(metadata: dict) -> list[str]:
    pins = {
        k.lower(): str(v)
        for k, v in metadata["tool"]["zaaggenz"]["environment"]["ci-pins"].items()
    }
    errors: list[str] = []
    for path in sorted((ROOT / "research").glob("**/requirements*.txt")):
        text = path.read_text(encoding="utf-8")
        for name, actual in _EXACT_PIN.findall(text):
            expected = pins[name.lower()]
            if actual != expected:
                errors.append(
                    f"{path.relative_to(ROOT)}: historical {name}=={actual} differs from canonical CI pin {expected}"
                )
    return errors


def sync(*, check: bool) -> list[str]:
    metadata = _metadata()
    errors: list[str] = []
    for path, expected in _generated(metadata).items():
        if check:
            if not path.exists():
                errors.append(f"missing generated file: {path.relative_to(ROOT)}")
                continue
            actual = path.read_text(encoding="utf-8")
            if actual != expected:
                errors.append(f"generated file drift: {path.relative_to(ROOT)}")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(expected, encoding="utf-8", newline="\n")
    if check:
        errors.extend(_workflow_errors(metadata))
        errors.extend(_historical_requirement_errors(metadata))
    return errors


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Generate/check ZaagGenZ dependency views from canonical pyproject.toml metadata"
    )
    p.add_argument("--check", action="store_true", help="verify generated files and workflow pins")
    args = p.parse_args(argv)
    errors = sync(check=args.check)
    for error in errors:
        print(error, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
