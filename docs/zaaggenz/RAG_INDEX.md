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
| `CONTEXT_AND_DECISIONS.md` | protected behaviours, artistic target, authority and source-access limits |
| `briefs/AGENT_OPERATING_RULES.md` | every implementation/research task |
| `briefs/VALIDATION_GATES.md` | acceptance evidence, tests, release readiness |
| `briefs/SPECTRAL_HARMONY.md` | ZG-013/014/017–024, 029–030, 033–034 |
| `briefs/RHYTHM_EXPECTATION.md` | ZG-025–032, 035–038 |
| `briefs/EXPERIMENTS.md` | ZG-015, ZG-033–040 |
| `briefs/ARCHITECTURE.md` | shared renderer/contracts/graph/timeline changes |
| `briefs/RISKS_AND_AUDIT.md` | default changes, overclaim risk, reference-pair limitations |
| `references/SOURCES.md` | literature/provenance claims and source-specific limitations |
| `REQUIREMENTS_TRACEABILITY.md` | why a task exists and which user requirement it addresses |
| `WORKED_WORKFLOWS.md` | end-to-end creative/research workflow expectations |

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
`OVERVIEW` + `CONTEXT_AND_DECISIONS` + `ARCHITECTURE` + `VALIDATION_GATES` + evidence from all direct parents.

## Machine-readable orchestration

- `programme/tasks.json` — titles, dependencies, groups and shared locks.
- `programme/dependency_graph.json` — parent DAG and topological levels.
- `programme/issue_map.json` — deployed stable ID → GitHub issue number mapping.

Stable IDs are the join key across documentation, commits, tests and issues.

## Retrieval discipline

Search for the stable ID, contract name or exact musical/DSP term first. Prefer one authoritative section plus neighbouring context to a large pile of disconnected snippets. If the expected document/artefact is missing, treat that as a blocker or documentation debt; do not fill the gap by inventing prior decisions.

### ZG-024 serial inverse-search passes
`docs/inverse/README.md` defines the ZG-024a laboratory and reuse boundaries;
`docs/inverse/RECOVERED_BASELINE.md` preserves predecessor provenance;
`docs/inverse/ZG024_RESEARCH_HANDOFF_1.md` records the first calibration and next research questions.
Issue #25 remains open: the first pass is substrate plus a bounded grid, not the final optimizer.
