# NYQ-004 — authenticated spectral-centroid virtual-clock control

**Experimental opt-in #253 / Draft #267, not a registered graph or sampler.**
\`zaaggenz_contracts.nyquismic_spectral_feature\` adds
\`nyq.source-bound-hann-centroid-steps.v1\`. It converts actual immutable
upstream float32 PCM into a *physical-time* right-continuous centroid
\`ModulationRoute\`, consumed by the existing exact-step event compiler and
native-grid PCM proof. Unlike RMS/transient controls, this responds to changes
in upstream spectral balance even when source amplitude is unchanged.

\`UpstreamCentroidPolicy\` stores a version, existing \`UpstreamRmsPolicy\`
(source ID, PCM SHA-256, source rate, channel, origin, full-scale reference and
window), explicit floor/ceiling Hz, minimum normalized **AC RMS**, low-confidence
policy and terminal-tail policy. Complete power-of-two windows of 32–8192
frames are required; partial/empty input refuses. A complete externally
supplied \`UpstreamGraphSnapshot\` and its current SHA-256 are **required**;
caller-only ancestor lists cannot qualify this feature. Source PCM is copied
once before source/DAG authentication, then only that private copy is read.

For each complete half-open window, subtract its mean (DC removal), apply a
Hann window and compute the magnitude-weighted centroid of positive rFFT
bins, excluding DC. Map centroid from the saved [floor, ceiling] Hz interval
to normalized [0,1] with no clipping. A feature outside the declared interval
refuses, rather than silently remapping it. Quantize the resulting control
once to a rational denominator at most 1,000,000, independently of output or
evaluation sample rate. The control step takes effect at the *window start*,
so offline lookahead is one full window. The saved source must be retained:
the route alone cannot regenerate the feature after source/graph changes.

An empty/AC-silent or weak window fails by default. \`neutral_zero\` is the
only optional explicitly stored low-confidence fallback; it produces zero
modulation for that window, not an invented spectral value. \`zero_after_source\`
(default) releases the control at the physical half-open source endpoint;
\`hold_last\` can be requested. Delayed sources are neutral before their
origin. Onset and tail each consume a point in the ordinary 256-point budget.
The feature and route diagnostics expose their hashes, window support,
centroid values, normalized AC RMS, fallback indices, lookahead and topology
proof. Do not mistake RMS for a statistical confidence score.

Numerical FFT reductions are finite float64 operations. Cross-platform
bit identity of the resultant rational feature has **not** been independently
established; a source-matched centroid tolerance and original Ubuntu/Windows
execution are required before product acceptance. The supplied DAG hash does
not prove that the caller used the *current Compose project revision*.
No cached feature from an unrelated PCM/method or unsupported live audio tap
is accepted. This does not alter the NYQ-002 sampler, source files, default
sound, rack registry, programme state or product WAV/FLAC export.

Focused proof:

\`\`\`sh
python -m unittest discover -s tests/contracts -p 'test_nyquismic_spectral_feature.py' -v
\`\`\`

The fixture uses actual frozen 500 Hz and 1500 Hz f32 upstream tones,
a separate target PCM, a verified acyclic cross-band graph snapshot, exact
physical clock events and native-grid rendered audio. It checks control
range, stage output difference, region/replay identity, DC/silent fallback,
delayed source, stereo selection, stale source/graph refusals, resource and
cancellation bounds. It does **not** assert spectral-centroid support
inside live Compose.
