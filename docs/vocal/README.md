# ZG-032 — local vocal-gesture capture

ZG-032 adds an **optional local** authoring path for vocal imitation. A short WAV can be imported, or the browser can request a recording input only after the user presses **Start recording**. Normal Compose, text gestures and the full instrument do not require recording permission or an input device.

The feature deliberately separates three things:

1. **ephemeral source audio** — bounded PCM held only in the loopback process;
2. **immutable analysis evidence** — authoritative source identity, regions, timing, confidence and abstention state;
3. **editable musical correction** — grid suggestion, sample offset, mnemonic, pitch/brightness correction and approval.

The exported Compose timeline contains derived musical data and the immutable source provenance embedded by the analysis/edit, not raw captured PCM.

## Launch

```console
python baseline/recovered_source/materialize_v2.py --out .
python -m pip install numpy==2.3.5 scipy==1.17.0 -r requirements-contracts.txt -r requirements-jobs.txt
python -m zaaggenz_vocal --open
```

The server binds only `127.0.0.1`. `/vocal` links to the accepted `/timeline` Compose editor and the full instrument. WAV import remains available when browser recording APIs are unavailable or permission is denied.

## Authoritative source identity

Vocal analysis/edit documents are version `1.1.0`. Canonical decoded audio first receives a full SHA-256 over little-endian, C-order, interleaved float32 PCM under the content domain `pcm-f32le-interleaved-v1`. That PCM hash is **not by itself** the authoritative vocal source identity because sample rate and channel interpretation determine the meaning of the same bytes.

The authoritative domain is `zaaggenz-vocal-source-v1`. Its canonical manifest binds:

- `content_sha256` of the canonical float32 PCM;
- `sample_rate_hz`;
- `channels`;
- `frame_count`;
- the explicit PCM domain.

The canonical JSON manifest is SHA-256 hashed in full and exposed as `capture-v1-<64 lowercase hex>`. `VocalAnalysis` recomputes this identity on construction, so altering the content hash, sample rate, channel count, frame count or authoritative ID is rejected. A short/truncated capture handle is not used as provenance.

`origin` (`local-import`, `local-recording`, or deterministic `generated-fixture`) is deliberately **provenance rather than source-interpretation identity**. It is therefore excluded from `capture-v1` so the same interpreted PCM remains the same semantic source. Origin is nevertheless covered by the immutable analysis/edit document digest. Inside one session store, attempting to insert an already-known source with a different origin fails rather than overwriting the earlier provenance. Exact duplicate PCM plus interpretation plus origin deduplicates and only refreshes its LRU position.

Paths and private filenames are never inputs to the authoritative identity. Raw PCM remains session-local.

### Legacy `1.0.0` policy

ZG-032 `1.0.0` analysis/edit records used `capture-<16 hex>` identifiers derived only from the PCM hash prefix. Those identifiers cannot prove sample-rate/channel interpretation and can refer to state that was historically rebound in a session store. They are therefore **not silently migrated or reinterpreted** as `1.1.0`.

Loading a legacy `1.0.0` `VocalAnalysis` or `VocalEdit` fails closed with an explicit diagnostic. If the original raw source is still available, re-import/re-analyse it and recreate the edit under `1.1.0`; this produces a new metadata-complete identity. If raw source was discarded, the old document remains historical evidence but is not promoted into the new authoritative identity domain by guesswork.

## Analysis and abstention

`analyse_vocal()` produces a versioned `zaaggenz-vocal-analysis` document. Mono and stereo are supported; capture duration is bounded to 30 seconds. Analysis source metadata is produced by the same canonical identity helper used by `SessionAudioStore`, and `VocalService.analyse()` mechanically requires the complete stored source record and analysis source record to match before creating an edit.

The estimator uses short-window RMS activity, autocorrelation periodicity and spectral flatness. Brightness observations are taken through the accepted ZG-012 multiresolution feature timeline. Every region records:

- original start/end sample;
- onset confidence and relative accent;
- `voiced`, `unvoiced` or `low-confidence` state;
- pitch value only when the region passes the explicit voicing/confidence gate;
- pitch confidence;
- brightness and brightness confidence;
- spectral flatness.

An unvoiced or low-confidence region **cannot** carry a confident pitch in the analysis contract. Noise and silence are tested specifically so they are not coerced into note estimates. This is an engineering estimator, not speech recognition or a claim about human vocal categories.

## Grid alignment without destroying timing

`make_edit()` maps each original onset into the accepted TimeMap, suggests the nearest selected grid point using exact rational arithmetic and the same half-to-even convention used elsewhere, then stores:

- `aligned_beat` — editable grid suggestion;
- `alignment_error_samples` — immutable difference between captured onset and the suggestion;
- `manual_offset_samples` — independent correction applied at compile time.

The original analysis samples remain unchanged. Editing the grid or offset never rewrites the captured observation.

## Manual correction and dictionary mapping

Each region can be independently:

- approved or excluded;
- assigned a project-local ZG-031 mnemonic token;
- kept on the estimated pitch, explicitly set to manual Hz, or explicitly unpitched;
- moved by exact beat plus sample offset;
- given a manual brightness value.

The active ZG-031 dictionary is snapshotted by registry hash. The same capture can therefore map through `local-soft` or `local-bright` without changing capture identity. Mnemonics remain project-local semantics, not universal vocal meanings.

By default a captured unvoiced region compiles to a **rest** with its timing retained. It becomes a note only after an explicit manual pitch correction. Clearing that correction returns it to the unpitched state.

## Source-preserving Compose output

`compile_edit()` converts approved rows to an ordinary ZG-008 PhrasePlan and accepted ZG-009 TimelineDocument. The target pitch is resolved through the active tuning; the protected source object is reused unchanged. Dictionary density can create the already-supported source-derived roll gesture. Brightness plus dictionary roughness/occupancy/width are exported as typed `deferred-explicit` automation with `protected_topology_rewrite=false`; ZG-032 does not silently modify the nonlinear graph.

`make_render_recipe()` creates a normal source-derived preview recipe. Renderer pitch/range limits remain explicit and fail instead of clamping.

## Raw-source discard is independent

`SessionAudioStore` retains at most four capture assets and evicts/discards them independently of the authoring state. Pressing **Discard source audio** removes the PCM from the session and changes only `source_disposition` in the edit document.

The immutable metadata-complete source record remains embedded in the analysis/edit alongside manual corrections. PhrasePlan and Compose timeline remain usable without retained PCM. Tests compile before and after source discard and require identical phrase/timeline data. This makes deletion of the local source independent from keeping the derived gesture or its provenance.

## Local HTTP trust boundary

The vocal server inherits the accepted loopback Host/Origin checks and timeline session-token model. Vocal mutation endpoints require the same random session token. Upload accepts only bounded WAV data; no API accepts an arbitrary filesystem path. Static routes are allowlisted.

The source-audio route accepts only the full `capture-v1-<64 hex>` identifier and serves PCM only while that exact source remains in the session store.

This remains a single-user loopback authoring server, not a public recording service.

## Browser workflow

The `/vocal` page exposes three explicit stages:

1. import WAV or choose to start/stop a local recording;
2. analyse, inspect confidence and edit alignment/pitch/brightness/mnemonic/approval with undo/redo;
3. update a preview, render through the normal timeline job path, discard source audio independently, or export the editable `.zgtimeline.json` document.

The page does not request recording permission during load. CI browser acceptance creates a browser context with recording permission absent, imports a WAV, performs a manual correction, renders, discards the source and exports the still-valid timeline.

## Verification

```console
python -m unittest discover -s tests/vocal -v
node tests/vocal/editor.mjs
python tools/vocal_fixture_report.py --out vocal-fixtures-48k.json --artifact-dir vocal-evidence-48k --sample-rate 48000
python tests/vocal/browser.py --out vocal-browser-acceptance
```

Identity regressions additionally require deterministic deduplication, same-PCM/different-sample-rate separation, identical flattened bytes under mono/stereo interpretation separation, origin-conflict rejection without overwrite, full-hash metadata tamper rejection, bounded LRU behavior and exact store→analysis→edit→preview identity continuity.

The deterministic 48 kHz report includes two conditions:

- direct generated float PCM;
- the same known signal passed through a PCM16 **recording-path** WAV boundary.

Both contain two known voiced regions and one known unvoiced/noise region. CI quantifies onset and pitch error, confidence, abstention, manual correction and source-discard invariance. The recording-path fixture is deliberately labelled synthetic; it is **not** represented as a human recording. Real human capture is private/session-local and can be evaluated with the same code without committing it to the repository.

Automated estimator accuracy, finite rendering and browser success are not evidence of owner listening approval, preference, emotion or biochemical response.
