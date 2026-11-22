# NYQ opt-in atomic 48-kHz file publication — bounded candidate

**Source lease:** new file only: zaaggenz_runtime/nyquismic_compose_file_export.py,
tests/runtime/test_nyquismic_compose_file_export.py, this document. Stacked on
#277 (itself stacked on #275 and the source-evidence-only #273). Do not merge
or register an ordinary product export until Integration independently qualifies
the complete main-based source assembly. This change does not edit graph/session,
#266, #267, #275, #277, programme authority, presets, UI, or any accepted default.

## Runnable opt-in output path

Call save_compose_controlled_48k_wav_file(binding, sonic, packet, evaluation,
absolute_wav_path) where binding comes from bind_completed_compose for a current
completed ordinary Compose job; packet must be the authenticated authored-route
controlled-clock packet covering the **actual full source asset** physical extent.

The function executes the existing #277 pipeline (real Compose source -> #267
clock -> #266 SamplerPlan -> pinned final FIR -> verified 48,000 Hz IEEE-float32
WAV bytes), then stages that WAV to an exclusive same-directory temporary file.
It fsyncs the file, verifies the staged byte SHA-256 against the authenticated
in-memory WAV receipt, and refuses stale jobs/edits or cancellation before
publication. The final operation holds the existing #275 job lock followed by
the document lock, rechecks current owned-job and session generation, samples
cancellation, checks ownership again, and atomically hard-links the staged inode
to the requested destination. The temporary name is then unlinked.

**No overwrite:** a destination already present before rendering or created by
an external process during rendering is never overwritten. The final hard-link
operation is an atomic no-clobber name publication on supported filesystems.
Unsupported hard links cause a fail-closed exception; no fallback to racy
pre-check plus overwrite rename. Destination parent must already exist, and
the explicit target must end with .wav.

The frozen SavedControlledWav48k receipt identifies output path, original
source/recipe/packet, sampler-to-WAV pipeline identity, WAV and float32 PCM
SHA-256, channel count, and frame count. Files remain valid historical exports
if the user edits the project *after* publication; a saved file is not an
ongoing authorization token for the current graph.

## Verify

Focused original-host test:

    python -m unittest discover -s tests/runtime -p 'test_nyquismic_compose_file_export.py' -v

Existing changed dependency and relevant integration tests:

    python -m unittest discover -s tests/runtime -p 'test_nyquismic_compose_delivery.py' -v
    python -m unittest discover -s tests/runtime -p 'test_nyquismic_compose.py' -v
    python -m unittest discover -s tests/runtime -v

The seven new synthetic-Compose tests check a real decodable on-disk float
WAV/PCM hash and nonzero audio, no clobber of an existing user file, project
edit during staging, owned-job revocation, caller cancellation after staging,
a competing external path creation at commit, and fail-closed invalid path.
All tests use disposable local output paths and no private recordings.

## Boundaries

This is a filesystem-delivery building block, not an approved UI action,
registered Compose exporter, graph/per-band insert, saved NYQ preset,
upstream-feature authority or broad output-format selector. It deliberately
does not replace the application's current export handling. The source
binding retains #275's same-process authority boundary. The staged file is
fsynced, but cross-platform parent-directory crash durability is not asserted;
the no-clobber hard-link primitive requires filesystem support. No external
plugin or dependency is added. No audio normalization, clipping, dither,
default change or owner-audition claim.

Integration must independently qualify exact-head source/PCM numerics,
late-publication semantics, original Ubuntu/Windows CI, ZG-024a and ZG-000
reverse-dependency results before any guarded admission. #252 and #253
remain unaccepted, #254 blocked, and MBR #242 physical and spectral gates
unaffected.
