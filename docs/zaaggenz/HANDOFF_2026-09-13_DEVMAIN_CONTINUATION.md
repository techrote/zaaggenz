# ZaagGen DEVmain continuation — handoff record (2026-09-13)

This file records the repository work completed during the current continuation session and the exact state at pause. It is intended as a restart point for a fresh agent/chat. Do not reinterpret it as a new programme specification; issue bodies, accepted contracts and the programme graph remain authoritative.

## Accepted work completed during this continuation

| Issue | PR | Merge commit | Final feature CI | Independent contracts/legacy CI | Result |
|---|---:|---|---|---|---|
| ZG-011 directional modal grammar / #12 | #65 | `2590a1428b73a830655a55b0f82a63772f6236a8` | `34731539464` | `34731539463` | merged |
| ZG-009 practical composition timeline / #10 | #66 | `74267daef47d4676c3bdd5ac8df39a3a8bb2e7f7` | `34732495376` | `34732495372` | merged |
| ZG-025 phrase-role windows / #26 | #67 | `063356f976a14da40b755adabbd5f250a403d8e2` | `34747324666` | `34747324681` | merged |
| ZG-026 nested meter and cross-rhythms / #27 | #68 | `114613842e45053db37a99f4410fca62b625cf62` | `34747877079` | `34747877069` | merged |
| ZG-027 directional gestures / #28 | #69 | `56346648fe8947b01dd2d2b1098f83e60fa43c62` | `34748349992` | `34748350105` | merged |
| ZG-028 linked fake-out / reinterpretation / return / #29 | #72 | `79c576c193bf34b8cb505aa75236b622f96246f1` | `34749006138` | `34749006065` | merged |
| ZG-031 safe text-to-gesture language / #32 | #71 | `59807209abe02d08e4b8899f044ac566e29a91ae` | `34748992559` | `34748991833` | merged |
| ZG-032 local vocal-gesture capture / #33 | #73 | `492e614524bc27ab2f6f1ae05eb6541c61d13e2f` | `34783707902` | `34783707873` | merged |
| ZG-015 blinded, level-matched listening / #16 | #74 | `a6ffdc7d22c2736aee7f9b228d1de869f7e062c1` | `34784571890` | `34784571889` | merged |

All merges above were made only after final-head Windows and Ubuntu checks passed. Protected defaults/frozen shared schemas were kept intact unless an accepted issue explicitly owned a new separate authoring wrapper.

## ZG-032 details worth retaining

ZG-032 added an optional loopback-only local vocal-control path without making microphone support a dependency of Compose or text-gesture workflows.

Key accepted semantics:

- raw capture/import PCM is session-local, content-addressed and independently discardable;
- immutable `VocalAnalysis` stores confidence-bearing onset/accent, voiced pitch where valid, brightness and explicit voiced/unvoiced/low-confidence state;
- unvoiced/low-confidence regions do **not** receive a confident pitch by force;
- editable alignment stores a snapped beat plus original timing error/offset;
- time, pitch and brightness corrections are independent and reversible;
- a manually supplied pitch can intentionally promote an abstained region into a note;
- project-local ZG-031 mnemonic dictionaries are reused rather than inventing a second text/control language;
- compiled PhrasePlan/TimelineDocument remain valid after raw source discard;
- brightness/mnemonic timbral changes remain typed deferred automation with protected-topology rewrite disabled;
- real browser acceptance starts without recording permission, imports WAV, corrects a region, renders through normal timeline jobs, discards source audio and exports Compose state.

Final deterministic 48 kHz evidence used known synthetic/PCM16 recording-path fixtures, not participant recordings. It measured about 30 ms onset error and roughly 1.2–1.5 Hz voiced-pitch error on the fixture; the middle noise region abstained. Both source-derived preview renders reported zero clipping. No human vocal data was committed.

## ZG-015 details worth retaining

ZG-015 added the reusable local listening/trial substrate now available to ZG-040 and later studies.

Accepted semantics:

- freeze exact already-rendered excerpts; do not silently regenerate a stimulus after project edits;
- stimulus provenance includes project revision, RenderRecipe hash, render cache key, source asset identity, excerpt boundaries, raw excerpt PCM identity and alignment metadata;
- level matching uses one documented playback-only whole-file RMS gain per stimulus plus sample-peak/headroom diagnostics;
- current implementation explicitly does **not** claim perceptual-loudness matching or true-peak measurement;
- A/B, ABX and 2–8 item multi trials are deterministic under their seed;
- browser-facing ABX state keeps answer truth opaque while trusted export retains it;
- ABX correctness, choice, task-specific ratings, confidence, effort, comfortable level, replay counts, time-local annotations, missing and aborted status are distinct fields;
- bundle reopen requires the exact playback blobs and refuses silent regeneration;
- ordinary Compose remains independent from the listening/research workflow.

The first CI attempt (`34784485317`) found an evidence-script defect only: report-only `wav_file`/`wav_sha256` fields were appended to strict matched-stimulus rows before passing them into `TrialManifest`. The validator was correct. Commit `3ee06c4166534346afdcd484b032a3607e79ecf9` fixed the report generator by keeping immutable matched rows pristine and moving WAV presentation metadata into a separate evidence table. Final run `34784571890` passed unchanged strict validators plus real Chromium acceptance on both platforms.

Remote final evidence recorded common matched RMS near `-32.4914 dBFS`, gains around `0.0`, `-3.2199`, `-1.0104 dB`, and roughly 18.18–18.54 dB sample-peak headroom for the deterministic three-stimulus fixture. These are engineering controls, not listener outcomes.

## Active issue at pause: ZG-017 / #18

Branch: `zg-017/partial-spectral-autotune`

The branch has **no implementation commits yet**. It was initially created from ZG-032 main, then fast-forwarded at pause to current main `a6ffdc7d22c2736aee7f9b228d1de869f7e062c1`, so a future continuation can start cleanly without reconciling ZG-015.

Issue #18 has a claim comment reserving the spectral-registry/render-integration work for this branch. No PR exists yet.

### ZG-017 design already established

Use the accepted ZG-013 `PartialTrackBundle` and ZG-007 `TuningSpec`; do not introduce a parallel component representation.

The intended first implementation is:

1. Build a validated/versioned spectral-retune request/plan wrapper outside frozen shared schemas.
2. Consume existing component track frames, including frequency, per-channel amplitudes/phases, support windows and confidence/ambiguity metadata.
3. Map transform-eligible confident components toward an explicit tuning/target lattice in log-frequency space. Support harmonic and explicitly nonharmonic teeth; low-confidence or ambiguous material is preserved rather than guessed.
4. Keep displacement/glide bounded and maintain track continuity across frames, starts, gaps, crossings and target changes.
5. Propagate the **same phase correction trajectory to all stereo channels** so existing inter-channel phase relationships are retained.
6. Resynthesise transformed sinusoidal ownership, while retaining the original ZG-013 transient and residual arrays unchanged. The effect should not retune attacks/residual by accident.
7. Amount `0` / bypass must follow the declared exact identity path, not a reconstruct-and-approximately-null path.
8. Expose source/requested/realised frequency plus confidence and the preserve/transform decision for inspection.
9. Provide retune-only first. Reweight/hybrid/Chordness remains ZG-018, and pre/post/inter-nonlinearity placement remains ZG-019.
10. Add isolated-tone, crossing, target-change, low-confidence, transient+tonal and stereo-antiphase fixtures. Measure target error, discontinuity, residual/transient preservation, stereo relation and transformed ghost energy.
11. Integrate through a bounded render adapter/job without changing `locked_bloom` or existing default DSP ordering.

Relevant accepted files already inspected:

- `zaaggenz_components/model.py` — `ComponentAnalysis`, `ComponentTrackerSpec`, exact-bypass semantics.
- `zaaggenz_components/reconstruct.py` — current sinusoidal resynthesis convention uses frame support, Hann weighting, frequency, anchor sample, per-channel amplitude and phase.
- `docs/zaaggenz/briefs/SPECTRAL_HARMONY.md` — target-comb/identity/residual/source-character constraints.
- `zaaggenz_tuning/*` and the frozen contract registry — reuse rather than fork.

### Immediate next steps when resuming

1. Re-read issue #18 plus `SPECTRAL_HARMONY.md` and current ZG-013 docs/tests.
2. Implement `zaaggenz_spectral` (or similarly narrow package) containing request/plan validation, target lattice assignment and phase-continuous transformed bundle/resynthesis.
3. Write acceptance tests before browser/UI work: exact bypass, isolated retune error, glide/target change, crossing ambiguity, low-confidence preserve, transient/residual unchanged, stereo antiphase preservation.
4. Add bounded render/job adapter and target/source/realised inspection data.
5. Generate deterministic 48 kHz evidence and cross-platform CI; only then open/merge the PR.

## Dependency consequences at pause

- ZG-015 is now accepted, so ZG-040 (study manifests/preregistration/statistics) is dependency-ready if its trial-registry lock is free.
- ZG-032 is accepted, so ZG-037 and the later Compose/Research UX chain have that prerequisite satisfied, but their other prerequisites still govern readiness.
- ZG-017 remains the active disjoint engineering stream and unlocks ZG-018/ZG-019/ZG-029 work downstream once accepted.

## Claims and evidence boundaries

Across this session:

- generated numerical/browser fixtures are not owner listening approval;
- synthetic recording-path evidence is not human participant data;
- acoustic descriptors are not preference/pleasure measures;
- no biochemical/reward claim is inferred;
- no private reference audio was committed;
- `locked_bloom` and source-preserving behavior remain compatibility anchors.

Pause state is intentional. No background work is running.