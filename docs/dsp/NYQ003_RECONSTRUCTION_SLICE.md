# NYQ-003: time-aware nearest/cubic reconstruction implementation slice

Scope: issue [#252](https://github.com/techrote/zaaggenz/issues/252), dependent on
the merged and accepted NYQ-002 kernel (#251). This **does not complete NYQ-003**:
prefilters, guarded-clean filtering, uniform/irregular windowed sinc and final
numerical-to-delivery conversion/convergence remain blocked on separate validated
methods and exact-final-head acceptance. NYQ-004 is a separate clock owner.

## Opt-in capability table

| Reconstruction | Capture source | Clock event geometry | Semantics |
| --- | --- | --- | --- |
| `hold_v1` | NYQ-002 linear or nearest | static / step / linear-Hz | Existing unchanged right-continuous hold |
| `linear_time_v1` | same | same | Existing unchanged exact event-time interpolation |
| `nearest_time_v1` | same | same | Choose nearest captured event by physical time; exact half-interval ties select the preceding capture |
| `cubic_time_v1` | same | same | Four-point local nonuniform cubic Hermite reconstruction; one-sided endpoint derivatives, final capture hold |

All named modes are strictly opt-in values in the existing `SonicSpec`
snapshot; the default remains `hold_v1`. The policy is a new enum, not a
replacement of legacy bitcrusher hold or `zg.kaiser_polyphase_zero_phase.v1`.
No generic rack graph dispatch is enabled. Both modes apply to the admitted
fixed numerical output grid and inherit the previous `off_v1` prefilter.

Cubic uses each neighboring segment's actual `t[k]` in seconds. For interval
`[t[k],t[k+1])`, define `d=(t[k+1]-t[k])` and `u=(t-t[k])/d`.
The Hermite endpoint slopes are the centered two-event spans
`(s[k+1]-s[k-1])/(t[k+1]-t[k-1])` and
`(s[k+2]-s[k])/(t[k+2]-t[k])` when those neighbors are available.
At the first/last neighbor use the adjacent single-interval secant.
The usual cubic Hermite basis blends those slopes and the two adjacent captures.
This is a **finite, non-bandlimited interpolation**, not an anti-aliasing filter:
it may overshoot and does not silently normalize, clip or suppress images.
It uses at most one event before and two after the current interval (four
captures total), with the full admitted plan as lookahead. Before the first
capture output is zero, and after the last capture it is held. The sampler's
established half-open extent, wet, dry, cancellation, region/checkpoint, and
capture/event ownership remain authoritative.

The independent fixture exercises time-nearest midpoint selection, an
irregular linear-Hz event clock, cubic endpoints and an analytic Hermite
midpoint, chunk/checkpoint equality, silent stereo, exact bypass and cancellation.
Run:

```sh
python -m unittest discover -s tests/dsp -p 'test_nyquismic_reconstruction.py' -v
python -m unittest discover -s tests/dsp -p 'test_nyquismic_sampler.py' -v
python -m unittest discover -s tests/contracts -p 'test_nyquismic*.py' -v
```

**Nonclaims:** No sinc kernel, prefilter, local evaluation-rate convergence,
export WAV conversion or product UI. Those remain the explicit #252/#256/#258
work; numerical tests do not establish owner musical preference or Windows
instrument acceptance.


## Follow-up: explicit static source prefilter

An opt-in `fir33_hann_static_0p45_v1` source filter is now available alongside
`off_v1`. This is a real pre-capture filter, independent of `capture` and
`reconstruction`, **not** a generic graph node or delivery antialias filter.

- 33-tap symmetric linear-phase FIR, Hann window, ideal sinc prototype;
  cutoff = exactly 9/20 of the saved static virtual rate in physical Hz.
- Coefficients are computed in float64 and normalized to unity DC response;
  the source PCM or rendered audio is never peak/RMS normalized or clipped.
- Offline zero-delay alignment with 16 **source** frames of lookahead
  and symmetric pre/post ringing. `zero_pad` or `edge_hold` applies to FIR
  edge extension as well as the subsequent source interpolator.
- Strict capability gate: static virtual rate below immutable source rate,
  no changing base-Hz automation, at least 33 allowed filter taps.
  Routed/quantized/jitter geometry remains unavailable until NYQ-004.
- Filtered capture uses the original immutable `pcm-f32le-interleaved-v1`
  source and never mutates that input. The `SonicSpec` opt-in setting
  changes `sonic_sha256`; method, cutoff, source-frame support and
  float64-le coefficient hash are exposed by sampler diagnostics.
- All-bypass and zero-wet remain exact raw-source identity after admission.
  The existing `off_v1` default and old bitcrusher/AA are untouched.

Independent fixture command:

```sh
python -m unittest discover -s tests/dsp -p 'test_nyquismic_prefilter.py' -v
```

The fixture measures high-frequency capture suppression versus deliberate
folding with no prefilter, passband fidelity, symmetric impulse response,
stereo/silence/empty input, region identity, source immutability,
serialization/fingerprint distinction and failure on unsupported dynamic
cutoff or undersized tap budgets. This is not a guarded-clean filter or a
numerical-convergence/final-conversion claim. Those remain part of #252.
