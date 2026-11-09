# NYQ-004 reproducible controlled-clock proof WAV pack

Issue #253; draft PR #267. This is an **opt-in experimental demonstration** of
the existing native-grid `render_controlled_audio_proof` consumer. It does not
register a product processor, promise high-quality resampling, enter the normal
Compose/Project pipeline, or certify the NYQ-004/005 dependency gates.

Generate in a new directory (existing evidence cannot be overwritten):

```sh
python tools/nyq004_proof_pack.py --out nyq004-proof-pack
python -m unittest discover -s tests/dsp -p 'test_nyquismic_proof_pack.py' -v
```

The pack contains `manifest.json`, one synthetic input WAV and eight real
controlled-clock WAV files: static hold, physical-time stepped rate, explicit
nearest-Hz rate ladder, counter-addressed seeded frequency-cell jitter,
time-linear reconstruction, an **input-derived RMS clock**, and an
**input-derived positive RMS-rise transient clock**, plus a **tempo-synchronised
triangle LFO clock** with a 120-to-180 BPM change at half a second. The latter
compiles the immutable synthetic input into eight exact, 1/8-second,
right-continuous control windows with an explicitly documented 1/8-second
full-window lookahead and 240 Hz per-unit RMS depth over a 360 Hz base.
It is a real time-varying input-derived clock, not another static hold. All cases have the **same immutable synthetic
source** and run at its 12 kHz native grid for one second. The source is
entirely generated from integer periodic sequences in the script, with no
external samples or licensed reference audio.

The v4 manifest adds the saved beat-synchronised triangular LFO source,
its complete exact-time compiled route, and a real event-driven float32 PCM
render. A regression compares the first half against an unchanged-tempo
counterfactual byte-for-byte and proves the second half changes without
resetting past clock phase. This is a bounded musical modulation/audio proof,
not registered Compose automation, a saved project or product export.

The v3 manifest additionally records a separate sixteen-window transient
policy and compiled positive-RMS-rise lane, with 1/16-second full-window
lookahead, a 360 Hz base, a 960 Hz-per-unit rise depth, and no hidden
onset hold or smoothing. Both derived examples use the identical original
synthetic PCM; their rates and physical event ledgers are different.
The v2 manifest records the RMS source content hash, bounded policy, compiled
route/identity and method diagnostics, plus the declared synthetic upstream
relationship. **Graph ancestry is not verified**: the proof script declares
its own source tap, but does not certify production acyclic cross-band routing
or confidence-aware feature-graph validation. Earlier v1/v2/v3 packs are immutable
historical evidence and are not overwritten or silently relabelled.

Each case records the full saved SonicSpec, source identity, exact physical
clock event-ledger SHA-256, method, source-native floating PCM SHA-256 and
container WAV SHA-256. The WAVs contain original finite IEEE float32 values,
not int16/clipped/normalized approximations. Generation completes in a
temporary sibling directory, atomically renames the complete pack to the
requested path and refuses replacement of existing evidence.

The method is deliberately limited to origin-zero native-grid hold/time-linear
reconstruction without prefiltering. It has no evaluated higher-rate quality
or final delivery anti-alias oracle, no production input-derived feature tap, no general
graph/registered rack or product export, no owner listening and no physical
Windows proof. Hosted Ubuntu/Windows numerical testing at the **exact PR head**
is required before treating the generated files as qualified implementation
examples. A pleasant sound is not proof of filter or clock accuracy.
