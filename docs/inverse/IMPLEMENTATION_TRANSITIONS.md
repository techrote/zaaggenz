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
