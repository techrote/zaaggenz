# ZG-024e diagnostic result — coupling helps starvation but does not generalise

**Child:** #227 · **Parent:** ZG-024 / #25  
**Decision:** **mixed/no-go; no production optimizer promotion**

This is the post-outcome record for the preregistered experiment in `ZG024E_DIAGNOSTIC_PROTOCOL_V1.md`. It does not amend the frozen protocol, change gates/objectives, or turn confirmation results into search feedback.

## Freeze and disclosure chronology

The design was frozen at `a7156aa6cb148582a943b8c0f211e5f603b1670b` before ZG-024e fixtures/outcomes existed. Development then ran on fresh fixtures and selected exactly one intervention by fit-side eligibility/starvation/fit evidence only. The exact successful selection artifact was committed at `3364e563aa8094bc39655570d7197542fba2e6b5` before the confirmation module existed.

Frozen selection:

- decision SHA-256: `d673e22602aee773005e242910a0a54b60f2e9cedfff26c5d6898b3cf3ba6629`;
- intervention: `zg024e.coupled-ab-36.v1`;
- matched null: `zg024e.factorized-36-balanced.v1`;
- primary development diagnosis: **cross-family coupling**.

Development supported that diagnosis: the coupled method produced eligible final alternatives in **12/15** cases versus **7/15** for its matched null (+5), with zero ineligible promotions. Increased total budget was a secondary supported mechanism (balanced 36: 7/15 versus factorized 24: 4/15, +3). Wider parent retention did not help.

## Untouched confirmation outcome

Confirmation used fresh `confirm2-*` targets, seeds `53`, `307`, `4099`, sealed holdouts, the frozen coupled intervention, its matched null, equal-budget ZG-024b flat controls and the historical 24-evaluation factorized control.

The frozen positive rule **fails**:

| Criterion | Result | Required |
|---|---:|---:|
| structure/spectral eligible seeds | **2/3** | >= 2/3 |
| overall coupled eligible cases | **6/9** | >= 7/9 |
| matched-null eligible cases | **6/9** | context |
| eligible-case gain over matched null | **0/9** | >= +2/9 |
| ineligible promotions | **0** | 0 |
| safety sentinels | **pass** | pass |
| exact logical-budget integrity | **pass** | pass |
| held-out non-regression | **fail** | pass |

The targeted starvation hypothesis is therefore only partly confirmed. Joint A+B variation changes the failure mode enough to recover eligible structural/spectral alternatives on two seeds, but the benefit does not survive as a general availability advantage over the matched factorized method.

### Holdout result

For every confirmation family with finite medians, the selected coupled method exceeds the preregistered 1.10 non-regression limit against the best equal-budget flat control:

| Confirmation family | Coupled median holdout | Best flat median | Ratio |
|---|---:|---:|---:|
| structure/spectral starvation | 0.578281 | 0.429894 (coordinate refine) | **1.345** |
| mixed texture | 0.480580 | 0.211326 (shifted Halton) | **2.274** |
| coupled identifiability | 0.611874 | 0.327870 (shifted Halton) | **1.866** |

Holdout results were evaluated only after fit-side searches/selections were complete and did not revise proposals, promotion, ranking, stopping or the frozen method choice.

## Fixture/seed availability

The coupled method's confirmation availability is:

- `confirm2-structure-spectral-starvation`: seed 53 fails closed at AB; seeds 307 and 4099 produce eligible finals;
- `confirm2-mixed-texture`: seed 53 fails closed at AB; seeds 307 and 4099 produce eligible finals;
- `confirm2-identifiability-coupled`: seeds 53 and 4099 produce eligible finals; seed 307 fails closed at AB.

The matched balanced factorized method also produces 6/9 eligible finals overall. Coupling therefore addresses a specific A-only promotion bottleneck but is **not sufficient** to solve the parent feasibility/generalisation blocker.

## Safety, determinism and integrity

The negative decision is not caused by weakened safeguards:

- rejected/ineligible candidates are never promoted;
- transient-v4, silence, level, energy/bandwidth, clipping and hidden-output gates remain unchanged;
- deliberately unsafe sentinels remain rejected;
- logical budgets and fail-closed unspent work remain exact;
- checkpoint/replay, cancellation, cache separation, provenance and fit/holdout-capability regressions remain covered by the inherited and focused suites;
- source PCM, renderer/DSP topology, tuning, objective weights, validation thresholds, defaults, private-reference/final-master semantics and `locked_bloom` are unchanged.

## Cross-platform evidence and exact-output equivalence

Ubuntu and Windows agree on all decision-relevant availability, fit, holdout, safety, Pareto-count, retention and budget outcomes under the frozen absolute `1e-7` / relative `1e-5` numerical policy.

The first portability audit also exposed one useful non-decision discrepancy: on `confirm2-identifiability-coupled` seed 4099, Windows records two exact-output equivalence pairs at the final C stage while Ubuntu records one. The extra Windows pair is the drive/input-trim combination `6.55 + (-5.8)` versus `8.8 + (-8.05)`; the raw binary64 sums differ at approximately machine precision. Windows rounds both paths to byte-identical f32 PCM, while Ubuntu produces distinct exact PCM asset hashes. Their fit/holdout measurements remain portable.

Accordingly, exact PCM equivalence groups remain recorded in **full per-platform evidence**, but are classified as environment-exact identity rather than a portable semantic. They never participate in promotion/ranking. The portable projection compares the promotion counts and tolerance-based measurements instead of pretending bit-identical PCM is cross-platform guaranteed.

Initial untouched confirmation evidence on run `35525526917` recorded Windows evidence SHA-256 `770779b08fe6188e88f74963ae40693a614124825380324c2fec2e5b5bced659` and Ubuntu evidence SHA-256 `b33cbba47ab1e8c61e07cd34f31992ce4d224c00c9e3a2b76df74bbf132b373e`. Environment-specific exact identities are expected to differ.

## Decision

**No ZG-024e production optimizer is promoted.** The strict A→B→C factorization is implicated in the original starvation, but replacing the A-only boundary with coupled A+B coverage does not provide the required general availability advantage or held-out generalisation.

Parent ZG-024 / #25 remains open, with the blocker narrowed from generic eligible-candidate starvation to:

`research:ZG-024-coupled-search-heldout-generalisation`

A future pass should target fit-side generalisation/selection robustness without inspecting holdouts: e.g. transparent jointly varying coverage with deterministic multi-fit-window stability or observable/equivalence-aware parameterization, still compared against the strong flat controls. Do not tune against these now-disclosed confirmation holdouts, and do not repeat them as a fresh test set.
