# NYQ opt-in full-mix 48-kHz WAV handoff — bounded candidate

Scope: NYQ-003/#252 + NYQ-004/#253 production integration; stacked on #275 at
`b072bf44d2d649752b217e8a4cbaa631d235cfc8`. The **parent must receive
independent approval and Integration-owned admission before this may land**.
Only new `zaaggenz_runtime/nyquismic_delivery.py`, a disjoint runtime test
file, and this document belong to this candidate. Do not merge or accept #252,
#253, #254, or #242 based on this slice.

## Operation and output

`export_compose_controlled_wav48(handle, cancelled=...)` requires an
authenticated `ComposeControlledRender` from the real full-context ordinary
Compose session, #267 controlled-clock packet and #266 SamplerPlan. It renders
the **entire** admitted numerical phrase, performs opt-in 48,000-Hz delivery
conversion, encodes an in-memory **IEEE float32 RIFF/WAVE** asset, and returns
a frozen `ControlledWav48` record. Its `receipt()` excludes actual audio and
includes source/recipe/render identity, evaluation and delivery rates,
filter coefficient SHA-256, numerical and delivery PCM SHA-256, and complete
WAV SHA-256. The current in-memory byte interface deliberately has no file
overwrite or external recording side effect.

This is not registered as a Compose graph/rack insert, UI effect, per-band
route, final project export command or upstream-feature tap. It does not alter
defaults, Source PCM, synthesis, artistic virtual rate, or legacy WAV export.

## Exact signal policy

- Accepted numerical input grids: 192,000 / 384,000 / 768,000 Hz. Delivery
  clock: exactly 48,000 Hz. No implicit 44.1-kHz or alternative export rate.
- Fixed symmetric low-pass FIR: `scipy.signal.firwin(20*D+1,
  cutoff=1/D, window=('kaiser', 8.6))`, where `D =
  evaluation_rate_hz / 48000`; then `resample_poly(x, 1, D,
  window=taps, padtype='constant', cval=0.0)`. The actual float64
  little-endian tap bytes are identified by SHA-256.
- Full numerical phrase length `N` becomes `ceil(N/D)` delivery
  frames. Zero extension defines the exact end-support policy. FIR has
  phase-symmetric noncausal support; it may ring before/after transients.
- Preserve finite amplitudes outside [-1,+1] as float data. No clipping,
  gain matching, loudness normalization, dithering, clock retiming or
  delivery-to-virtual feedback. A single fixed evaluation pass is **not**
  a convergence certificate or accepted spectral portability result.
- Finite mono/stereo arrays only; 128 MiB maximum encoded WAV bytes.
  Reject nonfinite source/output including float32 cast overflow, invalid
  grid/channel/shape, stale render, and cancellation before final handoff.
  Expensive FIR and encoding execute outside Compose locks. Final return
  shares #275's synchronized edit/revocation/cancellation publication guard.

This intentionally attenuates accidental >24-kHz evaluation-domain content
before 48-kHz export. Already-folded virtual-clock alias components within
the audible band remain; pre-sampling character is not silently repaired.

## Reproduction and qualification

```sh
python -m unittest discover -s tests/runtime -p 'test_nyquismic_delivery.py' -v
python -m unittest discover -s tests/runtime -p 'test_nyquismic_compose.py' -v
python -m unittest discover -s tests/runtime -v
```

The new tests exercise real Compose render -> controlled-clock SamplerPlan ->
decodable 48-kHz float WAV, saved-session cold-reopen byte identity, stale edit
during WAV encoding, late caller cancellation, source revocation, stereo,
over-full-scale float preservation, exact partial-frame output extent, and
an independent 6-kHz pass / 40-kHz-to-8-kHz stopband tone oracle.

Developer local smoke can verify syntax and isolated FIR properties, but is not
equivalent to the original Ubuntu/Windows integration executions. Log exact
head, direct/reverse original-host CI, run artifacts, source hash and independent
review before considering this a production path. Published receipt is
source-bound only at #275's full-mix admission boundary.

Remaining: independent parent admission, authentic registered
graph/upstream-feature route, selected output rate/preset save schema,
first-class product UI/export workflow, model-aware #252 numerical
convergence, #253 complete modulation/audio-derived policy, final listening
and owner acceptance, and both independent MBR-004 gates.
