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
