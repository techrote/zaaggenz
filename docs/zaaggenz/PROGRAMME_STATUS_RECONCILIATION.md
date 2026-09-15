# Programme status reconciliation — 2026-09-15

This record closes the bootstrap-era documentation contradiction tracked by issue #88. It does not replace the machine-readable programme state. Live implementation/evidence/research/owner-gate/readiness truth is [`programme/task_state.json`](../../programme/task_state.json); the documents below serve distinct explanatory roles.

## Authority and audit result

Authority remains:

1. accepted code, tests and completion/evidence records;
2. versioned contracts/ADRs and accepted recipes;
3. `programme/task_state.json` for current stable-task state/readiness;
4. current issue scope and master atlas;
5. research/design briefs;
6. historical conversation/planning snapshots as navigation/provenance only.

The stable `ZG-001…ZG-045` atlas, `programme/tasks.json`, `programme/dependency_graph.json` and `programme/issue_map.json` were checked during this reconciliation. No planned DAG edge or stable-ID mapping was changed: the defect was stale narrative status, not a newly proven dependency-graph error.

## Core document disposition

| Document | Status after audit | Reconciliation |
|---|---|---|
| `OVERVIEW.md` | current status pointer valid | #89 made `task_state.json` the live readiness authority and converted the old ZG-001 blocker into historical context. No second status vocabulary is introduced here. |
| `CONTEXT_AND_DECISIONS.md` | **stale planning claims repaired** | Keeps the original access snapshot as explicitly historical, adds accepted ZG-001 archive/runtime identities, and points live status to `task_state.json`. |
| `RAG_INDEX.md` | current | Already points to `task_state.json` and the latest accepted serial ZG-024 handoffs (`ZG024_RESEARCH_HANDOFF_1.md` and `_2.md`). |
| `REQUIREMENTS_TRACEABILITY.md` | status-neutral | Explicitly labelled a requirements map, not a live completion report; readiness points to `task_state.json`. |
| `WORKED_WORKFLOWS.md` | status-neutral | Explicitly labelled target end-to-end workflows, not assertions that every capability is complete. |
| `programme/tasks.json` | retained | Planned task metadata/dependencies/locks remain authoritative for the planned programme. |
| `programme/dependency_graph.json` | retained | Planned parent DAG unchanged. |
| `programme/issue_map.json` | retained | Stable-ID → top-level issue mapping unchanged. |
| `programme/task_state.json` | live state authority | Orthogonal implementation/evidence/research/owner-gate/blocker/readiness state accepted in #89. |

## Current programme snapshot

This summary is descriptive; the JSON state is authoritative.

- **ZG-001:** baseline recovery/provenance is accepted. The original owner-supplied ZIP SHA-256 is `90be319a4660a637077df935a8ebcbd1bb4c3a629e28e2f6d4bfe62d88dfe8a8`; the compact recovered runtime payload SHA-256 is `eaf5d3ab822dfa121cd3b795d62619af9e62c041fb02de19f8dbeafb0014c919`. Source recovery is **not** a current blocker.
- **ZG-002…ZG-021:** accepted implementation/evidence is currently dependency-satisfying according to `task_state.json`; corrective follow-ups may still harden individual boundaries without automatically erasing accepted prerequisite evidence.
- **ZG-022:** substantial implementation/evidence is accepted, but the owner listening/default-approval gate remains pending. It is not dependency-satisfying.
- **ZG-023:** accepted and dependency-satisfying; #94 separately hardens real immutable source binding before later workspace integration relies on it.
- **ZG-024:** serial inverse-search research remains active. PR #84 and PR #86 plus handoffs 1/2 are accepted partial evidence; #87/#92/#134 remain relevant and the parent is not dependency-satisfying.
- **ZG-025…ZG-027:** accepted and dependency-satisfying under the current state record.
- **ZG-028:** accepted implementation evidence exists, but completion/readiness is explicitly withheld by corrective blockers including #138; GitHub issue state therefore cannot be used as a proxy.
- **ZG-029:** active/partial with #91 ownership reconciliation outstanding. **ZG-030** remains blocked on ZG-029.
- **ZG-031/ZG-032:** accepted and dependency-satisfying under the current state record, with separate corrective work still tracked where applicable.
- **ZG-033…ZG-040:** formal study/research tasks remain planned rather than silently inferred complete from their prerequisites.
- **ZG-041…ZG-045:** later integration/performance/export/release work remains unsatisfied/not-started according to the state record; specific reconciliation/prerequisite blockers remain explicit where known.

## Historical source/access correction

The original planning audit correctly refused to invent production source when the v1.2.1 archive was unavailable to that run. That was a sound **historical** blocker. ZG-001 later recovered the exact owner archive and authenticated a compact source payload containing the application/runtime, 13 smoke tests, launchers, requirements and key examples. `baseline/recovered_source/README.md` is the provenance authority and materialised `app/...` paths are the concrete downstream baseline.

Accordingly, future documentation may describe source unavailability only as dated planning history. Present-tense language such as “ZG-001 must recover the source before implementation” or “production-source import is still gated” is contradictory and is rejected by the programme-document check.

## ZG-024 read-set reconciliation

The current serial inverse-search read set is:

- `docs/inverse/README.md` — laboratory/reuse boundary;
- `docs/inverse/RECOVERED_BASELINE.md` — predecessor provenance;
- `docs/inverse/ZG024_RESEARCH_HANDOFF_1.md` — deterministic laboratory calibration;
- `docs/inverse/ZG024_RESEARCH_HANDOFF_2.md` — fixed-budget strategy comparison and staged-search direction.

These are accepted partial/research handoffs, not evidence that parent ZG-024 is complete. Issue #25 remains the parent research task.

## Reproducible future audit

Run:

```sh
python tools/validate_programme_state.py --validate
python tools/check_programme_docs.py --check
python -m unittest discover -s tests/programme -p 'test_programme_*.py' -v
```

`check_programme_docs.py` verifies the core document set exists, points status-bearing prose to the accepted state authority, retains the latest ZG-024 handoff pointers, confirms key live state (ZG-001 resolved; ZG-022 owner-gated; ZG-024 active), checks the accepted baseline hashes against the recovered-source provenance document, and rejects known bootstrap-era present-tense blocker phrases.

When implementation/evidence changes, update `task_state.json` through review first. Narrative documents should consume that state rather than inventing a parallel completion vocabulary.
