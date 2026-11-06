# Unified local runtime ownership contract

Issue #95 establishes the production loopback runtime used by Compose and the accepted Listening, Inspector and Vocal-gesture workspaces. ZG-041 / PR #215 adds the explicit non-destructive Research hub on that same runtime without creating another session owner. These integration changes do **not** alter DSP, source audio, render recipes, musical defaults, protected provenance or listening-study truth semantics.

## Canonical launch and origin

`python -m zaaggenz_runtime` is the canonical launcher. The legacy module launchers (`python -m zaaggenz_timeline`, `zaaggenz_listening`, `zaaggenz_inspector`, `zaaggenz_vocal`) are thin workspace-selecting wrappers around the same runtime rather than separate user-facing servers. One process binds one loopback port and exposes:

- `/timeline` — authoritative Compose timeline and default ordinary music-making workspace;
- `/research` — explicit non-destructive Research hub over accepted Research surfaces;
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

The `/research` hub owns no independent project/session state and contains no implicit apply path. It reads the same authoritative `RuntimeSession` timeline/project identity, links to Inspector/Listening/Vocal, and leaves each accepted tool's capability and mutation contract intact. Entering Research does not mutate Compose. Trusted Listening authority remains a separate server-held capability and is never exposed by the Research hub.

## Staleness and publication

Inspector keeps the accepted complete source-binding stale checks from #94 and adds the runtime's current Compose revision as an independent publication/apply guard. If Compose advances while analysis is queued/running, the completed result is reported as stale and is not published into Inspector B/snapshot state. A stale source cannot start a new production analysis, be frozen, or be applied. Inspector transforms still require explicit Apply and do not write the Compose project.

Listening stimuli/trials remain immutable derived research records and retain their explicit source artifact revision/provenance even after Compose moves on. This is intentional: old research material is preserved rather than silently rebound to the latest project.

## Browser release identity and cache policy

Issues #102 and #201 establish one explicit browser/backend compatibility policy for the accepted sidecar surfaces. Timeline, Listening, Inspector and Vocal HTML, JavaScript modules and CSS are served with `Cache-Control: no-store, max-age=0, must-revalidate`, `Pragma: no-cache` and an explicit `X-Zaaggenz-Frontend-Release`. Inspector's earlier `no-store` rule is therefore retained and generalized rather than weakened. The recovered `/` instrument keeps its authenticated baseline response/version policy; this repair does not rewrite or fingerprint recovered source assets.

Each sidecar bootstrap exposes a `zaaggenz-web-release` record containing the workspace, web API version, frontend SHA-256, backend SHA-256 and final release ID. `/api/runtime/bootstrap` exposes the same release records for the four release-bearing sidecar workspaces. The `/research` hub uses the current Timeline release identity and runtime backend identity rather than inventing a fifth independent protocol/session owner. The frontend digest is computed from the complete first-party static bundle for that workspace, including Timeline's shared render transport and editor modules and Vocal's editor module. The backend digest is a bounded protocol manifest rather than only the outer `server.py`: it includes the complete accepted Timeline/contract/project/job protocol packages plus each workspace's own service/model/API package, and Vocal additionally binds its text-gesture protocol package. Under the unified runtime, the runtime server/session package is also bound. This closes #201's residual case where `service.py`, model, contract or session semantics could change while the #102 server-only identity stayed constant. Execution-only DSP/analysis/tuning packages are explicitly classified outside this browser protocol identity, so unrelated sonic implementation changes do not gratuitously invalidate open pages. `protocol_dependency_errors()` audits every declared protocol path and first-party import; an unclassified new first-party dependency or missing declared module makes release construction fail closed until the manifest is reviewed. The final release ID remains content-derived, not a manually bumped cache label. `zaaggenz-web-release/1.0.0` remains the envelope because its externally visible fields and compatibility semantics are unchanged; #201 strengthens the content set bound into `backend_sha256`. `WEB_API_VERSION` remains an explicit protocol compatibility field and must be bumped for a deliberately versioned incompatible protocol transition even though backend-byte changes already produce a new release ID.

Served HTML rewrites its first-party JS/CSS URLs with `?zg-release=<release-id>`. The entry module is generated from the tracked source by injecting the same release identity and by fingerprinting its local imports. Any request carrying an obsolete fingerprint receives HTTP 409 rather than current bytes under an old cache key. This closes stale-HTML and stale-child-module paths in addition to normal `no-store` behavior.

The injected entry-module gate adds `X-Zaaggenz-Frontend-Release` to same-origin state-changing browser requests. Browser-originated mutations are recognized by Origin/Fetch-Metadata or the release header itself and must present an explicitly compatible current workspace release ID. Missing or stale IDs fail with HTTP 409 and `frontend release mismatch; reload this workspace` **before** token-authorized state mutation. A page that remained open across a backend/content upgrade therefore cannot silently send its old request semantics into the new process; reload obtains newly fingerprinted HTML/JS and recovers. Ordinary non-browser local API clients remain compatible and continue to use the versioned API contract without pretending to be a cached browser bundle.

Compatibility is endpoint-owned rather than ambient. A workspace normally authorizes only its own exact current release identity. Timeline has two intentional browser-side caller dependencies: Listening renders exact Compose source through Timeline before freezing a stimulus, and Vocal renders its explicit compiled proposal through Timeline for a non-authoritative preview. Both caller release digests include the Timeline protocol owner, so a Timeline protocol edit also invalidates those callers. Timeline therefore accepts the current Timeline, Listening or Vocal release for Timeline mutations, subject to the existing session token. Inspector is not admitted as a Timeline browser mutation caller because its production binding is performed server-side. No release identity substitutes for session or trusted capabilities, and Vocal preview admission does not change its proposal-only application policy. This bounded caller rule prevents the cache/release gate from becoming ambient cross-workspace authority.

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

ZG-041 adds `tests/runtime/test_zg041_workspace.py` plus `tests/runtime/browser_zg041.py` to prove `/research` is non-destructive, carries the authoritative Compose revision/project identity, never exposes the trusted Listening capability, and preserves Compose editing state while traversing Research/Inspector/Listening/Vocal and back.

`tests/runtime/test_web_release.py` adds adversarial and boundary coverage for content-derived identity, the four release-bearing sidecar bootstrap/static policies, exact and obsolete asset fingerprints, stale CSS, missing/wrong/exact browser mutation headers, fail-before-mutation behavior, an already-loaded old release after a backend identity change, non-browser API compatibility, and every retained standalone wrapper. `tests/runtime/test_web_release_protocol_identity.py` freezes #201's pre-fix server-only reproduction, verifies service/model/contract/session changes invalidate exactly the affected release domains, proves unrelated DSP/docs bytes do not churn releases, and makes missing or newly unclassified first-party protocol dependencies fail closed. `tests/runtime/test_web_release_cross_workspace.py` separately proves that the current Listening and Vocal releases can use their intentional Timeline-render dependencies while the current Inspector release is rejected before Timeline state mutation.

`tests/runtime/browser.py` performs a real Chromium traversal of the recovered root plus the four release-bearing sidecar workspaces, renders one Compose artifact, freezes/binds that exact artifact across Research surfaces, verifies participant capability remains non-trusted, verifies Vocal proposal provenance, advances Compose, and observes Inspector source staleness and current timeline bootstrap on the same origin. It additionally leaves a Timeline page running while the backend release identity changes, verifies the old injected JS receives HTTP 409 on mutation, reloads on the same origin, and verifies the newly fingerprinted frontend can mutate normally.

## MBR-003 experimental Compose rack controls

The normal `/timeline` authoring screen now offers an **opt-in**, source-bound
four-band rack editing slice. Enable the rack, add the existing gain,
compression or bitcrush stage to one of the four spectral bands, edit its
contract-defined numeric parameters, reorder stages with the keyboard-accessible
Move up/Move down buttons, reset a built-in insert's numeric parameters to
contract defaults while preserving its ID, wet/bypass and order, explicitly
remove a supported built-in insert by stable ID, bypass stages/bands/the rack,
and edit crossover frequencies,
wet and confinement. Existing opaque/unsupported insert payloads cannot be
deleted through the built-in authoring control. A rack proposal is validated and memory
admitted by the existing Timeline backend; the authoritative RuntimeSession
changes only when the normal project validation accepts the resulting revision.
All changes invalidate playback so stale PCM cannot masquerade as the new sound.

Use **Render full phrase**, play/download the real WAV, then **Save project**
to retain the complete revision lineage. New, named user rack presets are
stored in that project, and can be recalled from its own source ancestor.
An existing user preset can be explicitly renamed (display only) or replaced
with the currently edited rack (sonic state and source provenance included);
ordinary **Save new preset** never silently overwrites an existing ID.
**Delete selected preset** requires confirmation, removes only a saved user
preset (not the active processing rack), and preserves all source revisions
and factory presets. Dismissing the confirmation makes no change.
Select a saved preset and use **Export selected preset** to download a portable
`.zgrack.json` carrying exact rack/sonic digests and source binding.
**Import rack preset file** works even on a project with no installed rack.
Import validates the whole rack contract, both digests, retained no-rack source
ancestry and non-overwriting preset identity. Import never changes the current
processing rack or the source; explicit **Load** applies the imported rack.
These commands use the same bounded revision-validation and undo/redo pipeline.
**Remove rack (dry)** restores the original source processing route without
changing source presets, locked_bloom or retained BODY/AUX/SUB ownership.

This is a bounded MBR-003 development slice, **not full MBR-003 acceptance**:
specialist spectral retuning/Chordness authoring, cross-band monitoring,
full spectral target construction, complete control-surface usability/accessibility and physical Windows acceptance
remain outstanding. Existing spectral and external insert payloads are shown
as preserved but not falsely advertised as editable. External VST3 hosting
remains outside Phase A and is not implied.


Crossover numeric controls enforce the executable rack's actual ordered
frequency contract before submitting an edit: 20 Hz ≤ low < mid < high <
0.49 × project sample rate. Equal neighboring frequencies or a high crossover
at the strict ceiling produce a field-level validation error, not silent
clamping or a new revision. Empty numeric controls, nonfinite input and
out-of-range parameters likewise report a labelled field-level error rather
than silently ignoring an invalid edit; the backend remains the authoritative
validator. The spectral **Add retune voice** degree and **Add retune segment**
sample-offset draft fields also require finite safe integers within their
documented bounds; blank, fractional and out-of-range inputs report which
draft field needs correction without queuing or publishing a source edit. Real Chromium acceptance verifies that these rejections do not
alter the working revision or canonical RuntimeSession.

Rack controls use stable action identities to retain the keyboard's active
input/button after a successful asynchronous, server-validated rack redraw.
This includes specialist retune voice labels, partial-ratio text fields and
timed-target labels, not only ordinary numeric controls. Invalid text retains
its native field-level validation; valid edits use the same authoritative
revision and save/reopen contracts.
This is a focus-management aid only: the accepted Project/rack revision,
processing order, source identity and export do not depend on browser focus.
If the active control disappears or becomes disabled (e.g. removing a stage),
no alternative action is invoked and focus is not redirected to another stage.

### Measured completed rack diagnostics (MBR-003 partial)
The expandable **Measured rack output** area displays actual per-band input,
post-band-wet, and routed-output peak/RMS readings from the selected, completed
render's immutable \`RenderArtifact.scopes.diagnostics.rack\`. It also lists
actual stage execution status, processor-internal maximum compressor gain
reduction where present, and spectral decision/abstention counts when supplied
by the executable processor. Numerical readings are dBFS, with zero amplitude
shown as negative infinity; no live or inferred metering is presented.

This area clears on any source/rack edit, import, or render invalidation.
Previously saved outputs are deliberately revision-bound; selecting one reopens
its exact snapshot rather than applying stale measurements to the new edit.
Region previews retain whole-phrase rack meter context, not cropped-region
meter readings. Missing metrics are explicitly marked unavailable. No
saved-state solo/mute, A/B dry render, or export-level compensation is
implemented by the measured-meter panel itself; saved/exported PCM and rack contracts are unchanged.


### Raw/dry monitoring-only A/B (MBR-003 partial)

Once a processed rack full-phrase render is selected in Compose, **Prepare raw/dry A/B**
requests a second bounded offline render of the same source and note arrangement,
with only the rack removed from a detached working copy. The authoritative
RuntimeSession and saved project never adopt this dry proposal. **Hear dry** and
**Hear processed** switch the local playback source; the processed output's WAV
Download remains unchanged. During dry monitoring the processed waveform and
meter display are hidden to avoid mislabelling them as dry measurements.

A/B preparation requires the exact current processed revision. Pending edits,
revision changes, source imports, cancelled jobs and output selection invalidate
its temporary URL/job, and server-side session generation checks reject stale
dry artifacts. A/B starts uncompensated. **Peak-match A/B (attenuation only)**
is an optional browser playback control enabled only after both completed
post-master peak measurements are finite and nonzero. It attenuates the louder
side to the quieter side's measured peak; it never amplifies, changes a saved
recipe, replaces the processed download, or claims RMS/loudness equivalence.
Switching dry/processed restores the corresponding gain; edits, changing
outputs and stopping playback reset volume to unity and revoke the comparison.
**Band solo/mute audition** is now an optional, separately queued numerical
job, bound to the exact selected processed Compose revision. Its four bands
use the rack's saved Butterworth crossover values on the **completed
post-master full-phrase mix**. Solo hears that filtered band; mute hears
the final processed mix minus that band. This is an honest post-master
listening filter, **not** a reconstructed pre-rack band stem or an alteration
to individual processor chains. The saved rack, working revision, original
completed output, selected download, factory sources and full-render PCM are
never changed. The temporary monitor is rejected on stale revisions and
invalidated on edits/output changes. Its extra filter memory is included
in the scheduler's admission budget. Monitor-only audio has no waveform
or rack meters masquerading as the full processed output; A/B peak matching
is disabled while band audition is selected. Changing band or mode discards
the previous audition so the user must prepare a new bounded job.

Hosted browser qualification does not constitute physical Windows/owner
auditory acceptance.


### MBR-003 internal spectral authoring (draft #270)

Ordinary Compose can now add a built-in `zg.spectral` stage. The initial retune
request uses the **saved source recipe's tuning** and one explicit primary
target voice (degree 0, partial ratios 1/2/3). No source or factory preset is
rewritten. Expand **Internal spectral retune** for amount, confidence, bounds,
slew, ambiguity policy and the primary voice's tuning degree. Move its stable
insert ID before or after compression/gain/bitcrush; the existing numerical
executor processes the serialized order. Changing a control is a detached
rack-edit proposal validated by the canonical Project/RackRecipe and adopted
through the one RuntimeSession. Invalid coupled bounds are rejected rather than
silently clamped.

Multiple saved retune target voices can now be added by explicit degree and
label in the same specialist panel (up to the contract's 32 voices), re-labelled,
assigned independently validated tuning degrees and strictly increasing
positive partial ratios (1–128), or removed while retaining at least one
voice. A new voice initially copies the displayed primary voice's partial
ratios. Saved source tuning and unrelated target state remain unchanged. Each edit
validates the complete bounded request
and source ancestry; stale voice snapshots fail closed. Real numerical
rendering and save/reopen use the same request, with no separate target engine.
Timed **retune change-points** are now explicitly editable at positive
absolute source-sample offsets from the start of the complete phrase (not
beats, playback-wall-clock seconds or crop-relative samples). Add a segment
after the last change-point, inheriting the preceding saved target voices,
then change any scheduled voice's degree, the segment start sample or its
display label, or remove that entire segment. This exposes actual executable
sample-timed target changes through the original spectral DSP and normal
revision/save/reopen/export path; it never constructs a second render engine.
A full expected segment/schedule snapshot rejects stale index edits. The
existing RackRecipe enforces strictly increasing starts, 64 segments maximum,
1..32 voices per segment, candidate-lattice/memory bounds and source binding;
invalid proposals do not adopt. The add-segment number input now displays
and enforces a source-sample minimum of **one sample after the last saved
change-point**, rejecting duplicate/backward timestamps locally with the
required range and no source/session proposal. When no larger representable
source-sample position exists, adding another segment is disabled with an
explicit explanation. This does not relax full backend validation. Changing a segment label does not alter its
sonic digest. New independent scheduled voice inventories and new Chordness
comb templates remain out of scope.

Imported source-bound `ChordnessRequest` stages expose their accepted mode,
selection, gain, confidence, assignment and objective-weight scalars, and a
bounded selection among existing saved comb templates. Switching modes never
constructs arbitrary new comb teeth, and invalid manual selection fails closed.
The UI deliberately does **not** reauthor opaque external stages, new comb
inventories or target schedules. These remain preserved
on save/reopen. Additional specialized target construction, monitoring-only
pre-rack band-stem inspection, RMS/loudness-matched A/B, physical Windows and owner
audition remain outstanding for MBR-003; passing deterministic/browser CI is
not a musical acceptance claim.
Band solo/mute selection changes now invalidate any prior or in-flight monitoring request (including A→B→A selection reversals), cancel known jobs and restore the exact processed output if a monitor was playing. Exported PCM and the saved rack remain unchanged.



### Rack preset form continuity (MBR-003 draft)

In-progress preset name/ID and the selected saved preset survive validated
rack-editor redraws within the same immutable project ancestry. Importing a
different source ancestry clears the unsaved form selection instead of
carrying it into another project. The ancestry key is presentation-only; it
is neither a project format change nor a source/authorization token. Saved
preset identity, export and audible rack processing are unchanged.
