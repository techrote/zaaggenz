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

## Follow-up: strict static-uniform windowed-sinc reconstruction

`sinc8_hann_uniform_v1` is an additional **opt-in** `SonicSpec.reconstruction`
value. The supported clock must be genuinely static/uniform: no Hz points,
phase resets, routes, quantizer or jitter. These capabilities are checked
during `SamplerPlan.prepare` even if the node will be bypassed. A separate,
physically time-aware nonuniform sinc policy remains unimplemented and is
**never** silently approximated using this uniform kernel.

For each numerical output time in an admitted capture interval, the
reconstruction sums captured event amplitudes with normalized weights

`w(x) = sinc(x) * (0.5 + 0.5*cos(pi*x/8))` for `|x| < 8`,
and zero otherwise, where `x=(t-t_capture)*f_virtual` counts fractional
virtual-event spacings. The window radius is **8 virtual samples**, with
nominal 17 event positions and 16 nonzero off-grid taps at most;
`budget.max_filter_taps >= 17` is required. The truncated kernel is
normalized by its own coefficient sum to preserve a constant input at source
edges; there is no overall audio-level normalization, clipping, or cleaning
of intentionally formed aliases.

The original zero-before-first-capture and last-capture hold boundary
conventions remain in force. The kernel uses admitted full-context captures,
not independent per-request or per-block edge padding, so resumed/region
renders are sample-exact relative to a full run. It introduces up to eight
virtual events of interpolation support (including pre/post ringing) but
does not change the requested output extent or perform a final delivery
conversion. Coefficient evaluation uses float64 NumPy sine/cosine; results
have numeric tolerance expectations rather than cross-platform bit identity.

The focused suite proves DC gain including truncated edges, exact event-grid
capture, Fourier suppression of a hold image at 11 kHz, preservation of an
intentional 7kHz-to-5kHz virtual alias, stereo, region/checkpoint identity,
zero-wet/bypass, cancellation, budget admission and irregular-clock rejection:

```sh
python -m unittest discover -s tests/dsp -p 'test_nyquismic_sinc.py' -v
```

This narrows the remaining #252 work but does **not** satisfy it. In particular,
finite adjustable prefilter cutoff/strength, guarded-clean baseline,
nonuniform reconstruction, local evaluation/final-conversion policy,
numerical convergence and frozen independent quality evidence remain
outstanding. All outputs still stay in the numerical sampler domain.


## Opt-in static FIR cutoff/strength selections

The static source FIR now also admits two discrete versioned policy strings:

| Saved `prefilter` | Cutoff | Filtered fraction |
| --- | --- | --- |
| `fir33_hann_static_0p45_v1` | 0.45 × saved virtual Hz | 1.0 (original unchanged) |
| `fir33_hann_static_0p30_v1` | 0.30 × saved virtual Hz | 1.0 |
| `fir33_hann_static_0p45_mix0p5_v1` | 0.45 × saved virtual Hz | 0.5 |

The half-strength mode adds a 0.5 unit impulse to the centre of the
0.5-strength DC-normalized kernel. It is therefore exactly a linear dry/FIR
capture-source blend, without modifying wet/dry output routing. All variants
retain 33 symmetric taps, 16-frame context, source-rate interpolation,
static-only admission, and final extent. Policy name, cutoff, mix fraction,
sonic identity and actual float64 coefficient bytes are explicit and
traceable in diagnostics; legacy `off_v1` and `0p45_v1` are unchanged.
These selections are **not** continuous user-editable cutoff/strength controls;
that contract/UI and guarded-clean/filter-convergence evidence remain #252 work.
Test: `python -m unittest discover -s tests/dsp -p 'test_nyquismic_prefilter.py' -v`.

## Bounded pre-capture FIR and source-window cancellation

The same versioned 33-tap FIR can now process an admitted immutable source in
**8192-source-frame output windows**, rather than one uninterruptible
full-channel convolution. Every window reads exactly 16 original source frames
on each side through the same full-context `zero_pad`/`edge_hold` extension;
the boundary between windows does not reset, pad, or truncate the signal.
An independent two-channel reference fixture compares the resulting float64
samples **bit-for-bit** with the previous monolithic convolution across two
window boundaries and a short terminal window. The filtering operation checks
the cancellation hook before each window, including the first, and publishes
no partially filtered capture table on cancellation. This does not change the
filter's 33-tap coefficient identity, source lookahead, sonic policy or numerical
delivery behavior.

Validation: `python -m unittest discover -s tests/dsp -p 'test_nyquismic_prefilter.py' -v`.
The test instruments convolution input lengths and verifies an interrupted
60,000-frame stereo request stops after only two source windows. It does
**not** establish full instrument/Windows playback, rate-convergence or
guarded-clean acceptance.

## Opt-in irregular-event physical-time Shepard/Hann reconstruction (experimental)

New policy `shepard8_hann_local_time_v1` is a *separate*, bounded
**non-bandlimited** reconstruction policy; it never reuses the uniform sinc
assumption. It accepts the existing NYQ-002 piecewise clock and reset
geometries, and shares frozen capture tables/checkpoint and half-open
boundaries. It does not make routed/quantized/jitter clocks executable until
NYQ-004's sampler adapter is accepted.

At requested physical output time `t`, for each captured event `k` in
`[owner-8, owner+8]`, define a positive local interval scale in **seconds**:
`h[k] = (t[k+1]-t[k-1])/2` at interiors; at source edges use the immediate
available interval. Define `x[k]=(t-t[k])/h[k]`. For `0 < |x| < 8`,
`w[k] = (1+cos(pi*x/8))/(2*x*x)`; otherwise `w[k]=0`. The
result is `sum(w[k]*capture[k]) / sum(w[k])`, with a fail-closed check for
nonpositive/nonfinite mass. At an exact event time the capture itself is
returned, avoiding the inverse-square singularity. The weights are positive,
so this policy has unity DC for a constant **captured event stream** and does not
overshoot the convex hull of captured samples. A nominally constant original
source with `zero_pad` can still yield nonconstant captures at its excluded
last source-frame endpoint: the full-context kernel correctly preserves that
separate capture-boundary policy rather than silently fabricating DC. It is continuous approaching
event positions, but **not** a physically exact sinc or high-quality
bandlimited reconstruction, nor a method for removing already formed
aliases. The Hann taper is smooth at its physical-time support boundary.

Admission requires `budget.max_filter_taps >= 17`. At most 17 captured
events contribute per output sample, with a maximum eight-index look
behind/ahead; this is independent of numerical output-grid block size.
Before the first capture output remains zero; after the last capture the
existing final hold applies. Output extent, wet/dry and master ownership do
not change. Near reset points the kernel can intentionally mix neighboring
captures across the discontinuity; no undocumented phase continuity,
anti-alias guarantee, delivery conversion or numerical convergence is
claimed.

Evidence: `python -m unittest discover -s tests/dsp -p
'test_nyquismic_nonuniform_kernel.py' -v` covers independent physical-time
weights on a changing-rate clock, exact captured samples, mono/stereo DC,
finite/convex-hull behavior, chunk/checkpoint identity, bypass, short/empty,
budget failure and cancellation. Final-head CI and independent acoustic
evaluation remain outstanding. No default sound or preset is promoted.

## Opt-in guarded-clean finite-filter comparison (static, bounded)

`fir129_kaiser_guarded_0p40_v1` adds a separate **129-tap symmetric
Kaiser-windowed source FIR**, beta 10.0, cutoff `0.40 * saved_virtual_Hz`,
DC-normalized with no hidden output gain/limiter and 100% filtered capture
source. It runs before virtual event capture and is explicitly a *cleaner
comparison*, not a universal alias-free or mathematically ideal reconstruction
policy. It admits **static-only** virtual rates from `source_rate/8` through
`source_rate/2`, with at least 129 available filter taps, and rejects
modulated rate points, out-of-range source/clock ratios and insufficient
budgets before preparing captures. Dynamic/irregular clean sampling and
measured convergence still belong to NYQ-003.

The exact symmetric kernel has 64 source-frame lookbehind/lookahead,
zero phase, and explicit `zero_pad` or `edge_hold` padding at asset
boundaries; 8,192-frame processing windows retain the identical complete
context. No filter tail extends the requested output extent. The result may
still ring near transients, and finite transition width cannot make every
possible high-frequency source clean. Its `prefilter_window`,
`prefilter_cutoff_hz`, `prefilter_strength`,
`prefilter_support_source_frames` and SHA-256 of little-endian float64
coefficients are included in diagnostics. Its policy identifier participates
in the sonic hash. All three original 33-tap policies, legacy bitcrusher and
default `off_v1` remain unmodified.

At 48 kHz source and 8 kHz virtual capture, the comparison uses a
**3,200 Hz cutoff**; independent tone tests compare an intended 900 Hz
passband and a 5 kHz would-be alias against the unfiltered and legacy FIR33
paths. Other cases cover stereo full-context convolution (including two
8,192-frame boundaries), region/checkpoint equality, serialization,
bypass/zero-wet, cancellation and strict unsupported rate/tap limits. Run:

```sh
python -m unittest discover -s tests/dsp -p 'test_nyquismic_prefilter.py' -v
```

No claim is made about per-band rack integration, source feature routing,
final numerical delivery conversion, global convergence, physical Windows
listening or musical preference.


## NYQ-003 continuation: isolated local numerical-delivery FIR component

`zaaggenz_dsp.nyquismic_delivery` now provides an explicitly opted-in
`convert_numerical_to_delivery` component with the strict, full-snapshot
`DeliveryConversionPolicy` (`nyq.delivery-conversion.v1`). This is a
**component and numerical-quality evidence tool**, not a change to the existing
`SamplerPlan`, master output path, export, graph, bitcrusher or preset
defaults. The core sampler still uses
`point_evaluation_no_conversion_v1` and does not advertise production
convergence.

The method `nyq.polyphase-delivery-kaiser10-24lobes.v1` uses an exactly
declared integer ratio `up/down` reduced by gcd, a symmetric odd
`24*max(up,down)+1` tap windowed-sinc/polyphase low-pass kernel,
Kaiser beta 10, a prototype cutoff of `1/max(up,down)` relative to the
interpolated-grid Nyquist, SciPy 1.17.0 `firwin` and `resample_poly` with
**constant-zero boundary extension**. The central physical time origin is
unchanged, the output length is `ceil(input_frames*up/down)` and partial
terminal extent is padded/cropped by this declared policy. The fixed
kernel coefficient SHA-256, ratio, method, source/output frame counts,
boundary, and clipping='none' are returned as diagnostics. Equal-rate
conversion is an exact identity, not a filter pass. The helper preserves
float64 output without clamping or peak/RMS normalization.

No implicit ratio approximation is admitted. The evaluation rate must be
at least the delivery rate, rates and all input samples must be valid, and
the generated kernel must fit the explicit resource budget. In particular,
192000-to-44100 conversion needs 15361 taps for this **specific** method,
which exceeds the default 4096-tap budget and is rejected instead of
silently using a shorter fallback. Empty mono/stereo PCM yields matching
empty output, and all intermediate/output samples must be finite.
The helper copies bounded input PCM into a private float64 snapshot
**before finite-data admission and external SciPy FIR execution**.
It does not pass a caller-owned float64 view through the filter: later
concurrent mutation of that view must not silently replace the checked
sample values. A deterministic adversarial regression mutates the caller's
buffer at the SciPy invocation boundary while verifying identical output
and immutable delivery PCM. This is one-call input ownership, not proof
against unsynchronised mutation *during* the initial copy or an independent
sonic/clock provenance oracle.
Cancellation is checked before and after one complete SciPy conversion;
the helper does **not** claim mid-kernel cooperative cancellation. Its use
for long-form work requires additional bounded-window streaming/context
qualification, and the actual saved export path must be separately wired.

An independent DSP test distinguishes high-frequency parent suppression
from the intentional **5 kHz difference product** of a nonlinear squared
28+33 kHz two-tone at 192 kHz before delivery to 48 kHz. This verifies the
ordering condition that delivery filtering cannot be applied prematurely
before nonlinear interactions. Additional tests cover 1 kHz passband,
36 kHz evaluation-image rejection, identity, stereo, empty/partial
terminal extent, coefficient identity, invalid numerics and ratios,
cancellation and budgets. Run:

```sh
python -m unittest discover -s tests/dsp -p 'test_nyquismic_delivery.py' -v
```

No same-model multi-rate convergence claim, fixed reference sequence,
spectral/transient acceptance threshold, production export support, or
musical superiority is established by this helper. Those remain required
to close #252. This comparison component cannot undo aliases formed at
the virtual capture stage.
