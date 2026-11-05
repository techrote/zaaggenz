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
also inconclusive. No arbitrary minimum loudness threshold is imposed on
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
