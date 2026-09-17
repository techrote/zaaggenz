# ZG-015 verification record

ZG-015 is verified by `.github/workflows/zg015-listening.yml` on Ubuntu and Windows plus the dependency-aware repository gates selected by ZG-000. The workflow materialises the authenticated recovered source, installs pinned numerical/browser dependencies, runs the complete listening suite and accepted project/jobs/timeline/QC regressions, generates full-rate 48 kHz listening evidence, and executes a real Chromium workflow.

The accepted listening contracts preserve immutable RenderArtifact-derived source identity, explicit whole-file RMS matching, participant/trusted capability separation, semantic result validation, transactional retained-audio accounting and bounded in-memory evidence metadata.

## Corrective semantic validation (#105)

The result wire format remains `zaaggenz-listening-result/1.0.0`, but authoritative validation binds A/B and multi choices to exact presented stimulus IDs, binds annotations to the trial, defines completed/aborted/missing observation policy, and validates annotation time against the frozen presentation clock whenever trusted stimulus metadata is available. Live submission and trusted reopen supply that timing context.

## Corrective level-match numeric integrity (#122)

`ListeningAudioStore.match()` validates external dBFS controls before conversion, rejects non-finite source/derived PCM and metadata, stages candidate playback, and preflights retained-byte budget before publication. Numeric or budget failure cannot remove pre-existing deduplicated playback.

## Corrective physical audio accounting (#115)

`retained-pcm-physical-bytes-v1` is the single audio-store accounting contract. Raw PCM plus unique retained playback PCM must fit the configured store budget before mutation. Failed operations leave prior material intact and playback content is deduplicated safely by SHA-256.

## Corrective registry/export bounds (#132)

`retained-listening-metadata-json-v1` bounds active trials, results and canonical metadata/export work. Admission is transactional. Trusted repeated observations remain distinct rather than being silently deduplicated, and reopen/import cannot bypass the same effective limits.

## Durable exact-playback archives (#98)

`zaaggenz-listening-archive/1.0.0` adds a bounded self-contained binary transport while leaving all existing listening `1.0.0` record formats untouched. It embeds either the trusted or participant-safe existing bundle and exact content-addressed raw/matched PCM. The custom framing has no filenames or extraction paths.

Archive verification checks magic/framing, canonical manifest bounds, manifest digest, material/stimulus shape, exact SHA-sorted blob index, restored `retained-pcm-physical-bytes-v1` accounting, every audio SHA-256 and the absence of trailing data before bytes are exposed to the listening store. Import then reuses ordinary store and registry admission. Missing/corrupt/truncated/oversized material fails without render or rematch fallback.

The corrective regression suite proves:

- trusted export followed by destruction of the original service and fresh-service reopen is bit-exact;
- matched playback SHA-256 and bytes remain identical;
- mono and stereo shape/provenance survive;
- completed, aborted and missing results retain order/semantics;
- identical raw/playback bytes deduplicate in transport while reopening reconstructs #115 physical accounting;
- one-byte corruption and truncation fail before retained state is installed;
- blob-count and total archive bounds reject before import;
- hostile stimulus names remain inert metadata because the archive has no path namespace;
- participant archives remain blind and cannot be reopened as trusted evidence;
- trusted HTTP archive/reopen routes require the trusted capability;
- cancellation during atomic publication preserves an existing destination and leaves no partial file;
- legacy metadata-only bundle reopen still fails closed in a fresh runtime rather than manufacturing missing audio.

The archive follows only already-frozen RenderArtifact excerpt bytes and matched derivatives. It does not chase source locators or private-reference paths. Source/audio topology, match mathematics, ABX truth generation/scoring, result identity, Compose state and audible/DSP defaults are unchanged.
