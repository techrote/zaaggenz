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

## Browser release identity and cache policy

Issue #102 adds one explicit browser/backend compatibility policy for the accepted sidecar surfaces. Timeline, Listening, Inspector and Vocal HTML, JavaScript modules and CSS are served with `Cache-Control: no-store, max-age=0, must-revalidate`, `Pragma: no-cache` and an explicit `X-Zaaggenz-Frontend-Release`. Inspector's earlier `no-store` rule is therefore retained and generalized rather than weakened. The recovered `/` instrument keeps its authenticated baseline response/version policy; this repair does not rewrite or fingerprint recovered source assets.

Each sidecar bootstrap exposes a `zaaggenz-web-release` record containing the workspace, web API version, frontend SHA-256, backend SHA-256 and final release ID. `/api/runtime/bootstrap` exposes the same records for all four workspaces. The frontend digest is computed from the complete first-party static bundle for that workspace, including Timeline's shared render transport and editor modules and Vocal's editor module. The backend digest covers the HTTP protocol owner plus the release-gate implementation; under the unified runtime, `zaaggenz_runtime/server.py` is also part of every workspace backend digest. The final release ID is therefore content-derived, not a manually bumped cache label. `WEB_API_VERSION` remains an explicit protocol compatibility field and must be bumped for a deliberately versioned incompatible protocol transition even though backend-byte changes already produce a new release ID.

Served HTML rewrites its first-party JS/CSS URLs with `?zg-release=<release-id>`. The entry module is generated from the tracked source by injecting the same release identity and by fingerprinting its local imports. Any request carrying an obsolete fingerprint receives HTTP 409 rather than current bytes under an old cache key. This closes stale-HTML and stale-child-module paths in addition to normal `no-store` behavior.

The injected entry-module gate adds `X-Zaaggenz-Frontend-Release` to same-origin state-changing browser requests. Browser-originated mutations are recognized by Origin/Fetch-Metadata or the release header itself and must present the exact current workspace release ID. Missing or stale IDs fail with HTTP 409 and `frontend release mismatch; reload this workspace` **before** token-authorized state mutation. A page that remained open across a backend/content upgrade therefore cannot silently send its old request semantics into the new process; reload obtains newly fingerprinted HTML/JS and recovers. Ordinary non-browser local API clients remain compatible and continue to use the versioned API contract without pretending to be a cached browser bundle.

CSS is deliberately not part of authorization: stale CSS cannot make a stale JS/API pair acceptable because mutation admission is bound to the entry-module release ID. Conversely, CSS itself carries the release query and no-store headers so old presentation bytes are not silently reused after a bundle change.

The retained standalone Timeline/Listening/Inspector/Vocal server classes build the same content-bound policy from their own protocol owners. The unified runtime includes its additional route owner in the backend digest, so a standalone and unified release may legitimately have different IDs while exposing the same `WEB_API_VERSION`.

## Capabilities and loopback security

The public session token is shared by Compose, Inspector, Vocal and **participant** Listening mutations because they belong to the same local session. ABX trusted authority is intentionally **not** unified with that capability. The `X-Zaaggenz-Trusted-Token` remains a separate server-held capability for trusted archive/reopen routes; it is never returned by `/api/runtime/bootstrap` or participant bootstrap. Participant trial IDs, server-held ABX truth, participant-safe exports/receipts and one-shot participant submission retain the #93 contract.

All composed handlers retain the existing loopback Host/Origin checks, bounded request bodies and the restrictive CSP already attached to the accepted workspace pages. The recovered root keeps its existing response policy rather than imposing a new CSP that could disable mature inline UI. Sharing an origin does not broaden trusted Listening authority. The release gate is evaluated only after the existing loopback Origin/Host boundary and does not substitute for tokens or trusted capabilities.

## Shutdown and failure semantics

The runtime constructs the scheduler first, injects it into Timeline/Inspector, and shuts it down exactly once. Injected services have idempotent close methods and never tear down a scheduler owned by another component. Constructor failure tears down any scheduler already acquired and closes the loopback socket.

A job ID is not an ambient capability. Timeline and Inspector verify service-local job ownership before status/result/cancel operations. This prevents cross-workspace cancellation or result access even though the underlying scheduler is shared.

## Verification

`tests/runtime/test_runtime.py` covers one-origin route availability, shared-resource identity, exact Compose artifact handoff to Listening and Inspector, Compose-edit stale rejection, job-ownership isolation, preserved blind participant/trusted separation, Vocal proposal capture/compile provenance, session serialization identity and exactly-once scheduler shutdown.

`tests/runtime/test_web_release.py` adds adversarial and boundary coverage for content-derived identity, all four bootstrap/static policies, exact and obsolete asset fingerprints, stale CSS, missing/wrong/exact browser mutation headers, fail-before-mutation behavior, an already-loaded old release after a backend identity change, non-browser API compatibility, and every retained standalone wrapper.

`tests/runtime/browser.py` performs a real Chromium traversal of the recovered root plus all four workspaces, renders one Compose artifact, freezes/binds that exact artifact across Research surfaces, verifies participant capability remains non-trusted, verifies Vocal proposal provenance, advances Compose, and observes Inspector source staleness and current timeline bootstrap on the same origin. It additionally leaves a Timeline page running while the backend release identity changes, verifies the old injected JS receives HTTP 409 on mutation, reloads on the same origin, and verifies the newly fingerprinted frontend can mutate normally.
