# Save-time supplement — retained 3B evidence only

This is an additive preservation note, not a revised research result. Source is
this conversation's completed chunk 3B for techrote/zaaggenz. No new numerical
work, fixture generation or test execution was performed for this save.

## Findings available at save time

The actual retained packet is zaaggenz_3B_packet.zip, 540111 bytes, SHA256
3bb3676e1f6411ef7504f679bde278519b57621bb37021152b310c35d4c1d500.
Its 87 files are readable; the original SHA256SUMS covers the other 86 files.
The nested preceding archive is a prerequisite/provenance record, not the main
payload: preceding/zaaggenz_3A_packet.zip, SHA256
f6bb7eae070cb8709b51510fe49b1681aa45183b495d64bc72323a996a67b893.
Its 74 files are readable and its 73 manifest entries verify. Standalone 3B
checkpoint, derivation, results and patch bytes equal their packet counterparts.

The retained new-tests JSON/log reports 14 passing methods. Adjacent JSON/log
reports 37 passing methods. Applied-patch JSON/log reports the same 14 methods
passing again, not additional unique coverage. These are 51 historical unique
positive methods and a 14-method repeat, not fresh tests performed by this save.
The fixture/report records seven captures, twelve checkpoint probes and eleven
partitions. This save checks retained records and bytes, not their mathematics.

The two deliberate-defect records each report one intended AssertionError and
zero errors. Their harness exit code is 0 because detection was expected.
The controls are one-probe output adapters, not full production-source mutants:
reset-restarted automation gives 17/16 rather than 47/32 at 19/8; an inclusive
past count gives 3 rather than 2 at 9/4. Do not relabel either as a candidate defect.

## Restoration requirements and limits

Use recorded base b2f0d3f0e20fcef3ffbca162179a060ff9d625b4, Git tree
97f10dbd2689af1c9e34bf53572c7760254a6ecb. The earlier PR candidate
0e0ae597c69a2d5552535f1e9936c3a288209823 is lineage, not a substitute base.
The packet source directory is a 37-file export, not a complete checkout. Keep
the full parent tree when preparing a restoration; the five overlay files and
changes.patch are additions only. Do not apply them during checkpoint saving.

Historical scripts contain the old temporary work path in logs/tracebacks. That
path is not a prerequisite. Packet README/COMMANDS supply relocatable roots.
Put any later replay output outside the preserved packet. The fixture generator
must not be run against its frozen output. Original manifests and the external
archive receipt must remain distinct from saved-payload/publication metadata.

The packet checkpoint was finalized at 16:36:53 UTC and its external receipt at
16:37:52 UTC on 2026-10-04; the receipt reports 14.872 minutes since chunk start.
The conversation's interface duration is not substituted for these retained
records. No tests were rerun to resolve duration/reporting differences.

No candidate defect or material contract contradiction is recorded for this one
family. Universal/multiple-reset/nonzero-reset, hard spacing limits, playback,
audio/filter history, native/Windows/browser/product and full CI acceptance remain
unverified. Audio restore is unavailable. The historical next reference was 3A R2
minimum-spacing admission; this save neither starts it nor authorizes acceptance.

No additional unwritten derivation or failure reproducer was available beyond
these retained records. This note adds restoration and interpretation cautions;
it does not invent missing calculations or waive incomplete coverage.
