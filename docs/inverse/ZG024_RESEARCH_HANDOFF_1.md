# ZG-024 research handoff 1 — foundations, not the final optimizer

**Scope:** ZG-024a / Startoff 1, issue #25 remains open. Base inspected: `6e0153d824608d6a9899c5ea8e8c0b9a29688c98`. No protected source/default changes, mandatory model, online optimizer, production UI replacement or claim of recovering an original chain.

## Architecture to attack experimentally

`zaaggenz_inverse` supplies small `1.0.0` contracts for bounded parameter axes/state, windows, objective/validation policy, stage/seed/budget, existing-recipe search requests, candidates, audit selection and checkpoints. It composes accepted contracts and `zg-c14n-v1`; source revisions come from `Project`, target/render audio uses `AudioAssetRef`, and exports are normal editable `RenderRecipe` values. Read [README](README.md) for exact formulas and invariants.

`recipes.py` binds numeric source/graph/automation/master-gain values through the existing registry and renderer. `objectives.py` reuses STFT, ZG-014 descriptors, ZG-018 Chordness, ZG-019 transients and ZG-020 timbre interaction, preserving component validity and observations. `laboratory.py` separates fit-only capability from the audit owner. `search.py` uses the existing scheduler/research lane, caches and atomic checkpoint publication. The recovered differential-evolution predecessor is unchanged and characterized separately in [RECOVERED_BASELINE](RECOVERED_BASELINE.md).

Useful entry points: `fixture.experiment()`, `run_grid(fit)`, `result.audit_selection(...)`, `audit.evaluate(candidate, selection)`, `submit_search_job(...)`, `save_checkpoint/load_checkpoint`. Search receives **no fixture, ground truth or holdout samples**. New algorithms should consume this fit-only interface rather than invent another renderer, objective, source state or scheduler.

## Exact deliberately boring baseline

`zg.inverse.cyclic-grid.v1`: canonical-pointer-sorted Cartesian product of three evenly spaced inclusive levels per axis in the fixtures. Integer levels use ties-to-even and deduplication. Start at `derive_seed(root_seed, 'inverse-grid-v1') % grid_size`, then take a cyclic prefix until the declared evaluation budget or product is exhausted. The ordering is independent of target hash/content. There is no adaptive refinement, fitted initialization, ML, population search or learned surrogate.

All candidates are retained. Eligible scalar rank is fit-only with ordinal tie-breaking; Pareto membership uses declared component axes, including explicit zero-weight diagnostics. Equivalent nondominated recipes are not merged. Each cold candidate renders twice for exact same-environment verification; physical repeats do not secretly increase the logical search budget. Parameter bounds are checked before rendering.

## Fixture catalogue and observed calibration

All targets are deterministic 6,000-sample / 12 kHz, one-beat synthetic experiments, source seed 24 and grid root seed `"24"`. Default fitting windows are `[0,1600)` and `[2200,3400)`; independent holdout is `[4000,5600)`. Truth belongs only to generation/tests/evidence. Exact identities, parameter bounds, states, seeds, losses and holdouts are in `examples/zg024a_inverse_calibration.json.gz`; the report command regenerates full records and checks that frozen calibration.

| Fixture | Axes / logical budget | Observation |
|---|---|---|
| identifiable | f0 60–84 Hz; decay 120–280 ms; 9 | Correct in-grid 72 Hz / 200 ms recipe has fit = holdout = 0 and a singleton fit frontier. This is a calibration positive control, not demonstrated arbitrary continuous recovery. |
| weak-residual | noise 0–0.006; decay 80–280 ms; 9 | Exact in-grid best; alternatives have fit scores about 0.001986 and 0.002858. Noise decay is exactly unobservable when noise level is zero. Small numerical distinctions should not be presented as strong identifiability. |
| drive-trim-equivalence | drive 10–14 dB; input trim −12…−8 dB; 9 | Three materially different recipes have identical PCM and zero losses because their drive-plus-trim sums coincide. All three remain on the frontier. |
| polarity-feature-conflict | harmonic count 7, 9, 11; 3 | Target is explicit polarity inversion. Spectral/level fit can be 0 while relative waveform error is 2. Waveform remains an explicit zero-weight Pareto axis; frontier retains two trade-offs. |
| holdout-step | late graph gain −6, 0, +6 dB at sample 3600; 3 | Every recipe fits both fit windows exactly. Holdout scores are **1.3065778324**, **0.7065475576**, **0**, respectively; the first two trigger the overfit warning. Holdouts do not pick the search winner. |
| sonority-nonlinear | accepted 2× antialiased tanh wet 0, 0.35, 0.7; 3 | Rich partial/Chordness/roughness/interaction path; known wet=0.35 gives exact fit and holdout. Non-best fit scores are about 0.096850 and 0.103049. |

Total: **36 retained logical candidates, 30 fit-eligible**, 72 cold verification renders plus 36 independent audit re-renders. The original recovered smoke, kept separate, improves **0.3585931590 → 0.3501547175**, 133 evaluations, quick differential evolution, `maxiter=3`, `popsize=3`, seed 7. It receives its inherited known-f0 hint. Its targets, loss normalization and budget differ, so comparing those scores to the grid as an optimizer competition would be invalid.

## Gates and fit/holdout interpretation

Waveform, magnitude-spectrum, absolute-level, periodicity, occupancy, comb-fit, relative roughness and timbre-interaction losses remain distinct; nullable descriptor abstention is not zero. The scalar is only explicit weighted RMS of scaled component losses, not a listening score. Raw target/candidate levels and enough intermediate descriptor/gain measurements are retained for reanalysis.

Separate gates cover silence, unintended level shifts, multiple lost attacks per channel, saturation/plateaus below or at full scale, bandwidth/absolute-band-energy collapse, invalid/non-finite data, actual final-output clipping, gain-normalization exploits and parameter bounds. Candidate parser checks state/recipe and result-component consistency. Optional acoustic exceptions are explicit `accepted-with-exceptions`; hidden gain handling, non-finite data and invalid provenance cannot be permitted.

The renderer still has accepted internal legacy RMS/noise-standard-deviation/final-peak normalization. Observable source/pre-master/post-gain/output levels and the exact output policy are recorded; unobservable internal gain factors remain **null**. Do not claim fully recovered gain history. Matching an aggressively distorted target is not automatically pathological: plateau excess is relative to that target, while destructive final clipping is separately measured.

The audit warning (`fit < 0.05`, `holdout-fit > 0.25`) is an exploratory engineering indicator, not a significance test. Tests alter holdout samples and adjacent out-of-fit padding without altering fit measurements or grid order. Repeatedly choosing research directions from this published holdout would consume it; reserve new fixtures/test windows before confirmatory comparisons.

## Reuse, determinism and cost

Render keys reuse the project cache convention, independently of search budget/target; feature keys include canonical excerpt PCM and all accepted method/configuration identities. Both use existing bounded `AnalysisCache`, eight entries by default. Equal-PCM recipes retain their own identity but share feature work: measured fit-cache hits/misses were 26/10 for drive-trim equivalence and 10/2 for holdout-step. Whole-signal/audit analysis is intentionally a separate cache owner, not a leak into fit.

Checkpoint policy is **verified-prefix-replay-v1**: store completed evaluation hashes and parent checkpoints; resume cold-replays the prefix and explicitly declares divergence on changed search, environment or results. This deliberately spends physical work for trustworthiness. It is not efficient long-running distributed checkpointing. Cancellation uses accepted cooperative semantics and does not promise mid-FFT or mid-legacy-render interruption.

Recorded local observation: CPython 3.13.5, NumPy 2.3.5, SciPy 1.17.0, Linux x86-64 / OpenBLAS 0.3.30, one numerical thread. Search plus fixture generation was approximately 0.69–3.01 seconds per case; rich whole/holdout audits cost another 5.22 seconds. All evidence including the retained predecessor took about **24.0 seconds**. These are host-specific timings, separated from evidence hashes, not performance guarantees. Cheap feature caching already matters; rich analysis costs more than the small parameter enumeration.

Same-environment identities/results are exact. Windows/Ubuntu CI compares portable definitions and metrics with predeclared absolute `1e-7`, relative `1e-5` tolerances while retaining each platform's exact identities. Environment changes reject exact checkpoint continuation. Do not substitute tolerant/rounded hashes for true content identity.

## Weaknesses and next-pass questions

The grid scales exponentially, is resolution-sensitive, and visits only a deterministic prefix under small budgets. The small fixture truths lie on the grid by design. This pass does not establish robustness to real recordings, unknown source families, timing shifts, long signals or production use. Only numeric registered axes and single-beat mono legacy-exact synth recipes are supported; discrete graph topology/stage enumeration needs a future explicit adapter. Rich target length is capped at 16,384 samples. Default fit weights/scales and gate thresholds need sensitivity analysis, not post-hoc tuning to make a preferred strategy win. In the identifiable fixture, the six wrong-root (60/84 Hz) trials are rejected by the derivative-anchor transient gate. These anchors also respond to periodic sharp structure: this is a measured potential false-positive/phase-sensitivity limitation, not proof that each trial destroyed a perceptual attack. Keep those rejected trials and measurements; explicitly ablate or improve anchoring before treating eligibility as a universal musical judgment.

Promising investigations: compare fixed-budget random/low-discrepancy coverage against the grid; test staged timing/envelope/root then spectral then texture searches; compare simple coordinate/coarse-to-fine schedules; ablate fit windows and component scales under frozen held-out evaluations; characterize equivalence classes or identifiable combinations before trying to estimate every raw parameter. Later search adapters must preserve complete candidate provenance and use identical logical budgets, while reporting physical renders and feature cost too. A persistent adapter to the accepted `ArtifactCache` and compact resumable state are opportunities only after their correctness/cost trade-off is measured.

**Evidence-backed warnings:** scalar spectral success alone misses polarity; fit-only success can hide late-envelope failure; drive/trim coordinates can be provably redundant; muting upper content or reducing gain can improve some normalized descriptors while destroying the signal. Do not use fixture truth as initialization, quietly expose holdouts, replace null descriptor values with perfect losses, auto-normalize candidates, deduplicate distinct recipes solely by PCM, or equate a small modeled roughness score with musical preference. The old differential-evolution result is not directly comparable to the new fixture scores. Aggressive optimizer research is now appropriate; choosing a final production optimizer is not yet justified.
