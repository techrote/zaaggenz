# Recovery repair and completion-claim correction

Live inspection found PR #49 unmerged, main at `8617ec05680593a64bad628b1dd4cebccba7d176`, and CI run 34691499466 failing before the smoke tests. My preceding claim of successful post-merge verification was incorrect. Issue #2 was reopened. This record supersedes that claim; a new merge and successful CI must be evidenced separately.

## Root cause and repair

The transport text of part 14 was corrupted and had an unexpected suffix. Cropping the text did not fix its content. The original owner ZIP was checked again (SHA-256 `90be319a4660a637077df935a8ebcbd1bb4c3a629e28e2f6d4bfe62d88dfe8a8`). Reconstructing the sorted GNU tar with the recorded metadata and xz -9e -T0 reproduced the ORIGINAL runtime SHA-256 `eaf5d3ab822dfa121cd3b795d62619af9e62c041fb02de19f8dbeafb0014c919` exactly. All other intended part Git blob hashes matched; corrected part 14 is `be161a3fa8f7f69dd6631ffe1a9a7dd473efea34` (7000 characters). The expected payload hash has not been weakened or changed.

The strict materializer now rejects extra non-whitespace text, missing/truncated parts, hash mismatch, unsafe/duplicate archive paths, links and conflicting destinations before writing. It bounds decompression, preserves ordinary executable modes without setgid, writes individual files atomically and permits an unchanged idempotent re-run. Whole-directory crash-transactionality is not claimed; use an empty output directory for a clean verification. `materialize.py` now delegates to the same verifier so documented entrypoints agree. Obsolete multipart subparts from the earlier failed transfer are not inputs to the explicitly enumerated 17-part archive.

## Local evidence

Eight recovery tests passed, including corruption, suffix, truncation, missing part, overwrite refusal, symlink refusal and non-directory ancestors. The reconstructed 34-file runtime passed Python compilation, JS syntax validation and all 13 recovered smoke scripts with PYTHONPATH set to app and one BLAS thread. No recovered audio/UI source file was modified.

## Interpretation fixes

The legacy final MASTER applies linear gain and then clips to [-1,1]; its linearity holds only below that clipping threshold. Its smoke test deliberately verifies clipping at positive gain. Do not call it unconditionally linear or silently replace it with a limiter. The compact source payload contains runtime files and two JSON examples, not every historical document/output in the original ZIP. Future edits should be ordinary tracked modules, not changes to compressed source chunks.

G0 integration is accepted only after successful repository CI and a confirmed merge. Local passing tests alone are not evidence that main has changed.
