# ZG-024 research handoff 3 — coupling diagnosis confirmed, generalisation remains open

**Scope:** terminal handoff from ZG-024e / child #227. Parent ZG-024 / #25 remains open and dependency-unsatisfied.

## Read this first

Use this handoff after:

1. `ZG024_RESEARCH_HANDOFF_1.md`;
2. `ZG024_RESEARCH_HANDOFF_2.md`;
3. `CANDIDATE_PROVENANCE.md`;
4. `TRANSIENT_PRESERVATION_GATE.md` and `TRANSIENT_V4_EVIDENCE_MIGRATION.md`;
5. `ZG024_STAGED_PROTOCOL_V2.md` and `ZG024_STAGED_RESULT.md`;
6. `ZG024E_DIAGNOSTIC_PROTOCOL_V1.md` and `ZG024E_DIAGNOSTIC_RESULT.md`.

Do not treat any published development or confirmation holdout in those documents as untouched again.

## What ZG-024e established

The accepted transparent search mechanism was not failing solely because of a small Stage-A/B/C budget or too-narrow parent retention. Development strongly implicated the hard A-only promotion boundary: a joint A+B stage produced eligible finals in 12/15 development cases versus 7/15 for the balanced factorized matched null. More total budget also helped, while simply retaining more eligible parents did not.

Untouched confirmation narrows that conclusion. Coupling repairs the **specific structural/spectral starvation symptom** on 2/3 seeds, but does not increase overall eligible availability versus the matched null (6/9 each) and fails the held-out non-regression rule on all three confirmation families. The result is therefore a valid mixed/no-go, not an optimizer recommendation.

## What not to do next

- Do not restore strict A→B→C as if ZG-024e had not implicated it.
- Do not promote `zg024e.coupled-ab-36.v1` into production.
- Do not weaken transient/silence/level/bandwidth/clipping gates or objective weights to make coupling pass.
- Do not use the disclosed `confirm2-*` holdouts to choose the next method.
- Do not collapse drive/input-trim or other raw parameters into a claimed original chain merely because their rendered outputs can be equivalent.
- Do not treat exact f32 PCM-equivalence grouping as cross-platform semantic identity; it is same-environment evidence.

## Narrowed next question

The active blocker is `research:ZG-024-coupled-search-heldout-generalisation`.

The next fresh preregistered experiment should ask why fit-selected coupled candidates generalise poorly even when they survive eligibility. Useful transparent hypotheses include:

- fit-side instability: candidates that look strong on the aggregate fit windows may be brittle across deterministic fit subwindows;
- observable parameterization: non-identifiable raw parameter combinations may need explicit equivalence-aware reporting/search coordinates without claiming unique recovery;
- coverage/refinement interaction: coupled A+B coverage may need to preserve more of the robust broad flat-search behavior before local C refinement.

Any next pass should keep independent sealed confirmation, multiple seeds, matched logical budgets, full candidate/Pareto lineage, the accepted safety gates and the ZG-024b flat controls. A fit-side stability signal may be investigated only if it is derived entirely from declared fitting information and preregistered before fresh confirmation disclosure.

## Integration state

ZG-024e research lives under `research/zg024e`; it does not alter `zaaggenz_inverse` production search/defaults. Parent acceptance therefore remains partial. A later production integration must be justified by fresh evidence that clears the remaining generalisation blocker, not by the development-only 12/15 availability result.

The exact ZG-024e development selection is permanently frozen in `examples/zg024e-development-selection.json`; the result and portability boundary are in `ZG024E_DIAGNOSTIC_RESULT.md`. Full CI artifacts retain per-platform exact candidate/output identities, while portable evidence compares only semantics that are intended to tolerate supported numerical-environment differences.
