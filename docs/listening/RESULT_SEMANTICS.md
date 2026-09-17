# ZG-015 result semantic contract

`zaaggenz-listening-result/1.0.0` remains the wire format. Issue #105 repairs validation that previously accepted internally impossible observations; it does not reinterpret any valid result field or change audio, matching, ABX truth generation, participant blinding, or result hashing.

## Canonical choices

Choice is deliberately separate from ratings. For A/B and multi-example trials it is either `null` or the exact immutable `stimulus_id` of one item in that trial's `presentation_order`. This permits endpoint-only comparisons without forcing a preference. For ABX it is either `A`, `B`, or `null`; a **completed** ABX result must contain `A` or `B`, and `abx_correct` is derived and checked only against the trusted manifest. No other choice spelling, label, filename, or arbitrary string is valid.

## Status semantics

A `completed` result may contain the declared ratings and optional comparison choice described above. An `aborted` result may retain partial but semantically valid observations—replay counts, declared ratings, confidence/effort/comfortable-level values, a canonical choice, annotations, and an explanatory note—but cannot claim ABX correctness. A `missing` result records absence rather than invented participant behaviour: choice is null, ratings and annotations are empty, confidence/effort/comfortable level are null, all replay counts including X are zero, and ABX correctness is null. A bounded free-text `note` may document the administrative reason for missingness.

## Annotation identity and clock domain

Every annotation must name one exact stimulus presented by the bound trial. Annotation `time_seconds` uses that frozen stimulus's playback clock: zero is the beginning of the first frame and `frame_count / sample_rate_hz` is the inclusive end marker. Times above that duration are invalid.

The frozen trial 1.0 manifest intentionally does not duplicate stimulus duration metadata. Therefore the authoritative service paths supply exact immutable timing metadata from the trusted listening store (live submission) or from the bundle's validated `Stimulus` objects (trusted reopen). Low-level historical `TrialResult`/`make_result` construction without that external timing context retains structural 1.0 compatibility and cannot certify duration; callers that need semantic timing validation must supply the context. Service submission and trusted reopen always do so. This is a semantic bug fix to 1.0, not a format bump: valid historical records retain their serialized bytes/digests, while legacy-invalid records fail when revalidated through an authoritative service/archive path.

## Integrity consequences

Result digest identity still covers the exact result record. Timing metadata is validation context, not hidden result state and is not inserted into the digest. Reopen revalidates choice membership, annotation membership, status policy, endpoint declarations, replay coverage and annotation duration against the same trusted manifest/stimulus identities used by live submission. Participant-safe projections continue to redact trusted trial identity and ABX correctness.
