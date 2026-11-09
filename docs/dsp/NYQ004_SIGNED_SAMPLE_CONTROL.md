# NYQ-004 bounded signed upstream sample-rate control

**Draft-only, not product graph registration:** NYQ-004 issue #253, PR #267.

A separately named and versioned \`UpstreamSignedSamplePolicy\` permits
**bipolar, one-sample-per-control-step** audio-derived virtual-clock rate
control. Unlike RMS-envelope and positive-rise transient adapters, this
preserves the **sign** of the upstream mono/selected stereo float32 sample.
It uses the established \`UpstreamRmsPolicy\` source ID, complete PCM SHA-256,
source rate, channel, origin and explicit reference amplitude; its
\`window_frames\` must be exactly 1. The RMS compiler authenticates a private
immutable copy of that PCM and its supplied DAG snapshot before the signed
control is read from the **same copy**. A stale source, missing/forward tap,
cycle, invalid channel, graph hash or nonfinite input fails closed.

Each signed f32 sample is converted to an exact Fraction relative to the
saved reference, checked against [-1,1] without clipping/normalization, then
rounded once to a <=1,000,000-denominator rational (the declared route
resolution). Right-continuous step points occur at exact source physical
timestamps. The first sample is neutral before any delayed \`origin_s\`.
\`tail=zero_after_source\` (default) emits an explicit zero-rate-control
point at the half-open source end; \`hold_last\` is an alternative declared
policy. The existing downstream \`ModulationRoute\` mapping/depth and positive
clock rate bounds remain authoritative. Zero control depth remains the
static virtual sampler, **not** the bypassed/dry source.

Each route contains at most 256 points, including delayed onset and zero
tail. Longer signals **reject** instead of silently downsampling the control.
At 8 kHz this intentionally confines one such full-rate slice to at most
32 ms, or slightly less if delayed. This is a bounded high-rate modulation
primitive, not a promised general long-form stream or continuously running
input tap. The inherited lookahead is conservatively one source sample and
must be included in future region-preview state. Stereo channel selection
is explicit; no automatic channel mixing is performed. A graph snapshot is
verified as an internally acyclic DAG **provided by the caller**; this code
does not independently bind the authoritative Compose graph or render
revision. This policy does not widen the frozen NYQ-002 \`ClockPlan\` API.

Tests exercise signed exact clock steps, time origin, tail and point budgets,
source/graph stale rejection, and actual 8-kHz cross-band signed modulation
driving 8-kHz PCM through the existing exact physical-time event compiler
and native-grid proof renderer. That **does not** qualify numerical-rate
convergence, ordinary rack/Compose, export or owner listening.

\`\`\`sh
python -m unittest discover -s tests/contracts -p 'test_nyquismic_signed_sample.py' -v
python -m unittest discover -s tests/dsp -p 'test_nyquismic_signed_sample_pcm.py' -v
\`\`\`
