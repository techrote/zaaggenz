# NYQ-002 — platform evidence and inverse compatibility

Scope: #251 / PR #265. This records the actual platform artifacts for the
fractional-event sampler and the exact inverse implementation/validation
registration they justify. The inverse manifest deliberately includes all
Python sources in its declared packages, so adding the sampler changes that
identity even though this issue does not insert Nyquismic into inverse recipes.

## Serialized source baseline

NYQ-001 / #250 was accepted before the sampler implementation began. The final
reviewed MBR-002 / PR #261 source candidate
`3eb0a3c58053843b36ff8b05319ba8c4398f2a9a` was integrated before collecting the
NYQ-002 platform evidence. Its inverse implementation identity is
`9da1f1f521292f0dd0e2ca444521260aa91301526d9798573289149736b33e6a`.
NYQ-002 final acceptance must follow acceptance of that MBR base; collecting and
reviewing the metadata while its final gates finish does not waive that order.

The immutable calibration retains implementation identity
`ff938e70ba2598d5f6f6f0bc305e01b580c373a8e5daca849e8d3f9392bee3a4`.
Its compressed file SHA-256 remains
`4dfde21014b1863177db5416c0b285c0c2648f579d0d418f80f0afd8506d2761`.
Both new transition rows therefore start from the original calibration identity.

## Actual pre-registration inverse evidence

[ZG-024a run 41549879763](https://github.com/techrote/zaaggenz/actions/runs/41549879763)
tested exact head `0b1ea16fc69dcd2bcc3b63bc8f7511fb7c62fd2e`, source tree
`5487790d8a75dfcf7e4e8b86568a3c68fe027831`, before either new registry row existed.
The Ubuntu and Windows jobs reached the frozen-calibration comparison, reported
the expected unregistered successor, and uploaded their actual generated
reports and complete replay records.

| Platform | Artifact | ZIP SHA-256 | Report evidence SHA-256 |
| --- | ---: | --- | --- |
| Ubuntu | 13190392636 | `40819f25cfe2f7300938ec0007962d2c8fc5e63c2ebbfab42c53bc649eb15b41` | `56cb791b4912679e334a97f28845f791cbc0ff656d43f02effeca74e9c01fe14` |
| Windows | 13190477943 | `4904a0d799cd4f26d14255b6716c1222f27f8474a7c0fd7df04f7abff3cc884c` | `9d6871aa154f5d88f4c6af533c189b6b5f7591d8368876fab4372eee06b761de` |

The downloaded archives match the GitHub artifact digests. Their exact member
hashes are:

| Member | Ubuntu SHA-256 | Windows SHA-256 |
| --- | --- | --- |
| `inverse-evidence.json` | `f102512a546536a3c81d3ae899c9d6d2b4c6ae900f993a458a0cbc952b6d8ed5` | `6c7a99b3e53b0c33b92f0384d9d7129aeb61d07f738b12bb3c4232311f49be81` |
| `inverse-full.json` | `1d9f9a6008d61fffe04d77e7f8428807a2000fb10730c3e288bd0e5d94443e9a` | `27b09fa672163ae44035b5a22c2a7b8409f2cd5873b489d0000ec36e52df6f05` |
| `inverse-timing.json` | `a99e64affd93ccfe3bbb74a9cbe20ad42500b7135e09db381395b04c5ba3a20e` | `abf31b93dfd593a32cf83d4a2a9e1b177f5b6f199d8ede24fbc69c39b2df8273` |

Both reports have six fixtures, 36 candidates, and the same 109-file manifest,
which exactly matches the tested sources. Recomputing each report's canonical
evidence hash succeeds. Full search-result hashes, candidate/recipe identities,
checkpoints, and fit/holdout/whole-signal summaries agree with the compact
report; telemetry references the same evidence identity.

The computed implementation identity on both platforms is
`9624e0bbfa30a34c17303573d7a48a46ee2f0ce3814dfdf209e2404a89ff8497`.
The unchanged `calibration_reference` and `compare_reports` functions report
exactly eight pre-registration differences on each platform: the unknown
implementation plus the same seven historical #87 transient-v4 validation
state/gate changes. There are no additional numeric, recipe, rank, eligibility,
budget, or source-definition differences.

Direct Ubuntu-versus-Windows calibration-reference comparison returns zero
failures under the original **ATOL 1e-7 / RTOL 1e-5**. Both platform references
also compare without failures against the separately generated local report,
whose internal evidence SHA-256 is
`059b0ead7eea0dc80d04b7b72dea4246d1465bb81ccffa3b6e8370f3b71e480e`.
The local report supplements the actual platform pair; it does not replace it.

## Exact source-manifest change

Comparison with the actual final-candidate MBR Ubuntu artifact 13189514086 from
[run 41549325055](https://github.com/techrote/zaaggenz/actions/runs/41549325055)
finds precisely these three changes. MBR has 108 manifest entries; NYQ-002 has
109. All other source hashes and manifest policies are identical.

| Path | Reviewed MBR SHA-256 | NYQ-002 SHA-256 |
| --- | --- | --- |
| `zaaggenz_contracts/nyquismic.py` | `60be0547faba711ad93555fa3747bb5a5ad8bcc9ff1637f330f9350fde41584d` | `ce4436b6653da261c889b9d4af02eade7c64d5d7520c8755507ad6f8a4f543cd` |
| `zaaggenz_contracts/nyquismic_clock.py` | `a47027c1a9c75e1851a4a9d52aa9607580de082b8d83a87391b26a1949c5a196` | `a96cef63025f420b7e920ecbd26ccc66e9dd237bcdb0efc62d19c8d4388fcc67` |
| `zaaggenz_dsp/nyquismic.py` | absent | `08ed328da73acd8c6d6cfacb06ed168b8e5a1dae056d7bcda5d5433170d4e2b9` |

## Sampler, clock, and independent-oracle artifacts

At the same exact head,
[ZG-016 run 41549879436](https://github.com/techrote/zaaggenz/actions/runs/41549879436)
passed on Ubuntu and Windows, including the independent fractional-event audio
oracles and the actual sampler report generator.
[ZG-002 run 41549879581](https://github.com/techrote/zaaggenz/actions/runs/41549879581)
also passed both platforms' contract and legacy-equivalence gates.

| Platform | NYQ artifact | ZIP SHA-256 | `report.json` SHA-256 |
| --- | ---: | --- | --- |
| Ubuntu | 13191305011 | `5d911a6027b96b2f60d2e70ea7680923cd33103a98b2efa581d76eeab96f2f9f` | `57edaa863405dd1d6613e21f174078aaf11e5be403f70dfbd21725844f83b670` |
| Windows | 13190636900 | `8ddcc852916d91ffea32f2e25cee4d7a5887302d30fa44c2e4494445abbda860` | `cd3a9fea3dd3f03f4a8727a847e81fcf2d16a70f6af9f3bb2a960848c91cb650` |

Each artifact contains ten actual examples at 12 and 48 kHz, with fractional
11,137 Hz hold, 11,730 Hz linear reconstruction, nearest capture, a linear clock
ramp, and reset/step timing. The 32 declared members include two original
synthetic source WAVs, ten raw output WAVs, ten separately RMS-matched listening
derivatives, and ten saved specification/evaluation/source/render/checkpoint
JSON records. Every member's recorded size and byte hash was checked against
the downloaded archive; all 22 WAVs are finite float32 with the declared rate
and extent. Each report binds the tested head and matching source/oracle hashes,
and records exact whole/chunk/resume and region agreement for all ten examples.

The source hash policy normalizes UTF-8 text to LF; output-member and WAV hashes
use exact bytes. The original clock fixture remains
`b42b2d9988df822169d8fd6e02a28dd208eff2b1e0ddf4a2d15df13c6c9ee5bd`,
and the independent audio-oracle source remains
`84737f6fa48a12a974da7c84b6f35c46134c4234abbaaaea9ef92d5be70fbed6`.
WAV sample values happened to agree exactly across this platform pair. That
observation is not a broader cross-platform identity, final antialias/SRC,
quality-convergence, owner-listening, or musical-improvement claim.

## Narrow registration and rejection checks

Only one #251 / ZG-016 implementation row is appended for the exact successor
and three manifest paths above. Only one #251 / ZG-024 validation row is
appended, copying the seven existing MBR path/from/to values verbatim. Before
editing either registry, applying these candidate rows in memory to both
actual platform references reduced the comparison failures from eight to zero.

The complete historical prefixes remain frozen:

| Registry prefix | Rows | Canonical digest |
| --- | ---: | --- |
| Implementation transitions through MBR-002 | 33 | `85b4f1da52692f7a60560da6d7eaf97426cc25e54ad61bf0e1e63210fc7bf32f` |
| Validation transitions through MBR-002 | 8 | `024b8bc464e270dc1b960c4019101d6dcd3b0c256224f14c16533726a2834d18` |

`tests/inverse/test_nyq002_transition.py` verifies those prefixes, the unchanged
calibration bytes, exact successor/issue/stable-ID/path metadata, and verbatim
seven-delta carry-forward. It rejects unknown successors, validation migration
without the exact implementation row, unauthorized validation states, numerical
score changes, recipe/source-definition changes, eligibility/rank/budget drift,
and evidence-hash tampering. Its constructed successor is explicitly a
comparator regression fixture, not generated audio or replacement evidence.

Run the focused registration tests with:

```sh
PYTHONPATH=.:app python -m unittest discover -s tests/inverse -p '*transition*.py' -v
```

Reproduce the existing frozen-calibration gate with:

```sh
PYTHONPATH=.:app python tools/inverse_foundation_report.py \
  --out inverse-evidence.json --full-out inverse-full.json \
  --telemetry-out inverse-timing.json \
  --check examples/zg024a_inverse_calibration.json.gz \
  --implementation-transitions examples/zg024a_implementation_transitions.json \
  --validation-transitions examples/zg024a_validation_transitions.json
```

The append changes no implementation source, independent fixture/oracle,
calibration, comparator, tolerance, default, preset, or programme-readiness
state. These registry/test/documentation files are outside the implementation
manifest roots, so the successor remains `9624e0bb...8497` after registration.
Exact-final-head direct and reverse-dependency CI must pass before PR #265 may
merge or #251 may close. The pre-registration failures above are historical
evidence of a fail-closed gate, not permission to skip final reproduction.
