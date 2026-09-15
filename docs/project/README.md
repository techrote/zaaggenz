# Immutable project state v1

ZG-003 stores **committed musical state as immutable RenderRecipe snapshots**. UI audition state is separate and is never serialized or promoted merely because a preview was requested.

A revision identifier is derived from the canonical recipe SHA-256 and parent revision. Recommitting an unchanged recipe is a no-op. Project files contain only portable contract data, revision ancestry and named render-slot metadata; local cache paths are deliberately absent.

Named render slots (`synth`, `arrange`, `arrange_bass`, `bass` products) bind a committed revision to an `AudioAssetRef` plus a cache key. The bounded local `ArtifactCache` keeps bytes and local locators outside project identity, verifies declared content identity before publication and again before returning a blob, and evicts least-recently-used records when its byte budget is exceeded.

## Artifact-cache byte identity

`AudioAssetRef.content_sha256` is always the SHA-256 of the **exact bytes stored in the cache** for both supported identity domains. The cache does not decode, transcode, normalize or reinterpret a payload while inserting it.

- `encoded-file-bytes-v1`: the supplied encoded byte sequence must hash exactly to `content_sha256`. `frame_count` describes the represented audio and is not inferred from encoded-file length.
- `pcm-f32le-interleaved-v1`: the payload is the canonical interleaved little-endian float32 sequence. Its byte length must equal `frame_count × channels × 4`, and SHA-256 of that exact sequence must equal `content_sha256`. This is the same byte/hash/shape boundary enforced by `RenderArtifact`.

The cache also stores a private `blob_sha256` for local corruption detection. Because both supported domains define `content_sha256` over the exact cached byte sequence, `blob_sha256` and the declared content hash must agree in index metadata. That invariant, and PCM byte-count/frame/channel consistency, are checked when an existing index is opened without first trusting or reading every blob. Retrieval then hashes the actual blob and revalidates the complete declared identity before returning bytes.

Caches created before this rule was enforced are **not silently migrated**. If an old index contains a valid private blob hash but a conflicting declared `AudioAssetRef.content_sha256`, opening the cache fails closed. The caller must discard/rebuild that local cache from authoritative render inputs; project revisions and render-slot provenance are not rewritten. This policy keeps cache repair separate from recipe/engine/product cache keys and from project identity.

`recipe_diff()` reports exact JSON-pointer-like paths rather than guessing whether a difference is musically important. Cache invalidation keys include recipe identity, engine identity and render product; quality/tuning/automation/stage-order changes are already part of recipe identity through ZG-002.

## File safety and migrations

Format `zaaggenz-project` / `1.0.0` rejects unknown fields, malformed ancestry, mismatched recipe/revision hashes, dangling render slots, duplicate JSON keys and unsupported versions. Files are written atomically. No historical on-disk zaaggenz project format is claimed to exist before v1; therefore there is **no invented legacy migration**. `migrate_document()` explicitly accepts current v1 and fails older/future versions until a reviewed migration is registered. This fail-closed behaviour is the migration baseline.

## Validation

CI materializes the authenticated v1.2.1 engine and proves that a LOCKED BLOOM recipe rendered before save and after reload is array-identical in the declared environment. Tests also cover audition isolation, cache identity/corruption/eviction, rejected partial publication, pre-fix cache fail-closed handling, revision tampering, recipe diffs and cache invalidation.
