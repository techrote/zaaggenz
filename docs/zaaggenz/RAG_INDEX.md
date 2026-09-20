# zaaggenz RAG / read-set index

This repository uses a **small section-oriented retrieval bundle**, not a mandatory runtime vector database. Agents should retrieve only the documents/sections needed for the current stable task, then read neighbouring context before implementation.

## Authority order

1. Recovered code/tests and accepted implementation evidence.
2. Versioned contracts/ADRs and accepted project recipes.
3. Current issue scope + master atlas.
4. Research/design briefs and source register.
5. Historical conversation snippets or screenshots only as navigation clues.

User intent controls the artistic target. Literature constrains factual/scientific claims. A proposed mathematical objective or model score is not an empirical listener result.

## Core documents

| Document | Retrieve for |
|---|---|
| `OVERVIEW.md` | task/dependency/concurrency questions; milestone and evidence-gate context |
| `CONTEXT_AND_DECISIONS.md` | protected behaviours, artistic target, authority and historical/current source-access distinction |
| `PROGRAMME_STATUS_RECONCILIATION.md` | dated status/document reconciliation audit and current-state transition record |
| `AUTHORITY_RECONCILIATION_RAG.md` | active pre-ZG-043 authority-reconciliation campaign plan, issue sequencing and autonomous execution read sets |
| `briefs/AGENT_OPERATING_RULES.md` | every implementation/research task |
| `briefs/VALIDATION_GATES.md` | acceptance evidence, tests, release readiness |
| `briefs/SPECTRAL_HARMONY.md` | ZG-013/014/017–024, 029–030, 033–034 |
| `briefs/RHYTHM_EXPECTATION.md` | ZG-025–032, 035–038 |
| `briefs/EXPERIMENTS.md` | ZG-015, ZG-033–040 |
| `briefs/ARCHITECTURE.md` | shared renderer/contracts/graph/timeline changes |
| `briefs/RISKS_AND_AUDIT.md` | default changes, overclaim risk, reference-pair limitations |
| `references/SOURCES.md` | literature/provenance claims and source-specific limitations |
| `REQUIREMENTS_TRACEABILITY.md` | why a task exists and which user requirement it addresses |
| `WORKED_WORKFLOWS.md` | target end-to-end creative/research workflow expectations |

## Active reconciliation campaign

Before changing programme state, authority-bearing front-door prose, RAG/read sets or pre-ZG-043 readiness guards, read `AUTHORITY_RECONCILIATION_RAG.md`. It records the 2026-09-19 audit findings, protected authority hierarchy, serialized repair sequence and focused read sets. #217 machine authority is merged via PR #222; #218 is the current human/RAG reconciliation; #219 follows with durable drift guards/final ZG-043 certification; separate ZG-042 hardening #220 remains a technical follow-up. The campaign document is a planning/retrieval aid; live readiness remains `programme/task_state.json`.

## Suggested read sets

### Baseline / platform — ZG-001…006
`OVERVIEW` + `CONTEXT_AND_DECISIONS` + `AGENT_OPERATING_RULES` + `VALIDATION_GATES`; add `ARCHITECTURE` once ZG-002 begins.

### Musical construction — ZG-007…011
Add `RHYTHM_EXPECTATION` for directional/modal/phrase semantics and `SPECTRAL_HARMONY` when tuning/sonority targets feed component-domain processing.

### Analysis / spectral instrument — ZG-012…024
`SPECTRAL_HARMONY` + `ARCHITECTURE` + `VALIDATION_GATES` + source IDs relevant to the chosen method. Do not substitute the paired reference for synthetic ground truth.

### Phrase / rhythm / gestures — ZG-025…032
`RHYTHM_EXPECTATION` + `ARCHITECTURE`; add `EXPERIMENTS` only when producing matched research stimuli or vocal-study infrastructure.

### Formal studies — ZG-033…040
`EXPERIMENTS` + `VALIDATION_GATES` + the creative brief that defines the manipulation + `SOURCES`. Freeze protocol/stimuli before confirmatory outcomes.

### Integration / release — ZG-041…045
`OVERVIEW` + `CONTEXT_AND_DECISIONS` + `ARCHITECTURE` + `VALIDATION_GATES` + evidence from all direct parents. Add `docs/runtime/ZG041_COMPOSE_RESEARCH.md` for the accepted Compose/Research boundary, `docs/performance/ZG042_LONGFORM.md` for long-form execution/resource authority, `docs/longform/README.md` + `docs/longform/VERIFICATION.md` for accepted ZG-043 arrangement/export ownership, and `docs/packaging/ENVIRONMENT.md` for the canonical package/environment prerequisite used by ZG-045.

### ZG-043 long-form arrangement / export
For work that consumes ZG-043 (especially ZG-044/ZG-045), read `docs/longform/README.md` then `docs/longform/VERIFICATION.md`, followed by the accepted ZG-029 ownership, ZG-030 pocket, ZG-041 Compose/Research and ZG-042 long-workload authorities referenced there. The long-form wrapper is `zaaggenz-longform-arrangement/1.0.0`; it does not replace Project v1 or Timeline v1. Simple note-event export is explicitly warning-bearing and is never authority over non-12-TET, spectral/adaptive/timbral or layer-ownership intent.

## Machine-readable orchestration

- `programme/tasks.json` — titles, planned hard dependencies, groups and shared locks.
- `programme/dependency_graph.json` — parent DAG and topological levels.
- `programme/issue_map.json` — deployed stable ID → GitHub issue number mapping.
- `programme/task_state.json` — current evidence-aware implementation/research/owner-gate/blocker state and the explicit `dependency_satisfied` decision for each stable task.

Stable IDs are the join key across documentation, commits, tests and issues. `programme/task_state.json` is the readiness authority layered over the planned DAG: GitHub issue open/closed is retained there only as an informational mirror. Validate it with `python tools/validate_programme_state.py --validate`; `--report` derives prerequisite readiness without consulting issue state. Validate the surrounding core prose with `python tools/check_programme_docs.py --check`.

## Retrieval discipline

Search for the stable ID, contract name or exact musical/DSP term first. Prefer one authoritative section plus neighbouring context to a large pile of disconnected snippets. If the expected document/artefact is missing, treat that as a blocker or documentation debt; do not fill the gap by inventing prior decisions.

### ZG-024 serial inverse-search passes
Read the current lineage in this order:

1. `docs/inverse/README.md` — laboratory/reuse boundary;
2. `docs/inverse/RECOVERED_BASELINE.md` — predecessor provenance;
3. `docs/inverse/ZG024_RESEARCH_HANDOFF_1.md` — deterministic laboratory calibration;
4. `docs/inverse/ZG024_RESEARCH_HANDOFF_2.md` — fixed-budget grid/uniform/Halton/coordinate comparison and gate interaction;
5. `docs/inverse/CANDIDATE_PROVENANCE.md` — Candidate 2.0 / authenticated search-binding evidence from completed corrective #134 / PR #187;
6. `docs/inverse/TRANSIENT_PRESERVATION_GATE.md` — accepted `zg.inverse.transient-onset-contrast.v4` eligibility diagnostic from completed #87 / PR #194;
7. `docs/inverse/TRANSIENT_V4_EVIDENCE_MIGRATION.md` — migration of frozen research evidence to the accepted transient-v4 semantics;
8. `docs/inverse/ZG024_STAGED_PROTOCOL_V2.md` — frozen staged-search protocol;
9. `docs/inverse/ZG024_STAGED_RESULT.md` — accepted mixed/no-go outcome from completed #92 / PR #195; **no production optimizer was promoted**;
10. `docs/inverse/ZG024E_DIAGNOSTIC_PROTOCOL_V1.md` — preregistered eligible-starvation/generalisation causal diagnostic;
11. `examples/zg024e-development-selection.json` — development-only frozen choice of coupled A+B search and its matched factorized null;
12. `docs/inverse/ZG024E_DIAGNOSTIC_RESULT.md` — untouched confirmation result: coupling reduces the targeted structural/spectral starvation but fails overall availability and held-out generalisation, so no production optimizer is promoted;
13. `docs/inverse/ZG024_RESEARCH_HANDOFF_3.md` — current evidence boundary and next-pass hypotheses;
14. `docs/inverse/ZG024_LINEAGE_RECONCILIATION.md` — authoritative accepted/superseded PR and branch disposition;
15. `programme/task_state.json` plus parent issue #25's latest blocker record — current readiness authority.

Do **not** restart #87, #92 or #134: those child issues are completed evidence/history. ZG-024e / #227 is also terminal research history once PR #228 is merged; do not repeat its disclosed confirmation fixtures as a fresh test set. Parent ZG-024 / #25 remains research-active: coupling now explains part of the eligible-parent starvation, but untouched confirmation did not improve eligible availability over its matched null and regressed held-out performance against the best flat controls. The current blocker is therefore narrower: `research:ZG-024-coupled-search-heldout-generalisation`.
