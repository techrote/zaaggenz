# ZG-015 — blinded, level-matched listening and annotation

ZG-015 adds an **optional local Research workflow** beside Compose. It freezes exact completed renders into immutable listening stimuli, applies one documented playback-only level match, randomises A/B, ABX or multi-example presentation, records task-specific responses, and exports provenance/results without changing the working project.

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

The corresponding excerpt bytes are copied into a bounded local listening store. Later edits/renders do not modify them. If the exact bytes are missing on trusted bundle reopen, the system fails explicitly; it does **not** rerender the current project and pretend the stimulus is unchanged. Durable fresh-process archive transport is tracked separately by corrective issue #98.

This distinction is important for owner audition and controlled studies: a label such as “A” refers to frozen audio identity, not mutable UI state.

## Playback-only level matching

`ListeningAudioStore.match()` operates on 2–8 frozen stimuli. It measures whole-excerpt RMS and sample peak, chooses one common RMS target that respects a declared sample-peak ceiling, then applies one fixed gain per immutable stimulus.

Each matched row records source RMS dBFS/sample peak, matching gain, target and realised matched RMS, matched sample peak/headroom, resulting playback PCM SHA-256, method `whole-file-rms-common-target-v1`, and `true_peak_measured=false`.

Silent/near-silent material is rejected instead of being boosted. A requested target that violates the common peak ceiling fails rather than being silently limited. This is **whole-file RMS playback matching**, not perceptual-loudness matching or true-peak certification.

## Trial designs and blinding

Three closed trial types are supported:

- **A/B** — exactly two matched stimuli;
- **ABX** — exactly two matched stimuli plus hidden X identity;
- **multi** — 2–8 matched stimuli.

Trusted/offline `make_trial()` remains deterministic from its explicit seed for fixture and evidence reproduction. The HTTP participant workflow deliberately has a stronger boundary: the visible seed may determine presentation ordering, but **ABX truth is selected from server-held cryptographic randomness and is never derivable from that participant-visible seed**. The authoritative trusted manifest stores the exact truth and seed and is content-addressed as before.

The participant projection is a distinct `zaaggenz-listening-participant-trial/1.0.0` view. It contains the material required to conduct the task, but omits the seed and trusted manifest ID, sets `abx_truth` to null, and uses a fresh opaque 256-bit participant trial ID. The opaque ID is not a digest of hidden truth. This closes both the direct truth field leak and the two-candidate hash/origin-seed inference paths.

X audio is served only through the opaque participant-trial route and does not disclose a playback SHA header. A/B playback necessarily remains available to the browser so a listener can hear it; the capability boundary prevents protocol/metadata oracles, not a malicious participant performing arbitrary signal analysis on audio they are entitled to hear.

Neutral instruction templates are included for A/B, ABX and multi-example tasks. They avoid implying a preferred answer or telling the listener what acoustic property should be liked.

## Participant and trusted capabilities

The loopback HTTP service now has two explicit capabilities:

- `zaaggenz-listening-capability/1.0.0`, role **participant** — the token returned by `/api/listening/bootstrap`. It permits the visible freeze/match/create/play/submit workflow and **participant-safe export only**.
- **trusted/researcher** capability — a separate server-generated token that is never returned by participant bootstrap or static browser assets. It is required for `/api/listening/trusted-export` and `/api/listening/reopen`.

Loopback Host/Origin checks and CSP remain defence in depth; they do not substitute for role separation. Supplying the participant token to a trusted route, omitting the trusted token, or forging it fails with HTTP 403.

Participant-created ABX trials use server-held truth and expose only the opaque participant trial ID. Participant submission is terminal: once a response (completed, aborted or missing) is accepted, the same public trial cannot be submitted again. A retake requires a newly created trial. This makes the response boundary irreversible rather than allowing an answer to be edited after scoring.

The participant submission receipt deliberately withholds `abx_correct`, the trusted trial ID and any digest over the trusted result. Its `result_sha256` is the digest of the participant-safe receipt itself, so it cannot be used as a one-bit correctness oracle.

## Response fields remain separate

A trusted result stores independent fields rather than collapsing them into one score: comparison choice; ABX correctness (ABX only); named 0–100 task endpoints; confidence; effort; comfortable playback level; per-stimulus replay counts plus X replay count; time-local annotations; free note; and status `completed`, `aborted` or `missing`.

ABX correctness is validated from the hidden trusted manifest and is never inserted into ratings. Ratings are accepted only for endpoints declared before the trial. An aborted/missing result cannot claim ABX accuracy. Participant receipts/exports retain the submitted response but redact `abx_correct` to null.

These fields are observations, not audio descriptors. Liking/excitement/urge-to-move are not biochemical measurements.

## Export and reopen

There are now two non-interchangeable export surfaces.

`/api/listening/export` returns `zaaggenz-listening-participant-bundle/1.0.0`. It contains stimulus provenance, the participant-safe trial projection and participant-safe response projections. It never contains the trusted manifest ID, seed, hidden ABX truth or ABX correctness. The visible browser download button uses this format, including before a response has been submitted.

`/api/listening/trusted-export` requires the trusted capability and returns the existing `zaaggenz-listening-bundle/1.0.0`: complete stimulus provenance, authoritative trusted manifest including ABX truth, and full results including server-scored ABX correctness. `/api/listening/reopen` likewise requires the trusted capability and accepts only the trusted bundle format; a participant bundle cannot be reinterpreted as trusted evidence.

Raw/matched WAV bytes remain in the bounded local audio store rather than being duplicated into JSON. Trusted reopen validates every provenance object and requires the exact playback SHA-256 bytes to remain available. Missing audio causes an explicit error. This prevents an edited project from silently generating replacement research material.

## Browser workflow

The `/listen` page intentionally starts from already saved Compose project files:

1. choose project JSON files and **Render + freeze** them;
2. select A/B, ABX or multi, presentation seed and endpoints;
3. level-match and create the participant-safe trial (ABX truth is server-held, not derived from the visible seed);
4. use blind playback controls, comfortable level, stop/rest, ratings and time-local annotation;
5. submit completed/aborted state and optionally download the participant-safe bundle.

Compose stays available in a separate route and is not modified when a trial is created or submitted. Trusted archival export is intentionally not exposed to participant browser capability.

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

The direct HTTP suite checks pre-answer participant export, bootstrap, trial projection, X route, forged/missing trusted capability, trusted-ID misuse, one-shot submission, participant result receipts, trusted archival export, foreign Origin and invalid participant tokens. Service tests additionally cover A/B and multi views, participant-bundle rejection by trusted reopen, and exact trusted scoring.

Real Chromium acceptance performs the normal UI workflow and verifies that its downloaded bundle is participant-safe while the server-held trusted archive retains the exact hidden truth and score. Existing level matching, immutable stimulus identity, replay counts, annotations and Compose independence remain exercised.

Automated passing evidence demonstrates identity, matching, capability and workflow integrity. It is not owner listening approval and does not establish that any acoustic change is preferred.
