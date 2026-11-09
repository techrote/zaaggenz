# NYQ-004 — exact integer-octave step clock (v1)

**Contract subset:** `nyq.exact-integer-octave-step-clock.v1` in
`zaaggenz_contracts/nyquismic_controls.py`. The existing opt-in
`compile_step_clock_events` consumer now accepts ordered `log2_ratio`
routes **when their realized exponent is an exact integer and every
base-Hz/route automation is stepwise**. An exponent of +1 doubles the
virtual capture rate; -1 halves it. The time origin, phase and original
source duration are unchanged. This is a concrete musical octave switch,
not a fractional-octave clock approximation.

At every physical step, `2**integer` is evaluated in exact
`fractions.Fraction` arithmetic, after the preceding ordered additive-Hz
and logarithmic stages. Saved nearest-Hz ladders remain lower-tie exact;
seeded physical-time jitter cells use their existing source/group/channel
identities. The crossing solver integrates the resulting constant
rational-Hz rate across exact cut times. All interval boundaries are
half-open. Clock resets and event/spacing budgets still apply.

**Refusals:** A noninteger `depth * control` anywhere in the
requested time extent is a contract error, not a rounded octave. Any
time-varying linear control in the presence of a logarithmic route is
explicitly unsupported: its exponential clock phase would require a
different certified integration/root-isolation method. The general
instantaneous-rate inspector retains its existing Decimal80 support for
fractional powers; that does **not** imply admissible physical events.
Static controls with no points count as stepwise. The conservative
whole-request and intermediate-rate bounds have not been relaxed.

**Actual PCM fixture:**
`python -m unittest discover -s tests/dsp -p 'test_nyquismic_octave_step_pcm.py' -v`

The frozen 8 kHz source has a 200 Hz virtual clock, followed by
400, 100 and 200 Hz octave sections starting at 1/4, 1/2 and 3/4
seconds. The independent rational phase oracle predicts 225 crossings
at precisely certified times, with zero timestamp uncertainty. The test
exercises native-grid capture/hold PCM, no pre-change leak, changed
post-change output, same-host saved/reopened and region replay,
noncommuting add-vs-log stage order, linked/independent stereo jitter,
fixed-rate quantization, cancellation and strict negative cases.

This is **not** a general log2 ramp, fractional octave, production
`SamplerPlan` or rack integration, numerical evaluation-rate convergence,
delivery WAV export, cross-host sample-bit identity, VST or listening
acceptance. NYQ-003/#266 owns sampler integration; NYQ-004/#267 remains
Draft awaiting independent review and Integration-owned ZG-024a provenance
reconciliation. No legacy default is changed.
