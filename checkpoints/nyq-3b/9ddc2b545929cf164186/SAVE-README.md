# Nyquismic 3B Git preservation checkpoint

Source: this conversation, completed chunk 3B: piecewise-affine controls, coincident zero-phase reset and independent checkpoint oracle. Preservation only; not repository, kernel, audio or instrument acceptance.

## Immutable authority and identity

Repository: techrote/zaaggenz. Recorded and verified parent commit: b2f0d3f0e20fcef3ffbca162179a060ff9d625b4. Full parent tree: 97f10dbd2689af1c9e34bf53572c7760254a6ecb. PR candidate 0e0ae597c69a2d5552535f1e9936c3a288209823 is lineage only. Main still matched the parent at save preflight. No AGENTS.md exists in its verified 651-file inventory. Applicable docs/zaaggenz/briefs/AGENT_OPERATING_RULES.md was read; this save's explicit authorization overrides implementation/publication instructions.

Payload ID: 9ddc2b545929cf164186, the first 20 hex characters of SHA256 9ddc2b545929cf164186ca7ef380e713ac853ceb4187b0c3c483fc5dd241d5b7. It hashes the sorted original path/hash manifest: the 87 packet members under packet/, original/zaaggenz_3B_packet.zip and original/zaaggenz_3B_VERIFICATION.json. Lines are SHA256, two spaces, relative path, LF. Publication metadata does not modify original evidence or enter that identity.

Actual original archive: zaaggenz_3B_packet.zip, 540111 bytes, SHA256 3bb3676e1f6411ef7504f679bde278519b57621bb37021152b310c35d4c1d500. Its 87 files and 86 original checksum entries verified. The nested preceding/zaaggenz_3A_packet.zip is retained as prerequisite/provenance, not substituted for 3B; SHA256 f6bb7eae070cb8709b51510fe49b1681aa45183b495d64bc72323a996a67b893, 74 files, 73 checksums verified.

## Saved format and restore-path map

capsule/capsule-000.xzpart through capsule-006.xzpart concatenate to one lossless XZ preservation capsule. CAPSULE-MANIFEST.json specifies every fragment and original archive identities. RESTORE.py restores exact original file bytes and ZIP envelopes, checks original manifests and refuses existing output. The capsule includes all original path/hash/size records, ZIP metadata and 76 deduplicated novel text objects. The 37 unchanged source/dependency files are referenced by immutable parent path/blob; the complete inventory is reconstructed from that parent. This is not a partial tree replacement.

Run only in a new recovery directory, using Python stdlib and a clone containing the parent:

```sh
python checkpoints/nyq-3b/9ddc2b545929cf164186/RESTORE.py --repository /path/to/clone --output /new/external/recovery
```

This performs integrity/restoration only, never research or fixture generation. Exact original ZIP reproduction was verified with zlib 1.3.1; a different encoder must not be allowed to manufacture an alternative archive identity. Original byte-for-byte archives are also supplied in the separate local fallback. LOCAL-RESTORATION-VERIFIED.json records the successful save-time reconstruction, not a numerical test.

Restored zaaggenz-3B/ is the original 87-file packet root: CHECKPOINT.md, derivation/results/commands/environment/independence records, frozen fixture, comparison tests, deliberate-defect scripts, all logs, changes.patch, original source manifests and nested predecessor. Original source/ remains a 37-file export. Restore a full checkout at the pinned parent before any separately authorized patch application. No overlay is installed by this checkpoint.

The five original overlay destinations, stripping overlay/, are:
- docs/dsp/NYQUISMIC_PIECEWISE_RESET_ORACLE_V1.md
- tests/contracts/fixtures/nyquismic-piecewise-reset-v1.json
- tests/contracts/nyquismic_piecewise_reset_compare.py
- tests/contracts/nyquismic_piecewise_reset_oracle_v1.py
- tests/contracts/test_nyquismic_piecewise_reset.py

Other scripts, including scripts/run_deliberate_defect_controls.py, remain packet tools and must not become production code. changes.patch is an alternative representation of the same five additions, not a second set to apply. Old absolute paths in historical tracebacks are not restoration dependencies. New output belongs outside preserved records. Reconstruct the identity manifest from restored original paths and the external receipt when checking payload ID.

## Frozen identities and historical status

Generator SHA256: 8808bdeeb96f74785557bd9bd808150785f62481a763c500acfbc932f155dadf.
Fixture SHA256: 08f4c891adea10d4415d00d54b2d947b1337b154821333ec531c2caec08f17db.
Derivation SHA256: 74012675635a8d751b49f87eb73ce86b3a745e15c5bdc7d005ea73e665da255c.
Patch SHA256: 63f56ec5136ca1ccb45185136a4978127d613d28c324fe223ee9bab02c5d1976.

Retained logs/reports support seven captures, twelve exact checkpoint probes and eleven partitions; 14 new methods passed, 37 adjacent passed, and the same 14 passed a restoration/discovery repeat: 51 unique historical positive methods, not 65. Two disposable one-probe controls each produced the intended assertion failure and no errors. They are not production mutants or candidate defects. Save-time work verified bytes/records only; no suite, mathematics or frozen generator was rerun. The unchanged timing rule is 2e-12 seconds plus 8 ulps; exact counts, IDs, phases and membership remain exact.

Historical disposition: no reproduced defect in this one family. Universal/multiple/nonzero-reset coverage, hard spacing limits, playback, audio/filter history, Windows/native/browser and full CI/product acceptance are not established. Clock restore is not audio resume. SAVE-SUPPLEMENT.md retains precise failure observations and duration-record caution without altering the historical checkpoint.

## Destination safety, exclusions and next action

The exact branch prefix and payload destination were absent before writing. Inspected 42 pinned workflow trigger definitions: only zg001-recovery.yml has push, restricted to main; other definitions do not target checkpoint pushes. No workflow was changed/dispatched/monitored. Only this checkpoint directory is additive; every parent entry must remain unchanged. No PR, comment, issue change, merge, queue operation, shared-resource use or active test installation is authorized by this save.

No local-only deliverable was intentionally excluded. Unchanged source bytes are recovered from the retained full parent rather than duplicated; no credentials, restricted texts or unrelated private data are included. The exact external original receipt is ORIGINAL-3B-VERIFICATION.json; original inner manifests stay inside the lossless capsule. SAVED-SHA256SUMS covers this compact publication payload except itself.

Next action: verify the remote ref/tree and checksums, then restore this packet in isolation for any separately authorized continuation. Historical next reference was 3A R2 minimum-spacing admission; this save does not start it or authorize acceptance.
