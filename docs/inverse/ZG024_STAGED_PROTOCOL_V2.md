# ZG-024d preregistered staged deterministic search protocol v2

This protocol supersedes the incomplete v1 draft on PR #195. During acceptance review, before any v1 calibration or confirmatory outcome was inspected, the v1 design was found not to cover the complete issue #92 contract: it did not explicitly separate structural/spectral/texture parameter families, retain multiple Pareto alternatives between stages, provide verified-prefix resume, or define the required fresh fixture programme. Any CI evidence generated from v1 is therefore invalid for selection and must not be used. This v2 document is the design freeze for the complete experiment and is committed before the confirmation fixture module is added or any v2 outcome is generated/inspected.

## Research question and non-goals

The hypothesis is that a transparent deterministic three-stage search can add value over accepted flat deterministic baselines at the same logical evaluation budget while preserving fit/holdout separation and the accepted transient-v4, silence and clipping gates. The experiment may conclude mixed/inconclusive. It does not infer an original production chain, tune any safety gate, change audible defaults, or justify ML/surrogate/population methods.

No strategy is promoted into production solely because it wins a synthetic aggregate. Production promotion requires clear development and untouched-confirmation evidence plus intact anti-degeneracy, lineage, replay, cache and portability evidence. Otherwise #92 closes as research evidence and #25 remains open with the blocker recorded.

## Exact stage definitions

All candidate states are complete `ParameterState`s over the declared fixture domain. Every domain axis must belong to exactly one family; unknown axes fail closed.

**Stage A — global structure.** Family A contains root/pitch/timing/envelope controls: `f0_hz`, `attack_ms`, `decay_ms`, `sustain`, `transient_click`, `noise_decay_ms`, and `sweep_semitones`. Proposals use a method-labelled shifted-Halton sequence on Family-A coordinates only; all other coordinates remain at the base state. This stage has no parent candidate.

**Stage B — spectral structure.** Family B contains harmonic/spectral controls: `harmonic_count`, `harmonic_decay`, `odd_even_ratio`, `harmonic_tilt_db_per_oct`, `harmonic_lock_cents`, and `roughness`. Stage B starts from retained Stage-A parents and uses parent-labelled shifted-Halton coverage on Family-B coordinates only. Parents are scheduled round-robin so a single early parent cannot consume the stage. Each proposal records exactly one Stage-A parent.

**Stage C — local texture/nonlinearity.** Family C contains `drive_db`, `input_trim_db`, `shaper_mix`, `hard_clip_mix`, `asymmetry`, `wavefold`, `preemphasis`, and `noise_level`. Stage C starts from retained Stage-B alternatives and performs bounded coordinate refinement on Family-C axes with radii `0.25, 0.125, 0.0625, 0.03125` of each declared axis span, parent-round-robin. If clipping/duplicate states would otherwise leave stage budget unused, a labelled Family-C shifted-Halton continuation around the same retained parents fills the remainder. This continuation is part of the frozen method, not a hidden fallback.

Only `FitEvaluator` is a strategy capability. Ground-truth recipes and `AuditEvaluator` are absent from proposal, promotion, stopping and ranking APIs. Holdout/audit evaluation occurs only after fit selection is frozen.

## Promotion and retained alternatives

At the end of Stages A and B, only eligible candidates can be promoted. Promotion first takes candidates on the declared Pareto front in deterministic fit-order, then supplements with the remaining deterministic fit ranking, to a maximum of **4 retained alternatives**. Exact-output equivalence groups (same retained render SHA with distinct parameter states) are recorded as identifiability evidence and are not deduplicated away. If no eligible parent exists, the search fails closed at that stage and records unspent downstream budget rather than promoting a rejected candidate.

Final results retain every evaluated candidate, the final Pareto front, a deterministic final retained set using the same rule, all promotion records, exact-output equivalence groups, parent IDs, proposal family, stage, axis/radius/coverage attempt, and logical-budget accounting. A single opaque optimum is never substituted for the retained evidence.

## Frozen method variants and total budget

Normal development and confirmation fixtures use **24 logical evaluations** and `render_repeats=2`. Three staged allocations are compared:

- `zg024d.staged-balanced.v2`: A/B/C = **8/8/8**;
- `zg024d.staged-structure.v2`: A/B/C = **10/7/7**;
- `zg024d.staged-texture.v2`: A/B/C = **7/7/10**.

Duplicate proposals do not consume logical budget. A normal benchmark is expected to consume exactly its 24-evaluation allocation. Safety-stop/sentinel runs may terminate early only when no eligible parent exists; their unspent amount and reason are evidence, not silently reassigned across stages.

Accepted flat comparators are `zg024b.uniform-splitmix.v1`, `zg024b.halton-shifted.v1`, and `zg024b.coordinate-refine.v1`, each receiving the same complete fixture domain, seed and **24 logical evaluations**. Grid-prefix is omitted because the full fresh domains make a 24-point prefix strongly order-dependent and it did not materially answer the staged-vs-flat question in the accepted handoff.

The deterministic seed set is **41, 211, 2027**. Cold evaluators are used for paired method comparisons. Physical render/cache cost is telemetry only.

## Checkpoint, cancellation and cache contract

The staged runner emits a checkpoint after every newly accepted logical evaluation. A checkpoint binds the staged run ID, complete method/design identity, numerical environment, next ordinal and exact candidate-record SHA prefix. Resume regenerates the deterministic prefix under `force_recheck`, requires byte-identical candidate SHAs, and fails closed on changed method/design/request/environment or replay divergence. Cancellation returns the latest complete prefix checkpoint; no partial candidate is published.

Renderer/feature caches retain the accepted foundation keys (recipe/render-engine/environment and feature identities), so bit-identical work may be reused between research strategies. The staged run ID additionally binds the staged method and design identity. Tests must prove cache reuse does not collapse two different staged method identities or allow a stale checkpoint/method to resume.

## Fresh development programme

Development fixtures are new targets using the accepted renderer but distinct truth/base recipes from published ZG-024a/b calibration targets. All keep explicit independent fit and tail-holdout windows. The development catalogue contains:

1. `dev-structure` — meaningful Family-A root/envelope displacement with B/C nuisance axes;
2. `dev-spectral` — meaningful Family-B harmonic displacement with A/C nuisance axes;
3. `dev-texture` — meaningful Family-C nonlinear displacement with A/B nuisance axes;
4. `dev-mixed` — simultaneous A/B/C displacement;
5. `dev-equivalence` — deliberate drive/trim equivalence manifold with A/B nuisance axes;
6. `sentinel-transient` — a wide attack envelope capable of generating transient-v4 rejection;
7. `sentinel-silence` — an attenuation range capable of silence/energy rejection;
8. `sentinel-clipping` — a hard-clip/drive range for clipping-gate evidence.

The first five are development comparison fixtures. The last three are anti-degeneracy sentinels and cannot select a method. A sentinel records every rejection reason and proves rejected candidate IDs never occur in Stage-A/B promotions or the final retained set.

Parameter truth is diagnostic only after fit selection. Normalized parameter error is never a primary endpoint or ranking input.

## Sealed confirmation programme

The confirmation module is intentionally absent at this design-freeze commit. It will be added only after this protocol is committed, creating a repository-history boundary between design freeze and confirmation disclosure. The module will define three new targets (`confirm-structure-spectral`, `confirm-texture-mixed`, `confirm-equivalence`) with distinct truth/base values, the same 24-evaluation total budget and the same fit/holdout capability separation. Confirmation targets cannot alter method allocation, promotion, radii, seeds, comparator set, endpoint policy or gates after disclosure.

The report must run all development comparisons and freeze the staged method choice **before lazily importing/building the confirmation catalogue**. Confirmation results may accept/reject the frozen choice but cannot select another staged method.

## Primary endpoints and frozen decision policy

Primary method comparison uses eligible best-fit objective score only. Per fixture/seed, a method with no eligible candidate ranks behind every method with an eligible candidate. Ties use absolute tolerance `1e-7` and relative tolerance `1e-5`, then deterministic method ID. Holdout score, truth/parameter error, wall-clock time and physical render count are diagnostics and cannot select/rerank.

Development selection computes each staged method's median rank across the five development fixtures and three seeds; lowest median rank wins, then lower median best-fit score, then method ID. The selected staged method is considered **development-supported** only if it beats or ties the best flat comparator on at least 9 of 15 paired development cases, has no more than 2 cases worse by >10%, and has zero promotion of ineligible candidates.

The frozen selected method is then compared with all three flat baselines on all three confirmation fixtures and all three seeds. **Production-candidate support** requires development support, confirmation beat/tie in at least 6 of 9 paired cases, no confirmation case worse than the best flat comparator by >10%, no holdout median regression >10% on any confirmation fixture where both values are finite, exact budget/replay/cache/gate integrity, and Ubuntu/Windows portable-outcome agreement. If this bar is not met, the result is mixed/inconclusive/no-go; thresholds and fixtures are not changed.

The issue may still be completed with an honest mixed/no-go result as explicitly allowed by #92. In that case no staged strategy is integrated into the production inverse package and parent #25 remains open with a precise next blocker.

## Portability and evidence

Portable evidence comprises per-run eligibility, best-fit score, post-selection holdout score, normalized parameter diagnostic, stage consumption, promotion counts, gate-rejection counts, and the frozen decision. Windows and Ubuntu compare these under `abs=1e-7`, `rel=1e-5`; environment-specific candidate/search/result identities remain explicit and are not required to match across operating systems.

Full artifacts retain every candidate and decomposed objective/validation record, all stage lineage, promotion/Pareto/equivalence records, audit selections, fixture catalogue identities, method/design identity and render/cache telemetry. Host wall-clock is separate telemetry and excluded from portable evidence identity.

## Foundation/protected semantics

ZG-024a/b frozen calibrations remain regression requirements. The accepted `zg.inverse.transient-onset-contrast.v4` eligibility threshold and all other validation gates remain authoritative and are not tuned here. No source PCM, protected source/audio ownership, renderer/DSP topology, tuning, normalization/clipping policy, objective weights, private-reference semantics, listening evidence, project defaults, cache-audio identity or provenance ownership may change in this pass.
