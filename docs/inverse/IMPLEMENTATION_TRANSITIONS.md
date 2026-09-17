# ZG-024a frozen-calibration implementation transitions

ZG-024a's checked-in `examples/zg024a_inverse_calibration.json.gz` is immutable historical calibration evidence. It records the exact implementation identity that produced the accepted foundation run. It is **not** rewritten merely because a later accepted prerequisite implementation changes.

At the same time, the ZG-024a workflow is intentionally a downstream compatibility suite for project/jobs/QC/analysis/components/descriptors/DSP/spectral/tuning changes. A legitimate source change in one of those implementation roots necessarily changes `implementation_sha256`, even when every portable calibration definition, parameter state, loss, eligibility result, ranking, holdout and numerical result is unchanged.

To represent that case without either weakening provenance or continuously rewriting historical calibration, CI supports a small reviewed transition registry:

`examples/zg024a_implementation_transitions.json`

## Rules

1. The frozen predecessor calibration remains byte-for-byte untouched.
2. Every fresh run still records its **actual** implementation manifest and `implementation_sha256`; the new identity is never rewritten to the predecessor hash.
3. A differing implementation identity fails by default.
4. CI may accept the identity difference only when the exact directed pair `old_sha256 -> new_sha256` appears in the reviewed registry with a stable ID, issue number, explicit changed source paths and rationale.
5. Wildcard changed paths are rejected. Transition records are pair-specific, not general exemptions.
6. After an accepted pair is recognized, the comparison aligns only the implementation-hash field in a temporary comparison copy. Every other portable discrete/numeric calibration field must still reproduce under the existing `1e-7` absolute / `1e-5` relative policy. Any other drift still fails.
7. Evidence-envelope self-hashes for both actual and expected calibration records are checked before comparison. A transition cannot legalize a tampered evidence record.
8. This mechanism does not grant checkpoint resumability across implementation identities and does not claim the two implementations are identical. It records a reviewed **compatibility result**: the accepted portable ZG-024a calibration did not change under the declared source transition.
9. New transitions require review of the full Windows and Ubuntu ZG-024a run. They are never generated or appended automatically by CI.

## First accepted transition — issue #137

ZG-016 issue #137 hardens the final bus so `unbounded_float` remains unclamped but cannot silently cast finite float64 values beyond the float32 representable range into ±Inf. It also rejects final-master arithmetic overflow before clipping policy handling. No limiter, normalization or hidden clamp was introduced.

The relevant implementation identity changed:

- predecessor: `ff938e70ba2598d5f6f6f0bc305e01b580c373a8e5daca849e8d3f9392bee3a4`
- #137 candidate: `c036445eeb5479e50666d239c5f7535959bc55a083fd87646bc59fe1af976564`
- changed implementation path: `zaaggenz_dsp/graph.py`

Before registering the transition, ZG-024a was run on both Ubuntu and Windows. All inverse unit tests, inherited prerequisite suites and browser transport tests passed. The frozen calibration comparison reported exactly one difference on both platforms: `/implementation_sha256`; no fixture, state, objective, eligibility, ranking, holdout or other portable numeric/discrete field changed.

The registry therefore preserves both facts: provenance changed because relevant source changed, and the accepted portable foundation calibration otherwise reproduced unchanged.

## Second accepted transition candidate — issue #106

ZG-005 issue #106 hardens every public QC certifier so non-finite input, non-finite controls and non-finite/undefined required metrics fail closed before tolerance comparison. `diagnose()` remains descriptive and does not silently turn NaN/Inf into a passing value. Existing valid zero/constant-source sentinel semantics and finite master-gain behaviour remain explicit.

Because the implementation identity is always measured relative to the immutable frozen calibration, the reviewed #106 candidate is cumulative with the already accepted #137 final-bus change:

- frozen predecessor: `ff938e70ba2598d5f6f6f0bc305e01b580c373a8e5daca849e8d3f9392bee3a4`
- cumulative #106 candidate: `a2cf798e817ecc0288b3fae2fe2a4c9c3e404994fc6a3afd0b13430a510cda12`
- implementation paths changed relative to frozen evidence: `zaaggenz_dsp/graph.py`, `zaaggenz_qc/checks.py`

Before registration, the PR merge ref was executed through the full ZG-024a workflow on both Ubuntu and Windows. On both platforms all 81 inverse tests, all inherited project/jobs/QC/analysis/components/descriptors/DSP/spectral/tuning suites, and browser transport checks passed. The frozen calibration comparison reported exactly one difference: `/implementation_sha256`, with the identical candidate hash above on both platforms. No fixture, candidate state, objective, eligibility, ranking, holdout or other portable numeric/discrete field changed.

The registry therefore accepts only that exact frozen-to-cumulative identity pair; it does not create a wildcard exemption or rewrite the frozen calibration.

## Third accepted transition candidate — issue #113

ZG-004 issue #113 removes post-validation metadata aliasing from `RenderArtifact`. Bounded asset/scope JSON is now snapshotted deterministically before validation; asset contract, PCM shape and content identity checks are performed against the exact retained snapshot; public `.asset`, `.scopes` and `.metadata()` calls return fresh ordinary JSON containers. The immutable audio bytes object is retained directly, so this hardening neither transforms nor copies rendered audio.

This candidate is cumulative with the accepted #137 final-bus and #106 QC repairs because the implementation identity is measured against the immutable frozen calibration:

- frozen predecessor: `ff938e70ba2598d5f6f6f0bc305e01b580c373a8e5daca849e8d3f9392bee3a4`
- cumulative #113 candidate: `ea2392f7987d27d2d6fa692a5191368cd611efe8464309a193edae7b50c6ad4c`
- implementation paths changed relative to frozen evidence: `zaaggenz_dsp/graph.py`, `zaaggenz_jobs/model.py`, `zaaggenz_qc/checks.py`

An unregistered merge-head run before the final deterministic-snapshot refinement exercised the full ZG-024a workflow on both Ubuntu and Windows: inverse, inherited prerequisite and browser transport suites passed, and both platforms failed the frozen comparison only at `/implementation_sha256` with the same then-current candidate identity. The registry entry above is deliberately exact and fail-closed for the final refined implementation; the repair may merge only after a full registered Ubuntu and Windows run reproduces the frozen portable calibration with no difference other than this declared implementation identity.

As with the earlier transitions, this record neither rewrites the frozen evidence nor grants a wildcard compatibility exemption. Any source change that produces a different implementation digest, or any drift in fixture/state/objective/eligibility/ranking/holdout/numerical evidence, still fails CI.

## Reviewed cumulative transition — issue #134

ZG-024 issue #134 closes a persisted-evidence gap: Candidate 1.0.0 stored several provenance SHA fields that were syntactically validated but were not all recomputable from material retained in the candidate itself. Candidate 2.0.0 therefore carries a mandatory content-addressed `InverseSearchBinding` with the canonical `SearchRequest`, fitting `AudioAssetRef` identities, method roots and complete numerical environment manifest. Reopening recomputes the historical search ID, method identities, environment identity, binding digest, stage/parent lineage and Candidate v2 identity. Legacy Candidate 1.0.0 fails closed for replay/regeneration because its missing binding cannot be reconstructed safely.

The reviewed cumulative identity is:

- frozen predecessor: `ff938e70ba2598d5f6f6f0bc305e01b580c373a8e5daca849e8d3f9392bee3a4`
- cumulative #134 candidate: `3e0920670fca37b5ac30447978125a3751dd6d1cee1ef7790aceb2e28b038178`
- newly changed implementation paths in #134: `zaaggenz_inverse/laboratory.py`, `zaaggenz_inverse/results.py`

Before registration, the complete ZG-024a workflow ran on Ubuntu and Windows. Both platforms passed all 93 inverse tests, including the new persisted-provenance adversarial suite, every inherited project/jobs/QC/analysis/components/descriptors/DSP/spectral/tuning suite, and browser transport. Both independently computed the exact identity above. The frozen calibration/independent-holdout comparison then failed closed with exactly one difference on each platform: the unreviewed `/implementation_sha256` transition. No portable fixture, state, recipe definition, objective, validation, eligibility, ranking, holdout or numerical evidence changed.

The registry entry authorizes only this exact frozen-to-cumulative identity pair. It does not weaken candidate verification, grant resumability across implementation identities, rewrite the frozen baseline, or permit any portable calibration drift. The registered rerun must still pass on both platforms before #134 can merge.

## Authoring / verification

Normal CI uses:

```text
python tools/inverse_foundation_report.py \
  --out inverse-evidence.json \
  --full-out inverse-full.json \
  --telemetry-out inverse-timing.json \
  --check examples/zg024a_inverse_calibration.json.gz \
  --implementation-transitions examples/zg024a_implementation_transitions.json
```

Without `--implementation-transitions`, comparison remains strict and any implementation identity difference fails. `--reference-out` remains the separate explicit mechanism for authoring a genuinely new calibration baseline; the transition registry is not a substitute for re-baselining when portable calibration semantics or results intentionally change.
