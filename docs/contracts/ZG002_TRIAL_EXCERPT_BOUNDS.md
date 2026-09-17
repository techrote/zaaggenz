# ZG-002 TrialSpec excerpt-bound correction

Issue #108 reconciles the frozen `TrialSpec` v1.0.0 schema and semantic validator around one existing invariant:

```text
0 <= start_sample < end_sample <= asset.frame_count
```

## Compatibility classification

This is a **patch-compatible validator hardening** under the contract-evolution policy. No contract version changes.

The exported Draft 2020-12 schema already defined both `start_sample` and `end_sample` with the shared non-negative integer schema. Therefore a negative excerpt coordinate was already rejected by the public `validate()` path during shape validation and was never an accepted v1.0.0 document. The residual defect was that the semantic `_trial()` predicate expressed only `start_sample < end_sample <= frame_count`, so the two validation layers did not independently encode the same physical-domain rule.

The correction adds the missing lower-bound check to semantic validation. It does not reinterpret, clamp, wrap, pad, migrate, or otherwise repair an invalid excerpt. Existing valid `TrialSpec` JSON, canonical bytes, digests and meaning remain unchanged.

## Boundary semantics

`TrialSpec` excerpts use half-open sample coordinates in the declared `AudioAssetRef`:

- `[0, frame_count)` is the exact full-asset excerpt and is valid when `frame_count > 0`;
- interior excerpts are valid when both endpoints satisfy the invariant above;
- negative coordinates, zero-length or reversed excerpts, and `end_sample > frame_count` are invalid;
- changing/tampering `asset.frame_count` can invalidate a formerly valid excerpt and must fail validation rather than trigger implicit padding or truncation;
- endpoints retain the existing JSON safe-integer domain.

Shape validation owns scalar lexical/range constraints such as non-negative integer coordinates. Semantic validation independently owns the complete cross-field containment invariant. A schema-only pass remains insufficient for ordering and asset-extent relationships.

## Consumer impact

Downstream study/listening consumers may continue to rely on the existing `TrialSpec` v1.0.0 identity and wire format. They may additionally rely on successful shared semantic validation to guarantee that every stimulus excerpt lies wholly inside its declared asset. No DSP, source audio, level matching, trial randomisation, endpoint, or artistic/default behavior changes in this correction.
