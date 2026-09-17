# Persisted inverse-candidate provenance

This document defines the corrective persistence boundary introduced by issue #134 under ZG-024. It does not change inverse fitting, DSP, objective semantics, fit/holdout separation, project/source ownership, or the claim that an editable inverse candidate is **not** identification of an original production chain.

## Candidate 2.0.0

Newly produced `InverseCandidate` records use candidate format **2.0.0**. The surrounding ZG-024 contracts remain at their existing versions; this is a deliberately narrow evidence-format migration because the previous candidate envelope could not authenticate several provenance claims after persistence/reopen.

Every Candidate 2.0.0 contains a mandatory `InverseSearchBinding` **1.0.0** under `provenance.search_binding` plus `provenance.search_binding_sha256 = zg-c14n-v1(binding)`. The binding retains only fit-side/search material:

- the complete canonical `SearchRequest`, including source revision, base `RenderRecipe`, target `AudioAssetRef`, domain, fitting windows, seed, budget, stage/parents, objective and validation policy;
- one canonical fitting-excerpt `AudioAssetRef` per fitting window, never holdout samples;
- method roots: renderer ID, inverse implementation root, render-engine root, derived implementation/render-engine identities, and feature-method identity;
- the numerical environment manifest used by the evaluator.

The persisted binding contains hashes/metadata for fitting excerpts, not their audio samples. Holdout and whole-target PCM remain owned solely by `AuditEvaluator` and are not added to the fit/search capability.

## Verification chain

`Candidate.from_dict()` now performs the following before accepting a reopened record:

1. Parse and validate the embedded `SearchRequest` and each fitting `AudioAssetRef` using existing contracts.
2. Recompute `implementation_sha256` from the persisted engine root plus renderer ID, and recompute `render_engine_sha256` from the persisted render-engine root plus renderer ID.
3. Recompute the environment SHA-256 from the complete numerical environment manifest.
4. Recompute the historical `zaaggenz.inverse-search-v1` search ID from the canonical request, implementation identity, feature-method identity and fitting-asset identities.
5. Recompute the search-binding SHA-256 over the complete binding.
6. Cross-check the duplicated candidate provenance fields (`source_revision_id`, base recipe, target asset, implementation, environment, render engine, feature method), stage and parents against the authenticated binding.
7. Recompute the Candidate 2.0.0 identity in domain `zaaggenz.inverse-candidate-v2`, which includes the search-binding SHA-256 as well as search ID, parameter state and editable recipe.
8. Continue the pre-existing render, feature, objective, eligibility and state↔recipe integrity checks.

Changing a provenance claim while retaining the old search/candidate identity therefore fails closed. Changing the embedded request/method/environment and its detached binding hash also changes the Candidate v2 identity, so a record cannot be silently rebound while pretending to be the old candidate.

These are content-addressed integrity guarantees, not a secret-key signature or proof about who authored a record. Replay under the declared implementation/environment remains the authority for actual rendering.

## Search identity and environment

The search-ID domain remains **`zaaggenz.inverse-search-v1`**. Its historical inputs are unchanged: request, implementation identity, feature-method identity and fitting-asset identities. Numerical environment remains a separate resumability dimension, as it was in `Checkpoint.environment_sha256`.

Candidate 2.0.0 additionally binds the complete environment manifest through `search_binding_sha256`; therefore environment provenance can no longer be edited after persistence while retaining the same candidate identity. This preserves existing search semantics while fixing the persisted-evidence gap.

Canonical `(n,)` and `(n, 1)` mono fitting inputs still canonicalize to the same `AudioAssetRef`, search binding and candidate identity. Environment-specific fields remain intentionally platform-specific; portable recipe/measurement comparisons continue to use the existing cross-platform tolerance policy rather than forcing environment hashes to match.

## Legacy Candidate 1.0.0 and checkpoints

Candidate **1.0.0** did not retain enough material to reconstruct its search binding after persistence. It therefore has no safe in-place upgrade rule. `Candidate.from_dict()` rejects such a record with an explicit instruction to replay/regenerate it under Candidate 2.0.0. The implementation must not infer missing request, fitting-asset, method or environment provenance from duplicated legacy SHA fields.

Current checkpoints remain `verified-prefix-replay-v1`. A checkpoint created and resumed under the same Candidate 2.0.0 implementation replays the completed prefix exactly. Older checkpoints/evidence necessarily diverge after this source/evidence-format transition because implementation/search/candidate identities change; they must be replayed under the reviewed current implementation rather than mixed with v2 evidence. Stage/parent lineage is part of the embedded `SearchRequest` and is cross-checked against the candidate's convenience provenance fields.

## Downstream consumers

Consumers must treat Candidate 2.0.0's `search_binding` as the authoritative self-contained provenance envelope and the duplicated top-level provenance fields only as validated projections. Consumers must not relabel a candidate by rewriting those projections.

The current production inspector does not yet consume persisted inverse candidates as authoritative project/render input; that integration remains tracked separately by #94. When #94/#92 consume inverse evidence, they should require Candidate 2.0.0 (or a later explicitly versioned successor) and preserve `search_binding_sha256` through any derived evidence.

## Protected semantics

This correction changes evidence identity only. It does not alter source PCM, rendering, graph topology, master gain, tuning, timing, parameter bounds, search enumeration, objective measurements, validation gates, fit/holdout isolation, cache audio content, or product defaults. It introduces no normalization, clipping, source substitution, holdout leakage, optimizer change, or preference claim.
