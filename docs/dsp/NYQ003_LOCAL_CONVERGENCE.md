# NYQ-003 isolated local numerical convergence evaluator

Status: **opt-in component on draft PR #266**. No production
`SamplerPlan`, rack graph, preview, waveform export or main/legacy
setting is changed. This does not close NYQ-003.

`FrozenConvergencePolicy` (`nyq.local-frozen-rate-convergence.v1`)
stores an explicit, increasing 3–4 evaluation-rate sequence (default
192/384/768 kHz) and three finite numerical tolerances, independently
of the sonic virtual rate, capture/reconstruction method and delivery
rate. The callback produces complete post-artistic-DSP numerical PCM
and declares fixed immutable source, sonic request, virtual-clock
and stochastic-control hashes for **every** comparator. It must truly
use the identical source, event realization, seed and sonic model at
each rate; caller identity assertions are not a substitute for a future
independent event/fixture oracle.

Every candidate has exactly the same physical-time extent. After all
sonic processing, the existing explicit `nyq.polyphase-delivery-kaiser10-24lobes.v1`
conversion applies the same final 48 kHz (or declared delivery) output
rate. No pre-trimming of nonlinear source frequencies is introduced.
Passes are bounded by the existing four-reference-pass limit, each
source/output by the normal finite frame/tap budgets, and cancellation
is tested before candidates, conversions, comparisons and publication.
Candidate PCM is copied into one private, bounded snapshot **before**
finite-sample validation and delivery conversion: an external cancellation
callback cannot substitute different samples in a caller-owned array after
validation while retaining the declared source/sonic identity. The copied
snapshot is numerical isolation, **not** independent verification that the
renderer honored its advertised clock and source hashes.

The result reports all exact rates, delivery filter method/coefficient
hashes and three independent *relative* successive-pass metrics:
time-domain RMS residual, delivery-band magnitude-spectrum residual
and first-difference/transient residual. Two consecutive adjacent
comparisons across **three distinct rates** must each pass all limits.
Output is only returned when nontrivial numerical agreement is achieved.
A completely silent pair has exactly zero measured residuals, but exercises
no clock or reconstruction discrimination: it is reported as
`null_signal=true`, `within_limits=false` and is **inconclusive** even
when all three numerical rates return identical silence. Empty extents are
also inconclusive. A comparison with **one delivery frame** is likewise
`insufficient_extent=true` / `within_limits=false`: it has only a single-bin
FFT and no first difference, so a copied RMS transient diagnostic cannot
count as an independent third metric. The measurement values remain available
for investigation, but such a short render cannot be certified as converged.
Likewise, an exactly constant, nonzero delivery channel has no independent
transient measurement: its first-difference norm is zero at both rates,
and its magnitude spectrum has only a DC bin. The evaluator now reports
`no_transient_evidence_channels` and refuses whole-result qualification
if any channel has no transient information at either rate; it preserves
all zero residual diagnostics. This conservative limit is not a rejection
of DC as a valid audio signal or an analytic DC-gain measurement. It is a
refusal to treat redundant comparison numbers as three independent local
convergence witnesses.
No arbitrary minimum loudness threshold is imposed on
quiet but nonzero signals. Each comparator is now scaled independently per **physical channel**,
using the larger absolute PCM amplitude of the two compared rates within
that channel. Each of the RMS, independent-channel magnitude-spectrum
and transient residuals reports the *worst* relative channel error; a loud
left channel cannot hide a lost, phase-shifted or attenuated quiet right
channel. This also prevents the squared RMS of a 1e-250 quiet channel
underflowing when a louder channel is present. There is no absolute epsilon
denominator: when a channel's reference norm is exactly zero but the
residual is nonzero, the finite diagnostic identifies the affected channel
in `zero_reference_metrics` and refuses convergence, even at tolerance 1.0.
Otherwise the explicit status is `inconclusive`
and `selected_audio=None`; malformed candidate, rate, hash, extent,
nonfinite data or budget is a hard failure before publication.

**Limit:** agreement across multiple evaluation rates does *not*
prove the same underlying dirty clock model, analytic truth, perceptual
fitness or correct product export; two wrong calculations can agree.
The diagnostics explicitly report `analytic_oracle_verified=false`
and `product_export_verified=false`. NYQ-003 acceptance still requires
frozen independent folding/imaging/transient fixtures, actual
local-to-sampler integration, versioned thresholds grounded in quality
evidence, failure cases, final-head CI and owner-dependent gates.

Focused test:
`python -m unittest discover -s tests/dsp -p 'test_nyquismic_convergence.py' -v`.

## Real physical-event sampler convergence bridge — 9 November 2026

The opt-in `evaluate_sampler_convergence` executes NYQ-002's actual immutable
source capture and reconstruction separately at every frozen numerical rate.
It verifies exact Fraction/Decimal80 virtual-event coordinates with epoch and
crossing against the first pass, rather than accepting only a caller-supplied
clock hash. Original input PCM, per-pass numerical PCM and final delivered PCM
identities are included in the diagnostic record. The downstream comparator's
existing RMS, spectral and transient thresholds and inconclusive/null policies
remain unchanged.

Unsupported external NYQ-004 control adapters and warp/cascade refuse.
Source extent must align to integral frames at **all** evaluated rates;
frame/tap/reference budgets and cancellation are enforced before publication.
The current sampler still binds the delivery rate to the immutable source rate.
This is local numerical evaluation, not product-export, analytic-oracle,
quality-default, or human listening admission. Nothing alters the existing
sampler, clock, renderer, graph or default sound.

Focused command:
`python -m unittest discover -s tests/dsp -p 'test_nyquismic_sampler_convergence.py' -v`

## One authoritative sampler comparator and finite-pass budget (9 November 2026)

`evaluate_sampler_convergence` is the authoritative real-sampler numerical
bridge. The older `evaluate_sampler_model_convergence` now delegates to it
rather than issuing a second, differently hashed physical-event qualification.
The old call surface only accepts a delivery rate matching the original
immutable source rate, consistent with the current SamplerPlan identity.
`ResourceBudget.max_reference_passes` is now enforced by the generic
callback evaluator before any numerical candidate runs; both sampler
entrypoints share the same strict preflight. This is a correctness/coordination
repair, not a new numerical evaluation guarantee or a quality-default change.

Focused regressions:
`python -m unittest discover -s tests/dsp -p 'test_nyquismic_sampler_convergence.py' -v`
and
`python -m unittest discover -s tests/dsp -p 'test_nyquismic_convergence.py' -v`.

## Separately declared source and delivery clocks (9 November 2026)

The real physical-event comparator now admits a delivery Hz different from
the immutable input PCM source rate. The output clock is bound into every
sampler pass's versioned `RenderIdentity`, as well as its final FIR conversion
and PCM digest. This is not a change to virtual-event timing or the saved
artistic reference clock. Source duration must produce exactly integral
numerical and delivery frame counts at all selected rates, and all conversion
ratios must fit the admitted FIR filter budget before audio rendering.

The legacy entrypoint delegates to the same physical-event sampler, with
an unchanged 48 kHz default. Unsupported 192000 -> 44100 conversion still
refuses before the first capture. The distinction between a comparison and
independent analytic truth/product WAV acceptance remains unchanged.

## Actual physical-time sampler convergence at opt-in 44.1 kHz (9 November 2026)

`evaluate_sampler_convergence`, `evaluate_local_convergence`, and the delegating
`evaluate_sampler_model_convergence` now accept an explicit independent
`delivery_policy=DeliveryConversionPolicy(method='nyq.polyphase-delivery-44100-via-48000.v1')`.
This freezes the SAME two-stage, post-artistic 48 kHz intermediate FIR method
across all three numerical comparison rates (192/384/768 kHz), without
altering the 8 kHz artistic capture events or the legacy direct-only default.
The selected delivery policy method and SHA-256 are recorded in the
convergence diagnostics, alongside each actual output PCM and FIR stage hash.

All stage ratios/tap budgets, source/numerical/delivery integral physical
extents and per-pass resource ceilings refuse **before** any virtual capture.
A 96 kHz frozen source lasting 0.1 seconds has 800 captures at the 8 kHz
artistic clock, 4,800 frames on the intermediate grid, and exactly 4,410
44.1 kHz final PCM frames. New actual-sampler tests verify the same physical
event ledger across numerical rates, the signed intentional 6 -> 2 kHz
fold, and final PCM identity against separately executed delivery. An
unselected 192 kHz -> 44.1 kHz direct FIR still fails its 4,096-tap cap.

This is a source-local bounded *same-model comparator*, not an analytic
truth oracle, declared convergence unless all metrics pass, application
Compose/graph integration, product WAV export or a new default quality policy.
