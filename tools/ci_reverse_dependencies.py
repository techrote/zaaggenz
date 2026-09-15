#!/usr/bin/env python3
"""Dependency-aware selector for accepted ZaagGenZ GitHub Actions workflows.

The existing feature workflows remain the source of truth for test/evidence commands.
This tool identifies only *missing* downstream workflow runs: consumers that are
transitively affected by changed implementation paths but whose existing
``pull_request.paths`` filters would not start them natively.

No third-party YAML parser is required; we only read the small, deliberately
regular ``on.pull_request.paths`` list used by this repository.
"""
from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / ".github" / "workflows"
CONFIG_PATH = ROOT / "programme" / "ci_reverse_dependencies.json"
GRAPH_PATH = ROOT / "programme" / "dependency_graph.json"
WORKFLOW_RE = re.compile(r"^zg(?P<num>\d{3})[a-z0-9-]*\.yml$")
MAPPED_WORKFLOW_RE = re.compile(r"^zg(?P<num>\d{3})")

EXCLUDED_SOURCE_PREFIXES = (
    "tests/",
    "docs/",
    "tools/",
    "examples/",
    ".github/",
    "programme/",
)
SOURCE_PREFIXES = (
    "zaaggenz_",
    "app/",
    "baseline/",
    "web/",
    "research/",
    "requirements-",
    "references/",
)


class AuditError(RuntimeError):
    pass


@dataclass(frozen=True)
class WorkflowAudit:
    filename: str
    stable_id: str
    pull_request_paths: tuple[str, ...]
    source_paths: tuple[str, ...]


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _unquote_list_value(text: str) -> str:
    value = text.strip()
    try:
        parsed = ast.literal_eval(value)
    except (ValueError, SyntaxError):
        return value
    return parsed if isinstance(parsed, str) else value


def pull_request_paths(path: Path) -> tuple[str, ...]:
    """Extract the literal on.pull_request.paths list from one workflow."""
    lines = path.read_text(encoding="utf-8").splitlines()
    in_pull_request = False
    pull_indent = -1
    paths_indent = -1
    collecting = False
    out: list[str] = []

    for raw in lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))

        if not in_pull_request:
            if stripped == "pull_request:":
                in_pull_request = True
                pull_indent = indent
            continue

        if collecting:
            if indent <= paths_indent:
                break
            if stripped.startswith("- "):
                out.append(_unquote_list_value(stripped[2:]))
            continue

        if indent <= pull_indent:
            break
        if stripped == "paths:":
            paths_indent = indent
            collecting = True

    if not out:
        raise AuditError(f"{path.name}: missing literal pull_request.paths list")
    return tuple(out)


def _is_implementation_pattern(pattern: str) -> bool:
    if pattern.startswith(EXCLUDED_SOURCE_PREFIXES):
        return False
    return pattern.startswith(SOURCE_PREFIXES)


def _matches(path: str, pattern: str) -> bool:
    # GitHub path filters and fnmatch are not byte-for-byte identical, but all
    # repository patterns admitted here are simple literals/prefix globs.
    return fnmatch.fnmatchcase(path.replace("\\", "/"), pattern)


def build_audit(root: Path = ROOT) -> tuple[dict, dict, dict[str, WorkflowAudit]]:
    config = _load_json(root / "programme" / "ci_reverse_dependencies.json")
    graph = _load_json(root / "programme" / "dependency_graph.json")
    owners: dict[str, str] = config["workflow_owners"]
    parents: dict[str, list[str]] = graph["parents"]

    errors: list[str] = []
    current = {
        p.name
        for p in (root / ".github" / "workflows").glob("zg*.yml")
        if p.name != "zg000-ci-impact.yml"
    }
    mapped = set(owners)
    if current != mapped:
        missing = sorted(current - mapped)
        stale = sorted(mapped - current)
        if missing:
            errors.append(f"unmapped feature workflows: {missing}")
        if stale:
            errors.append(f"mapped workflows not present: {stale}")

    audits: dict[str, WorkflowAudit] = {}
    for filename, stable_id in sorted(owners.items()):
        if stable_id not in parents:
            errors.append(f"{filename}: unknown stable id {stable_id}")
            continue
        prefix = MAPPED_WORKFLOW_RE.match(filename)
        expected = f"ZG-{prefix.group('num')}" if prefix else None
        if expected != stable_id:
            errors.append(f"{filename}: filename implies {expected}, map says {stable_id}")
        workflow_path = root / ".github" / "workflows" / filename
        if not workflow_path.exists():
            continue
        text = workflow_path.read_text(encoding="utf-8")
        if "workflow_dispatch:" not in text:
            errors.append(f"{filename}: downstream dispatcher requires workflow_dispatch")
        try:
            pr_paths = pull_request_paths(workflow_path)
        except AuditError as exc:
            errors.append(str(exc))
            continue
        source_paths = tuple(p for p in pr_paths if _is_implementation_pattern(p))
        if not source_paths:
            errors.append(f"{filename}: no implementation source path can be inferred")
        audits[filename] = WorkflowAudit(filename, stable_id, pr_paths, source_paths)

    for pattern, stable_ids in config.get("special_path_owners", {}).items():
        if not pattern or not isinstance(stable_ids, list) or not stable_ids:
            errors.append(f"invalid special_path_owners entry: {pattern!r}")
        for stable_id in stable_ids:
            if stable_id not in parents:
                errors.append(f"special path {pattern}: unknown stable id {stable_id}")

    # Every checked-in zaaggenz_* implementation package must be represented by
    # at least one workflow source path, otherwise the classifier could miss it.
    inferred_patterns = [p for audit in audits.values() for p in audit.source_paths]
    for package in sorted(p for p in root.glob("zaaggenz_*") if p.is_dir()):
        probe = package.name + "/__impact_probe__.py"
        if not any(_matches(probe, pattern) for pattern in inferred_patterns):
            errors.append(f"implementation package has no workflow owner: {package.name}")

    if errors:
        raise AuditError("reverse-dependency CI audit failed:\n- " + "\n- ".join(errors))
    return config, graph, audits


def _ancestor_fn(parents: dict[str, list[str]]):
    @lru_cache(maxsize=None)
    def ancestors(stable_id: str) -> frozenset[str]:
        result: set[str] = set()
        for parent in parents[stable_id]:
            result.add(parent)
            result.update(ancestors(parent))
        return frozenset(result)

    return ancestors


def classify_changed_paths(
    changed_paths: Iterable[str], root: Path = ROOT
) -> dict[str, object]:
    config, graph, audits = build_audit(root)
    parents: dict[str, list[str]] = graph["parents"]
    ancestors = _ancestor_fn(parents)
    changed = sorted({p.replace("\\", "/") for p in changed_paths if p.strip()})

    direct: set[str] = set()
    for path in changed:
        for pattern, owners in config.get("special_path_owners", {}).items():
            if _matches(path, pattern):
                direct.update(owners)
        workflow_name = path.removeprefix(".github/workflows/")
        if path.startswith(".github/workflows/") and workflow_name in audits:
            direct.add(audits[workflow_name].stable_id)
        for audit in audits.values():
            if any(_matches(path, pattern) for pattern in audit.source_paths):
                direct.add(audit.stable_id)

    impacted: list[WorkflowAudit] = []
    native: list[WorkflowAudit] = []
    dispatch: list[WorkflowAudit] = []
    for audit in sorted(audits.values(), key=lambda a: a.filename):
        closure = set(ancestors(audit.stable_id)) | {audit.stable_id}
        if not (direct & closure):
            continue
        impacted.append(audit)
        if any(
            _matches(path, pattern)
            for path in changed
            for pattern in audit.pull_request_paths
        ):
            native.append(audit)
        else:
            dispatch.append(audit)

    return {
        "changed": changed,
        "direct_stable_ids": sorted(direct),
        "impacted": [a.filename for a in impacted],
        "native": [a.filename for a in native],
        "dispatch": [
            {"workflow": a.filename, "stable_id": a.stable_id} for a in dispatch
        ],
    }


def audit_markdown(root: Path = ROOT) -> str:
    _, graph, audits = build_audit(root)
    parents: dict[str, list[str]] = graph["parents"]
    rows = [
        "| Workflow | Stable ID | Direct implementation trigger paths | Hard parents |",
        "| --- | --- | --- | --- |",
    ]
    for audit in sorted(audits.values(), key=lambda a: a.filename):
        source = "<br>".join(f"`{p}`" for p in audit.source_paths)
        hard_parents = ", ".join(parents[audit.stable_id]) or "—"
        rows.append(
            f"| `{audit.filename}` | {audit.stable_id} | {source} | {hard_parents} |"
        )
    return "\n".join(rows) + "\n"


def _read_changed_file_list(path: str | None) -> list[str]:
    if not path:
        return []
    return [line.strip() for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--changed-file", action="append", default=[])
    parser.add_argument("--changed-file-list")
    parser.add_argument("--github-output")
    args = parser.parse_args()

    if args.validate or args.audit or args.changed_file or args.changed_file_list:
        build_audit(ROOT)

    if args.validate:
        _, _, audits = build_audit(ROOT)
        print(f"reverse-dependency CI audit OK: {len(audits)} accepted workflow files")

    if args.audit:
        print(audit_markdown(ROOT), end="")

    changed = list(args.changed_file) + _read_changed_file_list(args.changed_file_list)
    if changed:
        result = classify_changed_paths(changed, ROOT)
        print(json.dumps(result, sort_keys=True))
        if args.github_output:
            out = Path(args.github_output)
            with out.open("a", encoding="utf-8") as fh:
                fh.write("matrix=" + json.dumps(result["dispatch"], separators=(",", ":")) + "\n")
                fh.write("has_work=" + ("true" if result["dispatch"] else "false") + "\n")
                fh.write("native=" + json.dumps(result["native"], separators=(",", ":")) + "\n")
                fh.write("direct=" + json.dumps(result["direct_stable_ids"], separators=(",", ":")) + "\n")
    elif args.github_output:
        with Path(args.github_output).open("a", encoding="utf-8") as fh:
            fh.write("matrix=[]\nhas_work=false\nnative=[]\ndirect=[]\n")

    if not (args.validate or args.audit or changed or args.github_output):
        parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
