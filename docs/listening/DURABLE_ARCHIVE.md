# ZG-015 durable listening archive contract

Issue #98 adds a transport layer without changing the accepted stimulus, trial, result or level-matching formats.

## Identity and version

The binary transport identifies itself as:

- format: `zaaggenz-listening-archive`;
- version: `1.0.0`;
- MIME: `application/vnd.zaaggenz-listening-archive`;
- role: `trusted` or `participant`.

The embedded JSON bundle remains an existing `1.0.0` bundle. Archive versioning is independent from the listening-record wire versions so durability can evolve without silently changing scientific/result semantics.

## Framing

The stream is deterministic:

1. magic `ZG-LISTEN-ARCHIVE\0\1`;
2. unsigned big-endian 32-bit canonical-manifest byte length;
3. canonical UTF-8 JSON manifest;
4. zero or more SHA-sorted blob records, each `32-byte SHA-256 | uint64 big-endian byte length | exact bytes`.

For a valid trial the manifest contains 2–8 raw material rows and 2–8 matched-playback rows. Its `blobs` table is the unique SHA-sorted union of all referenced audio. There are no archive filenames, entry paths, symlinks, extraction destinations or filesystem metadata.

The manifest contains its own SHA-256 over every field except `manifest_sha256`. Each material row records stimulus ID, content SHA, byte length, sample rate, channels and frame count. Exact float32 shape must agree with byte length.

## Validation order

`decode_archive()` fails closed on:

- total archive size above the configured limit;
- bad magic or manifest framing;
- manifest size above the configured limit;
- malformed/non-UTF-8/non-JSON manifest;
- unsupported format/version/role;
- duplicate/missing stimulus rows;
- unsorted/duplicate or over-limit blob table;
- material/blob length disagreement;
- restored PCM above the configured bound;
- storage-accounting mismatch;
- manifest digest mismatch;
- truncated/mismatched blob framing;
- any blob SHA mismatch;
- trailing bytes.

No filesystem extraction occurs at any point.

`reopen_service_archive()` then reconstructs immutable `Stimulus` and `TrialManifest` objects, binds archived bytes to the exact stimulus raw SHA and trial playback SHA, validates float32 shape/finiteness, preflights the ordinary `ListeningAudioStore` budget, and installs audio transactionally. It finally invokes the existing trusted metadata reopen path, which revalidates result semantics and #132 registry budgets. If metadata reopen fails, only PCM newly installed by that archive attempt is rolled back.

No missing content is regenerated, rerendered or rematched.

## Storage accounting

Archive manifests carry `retained-pcm-physical-bytes-v1` accounting:

- raw entries are counted per stimulus, matching `ListeningAudioStore` ownership;
- playback entries are counted once per unique playback SHA;
- `restored_pcm_bytes` is the exact store footprint the archive would add in an empty store;
- `archive_unique_blob_bytes` is the transport payload after SHA deduplication;
- `unique_blob_count` bounds transport cardinality independently.

Default archive limits are:

- 16 unique audio blobs;
- 256 MiB restored retained PCM;
- 20 MiB canonical manifest;
- 320 MiB entire archive.

The ordinary audio-store and listening-registry limits remain authoritative additional admission gates.

## Roles and blinding

A trusted archive embeds `zaaggenz-listening-bundle/1.0.0` and therefore preserves complete trusted trial/result provenance, including server-held ABX truth where applicable. Trusted export and trusted reopen require the researcher capability.

A participant archive embeds `zaaggenz-listening-participant-bundle/1.0.0`. It omits the trusted trial ID and seed, keeps `abx_truth=null`, and redacts `abx_correct`. A participant archive is explicitly rejected by trusted reopen; role is not inferred from payload contents.

## Legacy migration policy

`zaaggenz-listening-bundle/1.0.0` remains a supported **metadata-only** format. It is not reinterpreted as a durable package. Reopening it succeeds only when all referenced playback bytes are already resident. In a fresh runtime it fails with the existing explicit missing-audio/no-regeneration diagnostic. To carry a study across process restart, export `zaaggenz-listening-archive/1.0.0` before closing the source runtime.

There is intentionally no synthetic migration that rematches or rerenders a legacy bundle whose bytes are already gone, because doing so would manufacture new research material under an old identity.

## Atomic publication

`publish_service_archive()` first builds and validates the complete byte payload, then delegates to the accepted `atomic_publish_bytes()` primitive. Publication uses a sibling temporary file, flush + fsync, cancellation check, and atomic replace. A cancelled or failed publication leaves any previous destination intact and removes the temporary file.

## Rights/provenance boundary

Archive export follows only exact bytes retained by the listening stimulus store: the frozen `RenderArtifact` excerpt and its matched derivative. It never follows a source locator or arbitrary project/reference path. Consequently a private reference file is not included merely because a trial, project or provenance record mentions it. Existing rights/local-locator separation remains authoritative.

## Non-effects

This repair does not change:

- source or matched PCM generation;
- gain calculation or sample-peak policy;
- trial randomisation or ABX scoring;
- result semantics/digests;
- protected source/audio topology;
- Compose project state;
- DSP or audible defaults.
