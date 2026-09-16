# Validated DSP graph and multiband routing v1

ZG-016 makes stage order explicit without rewriting the known-good v1.2.1 source.

## Graph

`DSPNodeSpec` IDs resolve through a reviewed local registry; recipes cannot name Python modules, files or code. v1 executable nodes are identity, gain, tanh, hard clip, static four-band gain and the authenticated legacy SCULPT adapter. Cycles are rejected because **no bounded delayed-feedback node is registered yet**.

Every node declares channels, state/reset, phase, latency/lookahead, bounds and automation. Gain/tanh/hard-clip parameters can use deterministic sample-domain step or linear automation. Linear interpolation is the smoothing mechanism; a requested `step` remains deliberately discontinuous rather than receiving hidden smoothing. Static multiband/legacy-SCULPT parameters reject automation until a versioned implementation exists.

Automation capability is authoritative in the node registry through `x-automatable`. Shared `DSPNodeSpec` semantic validation and graph execution use the same registry capability lookup: an automation lane is accepted only for a registered numeric parameter whose `x-automatable` value is exactly `true`. Boolean, enum/integer, crossover, antialiased nonlinear and legacy-SCULPT parameters therefore fail contract validation before rendering rather than becoming contract-valid states that fail later in the executor. Unsupported lanes are rejected; they are never stripped, clamped or silently made static.

Node outputs are labelled taps when requested, so transforms can be placed before/after/between explicit nonlinear graph nodes and inspected independently. The authenticated legacy source remains opaque internally: its exposed tap is `legacy-source-post-internal-nonlinear`. ZG-016 does **not** fabricate unsupported pre-waveshaper access inside the old source.

## Final output policy

The graph executes in float64, but the v1 rendered PCM representation is float32. A successful render therefore has a hard **finite-output invariant**: finite graph input and accepted processing may not be published as NaN or ±Inf after master gain or representation conversion.

`unbounded_float` means **unclamped finite float32**, not unlimited numerical magnitude. Values above full scale remain unchanged when they fit the finite float32 range. A finite float64 graph result whose magnitude exceeds `float32.max` is rejected before conversion; it is not limited, normalised or silently saturated. Likewise, numerical overflow caused by the final master multiplication fails before `clip_at_full_scale`, `error`, or `unbounded_float` policy handling can hide an invalid intermediate. Successful diagnostics (`gain_linear`, driven/output peak and clip fraction) are therefore finite.

`clip_at_full_scale` retains its existing semantics for finite driven samples: values outside ±1 are deliberately clipped. `error` still rejects finite over-full-scale output. Neither policy is a recovery mechanism for arithmetic overflow.

## Legacy graphification

`graphify_legacy_recipe()` proves the recipe is an exact legacy projection, then moves the legacy SCULPT payload into an explicit `legacy.sculpt.v1` graph node. The source renderer is invoked without SCULPT/master, explicit nodes execute in stored DAG order, then the one declared output master policy runs.

This produces the same SYNTH/ARRANGE/A+B/BASS output as the recovered pipeline for the tested settings. Reversebass diagnostic component stems remain pre-master; `mix` is the post-master product, matching the frozen contract.

## Identity-safe multiband

The four analysis bands are a nested zero-phase Butterworth decomposition whose dry sum is algebraically the source. Processing follows:

`y = x + Σ P_i(F_i(B_i x) - B_i x)`

Only the **effect delta** is optionally re-confined. If every effect is identity, the router returns the original dry array without invoking a crossover at all. This prevents the earlier failure mode where re-filtering unchanged bands squared their transfer functions and coloured bypass.

Transition regions are deliberately filters, not brick walls. `confine_delta` means reduce out-of-band effect energy under the declared filter policy, not eliminate it mathematically.

## Scope

This issue does not implement spectral Auto-Tune, Chordness, sidechain semantics or a new source oscillator. Those consumers get explicit, validated insertion points without changing the present default sound.
