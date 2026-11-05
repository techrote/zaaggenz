# NYQ-004: instantaneous control-evaluation slice (not event geometry)

Issue [#253](https://github.com/techrote/zaaggenz/issues/253), after accepted
NYQ-002/#251. Independent of the NYQ-003 #252 reconstruction work.
**Draft and incomplete**: this provides deterministic physical-time point
evaluation of existing frozen NYQ-001 clock-control contracts, not clock phase
integration, event scheduling, sample/audio modulation, LFOs, feature taps or
saved Compose/UI execution.

## Supported `nyq.instantaneous-controls.v1` methods

- Right-continuous absolute-time base-Hz automation; exact rational step and
  piecewise-linear interpolations.
- Ordered normalized routes with additive-Hz (`f += depth * control`, exact
  rational float-depth encoding) and logarithmic octave mapping
  (`f *= 2 ** (depth * control)`, Decimal80 numerical approximation).
- Nearest finite positive Hz rate ladder, strict ordered finite cardinality,
  lower-Hz tie; ratios are expanded using explicitly stored references before
  selection, never the numerical evaluation rate. Final candidate selection
  compares the **exact rational representation** of the computed control Hz
  with the saved rational ladder levels. The logarithmic-route control value
  may itself have been approximated in Decimal80, but its completed value is
  not rounded a second time during nearest-level distance comparison.
  Fraction/Decimal cases a mere 1e-90 Hz across a ladder midpoint are tested;
  these must not collapse into an artificial lower-Hz tie.
- Stateless, counter-addressed `uniform_frequency_cells_v1` jitter through
  existing physical-time SHA-256 cell identity. Same stable instance/group and
  linked stereo share draws; independent channels are distinguished. Zero
  jitter depth is unchanged rate.
- Complete saved-range admission, explicit result of every intermediate
  operation, bounded time and channel. Changing a label never changes a
  realized value.

`evaluate_instantaneous_rate(SonicSpec, "p/q", channel=N)` returns a frozen
`RateControlSample` containing base/routed/quantized/realized rate strings,
route controls, physical jitter cell/index and identities. This is a
**single-time diagnostic**, not sufficient evidence for correct event timing.
In particular, integrating logarithmic/exponential rate controls, quantizer
switches, cellwise jitter and resets into a monotone clock requires additional
piecewise phase integration, crossing solves and event/budget oracles. The
NYQ-001/002 `ClockPlan` rejection for routed/quantized/jittered clocks is
intentionally retained. No silent numerical-grid approximation is introduced.
The owner-required LFO, envelope, transient/upstream feature control,
rate-set hysteresis and actual audio/GUI evidence remain future #253 work.

Run focused contracts:
```sh
python -m unittest discover -s tests/contracts -p 'test_nyquismic_controls.py' -v
python -m unittest discover -s tests/contracts -p 'test_nyquismic*.py' -v
```
Use exact-head Windows/Ubuntu reverse-dependency CI before acceptance; do not
close #253 or unblock #254 on this slice.


## NYQ-004 follow-up: exact segmented step-clock geometry

An additional standalone `compile_step_clock_events(spec, end_s, *, channel,
budget, cancelled)` now admits and emits **exact Fraction event coordinates**
for a tightly bounded subset of the saved control family. It integrates the
continuous phase over each half-open physical-time segment, including explicit
reset epochs. Segment cuts cover right-continuous base-Hz steps, ordered
additive-Hz route steps, quantizer switches and counter-addressed jitter-cell
boundaries. `StepClockEvent` includes ordinal, reset epoch, integer crossing and
the unrounded exact timestamp. Absolute physical-time jitter cells and stable
linked/independent channel identities make results independent of worker/chunk
order. Capture count and jitter-cell budgets are checked before event
publication; cancellation returns no partial output.

This supports the mathematical event schedule for step/additive routes,
nearest-Hz quantizers and bounded fractional-frequency jitter. It **rejects**
linear-Hz ramps, logarithmic routes, audio-derived controls and other unverified
combinations instead of evaluating them once per block. It is still an
experimental geometry API, **not a registered ClockPlan replacement**, and has
not yet been connected to SamplerPlan, runtime, saved instrument execution,
preview or export. The accepted clock's unsupported-mode guard remains intact.

Run the independent pure-clock oracles:

```sh
python -m unittest discover -s tests/contracts -p 'test_nyquismic_control_geometry.py' -v
```

The tests compare static event timestamps against accepted ClockPlan, exercise
analytic step and reset crossings, quantizer lower ties, deterministic
linked/independent jitter, unsupported-mode rejection, event/cell admission
and cancellation. Full NYQ-004 acceptance still requires real sampler
integration, additional waveform controls and exact-head CI.

## NYQ-004 continuation: certified affine-Hz phase integration

The standalone event compiler additionally admits **piecewise-linear Hz base
automation and additive-Hz routes**. Every rate point, route breakpoint, reset,
and jitter-cell boundary cuts the physical-time interval. Inside each segment
the aggregate rate is `f(t) = r0 + slope * (t-a)`, with the independently
evaluated midpoint fixing the exact rational slope. Its phase advance is
`r0 * dt + slope * dt**2 / 2`; no per-audio-block integration approximation
or hidden smoothing is used. Positive-endpoint admission is explicit.

Integer crossings solve the stable quadratic root
`dt = 2 * (crossing-phase) / (r0 + sqrt(r0**2 + 2*slope*(crossing-phase)))`.
Perfect-square rational discriminants yield **exact Fraction** timestamps.
Otherwise the integer square root of a fixed 128-bit dyadic-scaled rational
discriminant yields a platform-independent enclosing interval. The emitted
`StepClockEvent.coordinate_s` is the interval midpoint and
`coordinate_error_bound_s` is its certified half-width, required to be no more
than `1e-18 s`. Segment ownership and minimum event spacing are tested using
the whole uncertainty interval, not just the rounded midpoint.

The original step/static paths still return exact fractions with zero
uncertainty. Piecewise-linear **additive-Hz ramps with nearest-Hz quantization** are now
admitted by a separate exact-rational switch solver. The unquantized additive
curve is affine between declared automation points, resets and jitter-cell
boundaries. Each adjacent ascending ladder pair has a threshold equal to the
exact arithmetic midpoint of its two stored Hz values. The solver inserts
every strictly interior crossing of those thresholds as a physical-time cut;
it then integrates the selected quantized Hz as a constant over each open
segment, including any admitted cellwise jitter multiplier. This is true
zero-duration step switching, not a once-per-buffer approximation or a
smoothed transition. An exact upward tie returns the **lower** Hz to the
instantaneous inspector, while the phase integral over the following open
interval uses its midpoint/right-hand value; the isolated tie instant has
zero phase measure. The same segmentation handles falling ramps and resets.
All such events are exact Fraction timestamps (zero root uncertainty).

Admitted work is bounded by the declared event/segment budget, and no change
is made to the accepted NYQ-001/002 clock execution guard. Nonlinear/
logarithmic routes, LFOs, envelopes, features and actual `SamplerPlan`
integration remain unsupported. This is a numerical event proof, not a
production sampler/audio implementation. These source
changes do not alter the frozen `ClockPlan` admission guard.

Independent test command:
```sh
python -m unittest discover -s tests/contracts -p 'test_nyquismic_control_geometry.py' -v
```
The tests cover analytically integrated increasing/decreasing linear rates,
an exact half-second crossing, irrational crossings with certified residual
bounds, additive-route equivalence, reset epochs, stable jitter cells,
rising/falling/multilevel quantized-ramp switch boundaries, exact phase and resets, unsupported logarithmic integration, cancellation and resource budgets. A passing pure
geometry oracle is **not** saved-instrument acceptance or a verified
listening/render/export result.


## Additional pure control: explicit rational ratio ladder

`RatioLadder(version='nyq.ratio-ladder.v1', reference_hz='48000/1',
ratios=('1/3', '2/5', '3/7', '5/11', '7/13'))` is a complete strict
JSON/canonical-hash control-source record in `nyquismic_controls`. It
converts those ratios to **exact** resolved Hz with `as_quantizer()`,
which creates the existing `RateQuantizer(nearest_hz, lower tie)`. Neither the
numerical evaluation clock nor the delivery/export clock enters this mapping.
The specified five rational choices are ordinary test data, not privileged
musical ratios. Changing the stored reference changes the realized values
and the identity. Non-positive, duplicate, unsorted, oversized or out-of-range
ratios and incomplete/unknown JSON fields fail closed. No ratio is converted
through float or silently rounded to a nearest integer Hz.

This is useful today in the existing `evaluate_instantaneous_rate` diagnostic
and exact step-clock geometry for compatible static/stepped controls. The
`RatioLadder` companion is **not** yet a field of frozen `SonicSpec`, and
no project/rack/preset persistence or GUI claims are made. A future qualified
schema adapter must preserve both original ratios and the reference; persisting
only the compiled absolute-Hz quantizer loses ratio intent. Free/beat LFO,
envelope/transient, upstream feature routes and sampler integration remain
explicit #253 requirements.

Run: `python -m unittest discover -s tests/contracts -p 'test_nyquismic_controls.py' -v`.

## Versioned offline triangle LFO route-authoring source

`SampledLfoSource` (`nyq.sampled-lfo-source.v1`) is an optional **control
authoring** record for #253, separate from the sampler execution adapter.
It compiles a deterministic bounded **triangular** LFO into the accepted
`ModulationRoute` point vocabulary, not into a new renderer/session. Two
physical-time modes are explicit: `free_hz` (cycles/s) and `beat_sync`
(cycles/beat), with a strictly increasing saved step-tempo map (BPM).
The phase integral is rational seconds or the exact sum of BPM/60 segment
areas; grid evaluation and phase do not depend on numerical audio frame rate,
worker scheduling or export rate. Phase at 0 cycles is -1, at 1/2 cycles +1;
fractional phase and frequency values are accepted within hard bounds.

The saved source holds version, mode, frequency, phase, origin, time grid,
base BPM and tempo breakpoints. The compiled route holds explicit sample
times, exact rational triangle values, `linear` interpolation, requested
mapping and depth.
For a delayed physical-time origin, the frozen linear route is now emitted
with neutral pre-origin control and a separate counted onset point only when
its triangle value at onset is **exactly zero** (quarter/three-quarter phase).
Other delayed phases would require both an abrupt step and linear ramps in a
single saved route; they **fail closed** instead of leaking a pre-onset ramp.
This uses the existing 256-point budget, does not change zero-origin routes,
and does not claim a production sampler/graph capability.
 **Store both** if later editing of the original LFO
intent is required: the existing `SonicSpec` only stores its concrete
`ModulationRoute` and does not yet contain a nested LFO-source identity.
The compiler now **retains exact rational half-cycle turning points
(peaks/troughs) and off-grid tempo breakpoints**, alongside the requested
uniform authoring grid and final endpoint. These retained physical-time
breakpoints make the frozen *piecewise-linear triangle route* equal to the
declared exact triangle at all intermediate times, not merely at grid
samples, including across abrupt BPM changes. Exact phase and zero-depth
behavior are unchanged. The conservative four-points-per-cycle admission
rule still applies, and the **combined** grid/tempo/turning-point lane must
fit the existing 256-point budget or fail closed. No point decimation,
floating-point cusp rounding or quiet change of waveform is permitted.
This does not add a bandlimited sinusoid, jitter, continuous generic
audio-rate evaluator or real sampler/feature path. Each accepted route contains at most 256 points, with hard
bounds on physical grid, frequency, BPM and total requested extent.
Oversized authoring requests reject before materializing output; callers
may explicitly choose a shorter extent or coarser physical grid, **provided**
that the grid still samples at least four control points per cycle at the
fastest tempo/frequency **actually active in the requested extent**. Future
saved tempo points strictly after (or exactly at) the endpoint do not cause
an otherwise resolvable short preview to be rejected. Once a higher BPM is
within the extent, the same grid rejects it if underresolved. An underresolved LFO fails
closed rather than quietly collapsing to a static/aliased modulation route.

An optional callable `cancelled` hook is checked before work, during
bounded grid, tempo/turning-point and point-materialization loops, and again
before the route is published. A cancellation raises `ClockCancelled` with
**no partial route**, and does not mutate the saved source or the previously
compiled result. A noncallable hook is rejected. This is only authoring
cancellation, not proof of cancel-safe audio rendering or rack integration.

Evidence: `python -m unittest discover -s tests/contracts -p
'test_nyquismic_sampled_lfo.py' -v` checks exact free-Hz quarter-cycle
values, right-continuous tempo changes and accumulated beat phase, stable
route serialization and hash identity, actual instantaneous evaluator
consumption, partial endpoints, explicit budget failures and invalid
rates/depths/modes. **No change** to the accepted NYQ-001/002
`ClockPlan.require_geometry` rejection or original instrument path.
Sampler phase integration and upstream/feature-derived controls remain
outstanding; this authoring slice alone cannot close #253.


## NYQ-004 continuation: exact-time triggered ADSR gate authoring

The opt-in frozen source record `TriggeredEnvelopeSource`
(`nyq.triggered-envelope-source.v1`) and its `EnvelopeGate(on_s, off_s)`
records compile physical-second attack/decay/sustain/release envelopes into
the **existing** serializable `ModulationRoute` representation. No parallel
automation/session engine, new graph registry entry, or sampler capability is
introduced. Gate offsets interrupt attack/decay correctly: release starts
from the **actual instantaneous value** at note-off rather than jumping to
the stored sustain level. All four segments are exactly piecewise-linear,
with no evaluation-frame snapping, block smoothing or hidden resampling.

The authoring record stores an origin, strictly positive rational
attack/decay/release seconds, rational sustain in [0, 1] and ordered
absolute-time gates. A gate's release must finish before the next gate;
overlapping release tails and gates that exceed the saved time extent reject.
The compiler inserts only true physical-time slope-change points, including
truncated attack/decay points on early note-off. The total compiled route is
strictly bounded to the existing 256-point limit; excess gates reject instead
of truncating. Optional cancellation aborts without publishing a partial
route. Every field participates in full-snapshot JSON and source identity.
Save **both the editable source and the compiled route**: the existing
`SonicSpec` stores only the route itself. A zero-depth compiled route
preserves the static Nyquismic clock rather than automatically bypassing it.

This is **triggered envelope authoring**, not input-envelope following, a
spectral feature tap, a gate detector or cross-band modulation. It does not
make the accepted NYQ-002 sampler execute routed control; its
`ClockPlan.require_geometry()` guard remains in place. The independent
`test_nyquismic_triggered_envelope.py` covers early release, exact level
geometry, two-gate continuity, strict serialization and bounds, point budget,
cancellation, existing instantaneous-rate inspection and analytic
affine-Hz event integrals. Use:

```sh
python -m unittest discover -s tests/contracts -p 'test_nyquismic_triggered_envelope.py' -v
```

No full instrument, save/reopen UI, WAV/FLAC or human listening acceptance is
claimed. Input-audio/upstream controls and production audio clock integration
are still required to close #253.
