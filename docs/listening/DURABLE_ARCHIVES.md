# ZG-015 trusted durable listening archives

Corrective issue #98 replaces the metadata-only trusted listening bundle with a self-contained, content-addressed archive while leaving the participant-safe export unchanged.

## Formats and roles

`zaaggenz-listening-bundle/2.0.0` is the **trusted/researcher archive**. It contains the authoritative trusted trial manifest, validated stimuli, trusted results and exact PCM needed to reopen the trial in a fresh process. It is available only through the existing trusted capability boundary.

`zaaggenz-listening-participant-bundle/1.0.0` remains the **participant-safe export**. It contains no trusted manifest ID, seed, ABX truth, ABX correctness or embedded audio. A participant bundle is never accepted by trusted reopen.

Legacy `zaaggenz-listening-bundle/1.0.0` files are metadata-only. Reopen now fails with an explicit migration diagnostic. They cannot be made self-contained after the original retained PCM is gone; while the original process/store is still available, re-export the trial as 2.0.0.

## Content-addressed audio envelope

The trusted archive uses a pathless JSON envelope. PCM is represented as canonical base64 of exact little-endian interleaved float32 bytes under encoding `base64-pcm-f32le-interleaved-v1`. No archive member names or filesystem paths are accepted, so traversal/overwrite semantics are absent from the format rather than filtered after extraction.

Each audio blob records:

- role: `raw-excerpt` or `matched-playback`;
- SHA-256 of the exact PCM bytes;
- byte length, sample rate, channel count and frame count;
- the sorted immutable stimulus IDs that own/reference the blob;
- canonical base64 payload.

Identical raw content and identical matched playback are emitted once per role and may reference multiple stimulus IDs. Raw frozen excerpts and matched derivatives are deliberately different namespaces even when their bytes happen to match. On reopen, raw bytes must agree with each stimulus's frozen `raw_pcm_sha256`; matched bytes must agree with every `playback_sha256` in the trusted manifest. Shape and content hashes are verified before publication.

The archive also carries `bundle_sha256`, a digest over the trusted metadata plus blob descriptors/content hashes. It is a reproducible content identity, not a digital signature. Per-blob SHA-256 verification is still mandatory before PCM is admitted.

## Provenance and semantic validation

Reopen reconstructs `Stimulus`, `TrialManifest` and `TrialResult` objects through their accepted validators. In addition, the frozen stimulus ID is recomputed from the original `zaaggenz.listening-stimulus-v1` identity material so an edited raw hash/provenance block cannot retain an old stimulus ID.

Result timing is revalidated against the exact frozen stimulus clocks, preserving the #105 completed/aborted/missing semantics. Level-match metadata remains `whole-file-rms-common-target-v1`; no matching calculation is rerun during reopen. ABX truth/scoring remains server-held trusted state and is not projected into participant exports.

## Bounded transport

The 2.0.0 transport has explicit admission bounds:

- at most **16 logical audio blobs** (the current maximum 8 stimuli, with at most one raw and one matched blob per unique content role);
- at most **64 MiB decoded PCM** in one trusted archive;
- at most **8 MiB descriptor/manifest/result metadata**;
- at most **4,096 result records** in one archive export/reopen;
- at most **104 MiB JSON request body** on the trusted reopen route, covering base64 expansion plus metadata headroom.

These are archive-transport bounds, not retention/participant-count policy. They reject without truncation or eviction. Corrective issue #132 remains responsible for long-lived trial/result-registry cardinality and scalable retention/export policy; this repair does not claim to solve that separate problem.

Reopen validates declared counts, sizes and base64 length before decoding payloads. The destination `ListeningAudioStore` then applies its existing `retained-pcm-physical-bytes-v1` accounting and fail-on-budget policy, including playback SHA deduplication. A valid archive therefore cannot bypass #115 store admission.

## Transaction and failure semantics

Export builds and validates the complete in-memory archive before it is returned to the HTTP serializer. There is no partially published archive path or output file.

Reopen validates the complete envelope, object contracts, coverage, bundle digest, base64 and all PCM hashes before registry publication. Audio admission is one locked `ListeningAudioStore.restore_archive()` transaction: pre-existing hash/provenance collisions and the projected store budget are checked before any new stimulus/raw/playback entry is installed. Trial/result/participant mappings are preflighted before that audio transaction. Validation failure therefore leaves prior retained evidence untouched.

Missing, corrupt, non-canonical, oversized, foreign or duplicate audio entries fail closed. Reopen never invokes rendering, level matching or source regeneration.

## Rights and private-reference boundary

Trusted archive export walks only the exact frozen `Stimulus` objects participating in the selected trial and their already-retained raw/matched PCM. It does not traverse reference-analysis registries, local file locators or private reference collections. Private reference recordings are therefore not included merely because other research state refers to them. Existing source-content hashes and provenance remain metadata; no unrelated local source file is read during export.

## Compatibility invariants

The repair changes only trusted archival transport from 1.0.0 to 2.0.0. It does not change source rendering, frozen excerpt selection, sample values, matching gains, playback SHA identities, ABX truth generation, participant capability semantics, trial/result formats, Compose state or any audio DSP/default.
