# NYQ-004 — exact tempo-synchronised looping step control

Draft #267 / issue #253. Version: nyq.beat-grid-step-source.v1.

The optional BeatStepSource holds a repeating rhythmic pattern with rational
levels in [-1,1], a step length in musical beats, an absolute physical-time
origin, an initial pattern index and a piecewise-constant BPM map. These are
versioned, saved values. It is independent of the virtual capture clock:
tempo changes do not reset the beat count, source time or sampling phase.

At cumulative beat positions that are multiples of step_beats, the next
step's value takes ownership of the exact boundary (right-continuous).
Coincident tempo and step changes do not create duplicate transitions.
Between steps, a tempo change moves only *future* boundaries. The compiler
uses exact rational physical times, not render-block or native-grid time.

Example: step_beats=1/2, pattern [-1,+1], 120 BPM until t=1/2 and 180 BPM
thereafter. Exact transitions through one second are 1/4, 1/2, 2/3,
5/6 and 1 second. As an additive-Hz route of depth 80 on a 360 Hz base
this drives a 280/440 Hz alternating sampling clock. Integrated virtual
phase is 1040/3 cycles after one second, hence 347 physical capture
events with half-open crossing numbers 0..346.

## Frozen input and executable limits

- Store both the BeatStepSource and its frozen ModulationRoute. The source
  SHA-256 binds editable intent and the ordinary route has a separate digest.
  Changing tempo or phase requires recompilation.
- BPM values: 20..360; step_beats: 1/1024..64; 1..32 ordered normalized
  levels; physical-time tempo points strictly increase after source origin.
  Pattern phase is an exact saved integer, not evaluation-grid or UI order.
- The generated ModulationRoute is additive-Hz with right-continuous steps.
  The existing positive-clock bounds/depth rules apply. Delayed sources
  remain neutral before their physical origin, with no pre-onset ramp.
- At most 256 exact points may be emitted; too many steps fail before
  publication instead of being dropped or silently downsampled. Cancellation
  cannot publish a partial route.
- Short preview compilations have the exact control prefix of full renders;
  future tempo changes do not alter prior event timing. Bypass and zero depth
  preserve the original rendering boundary.
- Independent original PCM tests verify 8 kHz and 16 kHz source-native grids
  with the same physical-event ledger, exact crossing counts, clock/PCM
  differences, deterministic replay and region equivalence, plus negative
  invalid-parameter and cancellation controls.

## Test

    python -m unittest discover -s tests/dsp -p 'test_nyquismic_beat_steps_pcm.py' -v

This executes the *existing* exact physical-time controlled-event compiler
and source-native audio consumer. It is not a registered SamplerPlan adapter,
ordinary Compose insert, generalized evaluation/delivery conversion, physical
Windows export or accepted NYQ-004/#253 admission. NYQ-003/#266 owns sampler
reconstruction; none of its files, shared ZG-024a ledgers, old defaults,
factory presets, CI workflows or programme authority was modified.

## Opt-in tempo-synchronised integer-octave pattern

`BeatStepSource.compile_route(..., mapping='log2_ratio', depth=1.0)`
now emits a strict octave-step `ModulationRoute` for the existing
`nyq.exact-integer-octave-step-clock.v1` physical event compiler.
`add_hz` remains the default and is unchanged. The original source record
and its tempo/level/phase digest remain independent of the selected mapping;
the compiled saved route carries the mapping, depth, ordering and sonic identity.

For `log2_ratio`, **every** saved pattern level multiplied by the exact
binary representation of the specified depth must be an integer, even if a
short preview does not encounter that level. Otherwise compilation raises
`UnsupportedNyquismic`; no fractional-power approximation, snapping or
partial route is emitted. Full clock rate bounds, jitter, saved channel/group
and phase-reset rules are still enforced by `ClockSpec` and the event
compiler. Fractional level values are admissible when their products with
depth are *exactly* integral (e.g. ±1/2 with depth=2.0).

Independent oracle: 200 Hz base, pattern [-1,+1], half-beat steps,
120→180 BPM at t=1/2. The resulting 100/400 Hz rate sections start at
0, 1/4, 1/2, 2/3, 5/6 s. Integrated phase is exactly 225 cycles at 1 s;
the half-open ledger contains 225 strictly increasing rational capture
events, starting at 0 with the last at 99/100 s. Tempo changes only future
steps, never the source or virtual-clock epoch.

    python -m unittest discover -s tests/dsp -p 'test_nyquismic_beat_octave_pcm.py' -v

This numerical source-native PCM fixture tests saved-spec replay, region
identity, unchanged pre-tempo samples, changed post-tempo audio, the same
event ledger across 8/16 kHz native input grids, rational crossings, zero
depth, equivalent fractional-level patterns and explicit unsupported-mode
refusals. It does not claim a registered production sampler adapter,
numerical convergence, delivered WAV export or product/physical Windows
acceptance. NYQ-003 retains exclusive ownership of sampler reconstruction.
