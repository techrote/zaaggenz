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
