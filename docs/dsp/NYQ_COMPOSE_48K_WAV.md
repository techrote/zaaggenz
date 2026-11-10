# NYQ production candidate — source-bound, in-memory 48-kHz float WAV

**Scope:** opt-in full-mix production adapter for #249/#252/#253, stacked on
Integration's independently limited-claim #275 Compose binding and #273
consumer/packet evidence. This is a proposed source-disjoint follow-on, **not**
a registered instrument, graph node, ordinary Compose export path, approved
per-band insert or completed NYQ-003/NYQ-004 acceptance. Keep Draft/HOLD.

## Executable path

`zaaggenz_runtime.nyquismic_compose_delivery.render_compose_controlled_48k_wav`
accepts an actual `bind_completed_compose(timeline, completed_job_id)`
binding plus the selected `SonicSpec`, #267 authored-route clock packet and
`sampler_evaluation(...)`. It performs:

1. Full-phrase source/graph/session preflight and strict rational extent
   admission onto **both** numerical and 48,000-Hz grids.
2. Existing #266 controlled `SamplerPlan` at the caller's explicit numerical
   rate, with checkpoint/event-ledger semantics unchanged.
3. Existing NYQ-003 `convert_numerical_to_delivery` **after** artistic clock
   damage, with the versioned non-normalising Kaiser-FIR policy. There is no
   hidden anti-aliasing of the virtual capture *before* damage.
4. Explicit float64-to-float32 output conversion without clipping or peak
   normalisation, then in-memory IEEE-float WAV encoding at **48,000 Hz**.
   The WAV is decoded again before publication and its sample rate, shape,
   dtype and exact PCM bytes are checked.
5. Source-asset/recipe/packet, numerical PCM, converter kernel, output f64 PCM,
   decoded f32 PCM and WAV SHA-256 receipts. The whole result is published
   under #275's current-job/session final handoff lock, **after** FIR and
   serialization, so late edits, job cancellation and caller cancellation
   observed at that boundary refuse output.

This interface returns immutable bytes and a frozen receipt. It **does not
write to disk**: filesystem atomicity and integration with the standard
Compose export transaction must be separately qualified by Integration.
A caller saving bytes after return must revalidate its current session and
own an atomic-publication boundary; an external save is not certified here.
A newly created receipt object is not an independent graph authority.

## Qualification

```sh
python -m unittest discover -s tests/runtime -p 'test_nyquismic_compose_delivery.py' -v
python -m unittest discover -s tests/runtime -p 'test_nyquismic_compose.py' -v
python -m unittest discover -s tests/dsp -p 'test_nyquismic_delivery.py' -v
python -m unittest discover -s tests/dsp -p 'test_nyquismic_controlled_consumer.py' -v
```

Tests render synthetic one-second Compose PCM via a real `TimelineService`,
compile the author's six-event 4-to-8-to-4-Hz packet, and compare numerical
PCM/checkpoint replay against decoded 48-kHz float WAV via the independently
implemented pinned final FIR. They cover saved-document cold reopen and
injection of an ordinary Compose edit during WAV encoding, owned-job
cancellation after the FIR, and caller cancellation during encoding. A
small delivery budget must fail before sampler preparation. Recording original
supported Ubuntu/Windows CI, exact hashes, independent review and final-host
receipts remains required; writing the tests does not certify their execution.

## Explicit limits

No upstream audio-derived feature authority; no 44.1-kHz mode; no general
output-rate selector; no public editing UI, graph/registry/stack placement,
wet/dry rack integration, persistent saved NYQ preset or disk-export
transaction. This is a **48-kHz float WAV candidate**, not 16-bit PCM and
not approved product export. Do not update legacy/default processing, #266/
#267 owner files, provenance registrations or programme dependency state on
this branch. MBR-004 #242 Gates A/B remain independent external blockers.
#254 and VST #243 remain unstarted under their existing acceptance gates.
