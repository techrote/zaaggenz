# zaaggenz

**Offline/async rendered melodic-zaag synthesiser and investigative audio-science platform.**

This repository is bootstrapped from the audited **zaaggenz programme**: a 45-task implementation/research plan covering source-preserving synthesis, tuning and harmony, spectral retuning/Chordness, phrase and rhythm intelligence, reproducible audio research, and long-form musical construction.

Start with:

- [`docs/zaaggenz/OVERVIEW.md`](docs/zaaggenz/OVERVIEW.md) — master programme explainer, task atlas, dependencies and concurrency rules.
- [`docs/zaaggenz/RAG_INDEX.md`](docs/zaaggenz/RAG_INDEX.md) — task-oriented read-set / retrieval map for agents.
- [`docs/zaaggenz/CONTEXT_AND_DECISIONS.md`](docs/zaaggenz/CONTEXT_AND_DECISIONS.md) — protected behaviours, artistic direction and evidence boundaries.
- [`docs/zaaggenz/briefs/AGENT_OPERATING_RULES.md`](docs/zaaggenz/briefs/AGENT_OPERATING_RULES.md) — universal implementation rules.
- [`programme/tasks.json`](programme/tasks.json) / [`programme/dependency_graph.json`](programme/dependency_graph.json) — machine-readable orchestration graph.
- [`programme/issue_map.json`](programme/issue_map.json) — stable `ZG-*` IDs mapped to the deployed GitHub issue numbers.

## Direction

The artistic target is **bouncy, melodic zaag-oriented uptempo**, not generic noise maximisation and not a piep-kick clone. Research capabilities are designed to strengthen the instrument rather than turn it into a dashboard that occasionally makes sound.

```text
musical intent
  -> source-preserving notes / gestures
  -> tuning, sonority and phrase roles
  -> spectral / nonlinear / band-local transformations
  -> coordinated SYNTHLINE + exciter + BODY + AUX + SUB
  -> subtractive spectral space
  -> one declared final-output policy
```

Research follows a separate chain:

```text
registered inputs + immutable recipes
  -> calibrated measurements + uncertainty
  -> frozen matched stimuli
  -> controlled observations
  -> preregistered or explicitly exploratory analysis
  -> bounded conclusions
```

## Programme status

The complete issue programme is deployed: overview epic **ZG-000 / #1**, and implementation/research tasks **ZG-001…ZG-045 / #2…#46**. Stable `ZG-*` IDs are authoritative; GitHub issue numbers are deployment mappings.

The first implementation gate is **ZG-001**: recover and provenance-check the actual v1.2.1 source before downstream feature work assumes concrete paths or baseline hashes.

No issue title or closed state is evidence by itself. A dependency is satisfied only when the required artefact/evidence is accepted or an explicitly approved equivalent is recorded.
