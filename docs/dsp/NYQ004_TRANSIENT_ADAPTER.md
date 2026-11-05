# NYQ-004 immutable upstream transient-derived rate control

**Status:** opt-in component on draft PR #267, issue #253. This detector
does not register a graph node, perform graph ancestor discovery, relax
NYQ-002's routed-clock rejection or prove end-to-end audio execution.

UpstreamTransientPolicy uses an embedded, complete and versioned
UpstreamRmsPolicy (PCM SHA-256, upstream stable source ID, channel,
frame count, source rate, RMS window and explicitly saved full-scale
reference). It adds the exact rational minimum_rise threshold [0,1].
The source hash is of canonical interleaved little-endian float32 PCM.

The method nyq.upstream-rms-rise-transient-v1 first calls the **existing**
upstream RMS adapter, inheriting full-copy validation, rejection of foreign
source hashes/invalid channels/nonfinite audio, explicit verified-upstream
ancestor IDs and bounded windows. It computes the dimensionless value for
window k as max(0, RMS[k] - RMS[k-1] - minimum_rise), with RMS[-1]=0.
Subtraction and threshold comparison after the RMS quantizer are exact
rational arithmetic. A difference of two independently bounded-denominator
RMS levels can require a denominator near 10^12; the compiled rise is therefore
rounded once, deterministically, to at most 1,000,000 denominator (the RMS
source resolution), before entering the frozen Point contract. Very small
positive rises can become zero at that declared resolution; no rate clipping,
reordering or unbounded precision is introduced. The manifest/diagnostics
record both RMS and rise quantization denominators. Control changes
take effect at exact half-open window start times. The detector is a
positive window-envelope difference, **not** a sample-accurate broadband
transient detector or spectral-centroid feature, and it requires up to
one full RMS window of *offline lookahead*. No implicit smoothing, onset
confidence, attack shaping or normalization is applied. A falling edge
returns zero at the next window, rather than holding the last onset.

The ordinary saved ModulationRoute is a right-continuous step curve.
Store both policy JSON and compiled route JSON to retain the authoring
intent, method hashes and exact source binding. Source origin is currently
restricted to zero because route.initial otherwise exposes the first
window's onset before its declared support. A later real graph integration
must resolve physical origin, graph DAG provenance, placement and cache
invalidation itself. The sampler, project, rack, export and defaults remain
unchanged; NYQ-004 is **not** accepted by this component.

Regression:
python -m unittest discover -s tests/contracts -p 'test_nyquismic_transient.py' -v

Fixtures cover threshold/tie/step timing, adversarial non-coprime RMS denominator
re-quantization, actual control-rate evaluation,
serialisation, first-window rise, falling/steady edges, stereo, empty/silence,
source tampering, ancestry, delayed origin rejection, point budgets,
cancellation and input immutability.
