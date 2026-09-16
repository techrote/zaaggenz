# Contract evolution policy

Contract version `1.0.0` is a frozen consumer boundary. A change is classified before merge:

- **Documentation-only:** no accepted/rejected JSON or semantic meaning changes.
- **Patch-compatible:** validator bug fix that only rejects data already invalid by the documented v1 semantics, or accepts data already documented as valid. Requires regression vectors.
- **Minor migration:** new optional capability with explicit migration/default and no reinterpretation of existing fields. Consumers must advertise support.
- **Major migration:** field meaning, units, timing, phase, identity, graph/state or deterministic-randomness semantics change. Requires a new contract version and explicit migration tool or a precise incompatibility error.

No consumer may silently coerce an unsupported contract version, discard an unknown field, reinterpret units, execute free-form recipe data, or silently replace missing/unknown measurements with zero.

## Registry changes

DSP nodes, analysis methods, tuning loaders and grammar/source families use reviewed registries. New entries must declare identifier/version, bounds and units, state/phase/latency semantics where relevant, provenance/licence, tests, and compatibility. Registration does not imply default use.

The initial DSP node registry is intentionally tiny and contract-only. ZG-016 owns executable graph semantics and must preserve ZG-002 identities or explicitly migrate them.

### ZG-016 automation-capability correction

The ZG-016 automation validation repair is classified **patch-compatible** under contract `1.0.0`. Registry entries already declared `x-automatable`, the ZG-016 documentation already limited v1 automation to gain/tanh/hard-clip parameters, and the executable graph already rejected unsupported automation. A serialized `DSPNodeSpec` carrying automation for a parameter whose registry capability is not exactly `x-automatable: true` was therefore never an executable v1 state; accepting it in shared semantic validation was a validator defect rather than a supported contract meaning.

Corrected v1 semantic validation rejects those documents at admission. Existing valid serialized nodes and their identities are unchanged. No migration or silent lane removal is performed: a formerly shape-valid but non-executable node receives an explicit `… is not automatable` error and must be corrected by its author. The resulting implementation-identity transition is recorded explicitly for ZG-024a and does not waive any frozen calibration, holdout, provenance, or numerical comparison.

### ZG-002 formal-period correction

The `TuningSpec.keyboard.formal_period_degrees` correction is also classified **patch-compatible** under contract `1.0.0`. Frozen v1 already had an executable `KeyboardMap` consumer whose wrapping relation rejected zero; a zero formal period therefore had no executable v1 meaning even though the original JSON Schema interval `[-256, 256]` accidentally admitted it. Rejecting zero at shared admission makes the contract tell the truth earlier rather than reinterpreting a previously executable document.

The authoritative v1 domain is now `[-256, -1]` or `[1, 256]`. Existing positive values keep their meaning. Negative values also keep their existing arithmetic meaning and are covered by explicit end-to-end fixtures: each advance of one explicit keyboard-map period subtracts `abs(formal_period_degrees)` tuning degrees. The positive tuning `period_ratio` itself is unchanged. Scala/KBM explicit maps use the same domain; zero-size KBM expansion retains its narrower representability rule of positive `[1, 128]` because it must synthesize an explicit entry list.

No migration or contract-version bump is required for valid v1 documents. A serialized zero formal period is now rejected explicitly and must be corrected by its author; it is never clamped or replaced. Draft 2020-12 `integer` semantics still admit mathematically integral JSON numbers such as `12.0`, and the executable consumer evaluates those by the same exact integer value so schema-valid representation does not create a hidden consumer-only failure. No default tuning, automatic retuning, source audio, protected-source processing or audible baseline semantics are changed by this repair.

## Legacy v1.2.1

The legacy adapter is a compatibility bridge, not the new musical renderer. It must round-trip every recovered preset/default without changing audio. It rejects recipes containing new musical or DSP intent rather than dropping that intent when calling the old engine.

Any later change to a default sound remains governed by the baseline compatibility policy and requires explicit owner approval after a reproducible comparison.

## Schema and semantic validation

Exported Draft 2020-12 JSON schemas provide structural validation. `zaaggenz_contracts.validation` provides additional semantic checks that JSON Schema cannot express cleanly, including time ordering, tuning/reference relationships, graph acyclicity/connectivity, physical-frequency limits, phase/continuity permissions and run/trial publication rules.

A schema-only pass is not sufficient evidence of contract validity.

## Identity

`zg-c14n-v1` is project-specific and frozen with Python/Node vectors. Do not relabel it as JCS. A future identity algorithm must use a different domain tag/version and provide an explicit old→new relationship. Existing artifact/recipe hashes remain stable identifiers of their original representation.
