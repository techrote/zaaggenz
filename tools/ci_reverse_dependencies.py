#!/usr/bin/env python3
"""Dependency-aware selector for accepted ZaagGenZ GitHub Actions workflows.

Feature workflows remain authoritative for their exact test/evidence commands.
This tool identifies only *missing* downstream workflow runs: consumers that are
transitively affected by changed implementation paths but whose current pull-
request trigger would not start them natively.

Native trigger coverage and implementation ownership are deliberately separate:
workflow path filters may include dependency paths for regression coverage and
must never be mistaken for ownership of those packages.
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
MAPPED_WORKFLOW_RE = re.compile(r"^zg(?P<num>\d{3})")


class AuditError(RuntimeError):
    pass


@dataclass(frozen=True)
class WorkflowAudit:
    filename: str
    stable_id: str
    pull_request_paths: tuple[str, ...]

    @property
    def always_native(self) -> bool:
        return not self.pull_request_paths


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
    """Return literal pull-request paths, or empty for an unfiltered PR trigger."""
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

    if not in_pull_request:
        raise AuditError(f"{path.name}: missing pull_request trigger")
    return tuple(out)


def _matches(path: str, pattern: str) -> bool:
    # All source-owner and workflow trigger patterns admitted by this tool are
    # deliberately simple literals/prefix globs.
    return fnmatch.fnmatchcase(path.replace("\\", "/"), pattern)


def _source_owner_ids(config: dict) -> set[str]:
    return {
        stable_id
        for ids in config.get("source_path_owners", {}).values()
        for stable_id in ids
    }


def build_audit(root: Path = ROOT) -> tuple[dict, dict, dict[str, WorkflowAudit]]:
    config = _load_json(root / "programme" / "ci_reverse_dependencies.json")
    graph = _load_json(root / "programme" / "dependency_graph.json")
    owners: dict[str, str] = config["workflow_owners"]
    source_owners: dict[str, list[str]] = config.get("source_path_owners", {})
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
        audits[filename] = WorkflowAudit(filename, stable_id, pr_paths)

    for pattern, stable_ids in source_owners.items():
        if not pattern or not isinstance(stable_ids, list) or not stable_ids:
            errors.append(f"invalid source_path_owners entry: {pattern!r}")
            continue
        for stable_id in stable_ids:
            if stable_id not in parents:
                errors.append(f"source path {pattern}: unknown stable id {stable_id}")

    # Every accepted workflow owner must own at least one source surface. This
    # makes unfiltered workflows (currently ZG-002) explicit rather than letting
    # their lack of paths erase dependency propagation.
    source_ids = _source_owner_ids(config)
    for stable_id in sorted(set(owners.values())):
        if stable_id not in source_ids:
            errors.append(f"workflow owner has no source ownership: {stable_id}")

    # Every checked-in implementation package must be explicitly owned. Broad
    # consumer trigger paths (e.g. ZG-024a's zaaggenz_*/**) cannot satisfy this.
    source_patterns = list(source_owners)
    for package in sorted(p for p in root.glob("zaaggenz_*") if p.is_dir()):
        probe = package.name + "/__impact_probe__.py"
        if not any(_matches(probe, pattern) for pattern in source_patterns):
            errors.append(f"implementation package has no source owner: {package.name}")

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
    source_owners: dict[str, list[str]] = config["source_path_owners"]
    ancestors = _ancestor_fn(parents)
    changed = sorted({p.replace("\\", "/") for p in changed_paths if p.strip()})

    direct: set[str] = set()
    for path in changed:
        for pattern, owners in source_owners.items():
            if _matches(path, pattern):
                direct.update(owners)
        # Workflow-definition, programme-map and selector edits are validated by
        # the ZG-000 impact workflow itself. They are not product-source changes
        # and therefore do not fan out through the programme DAG.

    impacted: list[WorkflowAudit] = []
    native: list[WorkflowAudit] = []
    dispatch: list[WorkflowAudit] = []
    for audit in sorted(audits.values(), key=lambda a: a.filename):
        closure = set(ancestors(audit.stable_id)) | {audit.stable_id}
        if not (direct & closure):
            continue
        impacted.append(audit)
        if audit.always_native or any(
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
    config, graph, audits = build_audit(root)
    parents: dict[str, list[str]] = graph["parents"]
    source_owners: dict[str, list[str]] = config["source_path_owners"]
    rows = [
        "| Workflow | Stable ID | PR trigger | Owned implementation paths | Hard parents |",
        "| --- | --- | --- | --- | --- |",
    ]
    for audit in sorted(audits.values(), key=lambda a: a.filename):
        trigger = "all pull requests" if audit.always_native else "path-filtered"
        owned = [
            pattern
            for pattern, ids in source_owners.items()
            if audit.stable_id in ids
        ]
        source = "<br>".join(f"`{p}`" for p in owned) or "—"
        hard_parents = ", ".join(parents[audit.stable_id]) or "—"
        rows.append(
            f"| `{audit.filename}` | {audit.stable_id} | {trigger} | {source} | {hard_parents} |"
        )
    return "\n".join(rows) + "\n"


def _read_changed_file_list(path: str | None) -> list[str]:
    if not path:
        return []
    return [
        line.strip()
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


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
