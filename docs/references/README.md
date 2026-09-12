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

## Planning audit lineage

The six supplied files were already recomputed during the 2026-09-12 preflight using Python 3.13.5, NumPy 2.3.5, SciPy 1.17.0 and FFmpeg 7.1.5. Exact file identities are frozen in the registry. The original Activation/Zaagtivation planning method reproduced exactly in that run. `planning_audit_v1.json` records the dependency context and inference boundaries.

The integrated method deliberately retains sample peaks above 1.0. The files are mastered observations, not synthetic ground truth, and LUFS/true peak do not imply calibrated playback SPL.

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
