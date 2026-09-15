# Unified local runtime ownership contract

Issue #95 establishes the production loopback runtime used by Compose and the accepted Listening, Inspector and Vocal-gesture workspaces. It is an integration repair; it does **not** change DSP, source audio, render recipes, musical defaults, protected provenance or listening-study truth semantics.

## Canonical launch and origin

`python -m zaaggenz_runtime` is the canonical launcher. The legacy module launchers (`python -m zaaggenz_timeline`, `zaaggenz_listening`, `zaaggenz_inspector`, `zaaggenz_vocal`) are thin workspace-selecting wrappers around the same runtime rather than separate user-facing servers. One process binds one loopback port and exposes:

- `/timeline` — Compose timeline;
- `/listen` — participant-facing listening tools;
- `/inspector` — non-destructive harmonic-comb Inspector;
- `/vocal` — local vocal-gesture capture/compilation;
- `/` — the recovered instrument surface with workspace navigation.

The existing specialised server classes remain for focused development/tests. They are not the normal user launch path.

## Ownership

The unified process has exactly one `RuntimeSession`, one `TimelineService` and one bounded `JobScheduler`.

`RuntimeSession` owns the current immutable `TimelineDocument` snapshot and exposes its timeline revision, retained-project head revision and retained-project SHA-256. Successful Compose validation/render requests advance this owner only after the supplied document has passed the existing timeline contract. Timeline bootstrap always returns the current owned document, so a newly opened workspace cannot silently fall back to an unrelated startup copy.

`TimelineService` and `InspectorService` receive the same scheduler by dependency injection. Neither shuts an injected scheduler down; the runtime is the sole shutdown owner. Service-local job registries remain authoritative for access: sharing a scheduler does **not** let an Inspector job be cancelled/read through Timeline APIs or vice versa.

Listening consumes only completed `RenderArtifact` objects owned by that TimelineService. Inspector production binding consumes the same exact artifact: revision ID, recipe SHA-256, cache key, product, PCM content SHA-256, sample rate and frame count remain bound to the accepted source. No workspace reconstructs source PCM from display metadata.

Vocal capture owns only its session-local capture store and immutable analysis/edit data. Its compiled timeline is a **proposal**, never an implicit mutation of Compose. In the unified runtime every Vocal response carries the authoritative source-session identity plus `application_policy = proposal-only; explicit Compose import/apply required`.

## Staleness and publication

Inspector keeps the accepted complete source-binding stale checks from #94 and adds the runtime's current Compose revision as an independent publication/apply guard. If Compose advances while analysis is queued/running, the completed result is reported as stale and is not published into Inspector B/snapshot state. A stale source cannot start a new production analysis, be frozen, or be applied. Inspector transforms still require explicit Apply and do not write the Compose project.

Listening stimuli/trials remain immutable derived research records and retain their explicit source artifact revision/provenance even after Compose moves on. This is intentional: old research material is preserved rather than silently rebound to the latest project.

## Capabilities and loopback security

The public session token is shared by Compose, Inspector, Vocal and **participant** Listening mutations because they belong to the same local session. ABX trusted authority is intentionally **not** unified with that capability. The `X-Zaaggenz-Trusted-Token` remains a separate server-held capability for trusted archive/reopen routes; it is never returned by `/api/runtime/bootstrap` or participant bootstrap. Participant trial IDs, server-held ABX truth, participant-safe exports/receipts and one-shot participant submission retain the #93 contract.

All composed handlers retain the existing loopback Host/Origin checks, bounded request bodies and the restrictive CSP already attached to the accepted workspace pages. The recovered root keeps its existing response policy rather than imposing a new CSP that could disable mature inline UI. Sharing an origin does not broaden trusted Listening authority.

## Shutdown and failure semantics

The runtime constructs the scheduler first, injects it into Timeline/Inspector, and shuts it down exactly once. Injected services have idempotent close methods and never tear down a scheduler owned by another component. Constructor failure tears down any scheduler already acquired and closes the loopback socket.

A job ID is not an ambient capability. Timeline and Inspector verify service-local job ownership before status/result/cancel operations. This prevents cross-workspace cancellation or result access even though the underlying scheduler is shared.

## Verification

`tests/runtime/test_runtime.py` covers one-origin route availability, shared-resource identity, exact Compose artifact handoff to Listening and Inspector, Compose-edit stale rejection, job-ownership isolation, preserved blind participant/trusted separation, Vocal proposal capture/compile provenance, session serialization identity and exactly-once scheduler shutdown.

`tests/runtime/browser.py` performs a real Chromium traversal of the recovered root plus all four workspaces, renders one Compose artifact, freezes/binds that exact artifact across Research surfaces, verifies participant capability remains non-trusted, verifies Vocal proposal provenance, advances Compose, and observes Inspector source staleness and current timeline bootstrap on the same origin.
