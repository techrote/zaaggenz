# zaaggenz

**Offline/async rendered melodic-zaag synthesiser and investigative audio-science platform.**

This repository is being bootstrapped from the audited **zaaggenz programme**: a 45-task implementation/research plan covering source-preserving synthesis, tuning and harmony, spectral retuning/Chordness, phrase and rhythm intelligence, reproducible audio research, and long-form musical construction.

Start with:

- [`docs/zaaggenz/OVERVIEW.md`](docs/zaaggenz/OVERVIEW.md) — master programme explainer and task atlas.
- [`docs/zaaggenz/RAG_INDEX.md`](docs/zaaggenz/RAG_INDEX.md) — section-oriented retrieval map for agents.
- [`docs/zaaggenz/CONTEXT_AND_DECISIONS.md`](docs/zaaggenz/CONTEXT_AND_DECISIONS.md) — protected behaviours and decision history.
- [`docs/zaaggenz/briefs/AGENT_OPERATING_RULES.md`](docs/zaaggenz/briefs/AGENT_OPERATING_RULES.md) — implementation rules for agentic work.
- [`programme/tasks.json`](programme/tasks.json) and [`programme/dependency_graph.json`](programme/dependency_graph.json) — machine-readable orchestration graph.

## Direction

The artistic target is **bouncy, melodic zaag-oriented uptempo**, not generic noise maximisation and not a piep-kick clone. Research capabilities are designed to strengthen the instrument rather than turn it into a dashboard that occasionally makes sound.

The central product chain is:

```text
musical intent
  -> source-preserving notes / gestures
  -> tuning, sonority and phrase roles
  -> spectral / nonlinear / band-local transformations
  -> coordinated SYNTHLINE + exciter + BODY + AUX + SUB
  -> subtractive spectral space
  -> one declared final-output policy
```

The scientific chain is:

```text
registered inputs + immutable recipes
  -> calibrated measurements + uncertainty
  -> frozen matched stimuli
  -> blinded observations
  -> preregistered or explicitly exploratory analysis
  -> bounded conclusions
```

## Programme status

The planning bundle has been audited and is being published as GitHub issues with stable IDs `ZG-001` … `ZG-045`, plus overview epic `ZG-000`. Stable IDs are authoritative; GitHub issue numbers are deployment artefacts.

No issue title or closed state is evidence by itself. Dependencies count as satisfied only when their required artefacts/evidence are merged or an explicitly approved equivalent is recorded.
