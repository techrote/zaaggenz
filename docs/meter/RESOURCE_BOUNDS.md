# ZG-026 executable meter work bounds

`MeterPlan` 1.0.0 uses exact rational beat coordinates, but lexical rational bounds are not execution bounds. A valid rational such as `1/9999999999999` can describe trillions of ticks inside a short active window. ZG-026 therefore applies a finite executable-work contract before any tick or control row is materialised.

## Authoritative limits

The implementation exports these limits from `zaaggenz_meter`:

- `MAX_TICKS_PER_CLOCK = 65_536`
- `MAX_TOTAL_TICKS = 131_072`
- `MAX_CONTROL_ROWS = 262_144`

The per-clock limit deliberately permits a continuous 64th-note clock (`1/16` quarter-note beat) across the maximum `4096`-beat plan extent. Shorter plans may use proportionally finer exact rational periods. The aggregate and binding limits prevent otherwise-valid multi-clock or many-binding plans from multiplying a practical clock into an unbounded in-memory schedule.

These are rejection limits, not quantisation targets. The engine never rounds, coarsens, drops or coalesces authored ticks to fit them.

## Exact preflight

For each active window, the preflight uses the same phase-origin rules as tick expansion. Explicit reset beats partition the window into phase segments. For a segment `[lo, hi)` with positive period `p`, phase `q`, and selected phase origin `o`:

1. `first = o + q`
2. `k = max(0, ceil((lo - first) / p))`
3. `beat = first + k*p`
4. if `beat >= hi`, the segment contributes zero ticks; otherwise it contributes `ceil((hi - beat) / p)` ticks.

All values are Python `Fraction` objects and all counts are arbitrary-precision integers. There is no floating-point cardinality arithmetic and therefore no platform-dependent rounding or integer overflow in admission.

The plan estimate is then:

- each clock count: sum of its segment counts;
- total ticks: sum of all clock counts;
- control rows: for each binding, add the already-computed count of the clock it binds.

`MeterPlan(...)` performs this preflight after structural/relation/binding validation and before an executable authoring object is published. `generate_ticks()`, `generate_all_ticks()`, `control_schedule()` and periodicity overlays require a `MeterPlan`, so they cannot receive an authoring object that exceeded these limits. `work_estimate(plan)` exposes the same exact accepted cardinalities and limits for later scheduler/runtime integration without enumerating ticks.

## Reset and re-entry semantics

`reset_on_entry`, explicit `reset_beats`, inactive gaps and re-entry remain musically unchanged. Segmentation is part of the exact count, so adding resets cannot bypass the budget. A tick exactly at a half-open segment/window upper boundary belongs to the following segment only when that following segment's phase rules generate it.

## Compatibility decision

The meter-plan format remains `1.0.0`. This is a corrective executable-domain restriction, not a reinterpretation of accepted tick timing: practical plans that were already safely executable generate exactly the same beat/sample positions and control values. Previously accepted documents whose only consequence was pathological resource expansion now fail at authoring admission with an explicit cardinality diagnostic. No stored plan is silently rewritten and no clock is resampled.

If a future product requirement needs schedules beyond these limits, it requires an explicit reviewed resource-policy change (and scheduler admission if asynchronous expansion is introduced), not a caller-side estimate override.

## Regression coverage

`tests/meter/test_meter_budget.py` covers the smallest syntactically legal positive period, maximum plan extent, zero/one tick, exact and one-over per-clock/plan/control-row boundaries, reset/re-entry accounting, a 64-clock × 64-window × 128-binding adversary, and a practical 64th-note clock across the maximum plan extent. Existing ZG-026 tests continue to verify 1:2:4 nesting, 3:2 cross-rhythm, resets/re-entry and exact TimeMap sample conversion.
