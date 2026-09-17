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

A listening stimulus is created **only from a completed `RenderArtifact`**. Freezing stores immutable project revision, exact RenderRecipe SHA-256, product/cache identity, source audio identity and shape, exact excerpt frames, SHA-256 of the excerpt float32 PCM, and inherited region/offset alignment metadata.

The exact excerpt bytes are copied into the bounded listening audio store. Later project edits and renders cannot change them. Missing bytes are never regenerated from current project state.

The audio-store accounting contract is `retained-pcm-physical-bytes-v1`: raw frozen PCM is retained by stimulus identity, matched playback is content-addressed by SHA-256, deduplicated playback is counted once physically, and admission is transactional. Failed operations leave older study material unchanged.

## Playback-only level matching

`ListeningAudioStore.match()` operates on 2–8 frozen stimuli. It measures whole-excerpt RMS and sample peak, chooses one common RMS target that respects a declared sample-peak ceiling, then applies one fixed gain per immutable stimulus.

Each matched row records source RMS/sample peak, matching gain, target and realised RMS, matched sample peak/headroom, resulting playback PCM SHA-256, method `whole-file-rms-common-target-v1`, and `true_peak_measured=false`.

Silent/near-silent material is rejected instead of boosted. Non-finite controls or PCM are rejected before retained state changes. A requested target that violates the common peak ceiling fails rather than being silently limited. This is **whole-file RMS playback matching**, not perceptual-loudness matching or true-peak certification.

## Trial designs and blinding

Three closed trial types are supported:

- **A/B** — exactly two matched stimuli;
- **ABX** — exactly two matched stimuli plus hidden X identity;
- **multi** — 2–8 matched stimuli.

Trusted/offline `make_trial()` remains deterministic from its explicit seed for fixture and evidence reproduction. The HTTP participant workflow uses a stronger boundary: visible presentation ordering may use the supplied seed, but ABX truth is selected from server-held cryptographic randomness and is not derivable from participant-visible state.

The participant projection is `zaaggenz-listening-participant-trial/1.0.0`. It omits the trusted manifest ID and seed, sets `abx_truth` to null, and uses a fresh opaque 256-bit participant trial ID. X audio is served through the opaque participant-trial route without a playback-SHA response header.

## Participant and trusted capabilities

The loopback service has two explicit capabilities:

- `zaaggenz-listening-capability/1.0.0`, role **participant** — returned by `/api/listening/bootstrap`; permits the visible freeze/match/create/play/submit workflow, participant-safe metadata export, and participant-safe archive export.
- **trusted/researcher** capability — a separate server-generated token never returned by participant bootstrap/static assets; required for trusted metadata export, trusted archive export, metadata reopen and durable archive reopen.

Loopback Host/Origin checks and CSP remain defence in depth; they do not replace role separation. Participant-created ABX trials keep truth server-side. Participant submission is terminal; a retake requires a new trial. Participant receipts and exports redact `abx_correct` and never carry the trusted trial ID or a digest that acts as a scoring oracle.

## Response semantics and registry bounds

A trusted result stores comparison choice, ABX correctness where applicable, declared 0–100 task endpoints, confidence, effort, comfortable level, replay counts, time-local annotations, free note and status `completed`, `aborted` or `missing`. Choices and annotations are bound to actual trial stimuli, annotation time is checked against the frozen playback clock, and missing records cannot fabricate substantive observations.

The in-memory metadata registry is explicitly bounded by `retained-listening-metadata-json-v1`: default limits are 512 trials, 4,096 results per trial, 16,384 total results, 64 MiB canonical retained metadata, 16 MiB result metadata per trial and 20 MiB per JSON export. These are process-safety limits, not scientific sample-size guidance. No evidence is silently evicted or truncated.

## Metadata bundles versus durable archives

The existing JSON formats remain unchanged:

- participant-safe `zaaggenz-listening-participant-bundle/1.0.0`;
- trusted `zaaggenz-listening-bundle/1.0.0`.

Those **1.0.0 JSON bundles are metadata-only**. Trusted `reopen_bundle()` still requires referenced playback bytes to already exist in the current audio store and fails clearly if they are missing. It never rerenders or rematches. This behaviour is retained for compatibility and is not silently reinterpreted.

Fresh-process reproducibility uses the self-contained binary transport **`zaaggenz-listening-archive/1.0.0`** (`application/vnd.zaaggenz-listening-archive`). It carries the role-appropriate existing bundle plus exact frozen raw PCM and exact matched playback PCM. Every byte blob is addressed by its existing SHA-256, and reopen verifies the manifest digest, framing, lengths, shapes and every blob hash before the material can be used.

The archive is deliberately **not ZIP/TAR and has no entry filenames or extraction paths**. Stimulus names remain metadata only; hostile names such as `../x` cannot become filesystem paths. This removes traversal/overwrite/arbitrary-extraction semantics rather than attempting to sanitise a path namespace that the format does not need.

Archive defaults are bounded to 16 unique blobs, 256 MiB restored retained PCM, 20 MiB canonical manifest metadata and 320 MiB total archive bytes. Blob count, manifest length and total archive size are rejected before parsing/material installation proceeds beyond the declared envelope. Reopen then also passes through the ordinary audio-store and registry admission checks, so archive import cannot bypass #115/#132 resource contracts.

Transport may deduplicate identical raw/playback bytes by SHA. On reopen, the normal store accounting is reconstructed exactly: raw entries remain stimulus-owned and playback remains SHA-deduplicated. Missing, corrupt, truncated, trailing or mismatched content fails; there is no fallback to current source state.

### Trusted archive

`POST /api/listening/trusted-archive` requires the trusted capability and returns a role `trusted` archive containing full trusted bundle provenance, including ABX truth and server-scored results where present. `POST /api/listening/reopen-archive` requires the trusted capability and accepts only the archive MIME type. A participant archive cannot be reinterpreted as trusted evidence.

Programmatically, `export_service_archive()`, `reopen_service_archive()` and `publish_service_archive()` provide the same contract. `publish_service_archive()` uses the accepted atomic publication primitive: write a sibling temporary file, flush/fsync it, honour cancellation before publication, then `os.replace`. Cancellation/failure therefore cannot replace an existing complete archive with a partial one.

### Participant archive

`POST /api/listening/archive` uses the participant capability and returns a role `participant` archive. Its embedded bundle is the same participant-safe projection as the JSON export: no trusted manifest ID, seed, hidden ABX truth or ABX correctness. Exact audio bytes do not grant a metadata/protocol truth oracle beyond the audio the participant is already entitled to hear.

### Rights and private-reference boundary

The archive follows only already-frozen `RenderArtifact` listening stimuli and their matched derivatives. It does **not** follow source locators, project paths or reference-library links and does not automatically include private reference recordings merely because provenance or a study refers to them. Raw material in the archive is the exact frozen render excerpt represented by the listening stimulus, not an arbitrary upstream file.

## Browser workflow

The `/listen` page starts from saved Compose project files:

1. choose project JSON and **Render + freeze** exact material;
2. select A/B, ABX or multi, presentation seed and endpoints;
3. level-match and create the participant-safe trial;
4. use blind playback controls, comfortable level, stop/rest, ratings and time-local annotation;
5. submit completed/aborted state and optionally export participant-safe evidence.

Compose remains available separately and is not modified when a trial is created, submitted or archived. Trusted archival operations are intentionally not exposed through participant capability.

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

The archive regression suite covers fresh-runtime bit-exact reopen without render/match state, raw/playback SHA identity, mono/stereo shape, completed/aborted/missing results, transport deduplication with restored store accounting, corruption/truncation/bounds, inert hostile names, cancellation-safe atomic publication, participant/trusted role separation and the legacy metadata-only fail-closed path. HTTP tests cover participant and trusted archive capabilities plus binary trusted reopen. The ZG-015 workflow runs the suite on Ubuntu and Windows.

Automated passing evidence demonstrates identity, matching, capability, durability and workflow integrity. It is not owner listening approval and does not establish that any acoustic change is preferred.
