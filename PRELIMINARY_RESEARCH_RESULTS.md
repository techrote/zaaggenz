# zaaggenz preliminary research results — 2026-09-12

This is independent preliminary evidence, not an implementation of the unavailable v1.2.1 synthesiser. No production task is closed, no prerequisite is waived, and no default sound has been changed.

## Current gate

The main repository at `c1e4de5e94d9b0e304bac06f0746d6bd80f90832` and the uploaded programme contain planning material, not the actual application archive. ZG-001 / issue #2 remains blocked on source recovery. The programme ZIP SHA-256 is `f342f0dda48e5dfbae7b9d179a46313e4077f349f85fcbd4b5437f0bb348216e`. The live 45-task, 158-edge graph agrees with the supplied programme.

## Work completed locally

- Independent reproducible Python probes under `research/preflight-2026-09-12/` for spectral reconstruction and phase integration, band-delta identity, nonlinear aliasing, Chordness bias, tuning, dissonance, exact clocks, phrase roles, job scheduling and statistical design.
- 42 independent preflight tests passed. Sixteen synthetic result files reproduced with identical hashes in the recorded environment. These are not the old application's tests.
- 19 numerical output files plus a manifest and environment record; a verified lossless snapshot contains 21 files. It contains no source audio.
- Local analysis of six supplied recordings, including exact replication of the original two-track hashes and descriptor method, 1,231 complete one-second windows, six explicitly unreviewed candidate excerpt pairs and metadata-only level recipes.
- Twelve issue-oriented evidence notes and a targeted 25-record primary-source/prior-art register, including relevant corrections and counterevidence. This is not a systematic meta-analysis or participant study.

## Most consequential findings

### Exact reconstruction can conceal unusable retuning

For a known 440 Hz source, define residual as source minus an imperfect sinusoidal estimate. Identity reconstructs algebraically. Retuning only the estimate to 660 Hz while retaining the residual can leave substantial original-frequency/negative-estimate energy. In a one-second fixture with only +0.5 Hz estimation error, identity reaches the -300 dB reporting floor but transformed error is about +3.01 dB relative to the intended target. Separate bypass, decomposition, transformation and ghost-energy tests are essential. No actual partial tracker is claimed.

### Multiband confinement must preserve the dry path

A nested split can sum exactly while re-filtering every unchanged band fails identity. Relative errors were -9.68, -15.37 and -21.03 dB across three multitone cases. The proposed path is `x + sum(P_i(F_i(B_i x) - B_i x))`: confine the effect delta rather than the unchanged band. One high-mid bitcrusher fixture reduced out-of-region effect energy from 0.36385 to approximately 1.22e-6 under its declared transition allowance. This is not a brick-wall or causal/chunk-equivalence claim.

### Raw chord-fit scores reward dense targets

On 512 identical synthetic null spectra, average nearest-tooth fit rose from 0.2163 for a 25-tooth single-root target to 0.3417 for a 46-tooth major target and 0.6754 for a 217-tooth chromatic target. This is a target-density advantage, not a demonstrated improvement in perceived sonority. Keep coverage, displacement, capacity, energy, continuity and residual budgets distinct; calibrated synthetic-null scores are not listener probabilities.

### Low-frequency resolution and phase need explicit contracts

A 48+55 Hz fixture required the 16,384-sample window to resolve both peaks under the tested criterion at 48 kHz, spanning 341.33 ms. Isolated-tone phase precision does not establish two-partial resolution in a short attack. Integrating a known 48-to-55 Hz glide ends near 55 Hz; substituting moving frequency into `sin(2*pi*f(t)*t)` ends near 62 Hz. Observation support and phase origin must travel with every estimate.

### Repeated rounding drifts musical time

Across 75 clock configurations, accumulating rounded step lengths drifted as far as -1,536 samples (-34.83 ms) over 64 bars. Rounding exact rational absolute positions once stayed within half a sample. Nested 1:2:4 anchors are not equivalent to an independent 3:2 cross-rhythm. The 192 symbolic phrase recipes separate variation-location entropy from fill identity; neither measures human uncertainty.

### Listener numbers do not replace stimulus coverage

The synthetic crossed-design simulation generated 32,000 independent listener/item matrices under explicitly assumed variances, not observed effects. With 96 listeners but four stimulus families and a true null, listener-only inference rejected 59.45%; the known-variance oracle rejected 5.40%. A crossed normal approximation still rejected 14.55%, and a t approximation 8.85%. Failed approximations are retained. ZG-040 needs actual model/coverage validation, not a universal participant count.

### Reference analysis must not silently clip decoded floats

The preferred edit's top-RMS-quartile flatness is higher than the original (0.0823 versus 0.0610), reinforcing that low flatness is not a zaag-quality objective. Native FFmpeg true-peak estimates exceed 0 dBTP in all six files; lossily decoded sample peaks also exceed one. Preserve unclamped floats in analysis. These are observational mastered tracks, not matched causal examples or calibrated playback-SPL measurements.

## Reproduce the synthetic probes

Use an isolated environment; the recorded numerical versions are NumPy 2.3.5 and SciPy 1.17.0. No music files, GPU, network or model weights are needed for synthetic work.

```sh
python -m pip install -r research/preflight-2026-09-12/requirements-research.txt
python -m unittest discover -s research/preflight-2026-09-12 -p test_preflight.py -v
python research/preflight-2026-09-12/run.py --out /tmp/zaaggenz-preflight-results
```

Private-reference reproduction additionally requires the original local files and FFmpeg/ffprobe. Never commit those recordings. Exact file hashes are only a same-environment reproduction claim; numerical tolerance and method metadata govern cross-platform comparisons.

## Integration handoff

ZG-005/012/013/017: independent resolution, phase and residual fixtures. ZG-014/018/024: density and assignment counterexamples. ZG-007/020: tuning-format and dissonance sensitivity oracles. ZG-016/019/021/030: effect-delta identity and oversampling evidence. ZG-025..028: exact clocks and explicit phrase-role controls. ZG-003/004: revision ownership and bounded scheduling models. ZG-015/034..040: protocol and coverage checks. ZG-006/033: private-reference identities, replication and candidates awaiting manual review.

Production adapters, full-rate owner listening, source recovery, browser integration and participant-protocol approval remain separate requirements. No biochemical, preference or artistic-success outcome was measured in this pass.
