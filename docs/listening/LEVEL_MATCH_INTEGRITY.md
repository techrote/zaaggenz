# ZG-015 level-match numeric-integrity contract

This note records the corrective contract for issue #122. It does not change the `whole-file-rms-common-target-v1` matching method, frozen stimulus identity, playback hashes for previously valid requests, or the `zaaggenz-listening-*` 1.0.0 wire formats.

## External numeric controls

`ListeningAudioStore.match()` accepts two externally supplied dBFS controls:

- `peak_ceiling_dbfs` must be a real Python `int`/`float` value (not `bool`), must be finite, and must remain within the existing inclusive `-24.0 .. -0.1 dBFS` range;
- `target_rms_dbfs` may be `None` for the existing automatic common target, otherwise it must be a real finite numeric value whose dB-to-linear conversion is finite and strictly positive.

Strings, booleans, NaN and positive/negative infinity are rejected rather than coerced. Extreme finite dB values that overflow or underflow the linear conversion are also rejected explicitly. A finite explicit RMS target still has to satisfy the existing common sample-peak feasibility check; the matcher never silently limits it.

The loopback HTTP API uses the repository's strict JSON loader. Non-standard `NaN`, `Infinity` and `-Infinity` JSON tokens are rejected at the request boundary with HTTP 400 before matching is entered.

## Finite source and derived evidence

Before any playback-store mutation, matching now requires:

1. every frozen source sample used for matching to be finite;
2. source RMS and sample-peak statistics to be finite and non-silent under the existing threshold;
3. the chosen linear target and every derived gain to be finite and positive;
4. every derived float32 playback sample to be finite;
5. realised RMS/sample-peak statistics and every numeric field written to matched-playback metadata to be finite.

A failure of any of these checks produces no retained playback entry. Successful rows therefore remain safe for strict JSON serialization (`allow_nan=False`) and for later immutable trial validation.

## Transaction boundary

A match operation now computes all candidate playback bytes and metadata in local staging state. It computes the projected retained-byte cost before publishing any new playback hash. Only after all numeric checks and the existing store-budget check pass are staged playback blobs inserted.

This is intentionally compatible with the transactional/dedup accounting repair tracked by #115: an already retained playback hash is not removed when a later attempted match fails, and identical staged playback is counted once. Issue #115 still owns the broader single-budget model across raw additions, matched playback, logical ownership and persistence; this corrective change does not claim to close that separate work.

## Archive/API compatibility

No new wire-format field is required. Durable archive work tracked by #98 must preserve this invariant: matched playback metadata emitted by a successful matcher contains only finite JSON numbers, and corrupt/non-finite archive metadata must fail closed rather than be rewritten or regenerated.

The participant/trusted capability split, ABX truth handling, source/audio provenance, playback-only matching semantics and Compose state are unchanged.
