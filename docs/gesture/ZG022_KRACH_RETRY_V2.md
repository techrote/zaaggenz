# ZG-022 / #232 — Krach retry v2

The owner rejected all four v1 Krach candidates from PR #236 as "scratchy and nasty in a bad way". That pack remains rejected evidence, not production presets. This retry branches from accepted main rather than promoting the rejected branch. It is not a low-pass remaster of the old WAVs.

## New audition identities

- `zaag.krach-v2-pressure` / Pressure Roll: folded harmonic bloom over a retained low body.
- `zaag.krach-v2-bounce` / Rubber Bounce: smooth two-rate mid/upper modulation.
- `zaag.krach-v2-throat` / Throat Motor: broad moving resonances driven from the same phase-coherent source.
- `zaag.krach-v2-steel` / Rounded Steel: root-synchronous motor modulation without free-running ring oscillators or sample hold.

The common source uses the recovered synthesis substrate underlying approved families, with explicit new overrides. It does not copy their audio or modify their recipes. Noise, stochastic clicks, roughness AM, harmonic detuning and pitch jitter are removed at the source. Source and character processing run at four-times output rate and are decimated through a declared antialiasing filter. Surface distortion runs separately from the low body. There is no whole-mix nonlinear grit stage after the two are reunited. Boundary envelopes are explicit.

## Audition and reproducibility

Run `PYTHONPATH=app:. python -m zaaggenz_zaag.krach_retry --out EMPTY_DIRECTORY` after materializing the authenticated source and installing the declared dependencies. Supported output rates are 12 and 48 kHz. Tempo is bounded to 60–260 BPM. The CLI produces four sources, four eight-bar root loops, four matched-pattern melody clips, four presentation-only filter sweeps, a short comparison WAV and a local HTML player. WAVs use 24-bit mono PCM; a single linear matching gain is applied per item, with peak-safe reduction and no final compressor, limiter or clipping.

The root demonstration is now one source hit per beat; the melodic demonstration uses explicit six-ms sampler release gates to avoid overlapping/truncated tails. This is a disclosed presentation change, not a silent reinterpretation of the old arrangement contract. Existing renderers, registries and accepted presets are untouched.

Eight focused tests cover deterministic output at both rates, bounds/invalid inputs, source identity, unchanged accepted-family state, boundary envelopes, explicit note gates, matching policy, WAV format and manifest hashes. Engineering tests do not establish improved sound quality.

All four are `pending-owner`. No production catalogue/default change is made. The original six approved families remain accepted, and `locked_bloom` remains protected. Do not close #232 or merge as a creative success without the owner's new disposition.
