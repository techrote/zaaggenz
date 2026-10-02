# MBR-002 — inverse compatibility evidence

Scope: #240 / PR #261. This records the narrow inherited ZG-024a
implementation/validation transition created by the real saved-rack execution
path. It is evidence metadata, not a new calibration, comparator, preset,
schema, or inverse-research result.

## Serialized predecessor

NYQ-001 / PR #260 was allowed to complete first because it owned the same two
transition registries. Its exact final head `0e0ae597c69a2d5552535f1e9936c3a288209823`
passed all native and reverse checks and merged to main as
`b2f0d3f0e20fcef3ffbca162179a060ff9d625b4`. MBR-002 then merged that main
into its branch without conflicts before collecting successor evidence.

The accepted NYQ implementation identity is
`f562faec6d279b090ff0da28b7c73fc24082d875e2fa3d9c87cc50d95072bcd3`. The immutable calibration still has predecessor
`ff938e70ba2598d5f6f6f0bc305e01b580c373a8e5daca849e8d3f9392bee3a4`; transition rows continue to use that frozen calibration
identity in `from_implementation_sha256`.

## Actual pre-registration platform evidence

ZG-024a run **37054053752** tested exact MBR-002 head
`c3c0d5003578b789796dda7c96231af7e18e1bf5` after the NYQ merge and after the safe shared-render binding
compatibility correction. The latter changes `zaaggenz_timeline/service.py`,
which is outside the inverse implementation-manifest roots.

| Platform | Artifact | ZIP SHA-256 | report evidence_sha256 |
| --- | ---: | --- | --- |
| Ubuntu | 11247414378 | `16473cd2bac3584f29788af26b6e19e66fb2d3c3375784219597118fecfcf45d` | `cd146f2704c8b898f1e31513fe86ea31dbc477c13e5087824d915083997296af` |
| Windows | 11247686471 | `760c5f9d64c1c19edd3eb4ea906a7dc29f66ff5d8100464b89cc85de1aa1e926` | `4b774b29506ffa0a6012a8d35d6ee14b1e6912eae613f846eeca37391e81e8d8` |

Archive/member hashes were verified after downloading the actual Actions ZIPs.
`inverse-evidence.json` SHA-256 is
`3029ebd4ea13b5a5665003847cbdd46ab1dc09012aec4e6ef4ada1bc6974ba63`
on Ubuntu and
`f10cf52ef8bffeb3160449a15297983c47e798e0e976c6fc81cf2dc9c6ba0bbb`
on Windows. `inverse-full.json` SHA-256 is
`4d2f3622c8cac652751d407bf59a5198ab05740f515b5b25c58476fd44c21a4c`
and `080efc42f47419ea6ab7c7ee94960ffc9807c89582f8aa89136e1864c15966d3`
respectively.

Both reports contain six fixtures and 36 candidates and independently compute
implementation identity
`9da1f1f521292f0dd0e2ca444521260aa91301526d9798573289149736b33e6a`. Before registration, each unchanged comparator reports exactly
eight differences: that one unreviewed implementation identity plus the same
seven already-reviewed #87 transient-v4 validation state/gate projections.

Using the repository's `calibration_reference` / `portable_projection`
selection and unchanged absolute tolerance 1e-7 / relative tolerance 1e-5,
direct Ubuntu-versus-Windows comparison has **zero portable failures**. This is
a numerical portability result under the declared comparator, not a claim that
the platform evidence files or PCM are byte-identical.

## Exact implementation manifest delta

The accepted NYQ Ubuntu artifact was compared with the MBR-002 Ubuntu artifact.
NYQ contains 107 implementation source files; MBR-002 contains 108. Exactly nine
manifest entries differ and no other entry changes:

| Path | accepted NYQ SHA-256 | MBR-002 SHA-256 |
| --- | --- | --- |
| `zaaggenz_components/reconstruct.py` | `fe272515c86a032871eec074c7a92c8ee3f23acfe4cc95965cc2eb6da2d48ea5` | `0695c0013680de868b5584720f344eae1f0d96991e03c515f5e28639b36397eb` |
| `zaaggenz_components/tracker.py` | `1781cb6c51dd78449ca789fb8b6a12826c748f530f15e8f98d1e28cb2efd92b2` | `75f7da66e665bd9c3aee9869a34d7a2a75c4d57e0d3a59b24454f848a53ca9aa` |
| `zaaggenz_dsp/band_router.py` | `6b8f516b93582837cc2f47694766c916cc29ea33a78bcc1f7c95016fc037c9a1` | `1c4bf9600c09a6afa27c0e009b06112ed8ce431b4d8e3b620eb82baa8bb2fd7b` |
| `zaaggenz_dsp/dynamics.py` | `1f3d5af62e82940a01a9c2571725f711892f572a7aef97b275c1b7cb9d06f808` | `fad3480e42b0e4b5f97f2f77fdafc9e599bf7625b98f6d8e31159ff84e843335` |
| `zaaggenz_jobs/scheduler.py` | `d20afab5a11f2ad7892a01053eef0a43f09ca00494f80fae670dd92eaea388e1` | `80935fe95b1f79c39aad99d1bba9a839b4672b56f3702c3c4be5465338f35454` |
| `zaaggenz_spectral/band_selective.py` | `9845de80afdd6fbdee732119b2fc94785970f00309451d10d95ac59fc8000d4b` | `96fb1e7af2c12add2631b93d67c76a874e50d2abb7b147cdb1b625904a0b7559` |
| `zaaggenz_spectral/chordness_engine.py` | `6e2789996b6e68bad557b47870da9d2c65bdfcf580b30b7bbeb0da3e615216dc` | `9a5bd53fbada45f11392b290d14fa37106a22c56b07c5134a00053a6b3a699fc` |
| `zaaggenz_spectral/engine.py` | `b597e28c94f7bd21ae9e7e1ad102e48727c3d526ecd3cbccdf770d6dbbc4b10e` | `46f1fa97d32bca03752b8072d5cd46e7d4cec046a01b7a9ddc8e72abc22e04fe` |
| `zaaggenz_spectral/rack_executor.py` | absent | `47782349e6e7efee891fbab0f96d66dd93adad38ba76e9af239f6bed2611ae3b` |

These are exactly the paths recorded in the #240 implementation-transition row.

## Fail-closed registration

The implementation registry receives one exact #240 / ZG-021 successor row.
The validation registry receives one #240 / ZG-024 row carrying forward the
seven path/from/to values verbatim from accepted NYQ identity `f562faec6d279b090ff0da28b7c73fc24082d875e2fa3d9c87cc50d95072bcd3`.
No other historical row changes.

`tests/inverse/test_mbr002_transition.py` checks the exact successor, issue,
stable ID and manifest paths; exact seven-delta carry-forward; unknown-successor
and unauthorized-state rejection; numeric/recipe drift rejection; and evidence
hash tamper rejection. Its constructed successor is only a comparator fixture,
never replacement render evidence.

The compressed calibration, comparison code, tolerance values, objectives,
scores, ranks, recipes, budgets, protected source/factory audio, accepted rack
schema and presets remain unchanged. Because these registry/test/documentation
files are outside the implementation-manifest roots, this metadata append does
not change `9da1f1f521292f0dd0e2ca444521260aa91301526d9798573289149736b33e6a`.

Exact-final-head native and reverse-dependency CI must pass after this append
before PR #261 may merge or #240 may be closed.
