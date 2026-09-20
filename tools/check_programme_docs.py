#!/usr/bin/env python3
"""Check ZaagGenZ programme prose against accepted live task state.

The checker keeps three concerns separate:

* current authority/status surfaces must consume programme/task_state.json
  rather than inventing another readiness ledger;
* dated/historical status documents must identify themselves as historical so
  their once-correct "next step" language cannot masquerade as current state;
* stable semantic invariants (recovery, reacceptance, ZG-024 terminal evidence,
  and Compose/Research ownership) are checked against the accepted live state.

Validation is deliberately offline and bounded. GitHub issue open/closed state
is never queried or used as readiness authority.
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

CURRENT_DOCS = {
    "readme": "README.md",
    "deployment": "programme/DEPLOYMENT_STATUS.md",
    "overview": "docs/zaaggenz/OVERVIEW.md",
    "context": "docs/zaaggenz/CONTEXT_AND_DECISIONS.md",
    "rag": "docs/zaaggenz/RAG_INDEX.md",
    "reconciliation": "docs/zaaggenz/PROGRAMME_STATUS_RECONCILIATION.md",
    "requirements": "docs/zaaggenz/REQUIREMENTS_TRACEABILITY.md",
    "workflows": "docs/zaaggenz/WORKED_WORKFLOWS.md",
    "studies": "docs/studies/README.md",
    "runtime": "docs/runtime/README.md",
}

HISTORICAL_DOCS = {
    "research_scratchpad": "RESEARCH_SCRATCHPAD.md",
    "preliminary_research": "PRELIMINARY_RESEARCH_RESULTS.md",
    "devmain_handoff": "docs/zaaggenz/HANDOFF_2026-09-13_DEVMAIN_CONTINUATION.md",
}

# These current programme/status documents can be mistaken for a readiness
# ledger and therefore must direct readers to the machine authority. Runtime is
# checked for product/workspace ownership below rather than task readiness.
STATUS_POINTER_DOCS = (
    "readme",
    "deployment",
    "overview",
    "context",
    "rag",
    "reconciliation",
    "requirements",
    "workflows",
    "studies",
)

BASELINE_PROVENANCE = "baseline/recovered_source/README.md"
ZIP_SHA = "90be319a4660a637077df935a8ebcbd1bb4c3a629e28e2f6d4bfe62d88dfe8a8"
RUNTIME_SHA = "eaf5d3ab822dfa121cd3b795d62619af9e62c041fb02de19f8dbeafb0014c919"

STALE_BOOTSTRAP_PATTERNS = (
    re.compile(r"actual v1\.2\.1 source/archive still has to be recovered", re.IGNORECASE),
    re.compile(r"ZG-001[^\n]{0,100}remains the first hard gate", re.IGNORECASE),
    re.compile(r"first implementation gate is[^\n]{0,40}ZG-001[^\n]{0,120}recover", re.IGNORECASE),
    re.compile(r"production-source import still requires provenance/recovery under ZG-001", re.IGNORECASE),
    re.compile(r"must establish the actual code baseline before implementation", re.IGNORECASE),
)

ZG024_REQUIRED_RAG = (
    "CANDIDATE_PROVENANCE.md",
    "TRANSIENT_PRESERVATION_GATE.md",
    "TRANSIENT_V4_EVIDENCE_MIGRATION.md",
    "ZG024_STAGED_PROTOCOL_V2.md",
    "ZG024_STAGED_RESULT.md",
    "ZG024_LINEAGE_RECONCILIATION.md",
)

RAG_STALE_TERMINAL_PATTERNS = (
    re.compile(
        r"latest accepted serial ZG-024 handoffs[^\n]*HANDOFF_1[^\n]*HANDOFF_2",
        re.IGNORECASE,
    ),
    re.compile(
        r"current serial inverse-search read set[^\n]*HANDOFF_1[^\n]*HANDOFF_2",
        re.IGNORECASE,
    ),
)


class ProgrammeDocsError(RuntimeError):
    pass


def _load_state(root: Path) -> dict:
    return json.loads((root / "programme" / "task_state.json").read_text(encoding="utf-8"))


def _load_texts(root: Path) -> tuple[dict[str, str], str]:
    paths = {**CURRENT_DOCS, **HISTORICAL_DOCS}
    docs = {name: (root / path).read_text(encoding="utf-8") for name, path in paths.items()}
    baseline = (root / BASELINE_PROVENANCE).read_text(encoding="utf-8")
    return docs, baseline


def _historical_boundary_present(text: str) -> bool:
    has_historical = re.search(r"\bhistorical\b", text, re.IGNORECASE) is not None
    has_status_boundary = re.search(
        r"(not a live[^\n]{0,80}(?:status|programme)|superseded[^\n]{0,80}live[^\n]{0,80}status|"
        r"not[^\n]{0,80}programme specification)",
        text,
        re.IGNORECASE,
    ) is not None
    return has_historical and has_status_boundary


def _current_blocker_claim(text: str, stable_id: str) -> bool:
    return (
        re.search(
            rf"\b{re.escape(stable_id)}\b[^\n]{{0,160}}"
            r"(?:currently blocks?|is (?:a )?current blocker|remains (?:a )?current blocker|still blocks?)\b",
            text,
            re.IGNORECASE,
        )
        is not None
    )


def audit_texts(docs: dict[str, str], baseline: str, state: dict) -> list[str]:
    errors: list[str] = []
    required_docs = set(CURRENT_DOCS) | set(HISTORICAL_DOCS)

    missing = sorted(required_docs - set(docs))
    if missing:
        errors.append(f"missing programme document text: {missing}")
        return errors

    for name in CURRENT_DOCS:
        text = docs[name]
        if not text.strip():
            errors.append(f"{name}: empty current authority document")

    for name in HISTORICAL_DOCS:
        text = docs[name]
        if not text.strip():
            errors.append(f"{name}: empty historical document")
        elif not _historical_boundary_present(text):
            errors.append(f"{name}: missing explicit historical/non-live-status boundary")

    # Current status-bearing surfaces must consume the accepted state authority.
    for name in STATUS_POINTER_DOCS:
        if "task_state.json" not in docs[name]:
            errors.append(f"{name}: missing task_state.json authority pointer")

    tasks = state.get("tasks", {})
    z1 = tasks.get("ZG-001", {})
    z22 = tasks.get("ZG-022", {})
    z24 = tasks.get("ZG-024", {})
    z40 = tasks.get("ZG-040", {})
    z42 = tasks.get("ZG-042", {})

    if not (
        z1.get("implementation") == "accepted"
        and z1.get("evidence") == "accepted"
        and z1.get("dependency_satisfied") is True
    ):
        errors.append("live state no longer records accepted/satisfied ZG-001 recovery")
    else:
        for name in CURRENT_DOCS:
            for pattern in STALE_BOOTSTRAP_PATTERNS:
                if pattern.search(docs[name]):
                    errors.append(
                        f"{name}: stale live ZG-001/source-recovery claim present: {pattern.pattern!r}"
                    )

    if not (z22.get("owner_gate") == "pending" and z22.get("dependency_satisfied") is False):
        errors.append("live state no longer records ZG-022 owner gate as pending/unsatisfied")

    if not (z24.get("research") == "active" and z24.get("dependency_satisfied") is False):
        errors.append("live state no longer records ZG-024 as active research/unsatisfied")

    # Reaccepted tasks may retain dated rollback history, but current authority
    # prose must not call them current blockers while the live state satisfies.
    for stable_id, row in (("ZG-040", z40), ("ZG-042", z42)):
        if row.get("dependency_satisfied") is True:
            for name in CURRENT_DOCS:
                if _current_blocker_claim(docs[name], stable_id):
                    errors.append(
                        f"{name}: {stable_id} is dependency-satisfying but prose calls it a current blocker"
                    )

    # The current inverse read set must reach the accepted post-handoff evidence,
    # preserve the mixed/no-go interpretation and forbid restarting completed
    # child work merely because the parent remains research-active.
    rag = docs["rag"]
    for required in ZG024_REQUIRED_RAG:
        if required not in rag:
            errors.append(f"rag: missing current inverse authority pointer {required}")
    rag_plain = rag.replace("*", "")
    if "no production optimizer was promoted" not in rag_plain.lower():
        errors.append("rag: missing no-production-optimizer interpretation for ZG-024")
    if "Parent ZG-024 / #25 remains research-active" not in rag_plain:
        errors.append("rag: missing current parent ZG-024 research-active interpretation")
    if "Do not restart #87, #92 or #134" not in rag_plain:
        errors.append("rag: missing completed-child do-not-restart instruction")
    for pattern in RAG_STALE_TERMINAL_PATTERNS:
        if pattern.search(rag):
            errors.append("rag: stale Handoff-1/2-only terminal research claim present")

    # Accepted runtime authority: Compose is ordinary/current state, Research is
    # a non-destructive hub over that same RuntimeSession, and trusted Listening
    # authority remains separate.
    runtime = docs["runtime"]
    if "`/timeline`" not in runtime or "ordinary music-making workspace" not in runtime:
        errors.append("runtime: missing authoritative ordinary Compose/timeline boundary")
    if "`/research`" not in runtime or "non-destructive Research hub" not in runtime:
        errors.append("runtime: missing accepted non-destructive Research hub")
    if (
        "RuntimeSession" not in runtime
        or re.search(r"(?:exactly one|sole owner)[^\n]{0,100}`RuntimeSession`", runtime, re.IGNORECASE) is None
    ):
        errors.append("runtime: missing single authoritative RuntimeSession ownership")
    if re.search(r"trusted Listening[^\n]{0,120}\bseparate\b", runtime, re.IGNORECASE) is None:
        errors.append("runtime: missing separate trusted Listening capability boundary")

    # Accepted baseline identity must agree between current context/reconciliation
    # prose and the authenticated recovered-source provenance record.
    for digest, label in ((ZIP_SHA, "original ZIP"), (RUNTIME_SHA, "runtime payload")):
        if digest not in baseline:
            errors.append(f"baseline provenance missing accepted {label} SHA-256")
        if digest not in docs["context"]:
            errors.append(f"context missing accepted {label} SHA-256")
        if digest not in docs["reconciliation"]:
            errors.append(f"reconciliation missing accepted {label} SHA-256")

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
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate current/historical programme authority documents against live task state",
    )
    args = parser.parse_args()
    check(ROOT)
    print(
        "programme documentation OK: "
        f"{len(CURRENT_DOCS)} current authority documents and "
        f"{len(HISTORICAL_DOCS)} historical status documents reconciled"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
