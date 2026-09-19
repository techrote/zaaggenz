# ZG-040 preregistration and reproducible study scaffold

Status: **corrective reacceptance implemented; accepted dependency evidence is gated by PR #214 final-head CI**  
Manifest version: `zaaggenz-study-manifest/1.0.0`  
Trusted dataset version: `zaaggenz-study-dataset/1.1.0`

## Corrective contract — 2026-09-19

PR #211 established the original study-manifest, calibration and reporting machinery. A post-merge adversarial review then reproduced integrity and resource-bound failures and issue #41 explicitly revoked dependency acceptance until they were repaired. PR #214 is the bounded corrective implementation. It does not reopen broad defect discovery and does not alter protected rendering/audio/provenance semantics.

The corrected contract is:

- real participant outcomes are accepted for inference only through a content-addressed `StudyEvidencePlan` and exact trusted ZG-015 `TrialManifest`/`TrialResult` objects;
- every supplied trusted result is revalidated against its exact trial and its `result_sha256` must authenticate the supplied result content;
- participant, item, condition, endpoint, stimulus and trial assignment are frozen prospectively rather than taken from the outcome row at analysis time;
- statistical item identity comes from the frozen stimulus family/raw/playback identity; one physical raw/playback identity cannot be relabelled to inflate crossed item counts;
- caller amendment/deviation iterables are consumed once into bounded immutable snapshots before lineage validation, demotion decisions and report serialization;
- the maximum participant schedule is content-addressed in the evidence plan, omitted attempted cells remain explicit missing observations, and the frozen stopping rule is executed before a completion claim;
- endpoint scale, estimand, randomisation model, analysis method and confirmatory/exploratory role are checked as one executable contract before freeze/analysis;
- descriptive-only output cannot satisfy a confirmatory primary contrast;
- paired sign randomisation and bootstrap execution is preflighted against bounded pair/work limits, executed in batches rather than one unbounded matrix, and exposes cancellation/progress hooks;
- synthetic calibration datasets remain supported but carry `evidence_authority=synthetic-fixture` and `claim_scope=synthetic-fixture-only-no-participant-claim`; they are not participant evidence.

`programme/task_state.json` is the live readiness authority. It records ZG-040 as accepted only together with the corrective PR/evidence references and the final-head gates required by issue #41.

## Boundary

ZG-040 supplies research infrastructure. It does not make the instrument depend on studies and it does not convert a creative preference into a scientific claim.

ZG-015 remains authoritative for immutable listening stimuli, exact matched playback bytes, trusted/participant capability separation, trial manifests and result provenance. ZG-040 binds those identities into a study evidence plan and derives the statistical view from trusted result content. It does not duplicate audio, rerender stimuli, alter playback, expose blinded truth to participants or redefine the ZG-015 result format.

A `StudyEvidencePlan` is trusted study-control material, not a participant-facing payload. In particular, trusted ZG-015 trial metadata may contain information intentionally omitted from participant projections.

Private reference recordings are not study-manifest payloads. A study may bind authorised derived stimulus hashes/recipes while the underlying third-party audio remains outside the repository.

## Study manifest and freeze

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

The supported study-family vocabulary is the six families in `briefs/EXPERIMENTS.md`: reference/synthetic ablations, Chordness/timbre-dependent tuning, linked violation/recovery, variation/meter/gesture direction, vocal participation, and unfamiliar grammar learning. They do not share a compulsory endpoint; bounded-continuous, ordinal, binary and target-choice endpoints can be declared separately.

`freeze_manifest()` now rejects incompatible contracts before they can become preregistered. `crossed-row-column-conservative-v1` is a mean-difference method, paired randomisation requires the frozen within-cell-pair assignment model, and `descriptive-only-v1` cannot be a confirmatory primary method.

The freeze stores the canonical manifest and content identity. `verify_frozen_manifest()` rejects later stimulus, playback, endpoint, contrast, analysis, exclusion, missingness or stopping-rule mutation. A changed manifest therefore needs a content-addressed `StudyAmendment`; historical frozen evidence is never rewritten.

Post-outcome amendments are retained and demote confirmatory interpretation. `analyse_study()` first snapshots amendments and deviations into bounded owned tuples, so list, tuple and single-use generator inputs have the same semantic effect. Operational departures use `StudyDeviation` with machine-readable phase/category/impact and can explicitly invalidate confirmatory interpretation while retaining observations as exploratory evidence.

## Prospective evidence plan and observation binding

For real evidence, `freeze_evidence_plan()` binds the complete maximum-sample schedule to the study freeze before outcome analysis. Each assignment binds:

- a preallocated participant index and pseudonymous study-local participant ID;
- authoritative frozen item/family and condition;
- exact frozen stimulus ID;
- exact trusted ZG-015 trial ID;
- endpoint and the declared extraction rule (`rating`, `choice-indicator`, or `abx-correct`).

The plan contains exact trusted ZG-015 trial manifests and is itself content-addressed. Every participant slot through `stopping_rule.max_participants` and every required participant×item×condition×endpoint cell must be present. Rating extraction also binds the focus stimulus position and the corresponding predeclared ZG-015 endpoint. Choice/ABX extraction is constrained to compatible trial/endpoint designs.

`StudyDataset.from_zg015()` is the participant-evidence constructor. It revalidates each exact result against the frozen trial, verifies the result digest, derives the outcome rather than accepting a caller-provided rating, and rejects result/item relabelling. Missing or excluded observations have null outcomes; exclusions must cite a frozen pre-outcome rule, and a completed trusted result cannot be discarded post hoc as a technical exclusion.

The resulting dataset and report carry machine-readable evidence authority and evidence-plan SHA-256. Direct `StudyDataset(...)` construction remains only for deterministic synthetic calibration fixtures and is explicitly non-participant authority.

## Planned observations, missingness and stopping

Missingness is evaluated against frozen item families and the attempted participant schedule rather than only the rows that happen to be present. A missing side of a planned condition pair contributes to the denominator and cannot disappear by deleting the row.

For `fixed-complete-cases`, the frozen maximum participant target must be reached and every primary planned cell must be complete before the stopping rule is met. A study frozen for 100 participants therefore cannot become complete merely because eight participants produced analysable rows.

For a precision-target stopping rule, analysis cannot stop before the frozen minimum participant count. After that minimum it may stop when the frozen endpoint interval half-width reaches its target; otherwise the frozen maximum participant count is the terminal bound. Reports include the machine-readable stopping decision and reason.

Missing-data thresholds and `min_complete_pairs` remain separate from stopping. Exceeding either makes the affected contrast inconclusive; satisfying them does not by itself satisfy the stopping rule.

## Analysis templates

There is deliberately no universal “best” statistic.

### `crossed-row-column-conservative-v1`

For paired condition contrasts with recurring listeners and recurring items, the template computes complete listener×item differences, then uses listener-row and item-column mean variability together:

`SE = sqrt(var(listener means)/L + var(item means)/I)`

with `min(L-1, I-1)` t degrees of freedom. It intentionally double-counts some residual contribution and is conservative relative to a fully specified mixed model. It requires at least four represented listeners and four represented items and computes the frozen `mean-difference` estimand only.

This is not presented as a universal coverage theorem. ZG-040 retains simulation calibration under explicit variance/distribution/missingness assumptions, and later studies must freeze a more specialised model if their design requires one.

### `paired-cell-randomisation-v1`

This method is legal only when the manifest freezes `within-cell-pair-v1` assignment. It performs paired-cell sign randomisation and a separately labelled paired bootstrap interval for the declared mean/median difference.

Exact sign enumeration is retained for small pair counts, but execution is batched. Larger jobs are deterministic Monte Carlo under an authoritative pair/work envelope rather than allocating the former `draws × pairs` matrices. The report retains the accepted statistical method identifier `paired-cell-sign-randomisation-v1` while its `resampling` block records pair count, exact/Monte-Carlo mode, draw counts, batching and work accounting. Cancellation and progress are checked between batches.

The randomisation test does not become valid merely because data happen to be paired after collection; assignment exchangeability must be part of the frozen design.

### `descriptive-only-v1`

Exploratory summaries may report a paired effect/uncertainty interval without a confirmatory p-value. They cannot be a confirmatory primary contrast and cannot satisfy confirmatory completion.

## Multiplicity and completion outcomes

Confirmatory studies use frozen `holm-primary-v1` adjustment across analysable primary contrasts.

The report separates `confirmatory` and `exploratory` arrays and can finish as:

- `complete-difference-detected` — the stopping rule is met and at least one frozen primary contrast crosses adjusted alpha;
- `complete-null-compatible` — the stopping rule is met and planned primary evidence did not cross alpha; explicitly not proof of equality;
- `inconclusive` — missingness/minimum-pair/stopping requirements fail or confirmatory interpretation is invalidated;
- `complete-exploratory` — the study was declared exploratory.

Null and inconclusive outcomes are first-class completions of the evidence process where appropriate. No endpoint is silently swapped and no post-hoc positive result is promoted into the confirmatory section.

## Counterbalancing and planning

`balanced_cyclic_orders()` deterministically shuffles one base order from a frozen seed and rotates it across participants. Full cycles balance every condition across every position. The public corrective surface applies an executable output-cell bound before materialising the returned schedule.

`simulate_crossed_design()` and `plan_precision()` are bounded planning tools. Their listener/item/residual SDs, effect, outcome domain and missingness are explicit assumptions, never participant estimates unless a future study records them as such.

The committed adversarial fixture retains the preflight warning: with 96 listeners but only four items under SD assumptions 0.35/0.45/1.0, a listener-only analysis is grossly anti-conservative. It remains labelled `listener-only-naive-not-for-confirmatory-use`, not as a production method. Precision output is a projection under declared assumptions, not a universal sample-size recommendation.

## Verification and reacceptance evidence

After authenticated baseline materialisation:

```sh
python -m pip install numpy==2.3.5 scipy==1.17.0 -r requirements-contracts.txt -r requirements-jobs.txt
python -m unittest discover -s tests/studies -v
python -m unittest discover -s tests/listening -v
python -m unittest discover -s tests/qc -v
python tools/study_fixture_report.py --out zg040-study-evidence.json
python tools/validate_programme_state.py --validate
python -m unittest discover -s tests/programme -p 'test_programme_*.py' -v
```

The ZG-040 workflow runs its study, inherited listening/QC and deterministic evidence gates on Ubuntu and Windows. The corrective adversarial suite covers trusted-result tampering, item relabelling, single-use audit iterables, underfilled fixed stopping plans, omitted planned cells, incompatible estimand/method contracts, the reproduced 1,792-pair resource case, bounded counterbalancing, cancellation and progress.

Synthetic evidence artifacts contain no participant data. Passing the complete final-head gate establishes the corrected reproducible study scaffold; it does not constitute a participant result, owner preference evidence, biochemical claim, or permission to redistribute private reference audio.
