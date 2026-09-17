# Listening audio-store accounting

`ListeningAudioStore` uses the accounting method `retained-pcm-physical-bytes-v1`.

The store is deliberately **fail-on-budget**. It never evicts or regenerates frozen study material to make room for a new operation. A caller that needs a larger local study must construct the store with a larger explicit `max_bytes` or use a future reviewed durable-storage layer.

## Physical byte model

The authoritative retained-audio total is:

```text
raw_pcm_bytes
+ playback_pcm_bytes
= total_pcm_bytes
```

`raw_pcm_bytes` is the sum of exact frozen excerpt PCM byte strings retained by stimulus identity. Existing stimulus semantics are preserved: raw excerpts are not newly content-deduplicated by this corrective repair.

`playback_pcm_bytes` is the sum of unique level-matched PCM blobs keyed by their SHA-256. Multiple matched rows or trials may refer to the same playback hash; that physical blob is counted once. There is no reference-aware eviction because playback is never evicted during a store lifetime.

The byte limit covers retained PCM, the dominant bounded resource. Stimulus/trial/result metadata continue to use their separate schema/cardinality bounds and are not hidden inside a guessed per-entry byte surcharge.

`ListeningAudioStore.accounting()` returns the current method, raw/playback entry counts, each PCM byte subtotal, the total and `max_bytes`. This is the accounting snapshot that durable-storage work under issue #98 must preserve or reconstruct rather than inventing a competing ownership model.

## Transaction rule

Every mutating audio operation computes its additional physical bytes while holding the existing store lock and checks the projected authoritative total **before** publishing new retained audio.

- `add_artifact()` includes already-retained matched playback in its admission decision. Re-freezing an already-retained stimulus ID with identical PCM adds zero physical bytes; an identity collision with different PCM fails closed.
- `match()` stages all candidate playback blobs and metadata first. Existing playback hashes add zero physical bytes; new hashes add their exact PCM length. The complete projection is checked before any staged playback is inserted.
- A failed admission leaves existing raw stimuli and playback blobs unchanged. In particular, a later failed transaction cannot remove a playback hash shared by an older valid trial.

The exact limit is inclusive: a transaction whose projected total equals `max_bytes` is accepted; one byte over is rejected. The store does not clamp audio, drop stimuli, truncate playback or silently alter level matching to satisfy the budget.

## Protected semantics

This repair does not change stimulus identity, excerpt bytes, level-match method `whole-file-rms-common-target-v1`, playback SHA-256 identity, ABX truth/blinding, result semantics, source/render provenance, or any DSP/default audio behavior. It only makes the existing local-memory bound authoritative across both raw and matched PCM.
