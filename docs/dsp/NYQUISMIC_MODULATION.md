# Nyquismic Modulation — implementation specification

**Owner-approved name:** Nyquismic Modulation  
**Technical description:** modulated virtual sampling lattice / virtual sample clock  
**Master:** [NYQ-000 / #249](https://github.com/techrote/zaaggenz/issues/249)  
**Status:** implementation scope approved; this document is a specification, not evidence that the feature exists.  
**Planning snapshot:** 2026-10-02, main `2dc6390b6f134c897170b8b0bf88fdffe328e373`.

Read [implementation RAG](../zaaggenz/NYQUISMIC_IMPLEMENTATION_RAG.md) for the issue chain, ownership and kickoff; read [validation](NYQUISMIC_VALIDATION.md) for independent oracles and acceptance. Live accepted code/contracts remain authoritative. No runtime behavior, factory sound, default or canonical programme readiness is changed by this document.

## Purpose and product boundary

The owner proposed optionally modulating sample-rate behavior to create distinctive distortions, including non-integer ratios and deliberately imperfect resampling, analogous to amplitude bitcrushing. The agreed name is **Nyquismic Modulation**. The earlier spelling `nyquizmic` is only a retrieval alias, not a separate feature.

ZaagGenZ is primarily an offline synthesizer: there is no hard realtime, low-latency or processing-efficiency requirement for this feature. Faithful evaluation, useful artistic control, inspectability and reproducibility take priority. Finite admission budgets, bounded reference passes, progress, cancellation and atomic artifact publication still apply for correctness and resource safety. Do not turn those safeguards into an unnecessary realtime throughput gate.

Deliver a native opt-in DSP family in the ordinary Compose instrument and editable per-band rack. Support static and modulated virtual sampling, rate quantization, seeded clock jitter, explicit source-read-clock warping, and ordered damage cascades. Preserve the existing bitcrusher as a separate amplitude-quantization stage. No mandatory Research workflow, ML/GPU/cloud service or third-party plug-in is needed.

## Three separate clock authorities

| Quantity | Meaning | Identity and modulation rule |
|---|---|---|
| Delivery rate | Uniform PCM sample rate of the final artifact | Stored export/output setting; never varied inside a WAV/FLAC stream |
| Numerical evaluation rate | How accurately the DSP/continuous-time approximation is evaluated | Versioned render-quality policy, fixed for a pass; not a sonic modulation destination |
| Virtual rate | Artistic capture/reconstruction event clock inside the effect | Explicit positive Hz or a ratio to an explicitly stored reference; freely modulated within the accepted contract |

The immutable input asset also has a source rate and a declared interpolation/bandwidth model. Upsampling it does not recover information absent from the source.

Example, not a mandatory product default: a 48 kHz delivery may use a 384 kHz numerical domain while simulating an 11,730 Hz capture clock. A virtual ratio of `1/3` to a saved `48,000 Hz` reference means `16,000 Hz`; it must not become `128,000 Hz` when numerical evaluation moves to 384 kHz. Exporting the same sound at another supported rate must not silently change the artistic reference.

For explicitly source-pitch-locked clocks, save the reference source/control identity, requested/resolved frequency, phase and confidence/abstention semantics. No hidden pitch estimation or substitution. An intentionally output-rate-relative mode, if ever supported, is a separate declared sonic policy and cannot claim output-rate invariance.

## Continuous clock and capture semantics

Use physical time `t` and a positive finite instantaneous virtual rate `f_v(t)`:

```text
phi(t) = phi0 + integral from t0 to t of f_v(u) du
capture events occur at the declared integer crossings of phi
s_k = capture_interpolator(prefiltered_input, t_k)
```

NYQ-001 must freeze event origin, first capture, half-open interval conventions, endpoint and coincident-control/reset ordering, numerical precision, supported parameter bounds and invalid-request policy. The phase model above is the authority. `t_next = t + 1/f_v(t)` is only an approximation when rate changes within an interval, not the definition of a fast-modulated clock.

Use fractional event times. Do not implement arbitrary rates as `round(F_eval/f_v)` samples of hold, round events to block boundaries, reset phase at every chunk, or silently miss multiple crossings. A deliberately coarse capture grid is permissible only as a separately named artistic policy with a saved reference grid. Event scheduling must remain monotone and bounded; invalid clocks cannot be repaired by sorting event times.

For hold reconstruction:

```text
y(t) = s_k for t_k <= t < t_(k+1)
```

Time-aware linear/cubic reconstruction uses actual event spacing, not an assumed uniform grid. Lookahead is acceptable offline but must be declared and included in state/support. Sampling/holding at changing capture times can generate modulation artifacts; it does not by itself define an accumulated varispeed playback head.

## Sampler, playback warp and cascade modes

**Sampler** preserves the project/source timebase and requested output extent. It captures the input at the virtual events and reconstructs onto the stable output timeline. This is the direct sample-rate-reduction/time-resolution axis.

**Playback Warp** adds a distinct source read-time map:

```text
u(t) = u0 + integral from t0 to t of speed(v) dv
warped_input(t) = input_interpolator(input, u(t))
```

A constant `speed=2` traverses source time twice as fast. The first implementation is a fixed-output-extent effect with explicit zero-pad, edge-hold or bounded-loop source-boundary policy. Loop boundaries/crossfades, source origin and capture/read-clock coupling are sonic settings. Reverse/zero speed require their own tested capability or fail explicitly. No hidden global tempo change, timeline stretch, note displacement or automatic output-length alteration. Whole-asset length-changing varispeed is separate future scope.

**Cascade** is an ordered composition of accepted virtual stages, not a new project clock. Require at least three independently configured stages. For example: virtual `13,700 -> 51,200 -> 9,300 Hz` with explicit reconstruction at each stage, ending in the selected delivery format. Upward as well as downward virtual transitions may be useful because prior reconstruction images and later nonlinear operations interact. Stable instance IDs, seeds, bypass, order and clock-link groups survive editing.

Do not algebraically cancel two rate changes or fuse away an artistic intermediate reconstruction. Conversely, do not insert hidden delivery-band filtering at every stage. Numerical conversion boundaries and creative filter boundaries are different decisions.

## Capture interpolation, prefilter and reconstruction

Keep these independent in both the contract and UI:

| Stage | Required design choices | Important boundary |
|---|---|---|
| Capture interpolation | Accurate fractional source evaluation and an explicitly coarse nearest option | Controls how the existing source is sampled at event times |
| Virtual prefilter | Off, explicitly specified finite low-pass/strength, guarded clean comparison | Acts before intentional sampling aliases form |
| Virtual reconstruction | Hold, nearest, time-aware linear, bounded-support cubic, windowed-sinc with truthful capabilities | Controls the waveform/images generated from event samples |
| Final numerical conversion | Pinned high-quality reconstruction/anti-alias conversion to delivery rate | Prevents unintended evaluation-clock artifacts; not a hidden 'remove all Nyquismic aliases' stage |

Every advertised kernel has a concrete method/version, support/window, frequency/phase response, gain, padding and latency convention. Short/weak/ringing variants must be actual controlled kernel settings, not empty enum labels. Minimum-phase/asymmetric variants can be added only with a separately tested implementation; they are not implied by calling a filter 'dirty'.

A uniform-grid sinc is not automatically an ideal reconstructor for irregular timestamps. Uniform-only windowed-sinc is allowed as an explicit limited capability; selecting it with an unsupported modulated clock must fail. A nonuniform reconstruction policy needs its own derivation/normalization and independent tests, and must be named as an approximation unless a stronger claim is proved. Modulated prefilter tracking similarly needs defined smoothing/state and measured limits.

For a uniform virtual clock, aliases fold around multiples of its rate and the usual Nyquist boundary is useful. An irregular/modulated clock does not have a universal single instantaneous Nyquist theorem. A display of `f_v(t)/2` is a local guide, not a guarantee of recoverability or alias-free operation. Post-filtering may attenuate components but cannot generally undo information already folded into the passband.

Linear/cubic/sinc variants change frequency response and may introduce lookahead, ringing or overshoot. Record those properties and retain finite headroom behavior; do not silently normalize, limit or clip them. Zero-wet and bypass bypass the entire filter path after validation.

## Modulation and rate quantization

NYQ-001 freezes exact field names, numerical bounds and capability declarations; the following are required semantic groups, not an already accepted public API:

| Group | Required contents |
|---|---|
| Virtual rate | Absolute Hz or normalized ratio plus stored reference; positive admitted range |
| Rate modulation | Free-Hz/beat-sync LFO, envelope, step events, explicitly bounded audio-rate control |
| Mapping | Additive-Hz versus logarithmic/octave depth, polarity, route combination order, declared clamp/reject policy |
| Rate ladder | Finite Hz/ratio set, canonical rational encoding, tie rule, switching interpolation and optional hysteresis |
| Jitter | Named model, amount and units, distribution, bandwidth/correlation, seed/stream and minimum spacing |
| Phase/state | Continuous/per-note/explicit reset, origin, event ordering and serialized checkpoint version |
| Channel/clock links | Mono/stereo and inter-band linked/independent groups using stable IDs |
| Derived modulation | Declared upstream input/envelope/transient or immutable feature source, support time and fallback |
| Playback Warp | Read-speed map, source origin, boundary/loop/crossfade semantics |
| Cascade | Ordered stable stage IDs, per-stage settings, shared clock policy and finite stage budget |
| Mix/placement | Wet, bypass, bus/band, confinement/spill, pre/post stage location |
| Numerical policy | Evaluation domain, method/filter version, finite quality/reference plan, reported outcome |

Ratios such as `1/3, 2/5, 3/7, 5/11, 7/13` are useful test/user choices, not inherently better or more distorted ratios. Canonicalize fractions and bound denominator/list sizes. Quantization/smoothing order matters and is saved. A requested abrupt step remains abrupt unless a named smoothing policy is chosen.

Seeded clock jitter is not additive audio dither. Use stable event identities or a pinned physical-time stochastic field so chunking, worker order, evaluation-rate changes or label edits do not create a different performance. A bounded fractional-frequency noise model is a straightforward positive-clock option; interval jitter is a distinct model with explicit units and monotonicity rules. Zero input should remain zero unless an independently enabled audio-noise stage is present.

Input-dependent controls may consume the node's declared upstream input or a named pre-effect band tap. Cross-band routing must stay acyclic. Post-node self-dependent rate control and implicit algebraic feedback are out of scope; no unbounded solver. Reuse existing feature/detector machinery where suitable, pin source/method hashes, and respect feature support/latency/confidence. Spectral-centroid control is only advertised when actually implemented; missing or stale features cannot silently become a different modulation source.

## Accurate intentional damage

A non-integer or awkward rational conversion ratio is not inherently low quality. A well-designed converter can handle such ratios accurately [R1]. The artistic artifacts come from the selected aliasing/prefilter/reconstruction policy, the actual rate relative to source partials, clock modulation, and processing order. Do not claim prime denominators confer special sound by themselves.

The quality objective is **faithful evaluation of the saved dirty model**, not removal of all out-of-harmonic energy. Preserve deliberate virtual-clock aliases and reconstruction images while reducing accidental numerical folding, event-time quantization and implementation errors.

Use local high-rate domains where appropriate. Values such as 192/384/768 kHz and higher bounded comparators are candidate evaluation settings, not an automatic global default. Group adjacent operations when that preserves their intended intermediate waveform. Apply one final suitable conversion at a numerical-domain boundary rather than repeated unnecessary round trips; never erase intentional intermediate filtering/reconstruction.

Do not universally omit oscillator components above the final export Nyquist before nonlinear processing: higher components may mix back into the audible band. Preserve musically relevant intermediate bandwidth according to the local model, then filter at the correct boundary. Existing opaque source renderers remain opaque unless accepted code exposes a real tap; upsampling accepted source PCM cannot recreate discarded source information.

Optional convergence checking holds source representation, virtual event schedule, artistic kernels, modulation and jitter realization fixed while increasing numerical accuracy. Use independent analytic cases plus aligned waveform, spectral and transient error tests. Freeze candidate sequence, thresholds and maximum passes before comparison. Record the actual selected result/rate and converged/inconclusive/failure outcome. A higher-rate render is a comparator, not ground truth merely because its rate is higher. No indefinite retries, silent lower-quality success or global normalization to conceal differences.

The earlier general discussion of moving all ZaagGenZ quality defaults to 8x/16x is not authorized here. Existing `core.tanh.v1`, `core.hard_clip.v1`, AA policies and accepted preset rendering are unchanged; see [ZG-019 ADR](ZG019_ANTIALIAS_ADR.md). Broad quality/default/output-rate migration is separate scope.

## Graph, rack, source and output ownership

Reuse the accepted typed registry, graph, Project/RenderRecipe, RuntimeSession, JobScheduler, band executor and effect-delta router. The existing integer `hold_samples` bitcrusher remains unchanged; extend with a new versioned Nyquismic family rather than redefining old records.

The initial ordinary route is explicitly post-source/SYNTHLINE before the existing final master, with per-band inserts in the accepted four-band rack. Whole-mix placement requires an explicit saved declaration. Preserve BODY/AUX/SUB/SCULPT ownership and the complete SYNTHLINE; the spectral `sub` band is not the independent SUB stem.

Integration must extend the actual accepted MBR rack contract, preserving the old four stage anchors and all 24 permutations. Do not claim a frozen four-stage schema already supports arbitrary new kinds. Use explicit versioning/migration and truthful capability checks.

For each processed band, align implementation delay/lookahead with its original band before subtracting the effect delta. Preserve intentional playback warp rather than delay-compensating the creative effect away. Re-confine only the declared delta; transition-band leakage is measured, not called mathematically zero. Confinement remains the default, deliberate spill is explicit. See [ZG-021](ZG021_BAND_SELECTIVE_DSP.md).

All-disabled, empty-cascade and wet-zero are exact node/rack-boundary identities. Zero modulation depth reproduces the static chosen effect, not necessarily identity. Equal virtual/output rates alone do not prove identity unless capture phase, reconstruction, boundary and filter assumptions also hold. No hidden normalization, extra final master, or monitor-only solo/A-B compensation leaking into exports.

## Persistence, previews and bounds

Save complete sonic intent separately from display labels and numerical execution evidence. Cache identity includes source, node/rack/route/feature revisions, all sonic controls and numerical method/filter/evaluation settings. Changing quality changes the rendered artifact identity without silently changing the artistic recipe.

State covers integrated clock phase, event index, prior captures, jitter field/stream position, filter histories/support, read-head/loop position and cascade state. A region preview needs valid checkpoint/pre-roll/post-roll context. Starting every preview with a fresh clock is not equivalent to a full render. Record method-specific exact versus tolerance-based guarantees, and disclose contextual work without imposing a realtime limit.

Validate event counts, minimum spacing, source-read extent, rate-set sizes, cascade/route counts, kernel support, finite representability and quality-pass budgets before allocation where possible. Runtime violations fail atomically. Never coerce NaN/Inf into plausible PCM. Preserve the last coherent project/audio when a newer job is cancelled, stale, invalid, unconverged or fails.

WAV/FLAC are lossless delivery targets where supported by the accepted export path; numerical processing uses the accepted floating-point/output policy. Do not dither, requantize or run the master repeatedly between stages. Exports must come from the exact saved/audible revision, with any final representation conversion disclosed.

## Implementation and acceptance boundary

[NYQ-001 #250](https://github.com/techrote/zaaggenz/issues/250) starts with executable contracts/oracles; #251–#255 implement DSP; #256 integrates the accepted rack; #257 implements ordinary UI; #258 owns final numerical/Windows/workflow acceptance. #256 additionally requires accepted [MBR Phase A #242](https://github.com/techrote/zaaggenz/issues/242), not merely a closed issue. Core DSP need not wait for the rack. External VST3 Phase B and ZG-024 are not dependencies.

Named lossless demonstration renders and specific owner feedback are useful. Numerical correctness is not evidence of preferred sound, cultural authenticity or musical superiority. Existing factory sounds and owner approval/default-selection authority remain protected. No compulsory new ratings, human study or preset audition campaign is introduced.

## Primary references and limitations

[R1] SciPy, `resample_poly`: https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.resample_poly.html — rational polyphase conversion, FIR/window and boundary behavior. This API has fixed integer up/down factors; it is not by itself a variable-clock event solver.

[R2] SciPy, `upfirdn`: https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.upfirdn.html — explicit upsample/filter/downsample primitives and boundary modes. Reuse must follow the pinned installed version and actual kernel contract.

[R3] Native Instruments, BITE manual: https://docs.native-instruments.com/ni-tech-manuals/crush-pack-manual/en/bite — existing sample-rate reduction, jitter and filtering provide prior art. Nyquismic is a product name/integration scope, not a claim to invent those mechanisms; no proprietary code is implied or licensed by this reference.

[R4] Pablo Martinez-Nuevo, *Nonuniform Sampling Rate Conversion: An Efficient Approach*: https://arxiv.org/abs/2105.06700 — primary technical reference for time-varying/nonuniform conversion. It does not automatically validate arbitrary creative kernels, clock processes or their inverse reconstruction.

References checked 2026-10-02. Pin actual dependencies/licences during implementation; do not infer an implementation licence or a supported capability from a paper/manual citation alone.
