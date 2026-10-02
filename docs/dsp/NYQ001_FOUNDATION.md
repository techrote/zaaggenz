# NYQ-001 — frozen contract and integrated-clock foundation

Scope: #250 under #249. Contract family **1.0.0**; no audio kernel, rack
execution, product UI, delivery-rate change or factory/default promotion.
The source is `zaaggenz_contracts/{nyquismic,nyquismic_clock}.py`. This document
freezes the implemented foundation; the broader Nyquismic specification still
assigns audio kernels and instrument acceptance to #251–#258.

## Capability boundary

Implemented: immutable typed sonic/evaluation/identity/checkpoint data, strict
JSON decoding, complete-range validation, finite admission, exact piecewise
constant/linear-Hz phase integration, fractional event coordinates, explicit
source-time geometry, deterministic seed/cell addressing, and independent
analytic fixtures. `ClockPlan` is a clock calculator, **not an audio renderer**.

`SonicSpec.require_audio_execution()` always raises `UnsupportedNyquismic`,
including bypass, zero wet and empty cascades. `RackBoundary.require_execution()`
always rejects until #256. Unknown fields, versions, policies and implicit
migrations fail. No Nyquismic node/insert is registered in the existing DSP or
rack catalogue; no RenderRecipe, Project or MultibandRack schema is changed.
These standalone types are not an executable or opaque-preservation loophole
in those existing contracts.

The v1 declaration vocabulary includes ordered modulation routes, a nearest-Hz
rate ladder and counter-addressed jitter. Their *ranges and identities* are
validated, but `ClockSpec.require_geometry()` rejects them until #253, even a
zero-depth route or zero-amount non-`none` jitter model. There is no approximate
fallback. Source-pitch estimation, confidence-based substitution, sinusoidal or
audio-derived controls, prefilters other than `off_v1`, sinc/cubic reconstruction,
reverse/stopped playback, loop crossfade and nested cascades are unsupported.
A later child must explicitly version/extend capabilities, not silently ignore
one of these controls. A zero-depth route means its static effect, **not dry
identity**; today it is not yet an accepted executable route.

## Three clocks and immutable input

Virtual rates are artistic Hz, independent of numerical and delivery clocks.
`VirtualRate('1/3', 'ratio', RateReference('48000/1'))` resolves to exactly
16,000 Hz whether the evaluation policy says 48, 192 or 384 kHz. Absolute-Hz
rates have no reference. A ratio requires either stored Hz or an explicitly
resolved immutable control identity and Hz. `resolved_control` means a supplied
resolved value, not a live pitch detector: unresolved/abstained input must not
be disguised as this record. A future estimator must retain its requested,
resolved, confidence/abstention and method evidence in the bound upstream
control record. There is no automatic confidence fallback in this foundation.

`RenderIdentity` reuses the **existing immutable `AudioAssetRef` Contract**,
including its content domain/hash, source sample rate, frame count, channel
layout and level domain. The source rate is not inferred from delivery or
numerical rate. Capturing stored PCM does not recover absent source bandwidth;
`linear_v1` is the declared piecewise-linear source interpolation, not ideal
bandlimited reconstruction. Source/rack/graph/context revision identities are
separately mandatory. `bind_render_identity` checks source channel shape and a
first-stage playback map's source extent against the actual asset. Subsequent
cascade stage-input domains are #255's execution responsibility, not falsely
rebound to the original raw asset by this metadata helper.

## Authoritative event geometry

Within an epoch, with absolute physical origin `t0`:

```text
phi(t) = phi0 + integral[t0,t] f_virtual(u) du
capture k occurs at phi(t) = integer k
```

All stored seconds, rates, ratios and curve values use bounded rational `p/q`
strings. Constructor normalization reduces fractions only in this new family;
it does not relax the legacy rational validator. Integration, counts, epoch and
crossing IDs, ordering and half-open membership use exact `Fraction` arithmetic.
Linear interpolation integrates the **Hz** curve, not the period curve.
Automation `points_hz` are absolute Hz overrides, even when the initial rate was
given as a ratio. Each point lies strictly after the origin; the base value owns
the origin. Linear ramps begin at the preceding point (or the origin/base),
while step curves hold left values up to the next point and use right values at
that point. The final value holds after the last point.

Events belong to **[start, end)**. Phase zero captures at the origin. Nonzero
initial phase does not force an extra sample: the first next integer crossing
captures, with zero capture history beforehand. At an automation/reset tie,
right-continuous controls apply, then the reset establishes the new epoch/phase;
only that epoch's integer crossing can capture. A zero-phase reset replaces an
old coincident capture with exactly one new capture. A nonzero-phase reset
suppresses the old coincident crossing and retains the previous capture until
its next crossing. Resets do not reset input read position or jitter's absolute
cell field. There is no implicit reset at a chunk, region, sample or worker.

`ClockEvent(index, epoch, crossing, time_s)` has an absolute monotone event index
and epoch-local crossing ID. Rational roots convert directly to binary64;
irrational roots use the cancellation-safe quadratic inverse with a fresh
Decimal80 half-even context, then binary64. That approximate **display/capture
coordinate is not authoritative for endpoint membership**. Consumers must use
the exact phase/counter and interval queries for ties, not compare rounded
`time_s` against a rounded output-sample boundary. The method ID is
`exact_rational_piecewise_affine_decimal80_v1`.

A whole `ClockPlan` is admitted before allocating events. Region queries replay
that same absolute plan and return only their half-open interval; a small region
cannot evade that plan's full event budget. `events(cancelled=...)` checks at
segment boundaries and at most every 256 emitted events, raises `ClockCancelled`
and never returns truncated success. It does not publish an audio artifact.

Positive rate plus the maximum-rate bound guarantees minimum spacing within an
epoch. Across resets the previous/next event roots are checked before allocation.
Rational roots compare exactly; irrational roots receive 128-step rational
bisection enclosures. An insufficient **or unprovable** lower gap is rejected,
not sorted, coalesced or clamped. This conservative boundary may reject a value
indistinguishable from the minimum at that enclosure precision; it never admits
an unresolved subminimum spacing.

## Source time is a separate map

Sampler: `u(t) = t - clock.origin_s`. Varying capture spacing cannot alter this
map. Playback warp: `u(t) = source_origin_s + integral[origin,t] speed(v) dv`.
Speed is a dimensionless source-seconds/output-second ratio, positive throughout,
with its own step/linear physical-time curve. Capture frequency and playback
speed are independent. All modes retain the requested **output** extent; source
extent is not a new output length.

`source_time` computes coordinates only. Bounded sampler queries require the
actual `input_extent_s`; it is never guessed. Zero-pad returns `None` outside the
half-open source interval; edge-hold returns its endpoint coordinate, **not a
valid PCM array index**. Empty sampler input returns `None` even for edge-hold
because there is no edge sample. Unused overrides are errors. A playback map
stores its own positive source extent. Its zero-pad and edge-hold meanings are
the same. A loop projects onto `[loop_start, loop_end)` with exact modulo. The
source origin must start inside that loop; v1 has no implicit intro or crossfade.
Read distance and loop traversals are bounded even before a bounded-coordinate
query is requested. There is no source-read or audio implementation here.

The named `hold_v1` reconstruction declaration means right-continuous hold of
the last admitted capture. `linear_time_v1` means interpolation in physical time
between adjacent admitted captures, zero before the first and hold after the
last. It requires future/lookahead capture history within the **full render**
context; it does not invent a capture beyond that extent. Region context and
real audio histories are kernel/integration acceptance, not proved by these
clock-only fixtures. Tail policy is crop-to-output-extent, never normalization.

## Parameter reference and defaults

All enums/IDs are strings; flags are actual bools, not 0/1. Numeric mix/depth/
jitter fields reject bool, nonfinite and out-of-range values. Unknown fields or
missing fields in a saved snapshot fail; defaults apply only to constructors.
Rationals are reduced on construction; finite numeric values retain the existing
exact-number canonical identity rules. Tuples in typed constructors serialize
to JSON arrays. IDs are stable lower-case `[a-z][a-z0-9_.-]{0,63}`; labels are
Unicode strings up to 256 characters with the existing JSON surrogate checks.

| Record / fields | Units, domain and default; interpolation |
|---|---|
| `SonicSpec.version`, `mode`, `instance_id`, `label` | `1.0.0`; sampler/playback_warp/cascade (default sampler); stable ID `nyquismic`; display label empty. Not automatable. |
| `VirtualRate.value`, `unit`, `reference` | Positive rational Hz or ratio; default `11730/1`, `Hz`, null. Ratio needs a `RateReference`; resolved rate obeys the hard Hz bounds. |
| `RateReference.hz`, `kind`, `control_id`, `control_sha256` | Rational Hz default `48000/1`; stored_hz default has null control fields; resolved_control requires stable control ID and SHA-256. No implicit reference to an evaluation/export rate. |
| `ClockSpec.rate`, `origin_s`, `phase_cycles` | Default VirtualRate above; origin `0/1` seconds; phase `0/1` cycles, domain [0,1). |
| `Point.time_s`, `value`; `points_hz`, `interpolation` | Required rational seconds/value; Hz curve default empty, step. Step/linear only; base at origin, strictly ordered points after it, endpoint values in the complete valid range. |
| `Reset.time_s`, `phase_cycles`; `ClockSpec.resets` | Absolute seconds and [0,1) cycles; default phase zero, no resets. Strictly increasing times after origin. Phase reset retains capture history. |
| `ModulationRoute.id`, `mapping`, `depth`, `initial`, `points`, `interpolation` | ID route; mapping add_hz; depth 0 Hz (range ±1,536,000) or log2_ratio depth 0 octaves (±16); normalized rational initial 0 and points in [-1,1]; empty points, step/linear. Saved ordered route list defaults empty. Geometry still unavailable before #253. |
| `RateQuantizer.policy`, `levels_hz`, `tie`, `switching` | Default none, empty ladder, lower tie, step switching. nearest_hz requires an ascending unique rational Hz ladder. No hysteresis/smoothing is implied. |
| `JitterSpec.model`, `amount`, `cell_s`, `seed`, `stream` | Default none, 0 fractional-frequency amount, `1/1000` second cells, unsigned decimal-u64 seed `0`, stream clock. uniform_frequency_cells_v1 amount [0,.25]; cell duration [minimum spacing, 3600] seconds. none requires zero amount. |
| `ClockSpec.invalid_policy`, `order` | Only reject; only base-automation-routes-quantizer-jitter. No unnamed clamp. |
| `PlaybackMap.source_origin_s`, `speed`, `speed_points`, `interpolation` | Source seconds 0; speed 1 source-second/output-second, [1/64,64]; empty points, step/linear. Points after clock origin, complete speed range validated. |
| `PlaybackMap.source_extent_s`, `boundary` | Positive source seconds, default 1; zero_pad default, edge_hold or loop. |
| `loop_start_s`, `loop_end_s`, `loop_crossfade_s` | Source seconds, default 0, 1, 0. Valid bounded loop with start < end; only zero crossfade. Inactive loop coordinates retain defaults. |
| `SonicSpec.clock`, `playback`, `stages` | Sampler requires clock/no playback; warp requires both; cascade has neither and has an ordered tuple of 0–3 non-cascade stages. Stable IDs unique including parent. Empty cascade declares boundary identity but still cannot execute yet. |
| `capture`, `prefilter`, `reconstruction` | Defaults linear_v1, off_v1, hold_v1. Other declared capture: nearest_left_tie_v1; reconstruction: linear_time_v1. No other prefilter. These name sonic models, not an accepted audio implementation. |
| `channels`, `stereo_link`, `clock_group` | Integer 1 (mono) or 2 (stereo); linked default, or independent; optional shared clock ID defaults null. Shared groups must agree on clock and channel policies. |
| `wet`, `bypass` | Ratio [0,1], default 1; bool false. No automation accepted for these fields in v1. Neither bypass nor zero wet skips validation. |
| `bus`, `band`, `placement`, `confine_delta` | SYNTHLINE only; band null or sub/lowmid/highmid/air; post_source_pre_master only; confinement true. Spectral sub is not the separate SUB stem. No rack execution implied. |
| `input_boundary`, `initial_capture`, `tail`, `reset_history` | Defaults zero_pad (or edge_hold), crossing_only_zero_until_first, crop_to_output_extent, retain_capture. Other values fail. Inactive cascade clock/kernel fields retain canonical defaults. |
| `EvaluationPolicy.version`, `evaluation_rate_hz` | 1.0.0; numerical Hz integer 192000 default, range 8000–3072000. This is a planned evaluation domain, not newly enabled delivery rates. |
| `clock_method`, `audio_method`, `numerical_filter` | Clock method above; audio_method and numerical_filter are explicitly unavailable_nyq001. No pretend filter/renderer identifier. |
| `reference_rates_hz`, `budget` | Default empty tuple; bounded strictly increasing numerical Hz above the base; ResourceBudget defaults below. Passes are requested identities, not measured convergence. |
| `RenderIdentity` | Existing AudioAssetRef plus sonic/source/rack/graph/context SHA-256 identities; EvaluationPolicy; delivery Hz [8000,192000] default 48000; channel count; rational [start,end] coordinate bounds default [0,1], half-open output; version 1.0.0. Identity is planned, not artifact success. |
| `RackBoundary.spec`, revision hashes, `anchor_instance_id`, `side` | Typed SonicSpec, source revision/rack sonic hashes, accepted stable anchor ID, before/after (default after). Always rejects execution pending #256. |

Ordered modulation applies `f += depth_hz * control` or
`f *= 2**(depth_octaves * control)`. Every intermediate full range must be positive
and bounded. Admission does not assume correlations between routes. Log2 range
validation uses a conservative integer-octave envelope (floor lower exponent,
ceil upper exponent), so it cannot understate a floating exp2 extreme. Then the
rate ladder applies, then bounded frequency jitter. This is a named, frozen
ordering, not a claim that those kernels have run.

## Frozen finite resource limits

| Quantity | Hard limit / default budget |
|---|---|
| Instantaneous virtual rate | 1/1000 through 1,536,000 Hz inclusive |
| Minimum consecutive event spacing | 1/1,536,000 seconds, including resets |
| Absolute clock/output/control time | 0 through 3600 seconds; extent after origin |
| Reduced input rational | absolute numerator ≤ 9,999,999,999,999; denominator ≤ 1,000,000,000; raw spelling also bounded |
| Exact integrated phase numerator/denominator | 32,768 bits each; checked during integration |
| Sonic JSON | 65,536 UTF-8 bytes, also subject to existing JSON depth/node/string/2 MB limits |
| Capture events | 1,000,000 per admitted plan and aggregate stage/independent-channel budget |
| Nodes / ordered cascade stages | 128 nodes / 3 child stages; no nested cascade |
| Clock control points / resets / routes | 256 per curve / 256 resets / 16 ordered routes per clock |
| Rate ladder | 64 strictly increasing positive Hz entries |
| Declared filter support ceiling | 4096 taps; no such FIR kernel enabled in NYQ-001 |
| Source extent/read distance | 86,400 source seconds |
| Loop traversals | 1,000,000; loop width at least minimum event spacing |
| Numerical rate / resident numerical sample values | 3,072,000 Hz / 16,777,216 frame-channel values per pass |
| Additional reference passes | 4, with strictly increasing rates |

`ResourceBudget` can reduce max_events, max_frames, max_nodes, max_read_s,
max_filter_taps or max_reference_passes; it cannot raise a hard cap. Frame
admission includes channels and the largest delivery/evaluation/reference rate;
the finite pass count bounds total work. Cascade/shared clocks are conservatively
counted per stage, not discounted because sharing might later be optimized.
No CPU benchmark, latency target, realtime throughput gate or private runner is
introduced. These limits are admission rules, not a product duration promise.

## Randomness, state and identity

`event_seed` addresses (root seed, named stream, stable instance or explicit clock
group, epoch, absolute crossing, channel). Linked stereo uses channel zero;
independent stereo uses its actual channel. `clock_cell_value` addresses the
physical cell `floor((t-origin)/cell_s)` instead of an evaluation sample or event.
The jitter field is not rewound by a phase reset. Reordering preserves instance
IDs; duplication must use a new ID unless an explicit consistent clock group is
shared. No global PRNG cursor, chunk number, worker ID or evaluation rate is used.

Both functions use the existing tagged canonical serializer and SHA-256, with
separate `zaaggenz.nyquismic.event-seed.v1` / `zaaggenz.nyquismic.clock-cell.v1`
domain fields. The first 64 bits are big-endian. The uniform cell value is the
exact rational `(2*word + 1 - 2**64)/2**64`, lying strictly between -1 and 1.
Independent stdlib-derived known answers for root 0, stream clock, instance
nyquismic, channel 0: epoch/crossing 0 gives seed **14390279435749162811**;
cell 0 gives **-9124178743656200821/18446744073709551616**.

`ClockCheckpoint` version 1.0.0 stores clock SHA-256, absolute rational time,
epoch, next crossing, events strictly before that time, reduced phase numerator/
denominator as bounded canonical lowercase hex, and clock method ID. It is after
controls/resets but **before capture at its time**. Restore recomputes every field
and rejects foreign, stale or tampered state; it can resume a longer plan with
identical clock specification. It is deliberately **clock-only**.
`require_audio_restore()` rejects: actual capture/filter/readhead/cascade histories
and their numerical-policy/source binding belong to the relevant kernel child.

Every type supports strict JSON round-trip. `canonical_bytes()` exposes the
existing tagged exact-number canonical serialization (not RFC 8785/JCS).
`to_json()` is sorted portable snapshot JSON, not a new competing numeric
canonicalization. Full snapshot SHA includes labels. Sonic SHA excludes only
SonicSpec display labels recursively and includes latent bypassed settings,
ordered stages/routes and all sonic policy fields. Evaluation is a separate
record and cannot change sonic identity. Render SHA includes actual planned
evaluation method/rate/filter policy, immutable asset metadata and content,
source/rack/graph/context revisions, channels, region and delivery rate. It is
not proof of render completion or a cache publication authorization.

Default 1.0.0 identity goldens (these opt-in defaults do not change any factory
preset): sonic `08dcb6d3a9ddee94afba399d2a96a3f51e7252016031727af123953f6cb42921`;
full snapshot `b0ce639296a721e1fe33aab841b632d5a3dbc4acfdaf836f45cc1f4995f44f53`;
evaluation `c065ec529fd9a061ed5e77e64deb315c58d3e7d54d36b5f295d0a46a384ee044`. The executable tests freeze all three.

## Frozen independent fixtures and reproducibility

`tests/contracts/nyquismic_oracles.py` imports no production code. Constant times
use independent rational `k/f`; ramp times use a Decimal80 analytic quadratic
formula, with an independent 260-step Decimal80 bisection check for tiny slopes.
Step/reset examples are hand-derived piecewise integrals. Static alias locations
are exact rational folding, additionally checked by analytic discrete sine values.
These static aliases are **not** a nonuniform reconstruction/audio measurement.

The generator and oracle data were frozen before production comparisons:

| File | SHA-256 |
|---|---|
| `tests/contracts/nyquismic_oracles.py` | `c700d12382ca1d55402f37d86376f5d625d44ed37cdedccdb21474519785c8b2` |
| `tests/contracts/fixtures/nyquismic-v1.json` | `b42b2d9988df822169d8fd6e02a28dd208eff2b1e0ddf4a2d15df13c6c9ee5bd` |
| `tests/contracts/fixtures/nyquismic-legacy-anchors-v1.json` | `a0717357a33a5f88e398ec9b5a8c524d2d3e60782a4bfa1369f3336ebf977b18` |

Frozen timing tolerance: **2e-12 seconds + 8 ulps of the absolute timestamp**.
Counts, epoch/crossing IDs, half-open membership, exact rational phases, canonical
hashes and seed/cell values have **zero tolerance**. The 2 ps allowance is below
0.000004 of the minimum spacing; the ulp term covers bounded absolute-time
binary64 representation. It was not fitted to a winning renderer. Do not infer
bitwise cross-platform audio equality: there is no NYQ audio evidence here.

Legacy anchors are separately labelled a baseline snapshot, **not an independent
new DSP oracle**. They pin old example contract/schema identities, every original
factory recipe, 12/48 kHz empty rack sonic identities, bitcrusher defaults and
unchanged AA 1/2/4/8 metadata. Existing real-audio legacy/rack suites remain the
compatibility gates; new clock tests do not replace them.

## CI ownership, commands and next boundary

The existing unfiltered `zg002-contracts.yml` Ubuntu/Windows jobs discover
`tests/contracts/test_nyquismic.py` through `tools/check_contracts.py`. Checkout is
bound to the exact PR head, matrix concurrency is two, no extra workflow is added.
`programme/ci_reverse_dependencies.json` explicitly maps the two modules through
the existing contracts owner ZG-002, plus the Nyquismic test, oracle generator and
`tests/contracts/fixtures/nyquismic*.json`. The impact trigger includes those
non-package paths, and its regression test verifies downstream selection and no
duplicate native ZG-002 dispatch. Documentation is checked in this focused PR by
the same unfiltered contract gate; documentation-only edits do not create product
reverse-dependency fanout.

```sh
python baseline/recovered_source/materialize_v2.py --out .
# Use PYTHONPATH=app:. on POSIX (app;. on Windows), numerical threads = 1.
python -m unittest discover -s tests/contracts -p test_nyquismic.py -v
python -m unittest discover -s tests/rack -v
python tools/check_contracts.py --baseline --report contracts-check.json
python tools/ci_reverse_dependencies.py --validate
python -m unittest discover -s tests/programme -p test_ci_reverse_dependencies.py -v
```

Tests cover analytic constant/ramp/step/reset/alias fixtures, fractional and
near-integer rates, independent tiny-slope bisection, random rational clocks,
region/checkpoint partitioning, cancellation, explicit source maps, strict
round-trip and canonical/sonic/render identities, source metadata binding,
seed/group/channel invariance, invalid values/unknown automation/policies,
complete modulation-range admission and resource limits, preserved legacy
anchors and the closed graph/rack execution boundary.

Reconciled base: `b76d22df189d176ea371e14e2fb0eff74cd2f7af`, exact recovered tree
`b8b0a4af92fb15bb2bf367bb46e681e30400f789`; #259 and #248 are merged. #240 owns
runtime/render/API/export and remains separate. Local environment: Python
3.13.5, NumPy 2.3.5, SciPy 1.17.0, jsonschema 4.26.0, referencing 0.37.0,
threadpoolctl 3.6.0, numerical threads bounded to one. Exact PR-head CI and a
verified merge remain the acceptance authority, not this source-level record.
Only after #250 acceptance may #251 add the actual fractional-event audio sampler
using this clock authority and these oracles. #256 still owns a future typed rack
schema extension after its separate kernel and MBR Phase-A prerequisites.
