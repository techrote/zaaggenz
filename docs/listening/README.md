# ZG-015 — blinded, level-matched listening and annotation

ZG-015 adds an **optional local Research workflow** beside Compose. It freezes exact completed renders into immutable listening stimuli, applies one documented playback-only level match, randomises A/B, ABX or multi-example presentation, records task-specific responses, and exports provenance/results for exact local reopening.

Nothing in this workflow is required to compose, render or export music. Opening `/timeline` remains the normal Compose path.

## Launch

```console
python baseline/recovered_source/materialize_v2.py --out .
python -m pip install numpy==2.3.5 scipy==1.17.0 -r requirements-contracts.txt -r requirements-jobs.txt
python -m zaaggenz_listening --open
```

The server binds only `127.0.0.1`. `/listen` links back to Compose and the full recovered instrument.

## Immutable listening material

A listening stimulus is created **only from a completed `RenderArtifact`**. Freezing stores:

- immutable project revision ID;
- exact RenderRecipe SHA-256;
- product and render cache key;
- source audio content SHA-256, sample rate, channel count and frame count;
- exact excerpt start/end frames;
- SHA-256 of the excerpt float32 PCM;
- inherited region/offset alignment metadata.

The corresponding excerpt bytes are copied into a bounded local listening store. Later edits/renders do not modify them. If the exact bytes are missing on bundle reopen, the system fails explicitly; it does **not** rerender the current project and pretend the stimulus is unchanged.

This distinction is important for owner audition and controlled studies: a label such as “A” refers to frozen audio identity, not mutable UI state.

## Playback-only level matching

`ListeningAudioStore.match()` operates on 2–8 frozen stimuli. It measures whole-excerpt RMS and sample peak, chooses one common RMS target that respects a declared sample-peak ceiling, then applies one fixed gain per immutable stimulus.

Each matched row records:

- source RMS dBFS and sample peak;
- matching gain dB;
- target and realised matched RMS dBFS;
- matched sample peak and headroom;
- resulting playback PCM SHA-256;
- method `whole-file-rms-common-target-v1`;
- `true_peak_measured=false`.

Silent/near-silent material is rejected instead of being boosted. A requested target that violates the common peak ceiling fails rather than being silently limited.

This is **whole-file RMS playback matching**, not perceptual-loudness matching or true-peak certification.

## Trial designs and blinding

Three closed trial types are supported:

- **A/B** — exactly two matched stimuli;
- **ABX** — exactly two matched stimuli plus hidden X identity;
- **multi** — 2–8 matched stimuli.

Ordering and ABX truth are derived deterministically from an explicit seed using SHA-256-based draws. The manifest stores the seed, exact presentation order, full matched-stimulus rows, requested endpoints, instruction template and rest/comfortable-level policy. Its ID is a content digest over the entire manifest.

The browser receives an ABX manifest with the hidden truth removed. X audio is served through an opaque trial route; the browser cannot derive truth from the filename or playback hash shown for A/B.

Neutral instruction templates are included for A/B, ABX and multi-example tasks. They avoid implying a preferred answer or telling the listener what acoustic property should be liked.

## Response fields remain separate

A result stores independent fields rather than collapsing them into one score:

- comparison choice;
- ABX correctness (ABX only);
- named 0–100 task endpoints such as liking, sound quality, groove, source identity, sonority fit, harshness, excitement, tension, urge to move, recognition and difficulty;
- confidence;
- effort;
- comfortable playback level;
- per-stimulus replay counts and separate X replay count;
- time-local annotations attached to an identified stimulus;
- free note;
- status: `completed`, `aborted` or `missing`.

ABX correctness is validated from the hidden manifest truth and is never inserted into ratings. Ratings are accepted only for endpoints declared before the trial. An aborted/missing result cannot claim ABX accuracy.

These fields are observations, not audio descriptors. Liking/excitement/urge-to-move are not biochemical measurements.

## Export and reopen

A `zaaggenz-listening-bundle` contains:

- complete stimulus provenance documents;
- immutable trial manifest including hidden ABX truth for trusted export/reanalysis;
- all captured results.

Raw/matched WAV bytes remain in the bounded local audio store rather than being duplicated into JSON. Reopen validates every provenance object and requires the exact playback SHA-256 bytes to remain available. Missing audio causes an explicit error. This prevents an edited project from silently generating replacement research material.

## Browser workflow

The `/listen` page intentionally starts from already saved Compose project files:

1. choose project JSON files and **Render + freeze** them;
2. select A/B, ABX or multi, seed and endpoints;
3. level-match and create the immutable trial;
4. use blind playback controls, comfortable level, stop/rest, ratings and time-local annotation;
5. submit completed/aborted state and export the bundle.

Compose stays available in a separate route and is not modified when a trial is created or submitted.

## Verification

```console
python -m unittest discover -s tests/listening -v
python -m unittest discover -s tests/project -v
python -m unittest discover -s tests/jobs -v
python -m unittest discover -s tests/timeline -v
python -m unittest discover -s tests/qc -v
node tests/jobs/browser_transport.mjs
python tools/listening_fixture_report.py --out listening-fixtures-48k.json --artifact-dir listening-evidence-48k --sample-rate 48000
python tests/listening/browser.py --out listening-browser-acceptance
```

The full-rate evidence tool generates three original source-derived engineering stimuli, freezes them, creates common matched playback and emits A/B, ABX and multi manifests. It contains **no participant response data** and does not infer preference.

Real Chromium acceptance exercises project import, render/freeze, matching, opaque ABX X playback, endpoint ratings, replay counts, confidence/effort, time annotation, result submission, bundle export and navigation back to ordinary Compose.

Automated passing evidence demonstrates identity, matching and workflow integrity. It is not owner listening approval and does not establish that any acoustic change is preferred.
