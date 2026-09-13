# ZG-008 source-preserving melodic construction

ZG-008 turns the frozen v1.2.1 SYNTH source into explicit tuned note events without replacing the source sound or silently changing default presets. It consumes the accepted `TimeMap`, `TuningSpec`, `PhrasePlan` and immutable `RenderRecipe` contracts and publishes through the ZG-004 job/revision boundary.

## Two named render modes

`source-derived` is the preservation path and the default. The legacy source is rendered once. A neutral degree-0 event at the source reference is a direct float32 copy of that source; non-neutral notes use duration-preserving phase-vocoder/resample transposition. The nonlinear legacy synth is **not rerun per note**. The full note/tail belongs to the `synthline` stem.

`target-note` is explicitly different. It renders the legacy synth at each distinct requested target frequency (cached inside the phrase render) and therefore may change nonlinear timbral behaviour with pitch. It uses `phase_policy=reset-event`; selecting it is an intentional resynthesis decision, never an optimisation hidden inside source preservation.

Both modes use the same ZG-007 tuning coordinate calculation. The default bounded target range is 15–240 Hz and the source-derived pitch-ratio range is 0.25–4. These are implementation safety bounds, not musical recommendations.

## Event and gesture semantics

A `PhrasePlan` event uses its rational `beat` and `duration_beats` directly. Each onset and gate endpoint is independently converted with the shared `TimeMap` ties-to-even rule; event scheduling never accumulates a repeatedly rounded step. Rests retain timing but emit no audio.

- `gain_db` on an event is the event-level amplitude/velocity coordinate.
- `pitch_cents` is sampled as a glide around the tuning target. Static shifts use the duration-preserving path; a moving glide uses source playback-coordinate warping through the gate and crossfades into the final static-pitch tail.
- `gain_db` gesture automation is additive to event gain.
- `density_per_beat` creates source-derived roll retriggers. ZG-008 accepts a constant integer density per gesture. Time-varying or fractional density is rejected rather than collapsed to an arbitrary maximum; later phrase/gesture work can add an explicit variable-density grammar.
- `brightness_hz` and `roughness_fraction` are valid shared contract axes but are not owned by this renderer. They fail clearly here instead of disappearing; later DSP/gesture consumers may implement them.

## Tail and roll ownership

`tail.mode=preserve` retains the natural source-derived tail, including overlap beyond the nominal gate or phrase end. A positive `maximum_samples` caps the amount after the gate. `truncate` cuts at the gate and applies a short cosine release.

Rolls are deliberately not full-length overlapping re-renders. They live in the separate `exciter` stem, use tapered source-derived slices, and are capped by both the local retrigger interval and `roll_slice_max_ms` (120 ms by default). `synthline` always retains the full main event independently of the roll layer. The renderer reports retrigger count, minimum interval and maximum slice length per event so dense-roll behaviour is auditable.

## Output and jobs

The renderer exposes `synthline`, `exciter` and `pre_master` stems. The recipe's final `master_gain_db` is applied once after their sum, followed only by the declared clipping policy. No upward normalisation is introduced.

`make_render_executor()` binds recipe SHA-256, project revision, melodic-render-spec identity, float32 PCM identity and waveform/event scopes into a ZG-004 `RenderArtifact`. Cancellation is checked before/after source renders and throughout event/roll construction. Long construction work therefore has cooperative cancellation points rather than only a pre/post wrapper.

## Verification

After materialising the authenticated baseline, run:

```sh
python -m pip install numpy==2.3.5 scipy==1.17.0 -r requirements-contracts.txt -r requirements-jobs.txt
python -m unittest discover -s tests/melody -v
python tools/melody_fixture_report.py --out melody-report.json --audio-dir melody-listening
```

The tests cover exact neutral source identity, tails/gates, static pitch shift, stereo antiphase, non-octave and negative degrees, tempo-change timing without accumulated drift, glide endpoints, slow/extreme-BPM roll slicing, explicit density rejection, unsupported-axis rejection, the distinct target-note path, final master gain and ZG-004 artifact binding.

The report also emits a generated-source A/B pair: source-derived versus target-note degree 7, with B RMS-matched to A and common attenuation only if headroom requires it. These files are for listening inspection; no acoustic metric is treated as proof of artistic quality.

## Compatibility boundary

No existing preset, default web render, SCULPT setting or reversebass path is changed by this issue. The inherited ZG-001/ZG-002/QC workflows remain the authority for protected v1.2.1 behaviour. ZG-008 adds a new consumer for recipes containing phrase intent; the legacy thawer continues to reject such recipes rather than silently ignore them.
