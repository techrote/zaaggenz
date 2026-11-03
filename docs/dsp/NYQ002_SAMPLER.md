# NYQ-002 — fractional-event sampler kernel

Scope: [#251](https://github.com/techrote/zaaggenz/issues/251), following accepted
NYQ-001 in merged PR #260. This describes the implemented kernel and executable
evidence. Acceptance still requires final-head checks and verified main merge;
rack, Compose, warp, cascade and #249 completion remain later work.

## Interface and immutable identity

`zaaggenz_dsp.nyquismic` exposes `FrozenInput`, `sampler_evaluation`,
`SamplerPlan`, `SamplerCheckpoint`, `SamplerResult` and `render_sampler`:

```python
from zaaggenz_contracts.nyquismic import SonicSpec
from zaaggenz_dsp.nyquismic import FrozenInput, SamplerPlan, sampler_evaluation
source = FrozenInput.from_pcm(pcm, sample_rate_hz=48000)
plan = SamplerPlan.prepare(source, SonicSpec(), sampler_evaluation(192000))
numerical = plan.render()
region = plan.render(100, 900)  # Exact crop of this complete context.
```

The source uses existing `AudioAssetRef` and immutable canonical
`pcm-f32le-interleaved-v1` bytes. `from_pcm` performs one explicit float32
representation conversion, rejecting complex/nonfinite/unrepresentable values
without clipping/rescaling. Its bytes-backed view cannot become writable. An
optional supplied asset must match all PCM metadata/hash fields. Every numerical
rate reuses identical source bytes, rather than regenerating a signal.

The explicit evaluation pair is `fractional_event_sampler_v1` /
`point_evaluation_no_conversion_v1`. Existing `EvaluationPolicy()` defaults stay
`unavailable_nyq001`; mismatched pairs reject. SonicSpec remains 1.0.0. Generic
graph/rack dispatch is still unavailable; this is an explicit numerical kernel.
Existing RenderIdentity binds method/evaluation, immutable source, sonic identity,
source/context revisions and full extent. Execution identity additionally binds
numerical frame count and mono shape. Labels are cosmetic. Invalid supplied
revisions reject; only omitted (`None`) values receive content-derived defaults.
No-rack/no-graph identities explicitly name absent integration.

## Timing, source model and boundaries

Output frame `n` is at `clock.origin_s + n / evaluation_rate_hz` in
`[0, frame_count)`. Default frames are source duration rounded up on this grid;
bounded explicit counts are supported. Source position is `t - clock.origin_s`,
never accumulated playback speed. A per-note reset is a fresh saved origin/phase;
chunks/regions never reset phase. Explicit resets retain capture history.

ClockPlan remains the sole authority. `event_coordinate(index)` returns an exact
rational root or the existing Decimal80 root. `capture_count_at(Fraction,
inclusive=...)` settles membership using exact phase, including reset ties.
Rounded display times never establish ownership. Every crossing is captured,
including multiple events per numerical sample; there is no rounded hold period.

| Operation | Implemented meaning |
|---|---|
| `linear_v1` capture | Piecewise linear source-grid evaluation at fractional event coordinates. |
| `nearest_left_tie_v1` | Nearest source sample; exact half-sample ties choose the left. |
| `off_v1` prefilter | No prefilter; deliberate sampling aliases remain. |
| `hold_v1` reconstruction | Right-continuous last capture; zero before the first. |
| `linear_time_v1` | Interpolate actual adjacent capture times; zero before first and hold after final admitted capture. |
| `zero_pad` | Out-of-array integer samples are zero. Linear capture in the last interval ramps from the final sample to zero at the excluded source endpoint. |
| `edge_hold` | Out-of-array samples equal the corresponding edge; empty input stays zero. |
| Tail | Exact requested extent; no extra capture at its excluded endpoint. |

Linear reconstruction uses future capture context only inside the full extent.
`wet` mixes with the source's piecewise-linear dry representation on the numerical
grid. Active output is unclamped float64: no quantizer/master/limiter/dither/
normalization. Existing BitcrushSpec is unchanged and remains a separate stage.

Zero-wet/bypass validates all settings/budgets then copies original float32 PCM
exactly, including signed zero, with requested crop/boundary extension only.
Exact identity requires matched source/numerical grids; mismatched-grid bypass
rejects instead of silently resampling. Larger graphs must place conversion
outside the bypassed effect. Unsupported modes/routes/quantization/jitter and
convergence passes reject even behind bypass. A constant clock remains a static
sampling effect, not dry identity.

## Admission, state and failure

Full-context admission checks source/output channel-frame budgets, aggregate
event/independent-channel budget, complete read endpoint, physical time,
capability and minimum spacing before capture/output allocation. Original limits
remain. Source assets retain 8–192 kHz; numerical clocks use the separate existing
policy. A grid whose denominator cannot fit frozen rational checkpoint bounds
rejects. Regions receive no discount on whole-context work.

Preparation atomically creates immutable captures. Linked clocks share geometry
with independent channel values; independent stereo has separate identities and
conservative event admission. Static schedules agree until NYQ-004 adds jitter.
No global cursor/PRNG or worker-dependent state exists. Interpolation uses each
event's absolute first-frame arithmetic anchor: irregular chunks and full-render
crops are bit-exact within one numerical environment.

Usable plans can only be created by `SamplerPlan.prepare`. Direct construction
and `dataclasses.replace` reject, so callers cannot substitute unadmitted or
mutable capture tables while retaining an accepted execution identity.

`plan.checkpoint(frame)` stores execution/source/numerical/context identity,
next frame, existing verified clock state, previous/next capture IDs and values
(including lookahead), active/bypassed history and version
`nyq.sampler-checkpoint.v1`. Its boundary is after controls/resets and before
capture exactly at that time. JSON rejects unknown/missing fields. Restore
recomputes every field against the same complete immutable source/spec plan,
rejecting tampered history, foreign instances and stale context. Rebuilding that
plan first is supported; this is an offline checkpoint, not a live source stream.

Cancellation checks occur during clock generation, at most every 256 captures,
at most every 256 reconstructed frames, after progress callbacks and immediately
before success, including final flush. Failed/cancelled calls return no partial
audio/checkpoint and change no other request. `render_sampler` composes monotone
0–1 progress. Scheduler adapters can use
`cancelled=lambda: (ctx.check_cancelled() or False)` and `progress=ctx.progress`,
retaining the existing JobCancelled, sole pool, publication/cache and revision
authority. Runtime integration remains #256.

## Independent evidence and scope

Original frozen clock identities remain unchanged:

- Data: `b42b2d9988df822169d8fd6e02a28dd208eff2b1e0ddf4a2d15df13c6c9ee5bd`.
- Generator: `c700d12382ca1d55402f37d86376f5d625d44ed37cdedccdb21474519785c8b2`.

New standard-library Fraction/Decimal80 signal oracles have no production
imports. PCM tolerances are fixed at `2e-12` absolute/relative; original clock
tolerance stays 2 ps + 8 ulps. Divisible holds, ownership, bypass and same-host
partitions are exact; cross-platform bitwise equality is not claimed. Tests cover
all frozen clocks; 11,137/11,730 Hz; fractional/near-integer rates; saved rational
references; ramp/step/reset PCM; multiple captures per frame; the same nonlinear
source at multiple evaluation rates; stereo; empty/single/silence; boundaries;
tampered checkpoints; finite admission; and cancellation through publication.
An analytic tone control checks the 6 kHz → 2 kHz alias at an 8 kHz virtual clock
and predicts six-sample hold amplitude independently.

`tools/nyq002_report.py --out OUTPUT_DIRECTORY` emits ten real synthetic 12/48 kHz
examples, source WAVs, saved specs/evaluation/source identities, checkpoints,
hashes and diagnostics, verifying exact resume/chunk/region equality. Raw exports
stay untouched; separate `listening-matched` derivatives disclose one RMS scalar.
Existing ZG-016 Windows/Ubuntu CI runs tests and uploads evidence; no new workflow,
matrix or private runner is added. Diagnostics separate requested rate bounds,
measured reciprocal event intervals, admitted/captured counts, display rounding,
phase/reset origin, source/numerical rates, policies and exact output extent.

**Point evaluation is not final delivery conversion or a convergence
certificate.** Hold discontinuities have images above any finite numerical
Nyquist. NYQ-003 owns filters, conversion, additional kernels and same-dirty-model
quality characterization; NYQ-004 owns routed/jitter/quantized clocks. Their
extension boundary is saved spec/evaluation, exact ClockPlan geometry, immutable
source, full-context captures and verified history. Neither may silently change
this method or source representation.
