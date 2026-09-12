# ZG-002 architectural decisions

## ADR-002-01 — Rational musical time
Use reduced rational strings for beat/tempo positions and convert absolute event positions to integer samples with one explicit ties-to-even rounding step. Reason: avoid cumulative step-rounding drift and preserve exact tempo-map intent.

## ADR-002-02 — Separate musical intent from legacy execution
The v1.2.1 renderer is adapted without receiving unsupported new intent. A legacy thaw succeeds only for an exact legacy projection. Reason: a successful old-engine render must never imply that new tuning/phrase/DSP fields were honoured.

## ADR-002-03 — Explicit analysis uncertainty
Targets, estimates and measurements are separate roles; unknown/abstained values are null with explicit support. Reason: zero Hz/zero confidence are valid numeric concepts and cannot safely double as missing values.

## ADR-002-04 — Phase and remainder ownership are contract data
Partial tracks state anchor/phase convention, continuity, channel coefficients and transform eligibility. Residual/transient assets remain explicit. Reason: exact reconstruction does not prove a component can be safely retuned.

## ADR-002-05 — Typed bounded DAG, not a plugin host
DSP recipes reference reviewed node identifiers with declared parameters/state/latency/phase metadata. v1 contains no arbitrary code/module/file execution. Reason: make graph ordering explicit without inventing a speculative ABI or unsafe recipe executor.

## ADR-002-06 — Project-specific canonical identity
Use `zg-c14n-v1`, tagging JSON types and representing numeric values as exact binary rationals. Python and Node vectors are frozen. Reason: deterministic cross-language recipe/artifact identity without falsely claiming RFC 8785/JCS compatibility.

## ADR-002-07 — Named deterministic random streams
Store the root as an unsigned 64-bit decimal string; derive named stream seeds with SHA-256. Reason: JavaScript-safe interchange and no accidental perturbation of unrelated random processes when another stream is added.

## ADR-002-08 — Structural schema plus semantic validation
JSON Schema is exported for independent consumers, but semantic validation remains mandatory for relations such as time ordering, graph cycles, tuning references and physical bounds. Reason: structural validity alone cannot express the actual audio contract.
