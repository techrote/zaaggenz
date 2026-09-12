# zaaggenz contracts v1

ZG-002 freezes a bounded metadata and musical-intent boundary without changing the recovered v1.2.1 audio engine.

Version `1.0.0` defines eleven contracts: `AudioAssetRef`, `TimeMap`, `TuningSpec`, `FeatureBundle`, `PartialTrackBundle`, `GestureSpec`, `PhrasePlan`, `DSPNodeSpec`, `RenderRecipe`, `TrialSpec`, and `RunManifest`.

Beats and tempo positions use reduced rational strings. Event scheduling resolves absolute musical positions to integer samples with nearest/ties-to-even rounding. Tuning supports non-octave periods, sparse keyboard maps and negative degrees. Analysis distinguishes target, estimate and measurement, with explicit validity, confidence and sample support. Partial tracks declare phase convention, continuity, channel coefficients and residual/transient ownership.

`RenderRecipe` stores source intent, time/tuning/phrase state, a bounded typed DSP DAG, phase/reset/tail semantics, deterministic named random streams and one final output policy. The initial DSP registry is data-only and does not execute arbitrary recipe code.

The legacy adapter is strict: only exact projections of recovered v1.2.1 behaviour can be thawed into the legacy engine. New tuning, tempo-map, phrase or DSP intent is rejected rather than silently ignored.

Contract identity uses the project-specific `zg-c14n-v1` tagged representation; it is not RFC 8785/JCS. Python and Node implementations are checked against committed vectors. 64-bit random roots are decimal strings and named streams derive independent seeds with SHA-256.

After baseline materialization, run:

```sh
python -m pip install numpy==2.3.5 scipy==1.17.0 -r requirements-contracts.txt
python tools/check_contracts.py --baseline --report contracts-check.json
```

CI executes the same contract checks plus all recovered smoke tests on Linux and Windows. See `EVOLUTION.md` and `G1_EVIDENCE.md`.
