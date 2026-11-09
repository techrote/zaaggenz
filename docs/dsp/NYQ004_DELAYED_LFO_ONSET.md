# NYQ-004: exact nonzero delayed LFO onset

The existing `SampledLfoSource.compile_route` rejects an LFO that starts at
nonzero value after physical time zero. A single frozen linear
`ModulationRoute` cannot represent that discontinuity without leaking an
unrequested pre-onset ramp. This is correct fail-closed behavior.

`compile_delayed_lfo_additive_routes` in
`zaaggenz_contracts/nyquismic_lfo_onset.py` supplies an opt-in, versioned
two-route solution for **additive Hz**. It translates the original free-Hz or
beat-synced triangle source and its tempo changes into onset-relative seconds,
reuses the bounded exact turning-point compiler, and then stores:

- A zero-before-onset **step** lane holding the exact initial LFO level.
- A zero-before-onset **linear** lane holding half the difference from that
  onset level at each certified physical-time grid, tempo and cusp point, with
  twice the Hz depth.

The ordered sum is exactly zero before onset and exactly the original
`depth * LFO(t)` from the onset onward. This does not reset the sampling
clock's phase, move samples to frame boundaries, approximate a beat map,
silently round an onset value, or change an accepted virtual sampler.

The output carries `nyq.delayed-lfo-additive-route-pair.v1`, the immutable
source SHA-256, absolute onset/end and two stable route IDs. Both
`ModulationRoute` records serialize through the accepted `SonicSpec` schema;
save the original `SampledLfoSource` separately to retain editable intent.
Time beyond the compiled endpoint holds the last frozen route value; recompile
from the original source before extending a render. The existing per-lane
256-point budget and conservative complete-range/positive-rate admission still
apply; at high depths the two independently bounded lanes may refuse a
correlated rate that could otherwise stay within range. No guard is relaxed.
Log2 routes and a registered production SamplerPlan adapter are not claimed.

Run `python -m unittest discover -s tests/dsp -p 'test_nyquismic_lfo_delayed_pcm.py' -v`.
The test covers a nonzero delayed physical onset, analytic post-step affine
phase/crossing, no pre-onset PCM leak, exact saved repeat/region output, an
off-grid beat tempo change, zero-depth event identity and strict
invalid/cancel/budget refusal. It exercises the existing real
`compile_step_clock_events` and `render_controlled_audio_proof` consumer,
not a fabricated hold-period mock. Cross-evaluation-rate convergence, rack,
Compose, WAV export, native VST and owner audition are *not* qualified.

NYQ-004/#253 and its dependents remain gated on independent review,
source-identity reconciliation with NYQ-003, exact-head CI and Integration
acceptance. No programme or inverse-laboratory ledger is changed here.
