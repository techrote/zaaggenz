# G1 evidence checklist — ZG-002

This issue is accepted only when the repository branch and CI demonstrate all items below.

## Structural contracts

- Eleven v1 contracts have bounded Draft 2020-12 schemas and semantic validators.
- Unknown fields, unsupported versions, duplicate JSON keys, nonfinite values, unsafe integer numbers, cycles and excessive depth/size fail closed.
- Exported schemas contain only local fragment references; validation performs no network retrieval.

## Musical/time/tuning

- Reduced rational beat/tempo representation is exact and tempo maps round once at absolute positions.
- Long 64-bar/subdivision fixtures do not accumulate rounded-step drift.
- Non-octave periods, sparse keyboard maps and negative degrees validate; malformed/unmapped references fail.

## Analysis/phase

- Feature observations carry units, validity/confidence, target/estimate/measurement role and explicit sample support.
- Unknown/abstained observations use null rather than numeric zero.
- Partial tracks fix phase/channel conventions and prevent unknown continuity from authorizing transforms.
- Residual/transient references must align in sample rate, channel count, frame count and level domain.

## DSP/render

- Typed node graphs reject cycles, disconnected/dangling nodes, undeclared node types/parameters, forged state/latency metadata, bad units and out-of-bounds automation.
- Registry entries are data-only; no recipe-controlled module/code execution exists.
- Render recipes declare one source, tuning/time/phrase state, phase/reset/tail/random semantics and one output policy.

## Legacy equivalence

- Every recovered synth/reversebass/SCULPT preset round-trips through the legacy adapter.
- Full SYNTH, ARRANGE and reversebass-combined render paths are array-equal before/after wrapping at CI and full rate where covered by tests.
- Combined-render diagnostic stems include complete SYNTHLINE and remain equal.
- Transparent SCULPT and final MASTER behaviour remain unchanged.
- New tuning/tempo/phrase/DSP intent raises an explicit error instead of being silently ignored by the v1.2.1 renderer.

## Identity / portability

- Python and Node implementations match committed `zg-c14n-v1` vectors, including floating-point edge cases and Unicode ordering.
- Named 64-bit random streams are deterministic and independently derived from a string root.
- Contract tests and all 13 inherited baseline smoke tests pass on Linux and Windows CI.

Passing G1 freezes the contract examples/tests as the shared implementation surface for ZG-003/ZG-005/ZG-006 and their descendants. It does not implement those tasks or approve any audible default change.
