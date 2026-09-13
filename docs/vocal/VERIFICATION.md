# ZG-032 verification record

Branch: `zg-032/local-vocal-gesture`. Base: accepted ZG-031 main `59807209abe02d08e4b8899f044ac566e29a91ae`.

Local pre-publication checks on Python 3.13 / NumPy 2.3.5 / SciPy 1.17.0:

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

Final acceptance is produced by `.github/workflows/zg032-vocal.yml` on the PR head. It runs the vocal suite, accepted text/gesture/analysis/component/timeline regressions, deterministic 48 kHz evidence, Node editor tests, and real Chromium import/correction/render/discard/export acceptance on Ubuntu and Windows. The independent ZG-002 contracts/legacy workflow must also pass before merge.

Evidence boundaries: pitch/brightness confidence is estimator confidence, not listener confidence; unvoiced abstention is explicit; project-local mnemonic mapping is not universal phonetics; browser acceptance does not require recording permission; successful rendering is not owner audition approval or affective evidence.
