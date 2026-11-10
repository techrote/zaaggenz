# NYQ / direct saved Compose to offline A/B audition (opt-in)

This is one direct musician-facing command, built entirely on the exact existing #275 source/session adapter, #266 sampler, #267 clock packet, #277 48-kHz delivery, #281 dry/wet ZIP producer and #282 local A/B HTML publisher. It adds no second DSP implementation, no new session, no graph/rack registry mutation, no default sound change, no cloud call and no external recording access.

Run on a branch/build containing this candidate and its reviewed ancestors:

~~~sh
python -m zaaggenz_runtime.nyquismic_offline_audition \
  --project song.zgtimeline.json \
  --output song-ab.html \
  --virtual-hz 11730/1 \
  --evaluation-hz 192000
~~~

Open the new `song-ab.html` in a local browser. Press PLAY, choose A (original Compose post-rack) or B (the same original Compose audio after Nyquismic modulation), and seek/pause as needed. Both channels are embedded as unchanged, source-verified 48-kHz IEEE float32 WAVs. No level matching, clipping, normalization or extra sampler step is inserted by this wrapper. Browser hardware can independently resample its playback. A standalone browser/real listening test is **not** established by the Python tests.

## Source custody and publication boundary

The program invokes the existing #281 saved-project renderer **once** and lets its normal `TimelineService`/authoritative `RuntimeSession` bind the complete Compose source and immutable controlled-clock packet. It writes the existing source-authenticated A/B ZIP inside an auto-cleaned private temporary directory; verifies the temporary ZIP SHA before generating HTML; calls #282's independent WAV/decoded-PCM verifier and same-directory fsync/no-overwrite hardlink HTML publisher; and deletes the intermediate ZIP on both success and failure. **Only the user-requested HTML file is published.** An existing destination, symlink or competing writer fails closed.

Cancellation propagates through full rendering and both output stages. A user edit to the saved project *on disk* after the source snapshot is opened is not monitored: this is a one-snapshot offline command, not a live job attached to an already-open editor. Session and render-job cancellation/revision checks occur before the original A/B source ZIP publication; later HTML generation reads only that finalized immutable snapshot. No live-session authority is claimed after the render has closed.

The receipt includes the project snapshot SHA, authoritative source revision and recipe, controlled-clock packet SHA, dry/wet decoded float32 PCM SHA, source ZIP SHA, final HTML SHA, delivery rate and frame count. Receipts are hashes and audit references, not a digital signature or a claim of universal cross-host exact intermediate rendering identity.

Resource limits, 48-kHz integral frame/duration requirements, finite PCM, finite FIR and job budgets, three-entry archive validation, and native filesystem hard-link support are inherited unchanged from the actual producers. Large output exceeding #282's 64-MiB input limit fails closed. No user output is overwritten; crash-durable parent directory sync is not claimed.

## Qualification / owned paths

This Draft adds exactly:

- `zaaggenz_runtime/nyquismic_offline_audition.py`
- `tests/runtime/test_nyquismic_offline_audition.py`
- `docs/dsp/NYQ_DIRECT_AUDITION.md`

No changes to #266/#267 author source, #275 Integration adapter, #280/#283 assembled branches, CI or provenance, programme acceptance, shared registries, the accepted MBR rack/UI, defaults, or VST.

~~~sh
python -m unittest discover -s tests/runtime -p 'test_nyquismic_offline_audition.py' -v
python -m unittest discover -s tests/runtime -p 'test_*.py' -v
python -m unittest discover -s tests/timeline -p 'test_*.py' -v
python -m unittest discover -s tests/listening -p 'test_*.py' -v
python -m unittest discover -s tests/inspector -p 'test_*.py' -v
python -m unittest discover -s tests/vocal -p 'test_*.py' -v
~~~

New tests cover one genuine original synthetic saved Compose render through final portable HTML, independently decoded dry/wet PCM with manifest and output hashes, same-host cold reopen, preexisting user data, bad output/project, cancellation after source publication, intermediate ZIP tampering, late HTML fsync cancellation, competing destination writers, cleanup, and CLI receipt. They print numerical provenance in original-host CI logs. The existing ZG-041 matrix covers Ubuntu and Windows runtime and existing Chromium application smoke. Existing Chromium tests do **not** exercise standalone HTML playback.

**Admission boundary:** This remains a stacked, opt-in Draft until actual source-exact CI and independent ZaagGenZ Integration qualification. It is not ordinary registered Compose GUI export, per-band/upstream graph routing, full NYQ #252/#253 admission, #242 Phase-A operator/spectral acceptance, #254, or VST Phase B. Keep Integration's main-based #283 review independent and do not merge this branch without guarded source-safe reconciliation.
