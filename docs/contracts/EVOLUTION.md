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

## Legacy v1.2.1

The legacy adapter is a compatibility bridge, not the new musical renderer. It must round-trip every recovered preset/default without changing audio. It rejects recipes containing new musical or DSP intent rather than dropping that intent when calling the old engine.

Any later change to a default sound remains governed by the baseline compatibility policy and requires explicit owner approval after a reproducible comparison.

## Schema and semantic validation

Exported Draft 2020-12 JSON schemas provide structural validation. `zaaggenz_contracts.validation` provides additional semantic checks that JSON Schema cannot express cleanly, including time ordering, tuning/reference relationships, graph acyclicity/connectivity, physical-frequency limits, phase/continuity permissions and run/trial publication rules.

A schema-only pass is not sufficient evidence of contract validity.

## Identity

`zg-c14n-v1` is project-specific and frozen with Python/Node vectors. Do not relabel it as JCS. A future identity algorithm must use a different domain tag/version and provide an explicit old→new relationship. Existing artifact/recipe hashes remain stable identifiers of their original representation.
