# ZG-040 preregistration and reproducible study scaffold

Status: **post-merge corrective-active; implementation/evidence partial; not dependency-satisfying** (issue #41 reopened 2026-09-19)  
Manifest version: `zaaggenz-study-manifest/1.0.0`

## Current corrective hold — 2026-09-19

PR #211 established useful study-manifest, calibration and reporting machinery, but independent post-merge review found trust-boundary failures that make the current implementation unsafe as a prerequisite for confirmatory studies. Until issue #41 is repaired and reclosed, the remainder of this document describes the **intended contract**, not a claim that every guarantee is currently enforced.

Known corrective requirements:

- statistical outcome values, participant/item identity and assignment identity must be authenticated against trusted ZG-015 evidence rather than accepted beside merely well-formed hashes;
- repeated/crossed item identity must not be inflatable by relabelling the same physical evidence;
- amendments/deviations must be snapshotted once before validation so generators/iterators cannot erase post-outcome demotion or audit records;
- the frozen planned observation schedule, stopping rule and missing-data denominator must be executable; omitted planned cells remain missing rather than disappearing;
- endpoint scale, estimand, analysis method and confirmatory/exploratory role must be validated as one compatible contract;
- each method must compute the declared estimand; descriptive-only output cannot satisfy a confirmatory primary contrast;
- randomisation/bootstrap cardinality, memory and work need an authoritative bounded preflight plus batched execution/cancellation where necessary.

The synthetic calibration and null/inconclusive semantics remain valuable evidence, but they do not override these integrity gaps. `programme/task_state.json` is authoritative and currently marks ZG-040 partial/research-active/not dependency-satisfying.

## Boundary

ZG-040 supplies research infrastructure. It does not make the instrument depend on studies and it does not convert a creative preference into a scientific claim.

ZG-015 remains authoritative for immutable listening stimuli, exact matched playback bytes, trusted/participant capability separation, trial manifests and result provenance. ZG-040 binds the corresponding stimulus/raw/playback/trial/result SHA-256 identities in study evidence; it does not duplicate audio, rerender stimuli or expose blinded truth.

Private reference recordings are not study-manifest payloads. A study may bind authorised derived stimulus hashes/recipes while the underlying third-party audio remains outside the repository.

## Study manifest

A manifest freezes:

- study family and confirmatory/exploratory status;
- questions and directional/two-sided hypotheses;
- exact immutable stimulus, raw PCM and matched playback SHA-256 identities;
- ZG-015 matching method, target and peak policy;
- randomisation/counterbalancing method and deterministic seed where applicable;
- endpoint-specific scale definitions;
- named condition contrasts, estimands and analysis method;
- outcome-independent exclusion rules;
- missing-data threshold/minimum complete-pair policy;
- fixed or precision-target stopping rule;
- alpha/multiplicity and explicitly permitted confirmatory methods;
- pseudonymous participant-ID/privacy policy.

The supported study-family vocabulary is the six families in `briefs/EXPERIMENTS.md`:

1. reference/synthetic ablations;
2. Chordness/timbre-dependent tuning;
3. linked violation/recovery;
4. variation/meter/gesture direction;
5. vocal participation;
6. unfamiliar grammar learning.

They do **not** share a compulsory endpoint. Bounded continuous, ordinal, binary and target-choice endpoints can be declared separately and each contrast selects its own allowed analysis template.

## Freeze, amendments and deviations

`freeze_manifest()` stores the complete canonical manifest and its content identity. `verify_frozen_manifest()` rejects any later stimulus, playback, endpoint, contrast, analysis, exclusion, missingness or stopping-rule mutation.

A changed manifest therefore needs a content-addressed `StudyAmendment`. Amendment lineage records exact JSON-pointer paths and whether the amendment occurred prospectively or after outcome access.

Post-outcome amendments must be retained and must demote the affected run from confirmatory interpretation rather than silently treating the new plan as preregistered. **Current 1.0 code has a single-use iterable defect that can bypass this guarantee; do not rely on it for confirmatory work until #41 is reclosed.**

Operational departures use `StudyDeviation` with machine-readable phase/category/impact. A deviation may explicitly mark confirmatory interpretation invalid while retaining all observations for exploratory reporting.

Historical frozen evidence is never rewritten.

## Observation binding

`StudyDataset` is intended to be a normalised statistical view over trusted study evidence. **Current 1.0 implementation does not yet authenticate caller-supplied outcome values/item identity against the referenced ZG-015 trial/result evidence; issue #41 owns that corrective boundary.** Every row is intended to bind:

- pseudonymous study-local participant ID;
- item/family ID;
- exact frozen stimulus ID;
- trusted trial ID and result SHA-256;
- condition and endpoint;
- completed/missing/excluded state;
- optional predeclared exclusion rule;
- optional bounded familiarity moderator.

The dataset itself is content-addressed to the currently authorised manifest. A dataset from another freeze/amendment cannot be analysed as if it belonged to the current study.

Missing and excluded outcomes have null values; exclusions must cite a frozen pre-outcome rule. The scaffold never fabricates substantive values for missing observations.

## Analysis templates

There is deliberately no universal “best” statistic.

### `crossed-row-column-conservative-v1`

For paired condition contrasts with recurring listeners and recurring items, the template computes complete listener×item differences, then uses listener-row and item-column mean variability together:

`SE = sqrt(var(listener means)/L + var(item means)/I)`

with `min(L-1, I-1)` t degrees of freedom.

This intentionally double-counts some residual contribution and is conservative relative to a fully specified mixed model. Its role is a transparent bounded template, particularly when item cardinality is small. It requires at least four represented listeners and four represented items.

It is **not** presented as a universal coverage theorem. ZG-040 retains simulation calibration under explicit variance/distribution/missingness assumptions, and later studies must freeze a more specialised model if their design requires one.

### `paired-cell-randomisation-v1`

This template is legal only when the manifest freezes `within-cell-pair-v1` assignment. It performs sign randomisation of complete paired cells (exact through 16 cells, otherwise deterministic 32,768 draws) and reports a separately labelled 4,096-draw paired-cell bootstrap interval for the effect.

The randomisation test does not become valid merely because data happen to be paired after collection; assignment exchangeability must be part of the frozen design.

### `descriptive-only-v1`

Exploratory summaries may report paired effect/uncertainty without a confirmatory p-value. They cannot satisfy a confirmatory contrast.

## Multiplicity and completion outcomes

Confirmatory studies use frozen `holm-primary-v1` adjustment across analysable primary contrasts.

The report separates `confirmatory` and `exploratory` arrays and can finish as:

- `complete-difference-detected` — at least one frozen primary contrast crosses adjusted alpha;
- `complete-null-compatible` — planned primary evidence did not cross alpha; explicitly **not** proof of equality;
- `inconclusive` — missingness/minimum-pair requirements fail or confirmatory interpretation is invalidated;
- `complete-exploratory` — the study was declared exploratory.

Null and inconclusive outcomes are first-class completions when the planned evidence product is otherwise complete. No endpoint is silently swapped and no post-hoc positive result is promoted into the confirmatory section.

## Counterbalancing and planning

`balanced_cyclic_orders()` deterministically shuffles one base order from a frozen seed and rotates it across participants. Full cycles balance every condition across every position.

`simulate_crossed_design()` and `plan_precision()` are bounded planning tools. Their listener/item/residual SDs, effect, outcome domain and missingness are explicit **assumptions**, never participant estimates unless a future study records them as such.

The committed adversarial fixture deliberately repeats the preflight warning: with 96 listeners but only four items under SD assumptions 0.35/0.45/1.0, a listener-only analysis is grossly anti-conservative. It is retained as `listener-only-naive-not-for-confirmatory-use`, not as an available production method.

Precision output reports expected interval width/coverage under assumptions and whether a candidate grid meets a target. It is not a universal sample-size recommendation.

## Verification

After authenticated baseline materialisation:

```sh
python -m pip install numpy==2.3.5 scipy==1.17.0 -r requirements-contracts.txt -r requirements-jobs.txt
python -m unittest discover -s tests/studies -v
python tools/study_fixture_report.py --out zg040-study-evidence.json
```

The ZG-040 workflow runs on Ubuntu and Windows and also runs the accepted listening/QC regression suites. Evidence contains only synthetic manifests/datasets and assumed-variance simulations.

Passing this gate establishes a reproducible scaffold suitable for later protocol-specific work. It does not constitute participant evidence, owner preference evidence, a biochemical claim, or approval to redistribute private reference audio.
