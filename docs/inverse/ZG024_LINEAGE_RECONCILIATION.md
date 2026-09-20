# ZG-024 branch, PR and evidence lineage reconciliation

**Issue:** #90 · **Parent:** ZG-024 / #25 · **Audit base:** `main` at `f39d6d225011ac4a8103dfca7d58c2cbd2b22c41`

This record is preservation-oriented. It does not rewrite accepted history, promote a second inverse architecture, alter a calibration, or change product/DSP/audio behaviour. Branch commit IDs that were squash-merged are intentionally not described as ancestors of `main`: acceptance is established by the associated reviewed PR and merge commit, while the original reviewed head remains historical evidence.

## Authoritative PR lineage

| PR | Reviewed head | Accepted merge / disposition | Authority |
|---|---|---|---|
| #84 | `ff6a5400df802b21e18395a0657d1a17f9ddccff` | merged as `7316a6ceeeeac11a48264c925b639d6dfad07f53` | **Authoritative ZG-024a foundation.** Its contracts, laboratory, frozen calibration and handoff are the accepted foundation. |
| #85 | `6ae987eb12fa56307afddfc379d1374a87c02911` | closed unmerged, explicitly superseded by #84 | Preserved historical alternative only. It must not be treated as a competing accepted inverse framework. |
| #86 | `44db98add56a00a317554064b3c672de79cd21bd` | merged as `cf389e4a54fd925ec1071ae2128c367731e738aa` | **Accepted ZG-024b strategy-research pass.** |
| #187 | `ea79fbff0050f6534738f7428de8d5f0cc3d138d` | merged as `f4adbc5dc949bf89bab588222bc60fe0afe80887` | Accepted corrective #134 candidate-provenance binding. |
| #194 | `4bcdbf4a0fa2d37b2af777f12cd7e87bd1160f89` | merged as `7935accaa82f26479b1392725fe503b58611b4ab` | Accepted corrective #87 transient-v4 eligibility semantics. |
| #195 | `a5e3c814a1bafdecbeb055d284e4e1a375e7103f` | merged as `70d0744477f04485ecedc60d3792f80bd2478f0b` | Accepted #92 staged deterministic research, with the recorded mixed/no-go conclusion and no production optimizer promotion. |
| #196 | `c9f6b77730a1b1f9b19202e14b2f3f95b5f31bb4` | closed unmerged, superseded by #195 | Rejected/superseded staged-confirmation attempt. Its own final head failed ZG-000 ownership, cross-platform portable comparison and a clipping sentinel; #195 contains the accepted replacement evidence. |

Issue #25 therefore remains open. Reconciliation of repository history is not evidence that the inverse-search research programme has earned a final production optimizer.

## Branch inventory before cleanup

| Ref | Head SHA | Relationship to accepted history | Unique material at audit time | Disposition |
|---|---|---|---|---|
| `work/zg024a-inverse-foundations` | `ff6a5400df802b21e18395a0657d1a17f9ddccff` | Reviewed head of accepted PR #84. The branch commits are not direct ancestors after the accepted merge representation, but their reviewed content is represented by #84 / `7316a6ce...` and later `main`. | No evidence that must remain dependent on the branch ref; PR #84, its discussion and accepted `main` preserve the authority/evidence trail. | Safe to delete after this reconciliation record is merged. |
| `work/zg024a-lab-20260914` | `6ae987eb12fa56307afddfc379d1374a87c02911` | Superseded PR #85 alternative rooted before #84. | Contains a different inverse framework plus the numerical association experiment described below. The useful finding is preserved by immutable commit `0fa1ec97fe18cc1f8a1208d45a53c65cfcae1f80`, PR #85 discussion and this document; it is deliberately not promoted wholesale. | Safe to delete after this reconciliation record is merged. PR #85 stays closed and preserved. |
| `work/zg024a-association-stability` | `20cfce5c67b017ed647f0794d1a8d04c4df25450` | Based on accepted ZG-024a merge `7316a6ce...`; one branch-only commit. | The sole unique file is temporary `.github/workflows/zg024a-reconcile-source.yml`, which checks out `7316a6ce...`, archives it and publishes a one-day snapshot. The promised association repair was never ported onto this branch. | Temporary archival machinery only; safe to delete after this record is merged. Do not merge the workflow. |
| `work/zg024b-strategy-research` | `44db98add56a00a317554064b3c672de79cd21bd` | Reviewed head of accepted PR #86. | Reviewed ZG-024b material is represented by #86 / `cf389e4a...` and current `main`. | Safe to delete after this record is merged. |
| `zg024/provenance-binding-134` | `ea79fbff0050f6534738f7428de8d5f0cc3d138d` | Reviewed head of merged PR #187. | Accepted corrective content is represented on `main`; PR retains review/provenance history. | Safe to delete after this record is merged. |
| `zg024/issue-87-transient-gate` | `4bcdbf4a0fa2d37b2af777f12cd7e87bd1160f89` | Reviewed head of merged PR #194. | Accepted transient-v4 implementation/evidence is represented on `main`; PR retains review history. | Safe to delete after this record is merged. |
| `repair/zg024-staged-strategy-92` | `a5e3c814a1bafdecbeb055d284e4e1a375e7103f` | Reviewed head of merged PR #195. | Accepted v2 protocol, sealed-confirmation disclosure, ownership mapping, safety sentinels and mixed/no-go result are represented on `main`. | Safe to delete after this record is merged. |
| `repair/zg024-staged-confirmation-92` | `c9f6b77730a1b1f9b19202e14b2f3f95b5f31bb4` | Closed unmerged PR #196, explicitly superseded by #195. | Failed/superseded experiment is preserved by PR #196 and its discussion; the accepted replacement is #195. No accepted workflow depends on this ref. | Safe to delete after this record is merged. |

The issue-#90 reconciliation branch itself is active while its PR is under review and must not be rewritten or deleted before merge. After merge it becomes an ordinary merged work branch and can be deleted without affecting accepted history.

## Superseded #85 association-tie / sonority finding

PR #85 independently observed that identical candidate PCM on Ubuntu and Windows could produce materially different rich-fixture sonority measurements because tiny binary64 frequency differences changed component-track assignment. The recorded failing matrix was run `34889037449`; perturbations of approximately `1e-10 Hz` reproduced assignment fragmentation. The experimental repair is preserved at commit `0fa1ec97fe18cc1f8a1208d45a53c65cfcae1f80`: it added an **opt-in** integer-microcent assignment-cost policy while retaining raw frequency/amplitude/phase observations and the legacy default. The recorded Linux verification passed; the PR explicitly states that Windows verification of that repaired variant was not established.

This reconciliation chooses the acceptance-permitted **preservation rationale**, not a late port of that implementation:

1. the code lives inside a superseded alternative inverse architecture and was never accepted by #84;
2. the experimental repaired variant did not acquire the required cross-platform acceptance evidence before supersession;
3. current component, provenance, transient and inverse code has since accumulated accepted hardening, so transplanting the old patch would create a new measurement/method identity transition rather than merely cleaning history;
4. the later ZG-024 research path reached a documented mixed/no-go production conclusion, so branch cleanup is not a valid reason to alter accepted acoustic measurement semantics now; and
5. the finding itself remains reproducible research input because the exact experiment commit, observed failure mode and non-claim are now recorded on accepted `main`, independently of the branch ref.

Accordingly, **do not silently copy the old integer-microcent code into production and do not claim the portability problem is universally solved**. If future work reopens component-association portability, start a fresh focused issue from current `main`, preregister the policy, test Ubuntu and Windows, preserve legacy/default identity where required, and treat peak-selection/threshold/crossing boundaries as separate discontinuities.

## Temporary artefact audit

- `.github/workflows/zg024a-reconcile-source.yml` exists only on `work/zg024a-association-stability`; it was a one-shot accepted-source snapshot workflow and is not current CI. It must disappear with that branch rather than be merged.
- PR #85's temporary publication path was removed on its preserved final branch; the PR discussion records that removal. No write-enabled publisher from the superseded implementation is part of accepted `main`.
- The accepted ZG-024a/ZG-024b calibration files, implementation/validation transition records and later research evidence on `main` are **not cleanup targets**.
- No accepted handoff or RAG instruction requires checking out any superseded branch.

## Accidental issue records

Issues #81 (`[accidental] placeholder — closed`) and #82 (`[accidental] no-op — closed`) remain closed historical records. They are not programme tasks or dependency edges and must not be added to programme orchestration. Their existence is historical metadata, not work to erase.

## Behaviour and evidence boundary

This reconciliation changes documentation/tests only. It does not change source PCM, renderer/DSP topology or ordering, tuning, objective weights, validation thresholds, fit/holdout isolation, protected audio ownership, candidate/project/artifact provenance, recovered-source provenance, or audible/product defaults. ZG-024a and ZG-024b reproduction remains governed by their existing workflows and frozen evidence; this change neither edits nor regenerates those calibrations.

## Cleanup completion criterion

After this document is accepted, the refs marked **safe to delete** may be deleted only with a normal remote-ref deletion operation. Do not force-move them, repoint them to `main`, or delete PR/issue discussion. If the execution environment cannot delete refs, leave #90 open and record that tooling blocker precisely rather than pretending the cleanup is complete.


## ZG-024e eligible-starvation / held-out-generalisation diagnostic

Child **#227** / PR **#228** is the next serial research pass after accepted #92 / PR #195. It is a child of stable programme ID ZG-024, not a new stable ID.

The experiment was frozen in two repository-history steps before confirmation disclosure:

- protocol/design freeze: `a7156aa6cb148582a943b8c0f211e5f603b1670b`;
- development-selection freeze: `3364e563aa8094bc39655570d7197542fba2e6b5`;
- frozen selection decision SHA-256: `d673e22602aee773005e242910a0a54b60f2e9cedfff26c5d6898b3cf3ba6629`;
- selected intervention: `zg024e.coupled-ab-36.v1`;
- matched null: `zg024e.factorized-36-balanced.v1`;
- development diagnosis: `cross-family-coupling`.

Untouched confirmation is **mixed/no-go**. Coupled A+B search clears the specifically targeted structural/spectral availability threshold on 2/3 seeds, improving on the complete starvation seen in ZG-024d. It does not generalise into a production candidate: overall confirmation availability is 6/9, exactly the same as the matched factorized null, below the frozen 7/9 bar and with zero eligible-case gain versus the required +2. All three comparable confirmation families regress beyond the frozen 1.10 held-out ratio against the best equal-budget flat control. Safety sentinels, promotion integrity and exact logical-budget accounting remain intact.

One additional portability finding is deliberately retained rather than hidden. On `confirm2-identifiability-coupled` seed 4099, one drive/input-trim pair that Windows renders to byte-identical f32 PCM splits into two exact PCM identities on Ubuntu despite identical fit/holdout metrics within the portable tolerance. Exact PCM equivalence groups are therefore same-environment evidence only; full platform evidence retains them, while the tolerance-based portable projection compares the promotion counts/decisions and numeric measurements that are actually portable. Exact-output grouping never drives promotion or ranking.

PR #228 does not modify production inverse defaults or `zaaggenz_inverse` search ownership. After merge, its branch is ordinary merged-work history and may be deleted without losing the protocol, frozen selection, result or PR discussion. Parent #25 remains open and dependency-unsatisfied with the narrower blocker `research:ZG-024-coupled-search-heldout-generalisation`.
