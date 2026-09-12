# Immutable project state v1

ZG-003 stores **committed musical state as immutable RenderRecipe snapshots**. UI audition state is separate and is never serialized or promoted merely because a preview was requested.

A revision identifier is derived from the canonical recipe SHA-256 and parent revision. Recommitting an unchanged recipe is a no-op. Project files contain only portable contract data, revision ancestry and named render-slot metadata; local cache paths are deliberately absent.

Named render slots (`synth`, `arrange`, `arrange_bass`, `bass` products) bind a committed revision to an `AudioAssetRef` plus a cache key. The bounded local `ArtifactCache` keeps bytes and local locators outside project identity, verifies content hashes and evicts least-recently-used records when its byte budget is exceeded.

`recipe_diff()` reports exact JSON-pointer-like paths rather than guessing whether a difference is musically important. Cache invalidation keys include recipe identity, engine identity and render product; quality/tuning/automation/stage-order changes are already part of recipe identity through ZG-002.

## File safety and migrations

Format `zaaggenz-project` / `1.0.0` rejects unknown fields, malformed ancestry, mismatched recipe/revision hashes, dangling render slots, duplicate JSON keys and unsupported versions. Files are written atomically. No historical on-disk zaaggenz project format is claimed to exist before v1; therefore there is **no invented legacy migration**. `migrate_document()` explicitly accepts current v1 and fails older/future versions until a reviewed migration is registered. This fail-closed behaviour is the migration baseline.

## Validation

CI materializes the authenticated v1.2.1 engine and proves that a LOCKED BLOOM recipe rendered before save and after reload is array-identical in the declared environment. Tests also cover audition isolation, cache corruption/eviction, revision tampering, recipe diffs and cache invalidation.
