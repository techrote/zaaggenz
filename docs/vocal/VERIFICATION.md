# ZG-032 verification record

Original ZG-032 branch: `zg-032/local-vocal-gesture`. Base: accepted ZG-031 main `59807209abe02d08e4b8899f044ac566e29a91ae`.

Original local pre-publication checks on Python 3.13 / NumPy 2.3.5 / SciPy 1.17.0:

- ZG-032 vocal suite: **15 passed**;
- browser-editor Node checks: passed;
- accepted ZG-031 text gesture suite: **18 passed**;
- accepted ZG-027 gesture suite: **14 passed**;
- accepted ZG-012 analysis suite: **15 passed**;
- accepted ZG-013 component suite: **13 passed**;
- accepted ZG-009 timeline suite: **24 passed**;
- 48 kHz deterministic capture/recording-path fixture report: passed.

Local 48 kHz evidence contains two known conditions: direct generated float PCM and the same signal quantized through a PCM16 recording-style WAV boundary. Both yield three active regions with voicing states `voiced / unvoiced / voiced`. Onset error is 30 ms for all three regions. Voiced pitch errors are approximately 1.23–1.53 Hz. The middle noise region has no pitch estimate and compiles to a rest until explicit manual correction.

Both source-derived previews are finite and report `clipped_fraction = 0.0`. Explicitly correcting the unvoiced region to 136 Hz plus a 17-sample timing offset and manual brightness produces a note for that region only. Discarding the raw source after correction preserves PhrasePlan and TimelineDocument data exactly.

The local recording-path fixture is deterministic synthetic audio, not a human recording. This is intentional: CI must not commit private vocal material or imply that synthetic evidence is participant data. A private human recording can use the same local/session path without becoming a repository artifact.

## Corrective source-identity verification — issue #104

Repair branch `repair/zg032-vocal-source-identity-104` starts from main `e17753223bc1bf488164af094f72b84ac0ab0711`, after the accepted #120 unsigned-WAV decoding correction.

The repair deliberately changes only vocal source-provenance representation and session-store keying. `pcm-f32le-interleaved-v1` remains the exact canonical PCM content domain. `zaaggenz-vocal-source-v1` adds the authoritative interpretation digest over that full content SHA-256 plus sample rate, channel count and frame count. Origin remains provenance metadata rather than source interpretation, but conflicting origin cannot overwrite an already-known session source. The analysis/edit format is versioned to `1.1.0`; legacy `1.0.0` truncated capture IDs fail closed instead of being guessed into the new domain.

The corrective regression matrix requires:

- exact duplicate PCM + interpretation + origin to deduplicate deterministically;
- identical PCM bytes with different sample rates to retain distinct immutable identities without either record being rebound;
- identical flattened PCM bytes interpreted as mono versus stereo to have the same PCM content SHA where applicable but distinct authoritative source identities;
- source-ID, PCM-hash and interpretation-metadata tampering to fail model construction;
- a conflicting origin on an already-known source to fail without replacing the existing provenance;
- deterministic bounded LRU behavior after duplicate access;
- complete source identity agreement through store → analysis → edit → preview;
- raw-source discard to preserve compiled PhrasePlan/Timeline output and embedded source provenance;
- HTTP source-audio lookup to require the complete `capture-v1-<64 hex>` identity;
- the existing real-browser import/correct/render/discard/export workflow to remain green.

No source filename/path enters the identity. No DSP, pitch/brightness estimator, source-preserving renderer, protected topology, level/gain policy or musical default is changed by #104.

Final corrective acceptance is produced by `.github/workflows/zg032-vocal.yml` on the PR head on Ubuntu and Windows, together with the repository's relevant contract/legacy and reverse-dependency gates. Exact final PR/run/merge identifiers are recorded on issue #104 after all required automated checks pass.

Evidence boundaries remain unchanged: pitch/brightness confidence is estimator confidence, not listener confidence; unvoiced abstention is explicit; project-local mnemonic mapping is not universal phonetics; browser acceptance does not require recording permission; successful rendering is not owner audition approval or affective evidence.
