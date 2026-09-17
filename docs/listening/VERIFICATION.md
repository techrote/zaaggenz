# ZG-015 verification record

Branch: `zg-015/listening-trials`. Base: accepted ZG-032 main `492e614524bc27ab2f6f1ae05eb6541c61d13e2f`.

Local pre-publication checks on Python 3.13 / NumPy 2.3.5 / SciPy 1.17.0:

- ZG-015 listening suite: **13 passed**;
- accepted project suite: **16 passed**;
- accepted jobs suite: **23 passed**;
- accepted timeline suite: **24 passed**;
- accepted QC suite: **14 passed**;
- existing browser stale-result transport checks: passed;
- deterministic 48 kHz three-stimulus matching/trial report: passed.

The local full-rate report freezes three source-derived four-beat stimuli, matches them to one common whole-file RMS target and creates deterministic A/B, ABX and multi-example manifests. Matched RMS is approximately **-32.49 dBFS** in the local environment. Matching gains are approximately `0.00`, `-3.22` and `-1.01` dB; matched sample-peak headroom exceeds 18 dB in this fixture. These are sample-peak/RMS engineering quantities, not a perceptual loudness or true-peak claim.

Every stimulus records immutable project revision, RenderRecipe hash, render cache key, source asset identity, excerpt frames, raw excerpt PCM hash and alignment metadata. Every matched playback has its own PCM SHA-256. Tests edit/render projects after freeze and verify the frozen stimulus is unchanged; reopening a bundle in a store without exact playback bytes fails instead of regenerating from project state.

Trial tests distinguish A/B choice, hidden ABX accuracy, task ratings, confidence, effort, comfortable level, per-stimulus/X replay counts, time-local annotations and completed/aborted/missing status. No field is relabelled as preference, acoustic quality or biochemical response when it is not that endpoint.

Local Playwright acceptance was not claimed because a managed Chromium binary was not present in the local environment. The final PR workflow installs Chromium on Windows and Ubuntu and runs the real browser workflow against the actual loopback numerical server.

Final acceptance is produced by `.github/workflows/zg015-listening.yml` plus the independent ZG-002 contracts/legacy workflow. The PR/issue completion comment records final head SHA, workflow IDs, artifact IDs and remote evidence inspection.

## Corrective semantic validation (#105)

The result wire format remains `zaaggenz-listening-result/1.0.0`, but authoritative validation now binds A/B and multi choices to exact presented stimulus IDs, binds every annotation target to the trial, defines completed/aborted/missing observation policy, and validates annotation time against the exact frozen stimulus presentation clock whenever trusted stimulus metadata is available. Live service submission and trusted bundle reopen always supply that timing context. The canonical rules and compatibility policy are recorded in `RESULT_SEMANTICS.md`.

This repair does not alter frozen stimulus bytes, level matching, ABX truth generation, participant/trusted capability separation, valid-result serialization/digests, Compose state, or any DSP/default behaviour.

## Corrective level-match numeric integrity (#122)

The matching method and listening wire formats remain unchanged. `ListeningAudioStore.match()` now validates external dBFS controls as finite numeric values before conversion, rejects non-standard JSON NaN/Infinity tokens at the existing strict HTTP contract boundary, and requires source PCM, derived gains, matched PCM, realised statistics and emitted numeric metadata to remain finite.

Candidate playback bytes are staged and the existing retained-byte budget is preflighted before `_playback` is changed. This makes numeric failures transactionally clean and prevents an over-budget attempt from deleting a previously retained deduplicated playback hash. The broader unified raw/playback accounting and ownership work remains tracked by #115; durable archive work in #98 must preserve the finite-metadata invariant.

The hostile/boundary suite for this correction covers NaN/+Inf/-Inf RMS targets and peak ceilings, strings/booleans, exact peak-ceiling boundaries and just-outside values, extreme finite target conversion, non-finite source PCM, strict JSON request rejection, finite PCM/metadata assertions, and preservation of pre-existing shared playback across a failed staged match. The normative policy is recorded in `LEVEL_MATCH_INTEGRITY.md`.
