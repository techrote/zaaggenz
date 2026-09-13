# ZG-026 — nested metrical clocks and true cross-rhythms

ZG-026 separates **metrical hierarchy** from **independent cycles**. Fast articulation, half-rate bounce and quarter-rate sway are represented as exact nested beat clocks; a 3:2 relation is explicitly typed as a cross-clock rather than being inferred from an autocorrelation peak or relabelled half/double time.

The module is authoring/analysis infrastructure. It does not change `locked_bloom`, the frozen TimeMap/PhrasePlan schemas, or automatically apply modulation to the production renderer.

## Clock model

A `zaaggenz-meter-plan` stores exact rational `period_beats` and `phase_beats`, active windows, phase resets/re-entry policy, a stable clock identity and optional control bindings. Quarter-note beats are the canonical coordinate system. There are three clock kinds:

- **nested** — a root exact-beat clock, or an integer-period multiple of another nested clock. Child clocks share active/re-entry/reset windows and must remain phase aligned with their reference. The supplied articulation → bounce → sway hierarchy uses periods `1/4 → 1/2 → 1`, a 1:2:4 relationship.
- **cross** — an explicitly independent `pulses:reference_cycles` relation to another clock. The supplied `3:2` cross-clock has period `2/3` beat against one-beat sway. Power-of-two relations are rejected here because they belong in the nested hierarchy.
- **cycle** — an independent exact period/phase with no relation claim. This permits longer or quasi-independent modulation without forcing it into a 4/8/16-beat tree.

`active_windows` are half-open. `reset_on_entry=true` resets phase at re-entry. Explicit `reset_beats` start a new phase segment. Thus a long arrangement can stop a nested hierarchy, re-enter it later and reproduce the exact same phase rather than inheriting hidden oscillator state.

## Tempo maps and sample positions

Clocks stay in exact beat coordinates. `generate_ticks(..., time_map=...)` delegates beat→seconds integration and sample rounding to the frozen ZG-002 TimeMap contract. Tempo changes therefore alter sample spacing without changing metrical phase. Each tick records exact rational sample position, rounded sample and rounding error; rounding remains the declared nearest-ties-even, performed once after exact step-tempo integration.

Tests cover the contract limits **20 and 360 BPM**, changing tempos, 44.1/48 kHz operation and noninteger sample boundaries. Shared sway/bounce/articulation beats must map to the same sample on every nested clock.

## Stable anchors and variable control lanes

`stable_clock_id` declares the orienting level. Bindings separately name clock, layer, control, pattern values and whether the lane is an `anchor` or `variable`. An anchor binding must use the stable clock. The starter plan keeps `sway` stable while allowing articulation density, cross-clock brightness and long-cycle roughness to vary.

Bindings are **authoring schedules**, not implicit DSP. `control_schedule()` materialises exact beat/sample control events for later renderer/gesture integration. This issue does not silently add unsupported axes to frozen GestureSpec or modify final gain/normalisation semantics.

## Multi-hypothesis analysis

`periodicity_overlay()` compares declared clocks against measured beat or sample landmarks. For every clock it reports tick coverage, measurement alignment, median nearest-tick error and support under an explicit tolerance. It returns an `ambiguity_clock_ids` list and deliberately has **no winner**.

This distinction matters: if every fast articulation onset is measured, slower bounce and sway ticks can still have 100% coverage even though many extra events occur between them. Extra faster events therefore do not count as evidence that slow movement “failed.” Conversely, a 3:2 stream can support the declared cross-clock without being coerced into half/double-time BPM.

`overlay_feature_flux()` accepts the ZG-012 `FeatureTimeline` interface and uses valid spectral-flux landmarks as one possible measurement source. A flux threshold is an analysis choice, not a perceptual truth or unique beat detector.

## Starter fixture

`nested_124_cross32()` contains:

- 1/4-beat articulation;
- 1/2-beat bounce;
- 1-beat sway, selected as the stable anchor;
- true 3:2 cross-clock at 2/3 beat;
- independent 5/4-beat long cycle with 1/8-beat phase;
- an intentional nested-clock gap from beat 24 to 32 plus deterministic re-entry;
- explicit resets at beats 16 and 48 for nested clocks, and beat 40 for the long cycle.

The full-rate fixture tool creates four stereo measurement examples: nested baseline, disturbed fast layer with sway preserved, preserved fast layer with sway disturbed, and articulation plus true 3:2 cross-clock. The first three have identical per-channel click count/kernel/RMS/peak so the manipulation changes timing rather than event inventory or level.

```console
python -m unittest discover -s tests/meter -v
python tools/meter_fixture_report.py --out meter-fixtures-48k.json --audio-dir meter-clicks-48k --sample-rate 48000
```

These clicks are engineering evidence, not musical release candidates, owner audition evidence or proof that a particular metrical hierarchy is preferred.
