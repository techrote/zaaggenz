#!/usr/bin/env python3
"""Check core ZaagGenZ programme prose against accepted live task state.

This is intentionally narrow. It prevents known bootstrap-era status claims from
returning and verifies that status-bearing documents consume the accepted
`programme/task_state.json` authority instead of inventing another status
vocabulary. It does not infer implementation status from prose or GitHub issue
open/closed state.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from validate_programme_state import validate_state  # noqa: E402

CORE_DOCS = {
    "overview": "docs/zaaggenz/OVERVIEW.md",
    "context": "docs/zaaggenz/CONTEXT_AND_DECISIONS.md",
    "rag": "docs/zaaggenz/RAG_INDEX.md",
    "requirements": "docs/zaaggenz/REQUIREMENTS_TRACEABILITY.md",
    "workflows": "docs/zaaggenz/WORKED_WORKFLOWS.md",
    "reconciliation": "docs/zaaggenz/PROGRAMME_STATUS_RECONCILIATION.md",
}
BASELINE_PROVENANCE = "baseline/recovered_source/README.md"
ZIP_SHA = "90be319a4660a637077df935a8ebcbd1bb4c3a629e28e2f6d4bfe62d88dfe8a8"
RUNTIME_SHA = "eaf5d3ab822dfa121cd3b795d62619af9e62c041fb02de19f8dbeafb0014c919"

# These exact forms are live-status assertions from the bootstrap/planning era.
# Historical text may discuss prior unavailability when explicitly dated/labeled.
STALE_LIVE_PHRASES = (
    "The **actual v1.2.1 source/archive still has to be recovered",
    "production-source import still requires provenance/recovery under ZG-001",
    "must establish the actual code baseline before implementation",
    "v1.2.1 source archive | Not present in this run's filesystem",
)


class ProgrammeDocsError(RuntimeError):
    pass


def _load_state(root: Path) -> dict:
    return json.loads((root / "programme" / "task_state.json").read_text(encoding="utf-8"))


def _load_texts(root: Path) -> tuple[dict[str, str], str]:
    docs = {name: (root / path).read_text(encoding="utf-8") for name, path in CORE_DOCS.items()}
    baseline = (root / BASELINE_PROVENANCE).read_text(encoding="utf-8")
    return docs, baseline


def audit_texts(docs: dict[str, str], baseline: str, state: dict) -> list[str]:
    errors: list[str] = []

    missing = sorted(set(CORE_DOCS) - set(docs))
    if missing:
        errors.append(f"missing core document text: {missing}")
        return errors

    for name, text in docs.items():
        if not text.strip():
            errors.append(f"{name}: empty document")
        for phrase in STALE_LIVE_PHRASES:
            if phrase in text:
                errors.append(f"{name}: stale live bootstrap claim present: {phrase!r}")

    # Every core document that can be mistaken for current programme status must
    # direct readers to the accepted state authority.
    for name in ("overview", "context", "rag", "requirements", "workflows", "reconciliation"):
        if "task_state.json" not in docs[name]:
            errors.append(f"{name}: missing task_state.json authority pointer")

    # The serial inverse read set must not regress to the older handoff only.
    for handoff in ("ZG024_RESEARCH_HANDOFF_1.md", "ZG024_RESEARCH_HANDOFF_2.md"):
        if handoff not in docs["rag"]:
            errors.append(f"rag: missing current inverse handoff pointer {handoff}")
        if handoff not in docs["reconciliation"]:
            errors.append(f"reconciliation: missing inverse handoff pointer {handoff}")

    # Accepted baseline identity must agree between current context/reconciliation
    # prose and the authenticated recovered-source provenance record.
    for digest, label in ((ZIP_SHA, "original ZIP"), (RUNTIME_SHA, "runtime payload")):
        if digest not in baseline:
            errors.append(f"baseline provenance missing accepted {label} SHA-256")
        if digest not in docs["context"]:
            errors.append(f"context missing accepted {label} SHA-256")
        if digest not in docs["reconciliation"]:
            errors.append(f"reconciliation missing accepted {label} SHA-256")

    tasks = state.get("tasks", {})
    z1 = tasks.get("ZG-001", {})
    if not (
        z1.get("implementation") == "accepted"
        and z1.get("evidence") == "accepted"
        and z1.get("dependency_satisfied") is True
    ):
        errors.append("live state no longer records accepted/satisfied ZG-001 recovery")

    z22 = tasks.get("ZG-022", {})
    if not (z22.get("owner_gate") == "pending" and z22.get("dependency_satisfied") is False):
        errors.append("live state no longer records ZG-022 owner gate as pending/unsatisfied")

    z24 = tasks.get("ZG-024", {})
    if not (z24.get("research") == "active" and z24.get("dependency_satisfied") is False):
        errors.append("live state no longer records ZG-024 as active research/unsatisfied")

    # Requirements/workflow prose must explicitly disclaim status authority.
    if "not a live implementation-status report" not in docs["requirements"]:
        errors.append("requirements: missing non-status disclaimer")
    if not re.search(r"target end-to-end workflows", docs["workflows"], re.IGNORECASE):
        errors.append("workflows: missing target-workflow disclaimer")

    return errors


def check(root: Path = ROOT) -> None:
    state = _load_state(root)
    validate_state(state, root=root)
    docs, baseline = _load_texts(root)
    errors = audit_texts(docs, baseline, state)
    if errors:
        raise ProgrammeDocsError("programme documentation reconciliation failed:\n- " + "\n- ".join(errors))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="validate core programme documentation against live task state")
    args = parser.parse_args()
    check(ROOT)
    print(f"programme documentation OK: {len(CORE_DOCS)} core documents reconciled")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
