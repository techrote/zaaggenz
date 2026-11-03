# NYQ-003 same-model sampler convergence bridge

**Scope:** #252, experimental draft PR #266. This is a local
engineering-only adapter between the accepted NYQ-002 fractional-event
SamplerPlan and NYQ-003's frozen-rate convergence evaluator, **not**
production graph/rack/Compose, export, preset or default-quality wiring.

Method: nyq.same-model-sampler-convergence-bridge.v1.
Call evaluate_sampler_model_convergence(FrozenInput, SonicSpec, ...).
Every frozen rate executes the identical immutable source bytes, SonicSpec,
clock origin, capture and reconstruction setting through the actual SamplerPlan.
The complete event ledger at each rate is SHA-256 hashed as ordered
little-endian (index, epoch, crossing, binary64 time_s) records; a mismatch
fails before numerical comparison. Candidate identity is bound to the
canonical PCM, SonicSpec and ClockSpec SHA rather than an arbitrary callback.
No stochastic control route is admitted until NYQ-004 integration.

All evaluation grids must contain an **integer number of frames covering
exactly the original source duration**; other rates reject before rendering.
Normal event, FIR, frame, cancellation and memory budgets remain in force,
and numerical-to-delivery conversion remains *after* artistic sampling.
Diagnostics include all sampler render hashes, the shared physical event
ledger, all numerical residual metrics and a distinct inconclusive status
without qualified PCM for empty or divergent cases.

This narrows the unbound arbitrary-renderer-identity gap for the accepted
sampler subset. It does **not** independently verify the clock mathematics,
analytic folding/images, product preview/export, a graph/modulated sampler,
musical preference or Windows physical workflow. Both analytic and product
verification flags remain false; numerical tolerances are experimental.

Regression command:
python -m unittest discover -s tests/dsp -p 'test_nyquismic_sampler_convergence.py' -v

Tests exercise same-source sampler/event identities at three numerical
rates, actual high-rate output conversion, strict physical extent/budget
admission, routed-clock rejection, cancellation and empty-extent nonpublication.
