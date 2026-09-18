from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shlex
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"

_NAME = re.compile(r"^\s*([A-Za-z0-9_.-]+)")
_REQ_TOKEN = re.compile(r"^([A-Za-z0-9_.-]+)(?:\[[^\]]+\])?(.*)$")
_PYTHON_VERSION = re.compile(r"python-version:\s*['\"]?([0-9]+\.[0-9]+)")
_NODE_VERSION = re.compile(r"node-version:\s*['\"]?([0-9]+)")
_PIP_INSTALL = re.compile(
    r"(?i)(?:^|\s)(?:\S*python(?:[0-9.]*)?\S*\s+-m\s+pip|pip(?:3)?)\s+install\s+(.+)$"
)
_CONSTRAINT_EXEMPT_WORKFLOWS = {
    "zg001-recovery.yml",
}
_GENERATED_REQUIREMENTS = {"requirements-contracts.txt", "requirements-jobs.txt"}
_ALLOWED_PIP_FLAGS = {
    "--disable-pip-version-check",
    "--no-deps",
    "--no-build-isolation",
    "--quiet",
}
_VALUE_OPTIONS = {"-c", "--constraint", "-r", "--requirement", "-e", "--editable"}


def _metadata() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def _canonical_name(value: str) -> str:
    return value.lower().replace("_", "-")


def _requirements(rows: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in rows:
        match = _NAME.match(row)
        if not match:
            raise ValueError(f"cannot parse requirement {row!r}")
        out[_canonical_name(match.group(1))] = row
    return out


def _declared_requirements(metadata: dict) -> dict[str, str]:
    project = metadata["project"]
    out = _requirements(project["dependencies"])
    for rows in project.get("optional-dependencies", {}).values():
        out.update(_requirements(rows))
    return out


def _tool_policy(metadata: dict) -> dict:
    env = metadata["tool"]["zaaggenz"]["environment"]
    policy = env["external-tool-policy"]
    expected = set(env["external-tools"])
    if set(policy) != expected:
        raise ValueError("external-tool-policy must exactly cover external-tools")
    rows = {}
    for name in sorted(policy):
        row = policy[name]
        required = {"requirement", "required-by", "version-policy", "supported-range", "ci-version"}
        if set(row) != required:
            raise ValueError(f"external-tool-policy.{name} has unexpected fields")
        if row["requirement"] not in {"required", "optional", "test-dev"}:
            raise ValueError(f"invalid external tool requirement: {name}")
        if row["version-policy"] not in {"supported-range", "record-only"}:
            raise ValueError(f"invalid external tool version policy: {name}")
        if row["version-policy"] == "supported-range" and not row["supported-range"]:
            raise ValueError(f"supported-range required for {name}")
        if row["version-policy"] == "record-only" and row["supported-range"]:
            raise ValueError(f"record-only tool must not claim a support range: {name}")
        rows[name] = {
            "requirement": row["requirement"],
            "required_by": list(row["required-by"]),
            "version_policy": row["version-policy"],
            "supported_range": row["supported-range"] or None,
            "ci_version": row["ci-version"] or None,
        }
    return {"format": "zaaggenz-external-tool-policy", "version": "1.0.0", "tools": rows}


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
    tool_policy = json.dumps(_tool_policy(metadata), indent=2, sort_keys=True) + "\n"
    return {
        ROOT / "constraints" / "ci.txt": constraints,
        ROOT / "requirements-contracts.txt": view(
            ("jsonschema", "referencing"), "constraints/ci.txt"
        ),
        ROOT / "requirements-jobs.txt": view(
            ("threadpoolctl",), "constraints/ci.txt"
        ),
        ROOT / "package.json": json.dumps(package_json, indent=2, sort_keys=True) + "\n",
        ROOT / "zaaggenz_environment" / "tool_policy.json": tool_policy,
    }


def _workflow_run_blocks(text: str) -> list[str]:
    lines = text.splitlines()
    blocks: list[str] = []
    index = 0
    while index < len(lines):
        match = re.match(r"^(\s*)run:\s*(.*)$", lines[index])
        if match is None:
            index += 1
            continue
        indent = len(match.group(1))
        tail = match.group(2).strip()
        if tail in {"|", "|-", "|+", ">", ">-", ">+"}:
            index += 1
            body = []
            while index < len(lines):
                line = lines[index]
                if line.strip() and len(line) - len(line.lstrip()) <= indent:
                    break
                body.append(line[indent + 2 :] if len(line) >= indent + 2 else "")
                index += 1
            blocks.append("\n".join(body))
            continue
        if len(tail) >= 2 and tail[0] == tail[-1] and tail[0] in {"'", '"'}:
            tail = tail[1:-1]
        blocks.append(tail)
        index += 1
    return blocks


def _pip_install_commands(block: str) -> list[str]:
    normalized = re.sub(r"\$\{\{.*?\}\}", "python", block)
    normalized = normalized.replace("\\\n", " ").replace(chr(96) + "\n", " ")
    commands = []
    for line in normalized.splitlines():
        for part in re.split(r"\s*(?:&&|;)\s*", line):
            match = _PIP_INSTALL.search(part.strip())
            if match is not None:
                commands.append(match.group(1).strip())
    return commands


def _project_extra(spec: str, metadata: dict) -> tuple[bool, str | None]:
    if spec == ".":
        return True, None
    match = re.fullmatch(r"\.\[([A-Za-z0-9_.-]+)\]", spec)
    if match is None:
        return False, None
    extra = match.group(1)
    if extra not in metadata["project"].get("optional-dependencies", {}):
        return False, extra
    return True, extra


def _pip_command_errors(metadata: dict, workflow_name: str, args_text: str) -> list[str]:
    declared = _declared_requirements(metadata)
    pins = {
        _canonical_name(k): str(v)
        for k, v in metadata["tool"]["zaaggenz"]["environment"]["ci-pins"].items()
    }
    try:
        args = shlex.split(args_text, posix=True)
    except ValueError as exc:
        return [f"ambiguous pip install command: {exc}"]

    errors: list[str] = []
    context = False
    project_specs: list[str] = []
    requirements: list[str] = []
    index = 0
    while index < len(args):
        token = args[index]
        if token in _VALUE_OPTIONS:
            if index + 1 >= len(args):
                errors.append(f"{token} missing value")
                break
            value = args[index + 1]
            index += 2
            if token in {"-c", "--constraint"}:
                if value != "constraints/ci.txt":
                    errors.append(f"noncanonical constraint file {value!r}")
                else:
                    context = True
            elif token in {"-r", "--requirement"}:
                if value not in _GENERATED_REQUIREMENTS:
                    errors.append(f"noncanonical requirement file {value!r}")
                else:
                    context = True
            else:
                ok, _extra = _project_extra(value, metadata)
                if not ok:
                    errors.append(
                        f"editable install must be current project with declared extra, got {value!r}"
                    )
                else:
                    project_specs.append(value)
            continue
        if token.startswith("-"):
            if token not in _ALLOWED_PIP_FLAGS:
                errors.append(f"unsupported/ambiguous pip install option {token!r}")
            index += 1
            continue
        requirements.append(token)
        index += 1

    exempt = workflow_name in _CONSTRAINT_EXEMPT_WORKFLOWS
    if project_specs and not context:
        errors.append("editable project install must consume constraints/ci.txt")
    if requirements and not context and not exempt:
        errors.append("direct dependency install does not consume canonical constraints/requirements")

    parsed_names = set()
    for token in requirements:
        if token == "@" or "://" in token or token.startswith(("git+", "file:")):
            errors.append(f"direct URL/VCS dependency is not canonical: {token!r}")
            continue
        match = _REQ_TOKEN.fullmatch(token)
        if match is None:
            errors.append(f"cannot audit direct dependency token {token!r}")
            continue
        name = _canonical_name(match.group(1))
        parsed_names.add(name)
        suffix = match.group(2)
        if name not in declared:
            errors.append(f"undeclared direct dependency {name!r}")
            continue
        pin = pins.get(name)
        if pin is None:
            errors.append(f"declared dependency {name!r} has no canonical CI pin")
            continue
        if suffix != f"=={pin}":
            errors.append(
                f"{name} direct install must use canonical exact pin =={pin}, got {suffix or 'bare'}"
            )

    if exempt and (project_specs or context or not parsed_names <= {"numpy", "scipy"}):
        errors.append("ZG-001 exception is limited to exact recorded NumPy/SciPy pins")
    return errors


def workflow_install_errors(metadata: dict, workflow_name: str, text: str) -> list[str]:
    errors: list[str] = []
    for number, block in enumerate(_workflow_run_blocks(text), start=1):
        for command in _pip_install_commands(block):
            for error in _pip_command_errors(metadata, workflow_name, command):
                errors.append(f"run-block {number}: {error}; pip install {command}")
    return errors


def _workflow_errors(metadata: dict) -> list[str]:
    env = metadata["tool"]["zaaggenz"]["environment"]
    expected_python = str(env["ci-python"])
    node_range = str(env["node-supported"])
    node_match = re.fullmatch(r">=([0-9]+)\s+<([0-9]+)", node_range)
    if node_match is None:
        raise ValueError("node-supported must use the auditable '>=MAJOR <MAJOR' form")
    node_low, node_high = map(int, node_match.groups())
    errors: list[str] = []
    for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        errors.extend(
            f"{path.relative_to(ROOT)}: {error}"
            for error in workflow_install_errors(metadata, path.name, text)
        )
        for actual in _PYTHON_VERSION.findall(text):
            if actual != expected_python and path.name not in _CONSTRAINT_EXEMPT_WORKFLOWS:
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
        _canonical_name(k): str(v)
        for k, v in metadata["tool"]["zaaggenz"]["environment"]["ci-pins"].items()
    }
    exact = re.compile(r"\b([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+-]+)\b")
    errors: list[str] = []
    for path in sorted((ROOT / "research").glob("**/requirements*.txt")):
        text = path.read_text(encoding="utf-8")
        for raw_name, actual in exact.findall(text):
            name = _canonical_name(raw_name)
            if name in pins and actual != pins[name]:
                errors.append(
                    f"{path.relative_to(ROOT)}: historical {raw_name}=={actual} differs from canonical CI pin {pins[name]}"
                )
    return errors


def sync(*, check: bool) -> list[str]:
    metadata = _metadata()
    errors: list[str] = []
    try:
        generated = _generated(metadata)
    except (KeyError, TypeError, ValueError) as exc:
        return [f"invalid canonical environment metadata: {exc}"]
    for path, expected in generated.items():
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
    p.add_argument("--check", action="store_true", help="verify generated files and workflow install policy")
    args = p.parse_args(argv)
    errors = sync(check=args.check)
    for error in errors:
        print(error, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
