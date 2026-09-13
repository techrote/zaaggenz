# ZG-031 verification record

Branch: `zg-031/text-gesture-language`. Base: accepted ZG-027 merge `56346648fe8947b01dd2d2b1098f83e60fa43c62`.

Final acceptance is produced by `.github/workflows/zg031-textgesture.yml` on the final PR head. It runs syntax/dictionary/bundle/preview/render tests, accepted ZG-027 gesture tests, ZG-007 tuning tests and ZG-009 timeline tests on Ubuntu and Windows, then emits three full-rate 48 kHz generated-source evidence conditions. The independent ZG-002 contract/legacy workflow must also pass before merge.

The final PR and issue completion comment record actual final-head workflow IDs, artifact IDs and inspected hashes. This file intentionally does not predeclare a passing run.

Evidence boundaries: mnemonic dictionaries are project-local data, not phonetic universals; source spans are diagnostics rather than musical parameters; preview is non-mutating; reopening a bundle recompiles instead of trusting caches; structured gestures remain editable without text; unsupported timbral axes remain explicit ZG-027 deferred automation; fixture level matching is not perceptual-loudness or owner-listening evidence.
