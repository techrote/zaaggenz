# Listening registry resource contract

Corrective issue #132 bounds the in-memory trial/result registry used by ZG-015. The policy is versioned as `retained-listening-metadata-json-v1` and is deliberately separate from the physical PCM accounting introduced by #115.

## Why the registry is bounded

The participant HTTP body is bounded, and each individual `TrialManifest` / `TrialResult` is structurally bounded, but those facts did not bound repeated valid submissions. Before this repair, `ListeningService.trials` and the per-trial result lists could grow for the lifetime of the process and trusted export eagerly materialised every retained result. A retry loop, long-running research session or future shared runtime could therefore create unbounded resident metadata and export work without ever submitting an individually invalid record.

The bounds below are **process-safety envelopes, not scientific sample-size recommendations**. Larger studies should use the durable/spill-capable design tracked by #98 rather than raising an implicit in-memory requirement or silently discarding observations.

## Default executable envelope

`ListeningRegistryLimits` defaults to:

| Resource | Limit |
| --- | ---: |
| retained trials | 512 |
| retained results in one trial | 4,096 |
| retained results across the service | 16,384 |
| canonical retained registry metadata | 64 MiB |
| canonical result metadata for one trial | 16 MiB |
| one trusted/participant JSON export | 20 MiB |

Every limit is a positive integer and may be made smaller by an embedding runtime or test. Limits are checked before registry mutation. There is no automatic eviction, truncation, annotation clipping, result replacement or trial retirement.

The byte model counts the canonical strict-JSON representation used by the immutable manifest/result records plus 256 logical bytes per retained trial for the two opposite-direction trusted/participant identity index entries. Python-object/container overhead is deliberately not presented as a portable byte identity; the independent trial/result cardinality caps bound that implementation-dependent overhead.

`ListeningService.registry_accounting()` exposes the active limits, trial/result counts, trial metadata bytes, result metadata bytes and combined metadata bytes under method `retained-listening-metadata-json-v1`.

## Submission semantics

Participant trials remain terminal and one-shot: after a completed, aborted or missing participant response is accepted, a retake requires a new trial.

Trusted/programmatic `submit()` intentionally retains bit-identical valid submissions as **distinct result records** until a bound is reached. Version-1.0 `TrialResult` has no participant/respondent identity, so silently deduplicating byte-identical records could discard genuinely distinct observations. A retry loop therefore consumes explicit bounded capacity and eventually fails; it is never silently collapsed or overwritten.

Admission is protected by one service-level re-entrant lock. Concurrent requests share the same counters and byte totals; a race cannot cause two individually valid requests to overrun the declared limit.

## Export semantics

Trusted export computes the exact canonical size of the retained result array from admission-time accounting **before** materialising the result dictionaries. If the complete bundle would exceed `max_export_bytes`, export fails explicitly instead of constructing an arbitrarily large list/JSON response.

Participant export remains bounded more tightly by its existing one-terminal-response rule and is checked against the same export ceiling.

The existing `zaaggenz-listening-bundle/1.0.0` and participant-bundle `1.0.0` wire formats are unchanged. This repair changes executable admission/resource policy, not the interpretation or identity of a valid record.

## Reopen/import semantics

Trusted metadata-only version-1.0 reopen still requires every referenced playback SHA-256 to be resident in the exact audio store; missing playback is not regenerated. Durable self-contained playback transport remains #98.

Reopen now performs count/byte admission and validates every result before any registry mutation. A new trial plus all of its results is installed atomically. If the same trusted trial already exists, reopen is idempotent only when the retained result sequence is exactly the same. A bundle with a different sequence is rejected rather than overwriting, merging or dropping existing evidence.

This policy prevents import from bypassing normal limits and prevents a failed or ambiguous reopen from damaging prior research state.

## Relationship to adjacent repairs

- **#105** remains authoritative for semantic validity of choices, annotations and completed/aborted/missing observations.
- **#115** owns transactional **physical PCM byte** accounting for raw excerpts and matched playback. PCM bytes are not double-counted in the metadata budget here.
- **#122** remains authoritative for finite level-match controls and finite matched metadata.
- **#98** may add durable archives/content-addressed persistence. It must preserve these non-lossy admission semantics, enforce an equivalent finite retained/export envelope, and must not make reopen capable of bypassing bounds.
- **#95** may make the service longer-lived/shared. It should reuse the same locked admission/accounting model rather than introducing a second registry quota.

No source PCM, matching gain, ABX truth, result content, protected audio, project state or DSP/default behaviour is changed by this contract.
