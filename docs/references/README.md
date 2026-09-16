# Private reference ingest v1

ZG-006 makes locally supplied references reproducible **without committing source recordings**.

## Identity before filename

`references/private_registry_v1.json` records six expected SHA-256 identities, byte sizes, native format hints, explicit rights/redistribution status and the planning-audit measurements. `filename_hint` is convenience only and is never accepted as proof that a local file is the expected asset.

Users maintain a separate ignored locator file such as `reference-locators.user.local.json`:

```json
{"version":"1.0.0","paths":{"activation":"D:/private/Activation.mp3","zaagtivation":"D:/private/Zaagtivation.mp3"}}
```

Resolve metadata without audio analysis:

```sh
python -m zaaggenz_reference --locators reference-locators.user.local.json --out reference-verification.json
```

Add `--analyse` to decode locally via FFmpeg, preserve **unclamped f32 stereo** at 24 kHz and recompute the descriptor audit. Reports deliberately omit local source paths. A missing or hash-mismatched asset is reported; there is no filename-based substitution.

Verification reports are strict JSON: NaN and Infinity are not permitted evidence values. Descriptor construction also fails closed if any computed numeric evidence is non-finite.

### Stereo-correlation evidence

`stereo_correlation` is ordinary Pearson correlation for stereo inputs only when both decoded channels have non-zero variance. Its normal finite range remains `[-1, 1]`, so existing non-degenerate reference measurements retain the same interpretation and tolerance.

Pearson correlation has no mathematical value when either channel is constant. For such finite stereo audio the descriptor therefore emits `stereo_correlation: null`, never a fabricated `0`, `1`, or NaN. The adjacent `stereo_correlation_evidence` object records `status: "unknown"` and one of `left-channel-zero-variance`, `right-channel-zero-variance`, or `both-channels-zero-variance`. This reason is evidence provenance, not a failed source-identity or rights gate. The pre-existing mono convention (`stereo_correlation: 1.0`) is retained for compatibility and is labelled `legacy-mono-convention` / `mono-input` rather than being presented as an observed stereo measurement.

Planning comparison remains unchanged for the current frozen registry, which does not claim a stereo-correlation planning target. If a planning record explicitly requests correlation comparison and the observed value is unknown, that check is marked unavailable and non-passing; unknown evidence is never treated as numerical agreement.

## Planning audit lineage

The six supplied files were already recomputed during the 2026-09-12 preflight using Python 3.13.5, NumPy 2.3.5, SciPy 1.17.0 and FFmpeg 7.1.5. Exact file identities are frozen in the registry. The original Activation/Zaagtivation planning method reproduced exactly in that run. `planning_audit_v1.json` records the dependency context and inference boundaries.

The integrated method deliberately retains sample peaks above 1.0. The files are mastered observations, not synthetic ground truth, and LUFS/true peak do not imply calibrated playback SPL.

The zero-variance correlation rule is a numeric-integrity clarification of `zg-reference-descriptor-v1`: previously the edge case had no declared value and NumPy could leak NaN. It does not revise any finite, defined v1 correlation, source identity, rights status, decoded-audio ownership, planning target, or private-reference provenance.

## Pair annotation

`paired_suggestions_v1.json` carries six previous spectral-similarity suggestions as **zero-confidence automatic suggestions**. They are not accepted motif correspondence. Annotation structures support:
- segment/section function and confidence;
- multiple metre/pulse interpretations with confidence mass;
- manual vs automatic provenance;
- corresponding, unrelated or uncertain pair relations;
- local correspondence groups rather than one forced whole-track time warp.

A future manual review should create new manual records rather than silently upgrading these suggestions.

## Rights / repository safety

All six current references have `redistribution: not-authorized-in-repository`. This is a conservative repository policy, not a legal determination about the music. `tools/check_reference_safety.py` fails if Git tracks obvious compressed audio or bytes matching any registered private-reference SHA-256, even if renamed.

`references/private/` is ignored except for its `.gitignore`; local media and locator files stay outside normal project exports. Analytic development/holdout families are listed separately in `holdout_families_v1.json`.

No result here asserts a unique production chain, exact chord transcription or genre classifier.
