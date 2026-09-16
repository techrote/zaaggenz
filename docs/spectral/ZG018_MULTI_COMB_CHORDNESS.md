# ZG-018 multi-comb Chordness and spectral modulation

ZG-018 extends the accepted ZG-017 partial-domain transform with explicit multi-comb assignment and bounded amplitude shaping. It reuses ZG-013 `PartialTrackBundle` component ownership and ZG-014 descriptor methods. It does not define a second spectral representation and does not interpret Chordness, harmonicity or roughness as listener preference, pleasure or objective musical quality.

## Explicit comb templates

A `CombTemplate` is a named, serialisable list of strictly increasing target frequencies in Hz plus an explicit per-tooth occupancy capacity. This is intentionally more general than a chord label:

- harmonic targets can be generated from an explicit root with `harmonic_comb()`;
- a ZG-010 `VoicingFrame` can be adapted into one comb per declared fundamental with `templates_from_voicing_frame()`;
- users may supply arbitrary inharmonic or local-frequency teeth directly;
- no equal-temperament, twelve-tone, chord-name or key assumption is required.

Candidate templates are carried in `ChordnessRequest` and therefore remain visible even when descriptor selection is enabled.

## Selection and descriptor inputs

`selection_mode='manual'` requires the caller to name the selected template IDs. Multiple templates may be selected simultaneously.

`selection_mode='descriptor'` evaluates each visible candidate with the accepted ZG-014 target-comb descriptors. Selection uses the balanced `target_comb_fit` term plus an explicit density penalty from `ChordnessCoefficients`. The raw density-biased coverage, target precision, balanced fit, mismatch and density observations remain inspectable. The configured scalar is labelled an engineering selection score only.

ZG-014 pairwise roughness is retained as a separate before/after descriptor. It is not folded into a hidden chord-quality label.

## Executable selected-target budget

The executable target lattice is bounded by the **combined unique usable teeth**, not only by the size of each `CombTemplate`. After applying the asset/sample-rate Nyquist rule (`tooth_hz < sample_rate_hz / 2`), an active selection may contain at most **128 unique target teeth** across all selected templates.

The same rule now owns manual selection, descriptor selection and union evaluation:

- manual active selections are rejected before candidate-descriptor or transform work when their combined usable union contains more than 128 teeth;
- descriptor selection considers candidates in the existing deterministic score order and selects a whole template only when adding all of its usable teeth keeps the union within 128; an over-budget template is skipped as a whole and its teeth are never silently truncated;
- overlapping teeth are deduplicated exactly as union evaluation already did;
- teeth at or above Nyquist do not contribute to the union budget, while every selected template must still contain at least one usable tooth below Nyquist;
- exactly 128 unique usable teeth is valid; 129 is not.

Descriptor candidate evidence remains visible when a candidate is not selected because of the union budget. `selection_budget` records whether a candidate was selected and, for an over-budget candidate, the union cardinality that would have resulted. Active transform diagnostics expose `selected_union_size` and the fixed `selected_union_limit=128`; off mode reports size zero. This is an executable-resource/contract consistency bound only. It does not change a comb's musical score, truncate authored target teeth, or reinterpret Chordness as a preference metric.

`ChordnessRequest` remains version `1.0.0`: this is a fail-closed correction of a pre-existing executor invariant. Requests whose selected target exceeded 128 usable teeth were already non-executable because `evaluate_union()` rejected them later. The repair moves that invariant to authoritative selection and makes descriptor construction respect it; valid in-bound requests retain their previous target ordering and DSP semantics.

## Capacity-aware assignment

At each component-analysis anchor, transform-eligible rows compete for target teeth from the selected combs. Each tooth exposes a finite capacity. Rows are considered deterministically by amplitude × confidence and are assigned to the nearest target slot still below capacity and inside `max_assignment_cents`.

Inspection records target template, tooth, target Hz, assignment distance, occupancy and capacity per transformed frame. Capacity exhaustion or lack of an in-range target remains visible as a preserve reason rather than silently forcing a component onto another tooth.

ZG-013 uncertainty remains authoritative: low-confidence rows, component-policy preserves and (by default) ambiguous/reanchored tracks are not transformed.

## Transform modes

`mode='off'` returns the exact source PCM path.

`mode='retune'` changes eligible component frequency and phase only. Correction amount, displacement and cents/second slew are bounded. Phase correction integrates the realised source-to-target frequency delta and is shared across channels for a track frame, preserving inter-channel phase relationships.

`mode='reweight'` changes eligible component amplitudes only. Frequency and phase fields are copied exactly. Gain is derived from explicit distance to the assigned target using the request tolerance, then bounded by `max_gain_db`, `reweight_amount` and `max_gain_slew_db_per_second`.

`mode='hybrid'` combines the two independent bounded operations. A frame outside the retune displacement limit may still receive a bounded reweight if it has a valid assignment.

Transient and residual ownership remains unchanged in every active mode. Only the transformed sinusoidal component is reconstructed before the accepted ZG-013 transient and residual arrays are added back.

## Objective inspection

`ChordnessCoefficients` exposes five user-visible coefficients: target-comb fit, roughness, target density, reassignment magnitude and gain motion. Before/after inspection reports each term separately plus a configured total. The total is explicitly labelled a configured engineering objective, not objective truth or a perceptual/preference score.

The result also exposes candidate descriptor inputs, selected templates, every frame assignment/change, occupancy/capacity rows, before/after target-comb and roughness descriptors, and transform diagnostics.

## Bounded jobs and evidence

`submit_chordness_job()` runs the transform as a normal bounded `JobClass.RENDER` job with cooperative cancellation/progress and a conservative memory estimate.

`tests/spectral/test_chordness_model.py`, `tests/spectral/test_chordness_engine.py` and `tests/spectral/test_chordness_union_bounds.py` cover:

- explicit inharmonic/local combs and sonority adapters;
- exact off-state identity;
- reweight-only frequency/phase invariance;
- simultaneous capacity-bounded comb assignment;
- retune/hybrid movement toward declared targets;
- descriptor-selected visible candidates;
- exact 128/129 combined-target boundaries, overlap deduplication and Nyquist filtering;
- deterministic descriptor selection under the combined-target budget without tooth truncation;
- unchanged transient/residual ownership;
- inspection/objective transparency including selected-union cardinality;
- bounded scheduler execution.

`tools/chordness_report.py` emits deterministic 48 kHz synthetic engineering evidence on Windows and Ubuntu. The report is not listening evidence and makes no musical-preference claim.

## Deliberate exclusions

ZG-018 does not choose hidden chords, infer listener taste, optimise a psychoactive/pleasure target, or decide where the spectral stage belongs relative to nonlinear processing. Stage placement remains ZG-019 work. More sophisticated global assignment or adaptive sonority generation can be added later without changing the explicit template/request boundary introduced here.
