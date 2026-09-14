# ZG-024 research handoff 2 — deterministic strategy comparison

**Scope:** ZG-024b / research pass 2. Issue #25 remains open. Foundation base: `7316a6ceeeeac11a48264c925b639d6dfad07f53`. This pass compares search behaviour; it does **not** select a production optimizer or claim recovery of an original production chain.

## What was added

Research code lives under `research/zg024b`, outside `zaaggenz_inverse`. This is intentional: ZG-024a's implementation manifest hashes every Python file in the foundation package, so keeping that package untouched preserves the first-pass calibration and its identity.

The strategy runner accepts only the existing `FitEvaluator`. It therefore receives fitting excerpts and declared search metadata, not fixture truth, holdout samples or the `AuditEvaluator`. Candidates are still ordinary ZG-024a `Candidate` records produced through the accepted renderer/objective/validation path. Strategy-specific method identity, proposal lineage and verified-prefix replay live in a separate `StrategyResult`.

Four methods were frozen before outcomes were inspected:

| Method | Proposal rule |
|---|---|
| `zg024b.grid-prefix.v1` | Existing seeded cyclic Cartesian grid prefix from ZG-024a. |
| `zg024b.uniform-splitmix.v1` | Deterministic SplitMix64 coverage mapped directly into each bounded axis. |
| `zg024b.halton-shifted.v1` | Halton radical-inverse sequence with deterministic per-axis seed shift. |
| `zg024b.coordinate-refine.v1` | Seeded Halton start, coordinate probes at halving radii, current fit-best center; explicitly labeled Halton fallback only after four duplicate/clipped stagnant rounds. |

All methods consume unique logical candidate evaluations under the same fixture budget. Every cold evaluation still renders twice through ZG-024a for exact same-environment verification. Search seed, method and research implementation are part of run identity. Resume cold-replays the completed prefix and declares divergence if the request, strategy, environment or completed candidate differs.

## Frozen experiment design

Search seeds: `24`, `97`, `1337`. Core fixture/method comparisons total **48 runs**. The held-out late-gain sentinel is evaluated separately for the four methods and is excluded from aggregate strategy quality.

| Fixture | Axes | Budget | Purpose |
|---|---:|---:|---|
| `offgrid-envelope` | f0 60–84 Hz; decay 120–280 ms | 16 | Truth 73.3 Hz / 213 ms is deliberately off the five-level grid. |
| `offgrid-nonlinear` | drive 6–18 dB; shaper wet 0–1 | 16 | Off-grid nonlinear interaction; target drive 13.7 dB / wet 0.63. |
| `offgrid-timbre3` | f0; harmonic decay; odd/even ratio | 24 | Three-axis spectral/timbre coverage; five-level lattice has 125 points. |
| `offgrid-nonidentifiable` | drive; input trim | 16 | Accepted shaper observes their sum, so raw recipe coordinates are deliberately non-identifiable. |
| `holdout-sentinel` | late gain automation | 9 | All fitting windows occur before the gain step; holdout must expose arbitrary fit-equivalent choices. |

All targets use the same deterministic ZG-024a rendering path and independent fit/holdout window declaration. Parameter truth is used only after selection as a research diagnostic. For the drive/trim case, raw coordinate distance is intentionally not scored; the diagnostic is distance to the known observable `drive + trim` equivalence manifold.

## Cross-platform result

The first frozen matrix completed on Ubuntu and Windows. Both passed the new research tests and the unchanged ZG-024a inverse suite. Exact evidence hashes differ because environment identity is retained, but the entire portable outcome projection matched with **zero differences** under the preregistered absolute `1e-7` / relative `1e-5` policy.

Initial evidence-generation wall time was about **272 s on Ubuntu** and **311 s on Windows** for the complete matrix plus audits. These are host observations, not performance guarantees. Typical 16-candidate searches use 32 physical cold renders; coordinate refinement has similar render count but somewhat greater orchestration/feature cost because it repeatedly selects a center from accumulated fit results.

## Strategy outcomes

No strategy dominates across the four fixture families. That is the principal result.

| Method | Eligible top result availability | Paired fit wins/ties | Median selected fit | Median selected holdout | Median identifiable parameter error |
|---|---:|---:|---:|---:|---:|
| grid prefix | 58.3% | 2 / 12 | 0.01087 | 0.01443 | 0.2802 |
| uniform SplitMix | 91.7% | 3 / 12 | 0.02350 | 0.03133 | **0.1538** |
| shifted Halton | **100%** | **4 / 12** | 0.08919 | 0.13402 | 0.2734 |
| coordinate refine | 83.3% | 3 / 12 | **0.002284** | **0.002107** | 0.1945 |

Those aggregate medians must not be read as a league table because missing eligible results are non-random and the fixtures stress different structures.

Fixture-level behaviour is clearer:

- **Envelope:** uniform SplitMix wins all three seeds. Fit scores are approximately `0.0784 / 0.1912 / 0.2929`. Grid has no eligible candidate in any seed; coordinate has no eligible candidate for seed 24. This is heavily confounded by the transient gate discussed below.
- **Nonlinear drive/wet:** grid wins seeds 24 and 1337 at fit `0.000693`; coordinate wins seed 97 at `0.000554`. Coordinate selected holdouts remain about `0.00063–0.00241`. Grid's excellent acoustic fit can still be far from the generating raw coordinates (normalized parameter error about `0.280`), demonstrating that even this nominally identifiable recipe family has strong parameter trade-offs.
- **Three-axis timbre:** shifted Halton wins all three seeds with fit about `0.1603 / 0.1559 / 0.2954`. Grid produces an eligible result in only one of three seeds; uniform and coordinate each miss eligibility once.
- **Non-identifiable drive/trim:** coordinate wins seeds 24 and 1337; Halton wins seed 97. Coordinate's median normalized distance to the observable equivalence manifold is about **0.00336**, versus grid `0.0417`, uniform `0.0141`, Halton `0.0258`. Distinct raw drive/trim recipes remain valid alternatives rather than being collapsed into a false original-chain answer.

Search-seed sensitivity is material. The same method can move from strongest to weak under a fixed small budget. Later comparisons need multiple seeds or deterministic coverage designs; a single lucky seed is insufficient evidence.

## Eligibility-gate interaction

ZG-024a deliberately made anti-degeneracy gates independent from acoustic fit. Pass 2 shows why those two concepts must remain separable during optimizer research.

On `offgrid-envelope`, **all 48 grid candidate evaluations across the three runs are rejected from eligibility**, predominantly by `transient_loss`; coordinate seed 24 is similarly left with no eligible candidate. On `offgrid-timbre3`, several methods also lose whole runs to the transient gate. Retained rejected candidates still have finite decomposed fit measurements—for example the post-hoc lowest raw grid scores on envelope are roughly `0.67–0.73`—but the preregistered selected-result endpoint correctly reports no eligible winner.

This does **not** establish that grid search destroys transients. Handoff 1 already observed that the target-anchored derivative metric can react to periodic phase/root changes. The new result strengthens the need for a dedicated gate-ablation/validation pass before optimizer ranking is used as a musical recommendation. Do not weaken the gate merely to improve a method's score; test whether the measurement distinguishes perceptual attack loss from expected phase-sensitive waveform differences.

## Holdout sentinel

The sentinel remains decisive and strategy-independent in the intended sense. Every method gets **fit score 0** for its selected candidate because all fitting windows precede the late gain step. Every selected candidate is flagged as overfit after audit:

| Method | Selected late gain | Fit | Holdout |
|---|---:|---:|---:|
| grid | −6.000 dB | 0 | 1.30658 |
| uniform | −5.720 dB | 0 | 1.27963 |
| Halton | −5.795 dB | 0 | 1.28689 |
| coordinate | −6.000 dB | 0 | 1.30658 |

All nine evaluated candidates remain Pareto-equivalent on fitting evidence. Holdout performance does not retroactively rerank the search result. This demonstrates that a more adaptive proposal mechanism does not solve missing information and must not be allowed to inspect holdouts.

## Determinism, lineage and cost

New tests cover equal budget use, bounds, uniqueness, exact repeated runs, grid-wrapper equivalence, seed-dependent paths, explicit coordinate parent lineage, leakage resistance, verified-prefix resume for both static and adaptive strategies, and identifiability-aware truth diagnostics. Changing held-out target samples leaves every method's proposal states, fit scores and eligibility unchanged.

The research runner reuses the accepted scheduler research lane and memory estimate. It does not add a distributed optimizer or persistent service. Coordinate fallback is visible in proposal lineage; it is never silently presented as local refinement. Full CI evidence stores every candidate, component loss, validation record, parent/proposal record, exact result/checkpoint identity and selected audit. `examples/zg024b_strategy_calibration.json` is only the compact portable freeze used to detect outcome drift.

## What the evidence rules out

- **Do not select one universal optimizer from this matrix.** Method ranking changes by fixture and seed.
- **Do not infer recipe recovery from low acoustic loss.** The nonlinear case obtains near-zero acoustic fit with materially different generating coordinates.
- **Do not use holdouts as optimization feedback.** The sentinel shows arbitrary fit-equivalent choices can all fail unseen content.
- **Do not treat hard validation rejection as an optimizer score.** Gate validity and search quality require separate evidence.
- **Do not benchmark only on in-grid truth.** The off-grid fixtures expose coverage and local-refinement behaviour that the pass-1 calibration intentionally could not.
- **Do not use a single random/low-discrepancy seed as proof.** Small-budget variation is substantial.

## Recommended next research pass

The strongest next step is **gate/objective validation plus staged-search experiments**, not a leap to ML or a large evolutionary system.

First, isolate transient-gate behaviour with phase/root-controlled fixtures, deliberately destroyed attacks, and level-/spectrum-matched counterexamples. Preserve the gate as a separate diagnostic while determining whether eligibility should be parameter-family/stage aware.

Then compare transparent staged search under the same laboratory: coarse global coverage for timing/root/envelope, a second bounded spectral-structure stage, and a final local texture stage. A sensible research ablation is **global low-discrepancy coverage followed by coordinate/local refinement**, because this pass shows Halton is robust on the 3-D timbre case while coordinate refinement is strong on local nonlinear/equivalence-manifold cases. This is a hypothesis for the next experiment, not a production recommendation.

Only after staged deterministic methods have a stable benchmark should the project spend evidence budget on more elaborate optimizers such as differential evolution/CMA-style populations, Bayesian/surrogate search, or optional differentiable-DSP adapters. Any such comparison must preserve equal logical budgets, full candidate/Pareto records, independent holdouts, exact lineage and editable offline recipes.
