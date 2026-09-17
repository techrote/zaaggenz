# ZG-024d staged deterministic search protocol — issue #92

Status: **preregistered before confirmatory outcomes are inspected**.  This document freezes the experiment that follows the independently repaired transient-v4 eligibility work (#87).  It does not alter production search, renderer behaviour, protected audio, source provenance, tuning, objective weights, validation thresholds, or audible defaults.

## Question and decision boundary

ZG-024b found no universal winner among cyclic grid, SplitMix coverage, shifted Halton coverage and coordinate refinement.  It did, however, produce the specific hypothesis now under test: global low-discrepancy coverage may be useful for root/timing/envelope and spectral structure, while local coordinate refinement may be useful for nonlinear/texture coordinates.  ZG-024d tests that *staged* hypothesis under fixed logical budgets and against the two relevant ZG-024b ablations.

The candidate method is `zg024d.staged-halton-coordinate.v1`.  The equal-budget comparators are `zg024b.halton-shifted.v1` and `zg024b.coordinate-refine.v1`.  Grid and uniform remain frozen historical controls in ZG-024b; repeating them here would increase evidence cost without answering the staged-ablation question.

A positive result is deliberately difficult to earn.  Production candidacy requires all of the following on the untouched confirmation programme:

- fit win/tie rate against **each** comparator of at least 2/3 on paired runs with eligible results from both methods;
- staged eligible-winner availability of at least 90%, and no lower availability than either comparator;
- median independently audited holdout score no worse than 1.10× the better comparator median (plus the portable absolute tolerance);
- all fresh intentionally unsafe anti-degeneracy probes remain ineligible;
- every fit-equivalent late-gain confirmation sentinel is identified as overfit after independent audit.

Truth-coordinate error is reported only as a post-selection diagnostic.  It cannot qualify or disqualify a method because several accepted recipe families are intentionally non-identifiable.  A failure of any rule yields `mixed-confirmation-do-not-integrate`: issue #92 may close honestly with the exact blocker while parent ZG-024 remains open.  Thresholds, fixture domains, seeds, budgets and stage rules must not be edited in response to confirmation outcomes.

## Frozen stages and budget semantics

Every fixture explicitly partitions its complete parameter domain among three stages.  The partitions are fixture declarations, not target-derived inference.

| Stage | Frozen role | Proposal rule | Promotion |
|---|---|---|---|
| A — `stage-a-root-envelope` | root, timing, attack/envelope coordinates | deterministically shifted Halton coverage | fit-best, then eligible Pareto diversity, then fit order up to the declared cap |
| B — `stage-b-spectral` | harmonic/spectral-structure coordinates | parent-specific deterministically shifted Halton coverage | same fit-only rule |
| C — `stage-c-texture` | drive, trim, shaper wetness and local texture/nonlinearity | parented coordinate probes with halving radii | same fit-only rule |

Stage-C boundary clipping or duplicate exhaustion may switch to an explicitly labelled stage-local Halton fallback.  The fallback is part of the frozen algorithm and appears in lineage; it is never described as coordinate refinement.  A stage with no axes has zero logical budget and simply carries the previous retained parent set.  If a stage has no eligible retained parent, the next stage restarts from the declared base recipe rather than smuggling a rejected candidate into an adaptive role.

The declared budget unit is one **unique logical candidate evaluation**.  Duplicate/clipped proposals do not consume budget.  Every uncached candidate continues through the existing ZG-024a evaluator, including same-environment render verification.  The sum of A/B/C stage budgets must equal the existing `SearchBudget.max_evaluations`; no method receives additional fit evaluations, target-derived initialization, hidden retries, holdout feedback, or truth feedback.

The final candidate ranking is global across all evaluated eligible candidates.  Stage promotion affects future proposals, not whether an already evaluated valid candidate remains a possible result.  Full candidate/Pareto sets and proposal attempts remain evidence.

## Determinism, lineage, checkpoint and cancellation contract

Run identity binds the existing evaluator search identity, full staged plan, research implementation identity, numerical environment and declared logical budget.  Each candidate lineage row records stage, exact parent candidate identity, proposal family/coordinate/radius or low-discrepancy units, and ordinal.  Each promotion row records eligible count, eligible-Pareto count, cap, exact retained IDs and the fit-only reason.

Adaptive resume uses `verified-adaptive-prefix-replay-v1`: the completed prefix is cold-replayed under the same environment and every candidate SHA must match before continuation.  Changed request, plan, implementation or environment is divergence, not resume.  Cancellation publishes only a completed-prefix research checkpoint; it does not publish a partial search as product state.

## Fresh fixture programme

Development fixtures use seeds `31`, `211`, `2027`:

- `dev-root-envelope`: three off-grid root/attack/decay axes, 18 evaluations in stage A.
- `dev-spectral`: three off-grid harmonic-decay/odd-even/tilt axes, 18 evaluations in stage B.
- `dev-nonlinear`: drive/wetness local search, 18 evaluations in stage C.
- `dev-mixed`: six axes split 10/10/10 across A/B/C.
- `dev-nonidentifiable`: drive+trim equivalence manifold, 16 evaluations in C; raw-coordinate recovery is not success.
- `dev-holdout`: late gain automation outside fitting windows, 9 evaluations in A; audit must expose fit-equivalent overfit without feeding search.

The sealed confirmation set uses disjoint seeds `43`, `509`, `4099` and was defined before its outcomes are inspected:

- `confirm-mixed-a`: six axes, 10/10/10 A/B/C.
- `confirm-mixed-b`: root/attack, harmonic structure and nonlinear axes, 10/10/10 A/B/C.
- `confirm-nonidentifiable`: spectral plus drive/trim equivalence, 0/10/14.
- `confirm-holdout`: fit-equivalent late gain automation, 9/0/0.
- `confirm-transient-safe`: transient-bearing mixed source after transient-v4 repair, 12/8/10.

All targets use the accepted deterministic `RenderRecipe -> render_trace` path, canonical unclamped f32 audio, existing fitting/holdout windows and existing objective/validation policies.  Search receives only `FitEvaluator`.  Ground-truth recipes and independent holdout capability remain outside the strategy API.

## Anti-degeneracy probes

Three fresh one-candidate probes are evaluated through the same accepted evaluator and reported as confirmation guards:

- `safety-silence`: non-silent output against a truly silent target;
- `safety-transient-damage`: a deliberately 90 ms smeared attack against a sharp transient-bearing target;
- `safety-clipping`: extreme drive plus full hard-clip mix against an unclipped target.

Their exact validation records are evidence.  The protocol does not weaken or retune any gate if one behaves unexpectedly.  An intentionally unsafe probe remaining eligible blocks production promotion and becomes a follow-up defect/research blocker.

## Holdout, leakage and identifiability policy

Holdout samples, audit outcomes and fixture truth are not accepted by `run_staged`.  Promotion, proposal order, ranking and stopping use fit evidence only.  Tests mutate only held-out target samples and require identical proposal states, fit scores and eligibility.  The late-gain sentinels intentionally have fit-equivalent alternatives; independent audit may diagnose overfit but cannot retroactively rerank search.

For identifiable fixtures, normalized truth-coordinate error is a post-search diagnostic.  For drive/trim fixtures, the diagnostic is distance to the known observable `drive + trim` manifold.  Neither diagnostic claims recovery of an original production chain.

## Comparability and portable policy

Each paired method receives the same fixture, seed and logical budget with a cold evaluator/cache.  Development and confirmation results are reproduced on Ubuntu and Windows under Python 3.13, NumPy 2.3.5 and SciPy 1.17.0, single numerical thread, `PYTHONHASHSEED=0`.  Portable frozen projections use absolute tolerance `1e-7` and relative tolerance `1e-5`; exact evidence identities continue to retain environment identity where appropriate.

The full artifact records candidate components, lineage, promotions, audits and fixture catalogue material.  A compact portable reference is committed only after the first independent Ubuntu/Windows materialization agrees under the preregistered tolerance.  Any implementation change after that point must regenerate evidence transparently rather than editing expected values to hide drift.

## Compatibility and no-go boundaries

This pass lives under `research/zg024d` and does not modify `zaaggenz_inverse`, so frozen ZG-024a/b calibrations and the reviewed Candidate 2.0 provenance repair remain reproducible.  The following are explicitly out of scope unless the confirmation rule earns a separate reviewed integration step:

- no production optimizer replacement;
- no change to `locked_bloom`, renderer/DSP topology, source PCM, tuning, normalization or clipping policy;
- no change to objective weights or transient-v4 / other eligibility thresholds;
- no holdout-aware proposal, promotion, ranking or early stopping;
- no inference of a unique original production chain;
- no neural, Bayesian, CMA-style, differential-evolution or other opaque optimizer leap;
- no mutation of protected source/audio/provenance ownership or private-reference handling.

If confirmation is mixed, the correct outcome is evidence plus a precise blocker, not a forced winner.
