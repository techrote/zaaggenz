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
  selection, never the numerical evaluation rate.
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
uncertainty. Piecewise-linear ramps with **nearest-Hz quantization** are
explicitly rejected: their ladder-crossing times need separately certified
switch segmentation. Nonlinear/logarithmic routes, LFOs, envelopes, features
and actual `SamplerPlan` integration also remain unsupported. These source
changes do not alter the frozen `ClockPlan` admission guard.

Independent test command:
```sh
python -m unittest discover -s tests/contracts -p 'test_nyquismic_control_geometry.py' -v
```
The tests cover analytically integrated increasing/decreasing linear rates,
an exact half-second crossing, irrational crossings with certified residual
bounds, additive-route equivalence, reset epochs, stable jitter cells,
quantized-ramp rejection, cancellation and resource budgets. A passing pure
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
