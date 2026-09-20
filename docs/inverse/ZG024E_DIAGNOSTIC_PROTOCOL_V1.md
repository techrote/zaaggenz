# ZG-024e preregistered feasibility/generalisation diagnostic protocol v1

**Child issue:** #227 · **Parent:** ZG-024 / #25  
**Status:** design freeze; this document is committed before ZG-024e confirmation fixtures exist or any ZG-024e development outcome is inspected.

## Research question

Accepted ZG-024d established that the transparent staged mechanism preserves lineage, fit/holdout isolation, hard-gate integrity, replay and portability, but it did not provide reliable **eligible-candidate availability plus held-out improvement**. The selected 24-evaluation staged method produced no eligible result for any seed of `confirm-structure-spectral`, and mixed-texture held-out performance regressed.

ZG-024e tests three causal explanations without weakening gates or using holdout feedback:

1. **stage-budget allocation failure** — too little total or family-specific coverage;
2. **eligible-parent starvation / promotion bottlenecks** — useful eligible alternatives are discarded before downstream search;
3. **cross-family coupling / identifiability failure** — A-only intermediates are poor or ineligible unless structural and spectral coordinates can move together.

A null/mixed result is valid. This protocol does not authorize an opaque optimizer, production promotion, gate retuning, objective reweighting, or a claim of original-chain recovery.

## Capability and safety boundary

Search receives only `FitEvaluator`. Fixture truth and `AuditEvaluator` are orchestration-only capabilities.

Holdout samples and holdout measurements are unavailable to proposal, promotion, ranking, stopping, method selection and causal-hypothesis selection. Parameter truth is diagnostic only after selection. Rejected/ineligible candidates are never promoted.

The accepted transient method `zg.inverse.transient-onset-contrast.v4`, silence, level, energy/bandwidth, clipping, hidden-normalisation, non-finite and provenance gates remain unchanged. Their thresholds, objective weights/scales and portable tolerances are frozen.

No source PCM, renderer/DSP topology, tuning, project/default semantics, private-reference/final-master semantics, protected audio ownership or `locked_bloom` may change.

## Parameter families

Use the accepted ZG-024d family partition unchanged:

- **A — structure:** root/pitch/timing/envelope axes.
- **B — spectral:** harmonic/spectral axes.
- **C — texture:** local nonlinearity/texture axes.

Every fixture axis belongs to exactly one family. Unknown axes fail closed.

## Frozen diagnostic methods

All normal methods use deterministic shifted-Halton coverage and the accepted coordinate-refinement primitive. Duplicate proposals do not consume logical budget. Cold foundation evaluation still verifies each candidate twice.

### Accepted-style control

- `zg024e.factorized-24-control.v1`
- total budget **24**
- A/B/C = **10/7/7**
- promotion cap **4**
- identical factorized stage semantics to accepted ZG-024d structure allocation, but on fresh ZG-024e fixtures.

### Equal-total 36-evaluation allocation interventions

All three below consume **36** logical evaluations and retain at most **4** eligible parents:

- `zg024e.factorized-36-balanced.v1`: A/B/C = **12/12/12**
- `zg024e.factorized-36-a-heavy.v1`: A/B/C = **16/10/10**
- `zg024e.factorized-36-b-heavy.v1`: A/B/C = **10/16/10**

These distinguish more total coverage from family-specific reallocation while keeping the 36-evaluation cohort fair.

### Parent-retention intervention

- `zg024e.factorized-36-wide-parents.v1`
- A/B/C = **12/12/12**
- promotion cap **8**

Its matched null is `factorized-36-balanced`. Only eligible candidates may fill the wider retained set; rejected candidates remain unavailable.

### Coupling intervention

- `zg024e.coupled-ab-36.v1`
- first stage **AB = 24** shifted-Halton proposals that vary A+B coordinates jointly from the base state;
- promotion cap **4**;
- second stage **C = 12** bounded coordinate refinement/labelled continuation around retained AB alternatives.

There is no A-only promotion boundary in this method. Its matched null is `factorized-36-balanced`. This directly tests whether A-only intermediates are an artificial bottleneck when structural and spectral changes must compensate one another.

## Flat controls

The accepted flat ZG-024b methods remain controls:

- `zg024b.uniform-splitmix.v1`
- `zg024b.halton-shifted.v1`
- `zg024b.coordinate-refine.v1`

They run at **24** evaluations for the accepted-style control cohort and **36** evaluations for the 36-evaluation cohort. Grid prefix remains excluded for the same order-dependence reason recorded by ZG-024d.

## Fresh development programme

Search seeds are **53, 307, 4099**.

Development fixtures are new target/base combinations and use independent fit/tail-holdout windows distinct from the published ZG-024d confirmation catalogue:

1. `dev2-structure-spectral-starvation` — simultaneous A+B displacement, designed to expose whether an A-only promotion boundary starves a compensating spectral move.
2. `dev2-structure-budget` — dominant A displacement with B/C nuisance dimensions.
3. `dev2-spectral-budget` — dominant B displacement with A/C nuisance dimensions.
4. `dev2-mixed-texture` — meaningful A+B+C displacement.
5. `dev2-identifiability` — fresh drive/input-trim equivalence with structural/spectral nuisance dimensions.

Three safety sentinels reuse only the accepted gate semantics, not prior outcomes: transient destruction, silence, and destructive clipping. Sentinels cannot select a method or causal hypothesis.

## Development-only selection and causal diagnosis

For every development fixture/seed, record final eligible availability, best fit score, stage consumption, stop reason, complete rejection reasons, promotion ancestry, Pareto/equivalence structure, physical render calls and cache hits. Holdout is audited only after the development choice is frozen and cannot affect it.

### Intervention selection

Eligible final availability is the primary endpoint. Among the five 36-evaluation diagnostic methods, select the method with:

1. most development cases (of 15) with at least one eligible final alternative;
2. then fewest fail-closed starvation stops;
3. then lowest median eligible best-fit score;
4. then lexicographic method ID.

This is a diagnostic intervention selection, not production optimizer selection.

### Matched causal comparisons

Predeclare the matched null for each causal question:

- **more total budget:** `factorized-36-balanced` vs `factorized-24-control`;
- **A reallocation:** `factorized-36-a-heavy` vs `factorized-36-balanced`;
- **B reallocation:** `factorized-36-b-heavy` vs `factorized-36-balanced`;
- **parent breadth:** `factorized-36-wide-parents` vs `factorized-36-balanced`;
- **A+B coupling:** `coupled-ab-36` vs `factorized-36-balanced`.

A mechanism is **development-supported** only if its intervention gains at least **3/15** eligible-final cases over its matched null, introduces zero ineligible promotions, and does not create more than three additional >10% fit regressions among cases where both methods have finite eligible fits.

If multiple mechanisms pass, the selected intervention's own matched mechanism is the frozen primary hypothesis; other passing mechanisms remain secondary evidence. If none passes, the primary diagnosis is `no-single-tested-mechanism-supported`.

The selected intervention, its matched null and the primary diagnosis are written to a development-selection record **before** the confirmation module is added.

## Sealed confirmation programme

The confirmation module must not exist at this design-freeze commit. It will be added only after the development-selection record is frozen.

It will contain three new targets, distinct from ZG-024d and ZG-024e development targets:

1. `confirm2-structure-spectral-starvation`
2. `confirm2-mixed-texture`
3. `confirm2-identifiability-coupled`

The frozen selected intervention and its matched null are both run on all three seeds. Equal-budget flat controls are run at the selected intervention's budget. The accepted-style 24-evaluation control is also retained as historical-mechanism context. Confirmation cannot switch to another intervention after disclosure.

## Positive-result decision rule

A ZG-024e positive result requires **all** of the following on untouched confirmation material:

1. the selected intervention produces an eligible final alternative on at least **2/3** seeds of `confirm2-structure-spectral-starvation`;
2. it has eligible final alternatives on at least **7/9** confirmation fixture/seed cases;
3. it gains at least **2/9** eligible-final cases over its frozen matched null;
4. zero ineligible candidate is promoted or selected;
5. every safety sentinel still records the expected hard-gate rejection and no rejected sentinel candidate is promoted;
6. for every confirmation fixture where both medians are finite, selected median holdout score is no worse than **1.10×** the best equal-budget flat-control median, with no holdout used as feedback;
7. exact logical-budget accounting, same-environment deterministic replay/checkpoint/cancellation and cache-identity separation pass;
8. Ubuntu and Windows portable evidence agree under absolute **1e-7**, relative **1e-5** tolerance.

Fit improvement without eligible availability and held-out non-regression is not success.

If the selected intervention improves eligibility but fails the holdout rule, record that the diagnosed mechanism reduces starvation but does not solve generalisation. If coupling is the supported mechanism, state that the strict A→B→C factorisation is implicated; do not force another factorized optimizer. If no mechanism survives confirmation, retain the null/mixed result and narrow the blocker accordingly.

## Production and parent-state rule

ZG-024e does **not** promote a production optimizer merely because the diagnostic rule passes. Parent #25 may become dependency-satisfied only if its complete acceptance contract is independently shown to be met, including editable Pareto alternatives, holdout/generalisation, anti-degeneracy, deterministic lineage/replay and accepted integration evidence.

Otherwise production search remains unchanged, #25 remains open/research-active/dependency-unsatisfied, and its blocker is replaced only by a narrower evidence-backed next question.

## Evidence requirements

Full artifacts retain:

- exact SearchRequest and candidate/provenance identities;
- method/design/environment identities;
- all candidate records and decomposed fit/validation data;
- parent/promotion ancestry and exact-output equivalence groups;
- consumed/unspent logical budgets and proposal attempts;
- post-selection holdout audit;
- physical render/cache telemetry;
- checkpoint/replay/cancellation evidence.

Portable evidence excludes wall-clock timing and environment-specific hashes but retains all decision-relevant numeric/discrete outcomes.

All inherited ZG-024a/b/d, Candidate 2.0 provenance, transient-v4, contract and programme-authority regressions remain required.
