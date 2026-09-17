# ZG-006 annotation timing and extent contract

This document defines the timing/provenance contract used by reference annotations after corrective issue #116. It does not change any source audio, analysis DSP, planning descriptor, musical default or annotation relation semantics.

## Versioned coordinate domain

`references/annotation_timing_v1.json` is the portable timing catalogue for annotation format `1.0.0`. Its catalogue version is `1.0.0` and its coordinate-domain identifier is `decoded-native-rate-pcm-v1`.

A segment interval `[start_sample, end_sample)` is measured in decoded PCM frames at the exact referenced asset's declared native sample rate. The start is inclusive, the end is exclusive, and every accepted interval must satisfy:

```
0 <= start_sample < end_sample <= frame_count
```

The catalogue records, for each asset, the exact source SHA-256, sample rate, channel count and frame count used by this coordinate domain. It deliberately contains no local filesystem locator. `source_sha256` is the identity authority; an ID or filename alone is not provenance.

For the six existing references, the frame counts are the exact native-rate equivalents of the accepted decoded-duration evidence already frozen by ZG-006. Current annotation suggestions were authored in this native-rate domain (48 kHz for the current registry), so `paired_suggestions_v1.json` remains byte-for-byte compatible and keeps annotation version `1.0.0`.

## Validation

`load_annotation_timing(path, registry)` authenticates a timing catalogue against the portable reference registry before it may be used as evidence. It fails closed if:

- the asset sets differ;
- a source SHA-256 is rebound under the same asset ID;
- native sample rate or channel count differs;
- the exact frame count disagrees with the accepted decoded-duration evidence;
- the catalogue/domain shape or version is invalid.

`validate_annotation(annotation, timing_catalogue)` then requires every referenced asset to have authenticated timing metadata and rejects spans outside that exact extent. The original set-of-ID call surface remains only as a compatibility shorthand for the canonical checked-in registry: the IDs are resolved through the same authenticated timing catalogue before validation. There is no remaining ID-only acceptance path.

This is a semantic integrity correction, not a new annotation wire format. Existing valid `1.0.0` annotations require no rewrite. Previously accepted impossible spans were never meaningful observations and now fail rather than being silently clipped or projected.

## Landmark overlays

`overlay_landmarks()` continues to rescale source coordinates into the analysis timeline. It now validates source spans before projection. When an exact source frame count is supplied from the timing catalogue, it also checks that the declared source rate/extent is compatible with the analysis timeline. The legacy four-argument form derives a bounded source extent from the timeline, so even already-validated legacy callers no longer turn arbitrary out-of-source coordinates into partial or empty overlays.

Resampling changes only the coordinate representation used for the analysis overlay. It does not change the annotation's authoritative source-domain coordinates.

## Privacy and provenance boundaries

The timing catalogue contains only portable metadata. Private source paths remain exclusively in ignored locator files, source recordings remain excluded from tracked artifacts, and rights metadata remains in `private_registry_v1.json`. No private audio is introduced by this repair.

Ambiguous metre, confidence, manual/automatic provenance, correspondence groups, and `corresponding` / `unrelated` / `uncertain` relation semantics are unchanged.
