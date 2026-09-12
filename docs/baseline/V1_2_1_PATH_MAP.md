# v1.2.1 path and subsystem map

Materialize the verified recovery payload first:

```sh
python baseline/recovered_source/materialize.py
```

The runnable baseline then lives under `app/`. This map freezes what actually exists before later zaaggenz refactors.

| Path | Responsibility | Compatibility relevance |
|---|---|---|
| `app/uptempo_harmony/synth.py` | `KickParams`, presets, pitch trajectory, harmonic lattice/noise/nonlinear one-shot and loop synthesis | `locked_bloom`, oscillator/nonlinear topology, preset/import compatibility |
| `app/uptempo_harmony/arrangement.py` | arrangement sections/spec/events, scheduling, source-preserving articulation, legacy per-event re-synthesis, arrangement analysis | protect source-preserving SYNTH timbre and deterministic roll grammar |
| `app/uptempo_harmony/reversebass.py` | stateful BODY/AUX/SUB, short exciter, full SYNTHLINE mix, reversebass analysis | protect full SYNTHLINE in ARRANGE+BASS and stem semantics |
| `app/uptempo_harmony/multiband.py` | nested split, compressor/bitcrusher/pockets, SCULPT presets | preserve disabled bypass; future research must adapt rather than silently replace |
| `app/uptempo_harmony/audio_bus.py` | downward-only bus guard/statistics | headroom/crest semantics and accidental bus-saturation protection |
| `app/uptempo_harmony/analysis.py` | f0, spectrum, roughness/harmonic descriptors and WAV reading | baseline descriptor semantics; later research features must version changes |
| `app/uptempo_harmony/inverse.py` | single-event and multistage differential-evolution inverse synthesis | existing research capability; not a mastered-track stateful-bass inverse |
| `app/uptempo_harmony/search.py` | parameter-bank/search helpers | exploratory search path |
| `app/uh.py` | CLI: generate/analyze/morph/bank/invert/arrange/reversebass/sculpt | existing offline automation entrypoint |
| `app/webapp.py` | HTTP API, preview/generate/inverse/arrange/BASS routes, master gain, static files | browser/API compatibility, preview semantics, final gain and cache behaviour |
| `app/web/static/index.html` | workspace structure and persistent render deck | UI IDs exercised by regression tests |
| `app/web/static/app.js` | client state, transports, Morph Lab, themes and render workflows | session behaviour, theme persistence and render ownership |
| `app/web/static/app.css` | terminal-style skins including Earth/Neutral default | preserve UI identity unless intentionally changed |
| `app/tests/*_smoke.py` | 13 recovered application smoke scripts | recovered baseline acceptance suite |
| `app/examples/` | JSON preset/default examples | behaviour evidence, not reference recordings |
| `baseline/V1_2_1_CONTRACT.json` | frozen source/preset/render/API compatibility values | G0 compatibility boundary |

## Existing core data structures

`KickParams` is a dataclass serialised through dictionary/JSON helpers. It contains sample rate/BPM/f0, pitch motion, harmonic lattice, roughness/noise, nonlinear topology, envelope/filtering, peak and seed. Existing morph logic handles discrete sample rate, beat count, harmonic count, roughness minimum harmonic and seed specially.

`ArrangementSpec` contains tempo, bars/beats, sections, seed, source-preservation flag and bus parameters. With source preservation enabled, the finished SYNTH source is rendered once and arrangement variants are predominantly source-derived rather than returning every event through the full oscillator/fold/clip topology.

`ReverseBassParams` contains BODY/AUX/SUB state, coupling, event pitch/drive interaction, `synthline_level`, short `kick_level`, and bus controls. The combined renderer exposes stems including `synthline`, `body`, `aux`, `sub`, `kick`, `bass` and `mix`.

`SpectralSculptParams` holds four-band processing and subtractive pockets. The recovered `transparent` preset has `enabled=False`, and its frozen bypass is bit-identical in the recorded environment.

## Entry points

From `app/`:

```sh
python uh.py -h
python uh.py generate --preset locked_bloom --out locked_bloom.wav
python webapp.py --host 127.0.0.1 --port 8765
```

Windows launcher: `0WebUI.cmd`; Unix launcher: `0WebUI.sh`.
