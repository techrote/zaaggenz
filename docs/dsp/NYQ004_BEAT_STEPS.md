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
