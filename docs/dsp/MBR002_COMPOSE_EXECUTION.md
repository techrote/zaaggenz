# MBR-002: saved-rack execution in ordinary Compose

Scope: #240 under #238. The saved `MultibandRack 1.0.0` and Project/recipe
formats accepted by #239/#248 are unchanged. This delivers the backend route;
#241 still owns the editable UI and #242 complete Phase-A product acceptance.
External descriptors remain preservation-only, not native plug-in execution.

## One source route and one final master

`zaaggenz_melody.render.render_phrase` validates and admits the saved rack before
source synthesis. After rendering complete source-derived notes it executes:

```
SYNTHLINE -> saved rack -----------+
EXCITER (unchanged roll slices) ---+-> existing SCULPT OR graph -> final output policy
```

The rack never receives the roll EXCITER, BODY, AUX or independent SUB stem.
Existing full-mix arrangement/reversebass/SCULPT remain in the retained Project;
existing synth-owned SCULPT/graph survive Compose compilation and remain after
the rack. Source IDs, source binding, factory recipes, default selection and
preset tiers are unchanged. The rack applies no master, normalization, hidden
limiter or export conversion. The original output policy executes once after
the preserved topology. PCM export serializes that completed result rather
than running another processor/master.

Ordinary Compose's accepted source-derived synthesizer is mono. The standalone
saved-rack PCM executor supports mono and linked stereo (including spectral
analysis/reconstruction), without downmixing. This does not invent a stereo
Compose source method or extend the legacy source's rate capabilities.
12/48 kHz are exercised numerically and through the actual service/API route.
Other accepted contract rates are subject to existing processor capabilities
and explicit resource rejection, not an implicit resample/downmix.

Long-form's independently rendered section consumer retains an explicit
pre-synthesis rejection for rack-bearing projects. Its section boundaries are
not established as equivalent context for zero-phase/stateful rack DSP. This
is separate from Compose full/region WAV export, which is implemented here.

## Shared processor composition and exact mix semantics

`zaaggenz_spectral.rack_executor.compile_rack` validates a defensive saved
snapshot, the complete source binding and every insert, including bypassed
ones. Unknown/unavailable processor versions, automation and VST3 descriptors
fail before audio allocation even behind bypass. Accepted built-in chains
retain at most one of each legacy stage per band and stable instance IDs.
No new schema or arbitrary duplicate-processor chain is introduced.

`process_builtin_stage` is the shared primitive dispatcher used by both
`process_band_selective` and the new executor. It calls the original compressor,
gain, bitcrusher, component analysis, retune and Chordness implementations.
All 24 old stage permutations have direct numerical parity tests, including
noncommutative and genuinely transformed spectral fixtures.

For a stage input `x`, processor `P`, and saved insert wet `w`, the result is
`x + w*(P(x)-x)`. At wet one, return `P(x)` directly to retain its exact rounding;
at wet zero, retain the original input exactly. Processor-internal wet remains
an independent original parameter, not a substitute for insert wet.

Each band's stages execute in its saved order. Band wet scales the completed
chain's difference from the original band. The existing effect-delta router
then optionally re-confines that difference to the band's declared pocket.
The original dry source is not rebuilt by summing crossover bands. Rack wet
finally scales the sum of routed deltas. Deliberate spill remains explicit;
confinement is not described as a brick-wall or zero-leakage guarantee.

Empty/all-disabled/unity racks retain original sample bytes, dtype and shape,
including signed zero, after validation. Null/identity anchors retain the
existing whole-slot identity rules: an amount-zero spectral stage inside a
nonidentity chain still observes the original float32 analysis boundary.
Parameter state is never reset by bypass. The existing bitcrusher's midpoint
quantizer can produce DC from zero input; its accepted numerical behavior is
preserved rather than replaced with a new silence shortcut.

## Measured diagnostics, not animated meters

A completed rack reports input/output peak, RMS, per-channel values, finite
status and fraction above unity. Each band reports its original band input,
processed output after band wet, final routed-output band measurement, saved
order and stage IDs. Stage measurements surround the actual operation.
Compressor gain reduction is the processor's actual detector/smoothing result,
labelled as before insert wet; it is not inferred from output/input RMS.
Spectral reports include actual changed/preserved counts, analysis diagnostics,
bounded decision-reason counts/examples, estimated/requested/realised frequency
ranges and confidence/abstention evidence when available.

Effect-delta leakage diagnostics retain their original definitions and are
labelled after band wet, before global rack wet. Final routed band meters
include global wet. Silence reports real zero levels except where an enabled
processor genuinely produces nonzero output. Identity inputs shorter than
eight samples retain exact PCM and report band meters as unavailable with a
reason, rather than synthesizing plausible-looking values. Nonidentity
multiband inputs shorter than eight samples fail explicitly.

Region rack diagnostics are deliberately labelled `complete-input-context`:
they measure the full render, not just the crop. Separate region length/peak,
waveform, event offsets and selection identity describe the selected output.

## Region context and the authoritative execution path

`TimelineService` uses the existing `make_render_executor` / `render_phrase`
path for ordinary preview, saved-project rerender and export. `region_executor`
renders the full phrase and existing tail context, then crops at exact sample
indices. Source, filter, compressor, component-analysis and spectral state are
never restarted at an arbitrary selection boundary. A short selection receives
no memory/work discount. Tests compare exact full-render PCM slices and show
that independently restarted filtering is not equivalent.

The default 120 ms debounce occurs inside an admitted worker before synthesis,
with cancellation checks at most 10 ms apart during this delay. Identical
pending requests adopt their computation. Different regions of one revision
may coexist; new authoritative document revisions cancel obsolete owned work.
This is bounded offline execution, not a hard-real-time throughput guarantee.

## Revision authority, cache and publication

The unified runtime injects its single `RuntimeSession` and shared
`JobScheduler`; a standalone Timeline owns one of each. The session exposes an
atomic `(generation, revision)` read for cheap cancellation/publication checks.
Generation distinguishes an A -> B -> A edit from the original A request.
Vocal proposal previews use the same executor but explicitly do not change
Compose's authoritative document; they remain tied to its captured generation.

The rack render cache identity includes the accepted source/recipe sonic state,
all rack/processor parameters, order, bypass, wet/confinement, rate/layout,
render spec and installed implementation identity. The latter hashes relevant
LF-normalized Python implementation bytes, the actual installed accepted
legacy source/SCULPT modules, and NumPy/SciPy versions. It is computed once per
immutable installed process; modifying code in-place requires a restart.
No-rack legacy cache keys are unchanged. Cosmetic rack labels do not create a
new DSP key, but publication still binds the complete recipe/revision metadata.

The service's private request key additionally includes owner namespace, exact
document revision, full recipe hash, region and authoritativeness. It reuses
the existing bounded scheduler result cache for explicitly keyed RENDER jobs;
there is no second cache, pool or hidden global source store. Cache hits must
match revision, full recipe, cache key and product before acceptance.

Admission precedes document replacement or cancellation of coherent work.
Invalid, over-budget or queue-full requests therefore leave the last coherent
project/audio intact. A worker checks its token and immutable session binding
throughout DSP and before completion. Scheduler completion commits cancellation
and cache insertion under its existing lock. Status exposes audio/meters only
for the current accepted binding; WAV delivery guards both before and after
serialization. Explicit cancellation revokes publication even after completion.
An old immutable artifact can remain available to owned Research evidence,
without being publishable as current Compose audio. Fresh explicit requests
may reuse matching cached bytes after an ABA edit, but old job IDs stay stale.
The existing frontend revision/epoch checks remain; `stale` is now terminal
rather than causing indefinite polling. Authorization/release gates remain.

## Finite resource and cancellation bounds

The existing scheduler owns queue, lane and retained-result limits. Timeline
uses one interactive and one background worker, queue caps 8 total / 4
background, and retained scheduler history 16; service ownership IDs are capped
at 64 after terminal/evicted records are removed. Other owners' jobs cannot be
read or cancelled through Timeline. An injected scheduler is never shut down
by closing one service. Cache byte/entry limits remain the scheduler's limits.

Rack policy `zg.saved-rack-full-context-budget.1.0.0` bounds context to 60 seconds,
working reservation to 256 MiB, track-frame evaluations to 250,000 and aggregate
FFT points to 256,000,000. The caller may choose a smaller working limit, not a
larger unbounded one. These are admission limits, not a claim that every
combination of maximum duration/rate/channels/stages fits. Existing STFT/kernel
capabilities can impose stricter explicit rejection.

The estimate reserves whole-context PCM, four-band/filter/delta/meter scratch,
original source synthesis separately, STFT/multiresolution allocations,
track/decision snapshots and reconstruction/least-squares matrices. Bands run
sequentially; peak live spectral memory is reserved while aggregate work counts
all executed analyses. A selected region never hides this cost. Finite real
PCM, supported shape/rate and finite-float32 representability are checked;
invalid output fails atomically, never repaired by normalization or NaN coercion.

Cooperative checkpoints were added without changing arithmetic: per band/stage,
per tracker candidate/track/frame, per reconstruction track/frame and every
1024 compressor smoothing frames. Existing numerical-library calls and source
operations remain bounded indivisible calls: cancellation is not claimed to
preempt an FFT/LAPACK invocation or provide a universal millisecond deadline.

## Reproducible validation and boundaries

Materialize the authenticated source once, then run with bounded numerical
threads using the existing repository requirements and mapped workflows:

```
python baseline/recovered_source/materialize_v2.py --out .
python -m unittest discover -s tests/rack -v
python -m unittest discover -s tests/dsp -v
python -m unittest discover -s tests/spectral -v
python -m unittest discover -s tests/components -v
python -m unittest discover -s tests/jobs -v
python -m unittest discover -s tests/runtime -v
python -m unittest discover -s tests/timeline -v
python -m unittest discover -s tests/melody -v
python -m unittest discover -s tests/longform -v
```

Rack tests cover every legacy order, 12/48 kHz mono/stereo, genuine retune and
Chordness changes, tones/impulses/accepted sources, leakage, all bypass scopes,
null/unity/zero-wet and fractional mixes, invalid hidden settings, short/empty/
large finite inputs, deliberate spill, memory/work rejection and cancellation.
Real service/HTTP tests cover exact WAV PCM and saved reopen, source ownership,
SCULPT/graph plus single master, cache mutation/hits, debounce, cancellation
before publication, stale/ABA rejection, queue/memory rejection and proposal
ownership. Workspace protocol identity tests cover the session dependency and
retain fail-closed unknown-import auditing.

The existing ZG-021 Linux/Windows jobs run the rack suite; no parallel private
runner or duplicate new workflow is introduced. Source ownership/reverse checks
remain required at the exact final head. A local numerical pass is not an
independent review, browser/Windows product acceptance or permission to weaken
inverse calibration fingerprints. Any inherited fingerprint transition must
have its own actual platform artifacts, preserve all numeric thresholds and
historical evidence, and serialize with concurrent #250's metadata ownership.
