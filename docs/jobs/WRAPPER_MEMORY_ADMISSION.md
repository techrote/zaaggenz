# Authoritative job-wrapper memory admission

Corrective follow-up #136 makes resource estimates supplied by accepted job wrappers one-way conservative: a caller may reserve **more** memory than the wrapper's trusted floor, but may not replace that floor with a smaller value.

## Contract

Wrappers that know a workload-derived or accepted fixed memory floor pass both values through `zaaggenz_jobs.memory.authoritative_memory_reservation()` before calling `JobScheduler.submit()`.

- no override: reserve the wrapper floor;
- override exactly equal to the floor: accepted;
- override above the floor: accepted and forwarded unchanged;
- override below the floor: `JobError` before scheduler mutation;
- zero, negative, boolean, floating-point (including NaN/Inf), string, or other non-integer overrides: `JobError` before scheduler mutation.

The helper deliberately does not clamp an over-large reservation. `JobScheduler` remains the authority for `max_job_memory_bytes`, preview limits, and permanent interactive/background lane capacity. Consequently the #100 terminal-unschedulable rule still applies: an equal-or-higher truthful reservation that cannot ever fit its lane fails synchronously rather than being queued forever.

## Audited accepted wrappers

The repository-level wrapper audit for #136 covers every accepted module-level helper that directly submits scheduler work:

| Wrapper | Authoritative floor | Caller override |
| --- | --- | --- |
| `submit_retune_job` | `estimate_retune_memory_bytes(analysis)` | equal/higher only |
| `submit_chordness_job` | `estimate_chordness_memory_bytes(analysis)` | equal/higher only |
| `submit_placement_job` | `estimate_placement_memory_bytes(source, 1)` | equal/higher only |
| `submit_placement_family_job` | `estimate_placement_memory_bytes(source, 3)` | equal/higher only |
| `submit_adaptive_tuning_job` | existing accepted 8 MiB floor | equal/higher only |
| `submit_dissonance_map_job` | existing accepted 8 MiB floor | equal/higher only |
| `submit_grammar_render` | `grammar_render_memory(bundle)` | no caller override exposed |
| `submit_search_job` | `estimate_memory_bytes(evaluator)` | no caller override exposed |

The grammar and inverse-search wrappers already have no caller-controlled estimate path, so they require no code change.

## Estimate interpretation

This corrective repair does **not** reduce or retune the accepted estimators. Their purpose is conservative scheduler admission, not exact process-RSS prediction.

- Spectral retune retains the five `ComponentAnalysis` arrays and keeps the existing `6 * resident_bytes + 2 MiB` allowance for reconstruction/result copies plus plan/bundle overhead.
- Chordness keeps `7 * resident_bytes + 3 MiB` for its transformed bundle, descriptor/reconstruction/result working sets and metadata margin.
- Placement keeps `source.nbytes * (12 + 8 * variants) + 4 MiB`, with `variants=1` for one placement and `variants=3` for the retained three-result family.
- Adaptive tuning and dissonance mapping retain their accepted 8 MiB reservation. Their bounded contract data is small compared with audio-array jobs; this repair does not invent a lower floor merely to increase admission.

Regression fixtures assert that the spectral estimates exceed the concrete resident analysis-array bytes and grow with larger input, that placement family reservation exceeds the single-placement floor, and that representative defaults remain admissible under normal scheduler limits. These checks support conservatism without claiming the multipliers are perfectly tight on every Python/NumPy platform.

## Protected semantics

Memory admission is metadata only. This repair does not change spectral retuning, Chordness, placement DSP, adaptive-tuning math, source audio, protected component ownership, provenance, recipe/cache identity, output policy, or musical defaults. Cancellation and asynchronous execution remain owned by the existing executors and scheduler.
