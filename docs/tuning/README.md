# Tuning and pitch coordinates v1

ZG-007 makes pitch explicit rather than treating every operation as an unnamed semitone offset.

## Model

A `Tuning` has a reference frequency/degree, a period ratio, increasing explicit degree ratios beginning at 1/1, and an optional keyboard map. Degree arithmetic wraps by the number of explicit degrees per period and works for negative degrees and non-octave periods.

The shared `resolve_pitch_target()` API accepts **either** an abstract degree or a keyboard key. A mapped key resolves to the same degree/frequency calculation used by SYNTH/AUX/CLI consumers; an unmapped/out-of-range key is represented as an explicit rest (`None`), not coerced to a neighbouring pitch.

`root_hz`/`root_degree` are explicit overrides for root-locked construction. `analyse_frequency()` reports the nearest tuning coordinate for an observed frequency without mutating the tuning or the source preset. Analysis reference and synthesis intent remain separate.

## Scala

The parser/exporter supports bounded UTF-8 `.scl` and `.kbm` text with comments, ratios, cents, blank descriptions, sparse `x` keyboard entries and zero-size linear KBM maps where they can be represented explicitly. Important Scala syntax: an integer pitch token such as `1200` is a **ratio**, while `1200.0` is cents.

SCL import interprets the final listed pitch as the period and inserts implicit degree 0 = 1/1 into `TuningSpec`. Malformed counts, nonpositive ratios, unordered pitches and unmapped reference keys fail clearly. Export uses high-precision cents and is tested by cents-domain semantic round-trip rather than byte-for-byte reproduction of comments/formatting.

No external scale archive is bundled.

## Fixture pack

- `12tet-a440`: mathematical interoperability/reference fixture.
- `synthetic-ratio-7`: small ratio fixture useful for exact interval tests.
- `synthetic-13ed3`: 13 equal divisions of a 3:1 period, explicitly synthetic/non-octave.

These are coordinate/test systems, not claims about cultural modal grammar, emotional effect, or consonance quality. Modal directionality/phrase grammar is later work; Sethares/dissonance optimisation is later research.

## Validation

Linux/Windows CI checks ratios/cents, negative degrees, period wrapping, arbitrary roots, sparse keyboard rests, SCL/KBM edge cases, malformed inputs, shared pitch-target consistency, immutable analysis queries, CLI output and `TuningSpec` round-trip.
