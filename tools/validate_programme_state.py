#!/usr/bin/env python3
"""Validate and query ZaagGenZ evidence-aware programme state.

GitHub issue open/closed is deliberately informational. Hard-prerequisite
readiness is derived only from the explicit dependency_satisfied decision of
accepted programme evidence plus owner/research/blocker state.
"""
from __future__ import annotations

import argparse
import json
import re
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "programme" / "task_state.json"
TASKS_PATH = ROOT / "programme" / "tasks.json"
GRAPH_PATH = ROOT / "programme" / "dependency_graph.json"
ISSUE_MAP_PATH = ROOT / "programme" / "issue_map.json"

IMPLEMENTATION = {"not_started", "active", "partial", "blocked", "accepted"}
EVIDENCE = {"none", "partial", "accepted"}
RESEARCH = {"not_applicable", "planned", "active", "accepted"}
OWNER_GATE = {"not_applicable", "pending", "satisfied"}
ISSUE_STATE = {"open", "closed", "unknown"}
BLOCKER_KIND = {"dependency", "owner_gate", "research", "corrective", "external"}
BLOCKER_PREFIX = {
    "dependency": "task:",
    "owner_gate": "owner-gate:",
    "research": "research:",
    "corrective": "corrective:",
    "external": "external:",
}
BLOCKER_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*")
ISSUE_EVIDENCE_RE = re.compile(r"issue:#\d+(?::[A-Za-z0-9][A-Za-z0-9._/-]*)*")
PR_EVIDENCE_RE = re.compile(r"pr:#\d+(?::[A-Za-z0-9][A-Za-z0-9._/-]*)*")
COMMIT_EVIDENCE_RE = re.compile(r"commit:[0-9a-fA-F]{7,64}")


class StateError(RuntimeError):
    pass


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _require_enum(errors: list[str], sid: str, row: dict, key: str, allowed: set[str]) -> None:
    value = row.get(key)
    if value not in allowed:
        errors.append(f"{sid}: {key}={value!r} not in {sorted(allowed)}")


def _validate_evidence_ref(errors: list[str], sid: str, ref: str, *, root: Path) -> None:
    if ISSUE_EVIDENCE_RE.fullmatch(ref) or PR_EVIDENCE_RE.fullmatch(ref) or COMMIT_EVIDENCE_RE.fullmatch(ref):
        return
    if ref.startswith("docs:"):
        rel = ref.removeprefix("docs:")
        path = Path(rel)
        if not rel or path.is_absolute() or ".." in path.parts:
            errors.append(f"{sid}: invalid docs evidence ref {ref!r}")
            return
        if not (root / path).is_file():
            errors.append(f"{sid}: docs evidence ref does not exist: {ref!r}")
        return
    errors.append(f"{sid}: invalid evidence_ref {ref!r}")


def _validate_blocker_ref(
    errors: list[str],
    sid: str,
    blocker: dict,
    *,
    known_tasks: set[str],
) -> None:
    kind = blocker.get("kind")
    ref = blocker.get("ref")
    if kind not in BLOCKER_KIND:
        errors.append(f"{sid}: blocker kind {kind!r} invalid")
        return
    if not isinstance(ref, str) or not ref:
        errors.append(f"{sid}: blocker ref invalid")
        return

    prefix = BLOCKER_PREFIX[kind]
    if not ref.startswith(prefix):
        errors.append(f"{sid}: blocker {ref!r} must use {prefix!r} for kind {kind!r}")
        return
    token = ref[len(prefix):]
    if not BLOCKER_TOKEN_RE.fullmatch(token):
        errors.append(f"{sid}: malformed blocker identity {ref!r}")
        return
    if kind == "dependency":
        if not re.fullmatch(r"ZG-\d{3}", token):
            errors.append(f"{sid}: dependency blocker must name stable task ID: {ref!r}")
        elif token not in known_tasks:
            errors.append(f"{sid}: dependency blocker names unknown task {token}")


def validate_state(state: dict, *, root: Path = ROOT) -> None:
    tasks_doc = load(root / "programme" / "tasks.json")
    graph = load(root / "programme" / "dependency_graph.json")
    issue_map = load(root / "programme" / "issue_map.json")["stable_to_issue"]
    task_defs: dict[str, dict] = tasks_doc["tasks"]
    rows: dict[str, dict] = state.get("tasks", {})
    errors: list[str] = []

    if state.get("format_version") != 1:
        errors.append("format_version must be 1")
    if state.get("authority") != "accepted-evidence-v1":
        errors.append("authority must be accepted-evidence-v1")

    expected = set(task_defs)
    actual = set(rows)
    if expected != actual:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        if missing:
            errors.append(f"missing task state: {missing}")
        if extra:
            errors.append(f"unknown task state: {extra}")

    for sid in sorted(expected & actual):
        row = rows[sid]
        if not isinstance(row, dict):
            errors.append(f"{sid}: state must be object")
            continue
        _require_enum(errors, sid, row, "implementation", IMPLEMENTATION)
        _require_enum(errors, sid, row, "evidence", EVIDENCE)
        _require_enum(errors, sid, row, "research", RESEARCH)
        _require_enum(errors, sid, row, "owner_gate", OWNER_GATE)

        dep = row.get("dependency_satisfied")
        if type(dep) is not bool:
            errors.append(f"{sid}: dependency_satisfied must be boolean")

        refs = row.get("evidence_refs")
        if not isinstance(refs, list) or any(not isinstance(ref, str) or not ref for ref in refs):
            errors.append(f"{sid}: evidence_refs must be a list of non-empty strings")
            refs = []
        elif len(refs) != len(set(refs)):
            errors.append(f"{sid}: evidence_refs must not contain duplicates")
        for ref in refs:
            _validate_evidence_ref(errors, sid, ref, root=root)
        if row.get("evidence") in {"partial", "accepted"} and not refs:
            errors.append(f"{sid}: {row.get('evidence')} evidence requires evidence_refs")
        if row.get("evidence") == "none" and refs:
            errors.append(f"{sid}: evidence=none cannot carry evidence_refs")

        blockers = row.get("blockers")
        if not isinstance(blockers, list):
            errors.append(f"{sid}: blockers must be a list")
            blockers = []
        blocker_refs: set[str] = set()
        for i, blocker in enumerate(blockers):
            if not isinstance(blocker, dict):
                errors.append(f"{sid}: blockers[{i}] must be object")
                continue
            _validate_blocker_ref(errors, sid, blocker, known_tasks=expected)
            ref = blocker.get("ref")
            if isinstance(ref, str):
                if ref in blocker_refs:
                    errors.append(f"{sid}: duplicate blocker identity {ref!r}")
                blocker_refs.add(ref)

        mirror = row.get("github_issue")
        if not isinstance(mirror, dict):
            errors.append(f"{sid}: github_issue must be object")
        else:
            if mirror.get("number") != issue_map[sid]:
                errors.append(
                    f"{sid}: github issue number {mirror.get('number')} != issue_map {issue_map[sid]}"
                )
            if mirror.get("state") not in ISSUE_STATE:
                errors.append(f"{sid}: github issue state is invalid")

        # A prerequisite may only be declared satisfied when the evidence and
        # gates make that statement coherent. GitHub issue state is intentionally
        # absent from these rules.
        if dep is True:
            if row.get("implementation") != "accepted":
                errors.append(f"{sid}: dependency_satisfied requires implementation=accepted")
            if row.get("evidence") != "accepted":
                errors.append(f"{sid}: dependency_satisfied requires evidence=accepted")
            if row.get("owner_gate") == "pending":
                errors.append(f"{sid}: dependency_satisfied conflicts with pending owner gate")
            if row.get("research") in {"planned", "active"}:
                errors.append(f"{sid}: dependency_satisfied conflicts with incomplete research")
            if any(b.get("kind") in {"dependency", "owner_gate", "research", "external"} for b in blockers if isinstance(b, dict)):
                errors.append(f"{sid}: dependency_satisfied conflicts with hard blocker")

        if row.get("owner_gate") == "pending" and dep is True:
            errors.append(f"{sid}: pending owner gate cannot satisfy dependency")
        if row.get("implementation") == "blocked" and not blockers:
            errors.append(f"{sid}: implementation=blocked requires blocker")

    # The graph is authoritative for which prerequisite IDs exist. State does
    # not duplicate/redefine DAG edges.
    graph_parents = graph.get("parents", {})
    if set(graph_parents) != expected:
        errors.append("dependency_graph task IDs disagree with tasks.json")
    for sid, parents in graph_parents.items():
        for parent in parents:
            if parent not in expected:
                errors.append(f"{sid}: unknown graph parent {parent}")

    if errors:
        raise StateError("programme task-state validation failed:\n- " + "\n- ".join(errors))


def hard_prerequisites_satisfied(task_id: str, state: dict, *, root: Path = ROOT) -> bool:
    """Return readiness of a task's hard prerequisites from evidence state only."""
    validate_state(state, root=root)
    graph = load(root / "programme" / "dependency_graph.json")["parents"]
    if task_id not in graph:
        raise StateError(f"unknown task: {task_id}")
    rows = state["tasks"]
    return all(rows[parent]["dependency_satisfied"] for parent in graph[task_id])


def readiness_report(state: dict, *, root: Path = ROOT) -> dict[str, dict[str, object]]:
    validate_state(state, root=root)
    graph = load(root / "programme" / "dependency_graph.json")["parents"]
    rows = state["tasks"]
    report: dict[str, dict[str, object]] = {}
    for sid in sorted(graph):
        unsatisfied = [p for p in graph[sid] if not rows[p]["dependency_satisfied"]]
        report[sid] = {
            "hard_prerequisites_satisfied": not unsatisfied,
            "unsatisfied_parents": unsatisfied,
            "task_dependency_satisfied": rows[sid]["dependency_satisfied"],
        }
    return report


def with_issue_state(state: dict, task_id: str, issue_state: str) -> dict:
    """Test/helper operation demonstrating that issue state is only a mirror."""
    if issue_state not in ISSUE_STATE:
        raise StateError(f"invalid issue state: {issue_state}")
    out = deepcopy(state)
    out["tasks"][task_id]["github_issue"]["state"] = issue_state
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", default=str(STATE_PATH))
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--task")
    args = parser.parse_args()

    state = load(Path(args.state))
    validate_state(state)
    if args.validate:
        print(f"programme task state OK: {len(state['tasks'])} tasks")
    if args.report:
        print(json.dumps(readiness_report(state), indent=2, sort_keys=True))
    if args.task:
        print(json.dumps(readiness_report(state)[args.task], sort_keys=True))
    if not (args.validate or args.report or args.task):
        print(f"programme task state OK: {len(state['tasks'])} tasks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
