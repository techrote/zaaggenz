# Nyquismic Modulation — validation and acceptance plan

**Master:** [NYQ-000 #249](https://github.com/techrote/zaaggenz/issues/249)  
**Acceptance owner:** [NYQ-009 #258](https://github.com/techrote/zaaggenz/issues/258)  
**Status:** NYQ-001 contract/clock fixtures and tolerances are frozen below; audio numerical comparisons and instrument acceptance remain pending the later children.

Read the [specification](NYQUISMIC_MODULATION.md), [implementation RAG](../zaaggenz/NYQUISMIC_IMPLEMENTATION_RAG.md) and existing [validation gates](../zaaggenz/briefs/VALIDATION_GATES.md). Preserve baseline/accepted evidence and do not weaken a comparator to make a new renderer pass.

## NYQ-001 frozen reference set

The implemented contract, bounds and reproducibility policy are in
[NYQ001_FOUNDATION.md](NYQ001_FOUNDATION.md). Independent generator
`tests/contracts/nyquismic_oracles.py` has SHA-256
`c700d12382ca1d55402f37d86376f5d625d44ed37cdedccdb21474519785c8b2`.
Frozen analytic data `tests/contracts/fixtures/nyquismic-v1.json` has SHA-256
`b42b2d9988df822169d8fd6e02a28dd208eff2b1e0ddf4a2d15df13c6c9ee5bd`.
Neither calls a production clock/capture/reconstruction implementation.
The separately identified legacy snapshot has SHA-256
`a0717357a33a5f88e398ec9b5a8c524d2d3e60782a4bfa1369f3336ebf977b18`.

Clock time tolerance is **2e-12 seconds + 8 ulps** of the absolute timestamp,
frozen before production comparison. Integer event counts, epoch/crossing IDs,
interval membership, rational phase, hashes and counter-addressed random values
are exact. Static tone folding is independently checked, not falsely counted as
rendered audio evidence. Preserve these fixture bytes and add explicitly versioned
successors rather than regenerate a baseline to fit a later kernel. Source model,
final filter, reconstructed images/amplitudes, sinusoidal/audio-derived modulation
and cross-platform audio tolerances still require their own child evidence.

## Separate four questions

1. Does the clock/signal algorithm implement the saved mathematical model?
2. Does numerical evaluation faithfully preserve that model's intentional damage?
3. Does the actual saved instrument workflow execute that same model and revision?
4. Does the owner prefer the sound or want a new default?

The first three require executable acceptance evidence. The fourth is an independent artistic decision. A correct optional effect need not win a preference test, and an attractive example does not certify clock/state correctness. No new numerical rating campaign or human-study prerequisite is introduced.

## Independent timing and spectral oracles

Use a fixture implementation that does not simply call the production phase integrator, capture kernel or cascade executor under a different name. Record its derivation, input representation, precision and applicability. Analytic controls are stronger than treating the highest available sample rate as unquestionable truth.

**Uniform clock:** with phase zero and an initial capture at zero under the frozen convention, `t_k=k/f_v`. Check both exact divisible grids and non-integer relationships such as 11,137 and 11,730 Hz against a saved 48 kHz reference. Test values immediately either side of an integer hold ratio; a small parameter change must not become an unintended large rounded-hold jump.

**Linear-Hz modulation:** for `f_v(t)=f0+a*t`, the phase is `f0*t+a*t*t/2`. Solve the quadratic independently, using a cancellation-safe/high-precision expression near `a=0`. Include decreasing ramps whose complete admitted range remains positive. Test a control breakpoint exactly on and immediately beside a capture event.

**Sinusoidal frequency modulation:** integrate the declared sinusoid analytically before solving crossings; compare phase/events as well as reconstructed audio. This detects the error from substituting `t_next=t+1/f_v(t)` when the rate changes substantially inside an interval. Fast control cases must not be evaluated only once per processing block.

**Uniform tone aliases:** for a single real sinusoid at frequency `f` sampled at uniform `f_v`, expected baseband magnitude frequency is:

```text
f_alias = abs(((f + f_v/2) mod f_v) - f_v/2)
```

For example, 6 kHz at an unfiltered uniform 8 kHz virtual sampler folds to 2 kHz in the virtual baseband. Reconstruction may also create images: measure locations and amplitudes under the selected hold/interpolation/filter response, rather than attributing every output partial solely to the alias formula. Use coherent windows or a preregistered leakage-aware estimator. This static formula is not an oracle for arbitrary nonuniform clocks.

**Read-head warp:** independently integrate `u(t)=u0+integral(speed)` and use analytic sine/chirp/ramp inputs to test speed 0.5, 1 and 2, time-varying speed, source exhaustion and loop rules. Compare with capture-clock modulation to prove the modes are semantically distinct. Check output extent separately from traversed source extent.

**Impulse/DC/hold:** use known event phases to check initial capture, hold intervals, gain, delay, kernel support, overshoot and pre/post ringing. There is no hidden normalization. Zero input remains zero absent a separately enabled audio-noise generator.

## Required coverage matrix

| Suite | Required assertions | Primary owner |
|---|---|---|
| Contract and migration | Canonical round trip, units/bounds, mode/filter capability, rational normalization, explicit versioning, no unsupported lane stripping | NYQ-001 / #250 |
| Event geometry | Monotone fractional timestamps; constant/ramp/step/reset oracles; exact boundary rules; no lost multiple events | NYQ-002 / #251 |
| Static texture | Expected alias/image positions; integer/non-integer/near-integer rates; separate capture and reconstruction | NYQ-002/003 / #251–#252 |
| Filters | Measured passband/DC/stopband, support, latency, ringing/overshoot, edge/padding rules; truthful nonuniform capability | NYQ-003 / #252 |
| Numerical quality | Same artistic model across evaluation rates; independent analytic controls; waveform/spectral/transient residuals; bounded convergence disposition | NYQ-003 / #252 |
| Modulation | LFO/beat/step/envelope/audio-rate controls; mapping/order; zero-depth static equivalence; tempo/phase boundaries | NYQ-004 / #253 |
| Jitter and rate ladder | Reproducible streams/phase; linked/independent stereo; positive clock; tie/hysteresis/switch rules; explicit ratio reference | NYQ-004 / #253 |
| Derived/cross-band control | Correct upstream immutable tap/feature revision, support/confidence, missing/stale rejection, no cycles | NYQ-004/007 / #253/#256 |
| Playback Warp | Integrated source-time map, fixed output extent, speed-one assumptions, loop/exhaustion/state, no project retiming | NYQ-005 / #254 |
| Cascade/order | Three real stages; stable IDs; nonlinear neighbors; no algebraic removal of creative intermediates; all bypass combinations | NYQ-006 / #255 |
| Rack/ownership | Delay-aligned delta, confinement/spill, old four anchors/24 orders, protected pockets/stems, one master | NYQ-007 / #256 |
| Persistence and jobs | Exact saved/audible revision, cache invalidation, context-aware preview/full equivalence, cancellation/stale/atomicity | NYQ-007 / #256 |
| Real Compose | Actual controls to saved backend to PCM; reopen/A-B/undo/export; no second session; truthful capabilities | NYQ-008 / #257 |
| Final acceptance | Clean Windows artifact/walkthrough; supported Windows/Ubuntu tests; complete matrix and limitations | NYQ-009 / #258 |

All suites include supported mono/stereo, independent instances, empty/single/short/silent input, invalid/nonfinite values and finite-output checks. A node may reject a documented unsupported input, but never publish accidental garbage as success.

## Quality comparison protocol

Freeze the fixture source representation, artistic virtual rates, modulation routes/phase, jitter realization, kernels/support, nonlinear order, final comparison passband, numerical candidate sequence and acceptance tolerances. Do not regenerate an unrelated noise sequence or silently change the source's bandlimit at each evaluation rate.

Candidate evaluation domains may include 192, 384 and 768 kHz and a higher finite comparator when admitted. The actual supported sequence is an implementation result, not a global ZaagGenZ default. Reconstruct all compared outputs to a common declared timeline/rate with the same pinned final converter. Compensate only declared implementation delay; do not align away intended jitter/warp or optimize away parameter errors.

Measure absolute/relative waveform residual, audible/common-band spectral error, expected alias/image component error, transient peak/shape/timing, DC and finite output. Report below-noise-floor denominators separately rather than turning near-silence into unbounded relative errors. Do not use total 'alias energy' as a cost function that rewards removing the effect.

Include both easy and adversarial cases: static tones, dense harmonics, near-Nyquist input, deep frequency modulation, step changes, waveform folding/hard clipping after sampling, multiple cascades and an ultrasonic two-tone nonlinear difference-product control. The latter catches premature final-band filtering before nonlinear interaction. Source PCM bandwidth and simulated intermediate bandwidth are declared separately.

A pass requires independent oracle agreement and the frozen residual conditions, not only adjacent-rate agreement. Two implementations can share the same error. Bounded convergence selection stores every attempted rate, residuals, selected tested output and final disposition. Exhausting the admitted sequence yields an explicit inconclusive/failure status; it cannot trigger endless doubling or a mislabeled high-quality export. A separately requested fixed-rate render can retain its truthful fixed-rate label.

Cross-delivery tests compare only the shared representable band with common source/model settings. They do not claim bitwise equality between differently sampled files, universal output-rate support, or invariance for explicitly delivery-relative artistic parameters. Existing legacy renderers are not retroactively subjected to a new sound-changing invariant.

## State, chunk and region tests

Run the same fixture whole, in irregular chunks (including one-sample chunks where admitted), from serialized checkpoints and as interior region previews with required pre/post support. Compare event lists, stochastic identities, read-head position and final PCM separately. Fix the guarantee: bitwise identity where achievable in the same numerical environment, otherwise a justified frozen numerical tolerance. Do not claim cross-platform bitwise floating-point identity from same-platform tests.

Test note/reset events, automation breakpoints and tempo changes immediately before/on/after chunk and region boundaries. Include a preview beginning deep inside a hold, long filter, jitter realization, warp or loop. A fresh-state excerpt is a separately labeled audition, not a full-render-equivalent region preview.

Reordering a stable instance preserves its random identity; duplication follows a documented new-instance policy. Shared clocks are really shared, independent clocks have separate deterministic identities, and unrelated label/UI order changes cannot consume additional random samples.

## Compatibility and integration controls

Retain accepted legacy/default/source recipes and PCM hashes, including `locked_bloom`, old bitcrusher sample-0 hold semantics and existing AA/filter policies. New opt-in nodes never silently rewrite these records. No-rack projects and built-in-only MBR records remain compatible through explicit versioned adapters.

Require sample-exact disabled/zero-wet and empty-cascade identities at the appropriate node/rack boundary. A static wet sampler remains an effect; zero modulation depth is not assumed dry. Equal sample-rate values do not certify identity without phase/filter/boundary assumptions.

Test the existing effect-delta router with known latency and distinct band settings. Align implementation delay before subtracting the original band. Validate actual confinement response/leakage and deliberate spill; transition bands are not brick walls. Preserve complete SYNTHLINE and the independently owned BODY/AUX/SUB/SCULPT paths, with one final master. Monitoring-only A/B compensation/solo cannot enter exports.

Mutate one sonic control, input feature, source, instance order, evaluation method or context revision at a time and verify correct cache invalidation. Labels stay cosmetic. Reopen saved projects/user presets and verify that displayed settings, preview/meters and exported PCM are bound to the same revision; stale workers may never replace them.

## Resource and failure boundaries

Freeze explicit finite limits for events and minimum spacing, control/ratio-set size, graph/cascade depth, filter support/lookahead, source read extent, artifact size and reference passes. Preflight bounds before allocating large buffers when possible; validate runtime state as well. Bounds are safety limits, not claims that audio must complete within a realtime buffer deadline.

Exercise zero/negative/NaN/Inf clocks, bool-as-number, over-range depth, denominator zero, huge ratios and numerators, unsupported kernel/mode combinations, nonmonotone jitter, cycles, stale/foreign feature identities, float overflow and integer export limits. No silent clamp, sort, dropped lane, fallback preset, renormalization or finite-looking saturation may hide an invalid computation.

Cancel during event generation, filtering, source-read/loop operations, cascade stages, final flush, convergence checking and publication. Also test rapid superseding edits, output-write failure and restore/reopen. Previous coherent audio survives; failed/stale/partial output is not accepted or cached. Do not retry successful work or poll indefinitely.

## Instrument and listening evidence

On supported Windows 11 x64, perform the complete ordinary Compose workflow with real backend and browser: accepted source, selected-band Nyquismic insert, rate/modulation edits, character/prefilter change, cascade reordering, A/B/bypass/undo, user-preset and project save, close/reopen, context-aware preview and final export. Record recipe/artifact IDs and PCM evidence, not only screenshots. Supported numerical/browser Windows and Ubuntu CI remains required; Linux unit tests do not prove Windows UI behavior.

Create a small WAV/FLAC demonstration pack covering baseline, continuous clock sweep, rate steps, jitter, reconstruction contrast, playback warp, cascade and protected-bass/per-band use. Name actual files and supported embedded tags with mechanism/version. Include exact source/recipe/method hashes, settings, seeds and comparison cues. Keep raw exports distinct from one-scalar, explicitly labeled listening-matched derivatives; spoken labels do not contaminate clean audio.

Use original synthetic fixtures or permitted local references. Do not upload private reference audio, purchase plug-ins, change factory tiers or demand numerical owner ratings. Owner comments may establish favorites or defects without converting the acceptance work into a study.

## Evidence and closure record

Every child records its actual contract/method version, supported capability matrix, commands/environment, direct/reverse CI at the final head, tests and hashes, PR/merge on main, limitations and next dependency-ready task. Update the RAG map from accepted evidence only. Canonical `programme/task_state.json` remains the authority for ZG readiness; local NYQ issue closure is not a substitute.

The master remains open until #258 verifies mandatory core sampler, modulation, reconstruction, warp, cascade, rack, saved UI and export functionality. Explicitly unsupported optional combinations can remain unavailable; missing core functionality cannot be relabeled a limitation to close the chain. This acceptance does not certify external VST3 Phase B, ZG-024 research success, ZG-044/045 completion or a new preferred default sound.
