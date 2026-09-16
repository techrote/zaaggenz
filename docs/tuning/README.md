# Tuning and pitch coordinates v1

ZG-007 makes pitch explicit rather than treating every operation as an unnamed semitone offset.

## Model

A `Tuning` has a reference frequency/degree, a period ratio, increasing explicit degree ratios beginning at 1/1, and an optional keyboard map. Degree arithmetic wraps by the number of explicit degrees per period and works for negative degrees and non-octave periods.

The shared `resolve_pitch_target()` API accepts **either** an abstract degree or a keyboard key. A mapped key resolves to the same degree/frequency calculation used by SYNTH/AUX/CLI consumers; an unmapped/out-of-range key is represented as an explicit rest (`None`), not coerced to a neighbouring pitch.

`TuningSpec` v1 keyboard maps use one executable `formal_period_degrees` domain: `[-256, -1]` or `[1, 256]`. Zero is invalid because advancing one keyboard-map period by zero degrees does not define the wrapping relation consumed by `KeyboardMap`. Negative formal periods remain intentionally supported for explicit maps: advancing by one map period subtracts the declared number of tuning degrees, while moving backward adds them. This changes only the explicit keyboard coordinate mapping; it does not change the tuning's positive `period_ratio`, default tuning, or source audio.

JSON Schema's `integer` type admits mathematically integral JSON numbers (for example `12.0` after parsing). The executable `KeyboardMap` therefore evaluates a validated formal period by its exact integer value rather than introducing a stricter Python-representation-only rule. No invalid value is rounded or clamped.

`root_hz`/`root_degree` are explicit overrides for root-locked construction. `analyse_frequency()` reports the nearest tuning coordinate for an observed frequency without mutating the tuning or the source preset. Analysis reference and synthesis intent remain separate.

## Scala

The parser/exporter supports bounded UTF-8 `.scl` and `.kbm` text with comments, ratios, cents, blank descriptions, sparse `x` keyboard entries and zero-size linear KBM maps where they can be represented explicitly. Important Scala syntax: an integer pitch token such as `1200` is a **ratio**, while `1200.0` is cents.

KBM formal periods are checked at parse/object construction, before conversion to `KeyboardMap`. Nonzero explicit maps use the same `[-256, -1]` or `[1, 256]` domain as `TuningSpec`, including tested negative-period maps. A zero-size KBM has no explicit entries to carry that relationship, so its deterministic expansion is deliberately narrower: a positive formal period in `[1, 128]`, expanded to `0..formal_period_degrees-1`. Zero, negative and larger zero-size formal periods fail explicitly rather than being normalised.

SCL import interprets the final listed pitch as the period and inserts implicit degree 0 = 1/1 into `TuningSpec`. Malformed counts, nonpositive ratios, unordered pitches and unmapped reference keys fail clearly. Export uses high-precision cents and is tested by cents-domain semantic round-trip rather than byte-for-byte reproduction of comments/formatting.

No external scale archive is bundled.

## Fixture pack

- `12tet-a440`: mathematical interoperability/reference fixture.
- `synthetic-ratio-7`: small ratio fixture useful for exact interval tests.
- `synthetic-13ed3`: 13 equal divisions of a 3:1 period, explicitly synthetic/non-octave.

These are coordinate/test systems, not claims about cultural modal grammar, emotional effect, or consonance quality. Modal directionality/phrase grammar is later work; Sethares/dissonance optimisation is later research.

## Validation

Linux/Windows CI checks ratios/cents, negative degrees, positive and negative formal-period boundaries, zero rejection, schema/shared/consumer agreement, period wrapping, arbitrary roots, sparse keyboard rests, SCL/KBM edge cases including zero-size maps, malformed inputs, shared pitch-target consistency, immutable analysis queries, CLI output and `TuningSpec` round-trip.
