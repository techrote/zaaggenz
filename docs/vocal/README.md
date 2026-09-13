# ZG-032 — local vocal-gesture capture

ZG-032 adds an **optional local** authoring path for vocal imitation. A short WAV can be imported, or the browser can request a recording input only after the user presses **Start recording**. Normal Compose, text gestures and the full instrument do not require recording permission or an input device.

The feature deliberately separates three things:

1. **ephemeral source audio** — bounded PCM held only in the loopback process;
2. **immutable analysis evidence** — content identity, regions, timing, confidence and abstention state;
3. **editable musical correction** — grid suggestion, sample offset, mnemonic, pitch/brightness correction and approval.

The exported Compose timeline contains derived musical data and the source content identity, not raw captured PCM.

## Launch

```console
python baseline/recovered_source/materialize_v2.py --out .
python -m pip install numpy==2.3.5 scipy==1.17.0 -r requirements-contracts.txt -r requirements-jobs.txt
python -m zaaggenz_vocal --open
```

The server binds only `127.0.0.1`. `/vocal` links to the accepted `/timeline` Compose editor and the full instrument. WAV import remains available when browser recording APIs are unavailable or permission is denied.

## Analysis and abstention

`analyse_vocal()` produces a versioned `zaaggenz-vocal-analysis` document. Audio identity is SHA-256 over canonical interleaved float32 PCM. Mono and stereo are supported; capture duration is bounded to 30 seconds.

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

The immutable analysis, manual corrections, PhrasePlan and Compose timeline remain valid. Tests compile before and after source discard and require identical phrase/timeline data. This makes deletion of the local source independent from keeping the derived gesture.

## Local HTTP trust boundary

The vocal server inherits the accepted loopback Host/Origin checks and timeline session-token model. Vocal mutation endpoints require the same random session token. Upload accepts only bounded WAV data; no API accepts an arbitrary filesystem path. Static routes are allowlisted.

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

The deterministic 48 kHz report includes two conditions:

- direct generated float PCM;
- the same known signal passed through a PCM16 **recording-path** WAV boundary.

Both contain two known voiced regions and one known unvoiced/noise region. CI quantifies onset and pitch error, confidence, abstention, manual correction and source-discard invariance. The recording-path fixture is deliberately labelled synthetic; it is **not** represented as a human recording. Real human capture is private/session-local and can be evaluated with the same code without committing it to the repository.

Automated estimator accuracy, finite rendering and browser success are not evidence of owner listening approval, preference, emotion or biochemical response.
