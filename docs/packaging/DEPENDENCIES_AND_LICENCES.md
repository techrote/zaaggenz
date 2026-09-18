# Dependency licences and redistribution audit

This file is the release-audit index for the canonical environment introduced
by issue #103. `pyproject.toml` remains the dependency/version authority.
Licence strings here are audit guidance, not a substitute for the installed
distribution's licence files or legal review.

| Dependency/tool | Role | Upstream licence family normally declared | Redistribution note |
| --- | --- | --- | --- |
| NumPy | runtime numerical arrays/FFT support | BSD-3-Clause | wheel licence files must be retained if redistributed |
| SciPy | runtime signal processing | BSD-3-Clause | wheel may include separately licensed numerical components; inspect release wheel |
| threadpoolctl | runtime numerical thread control | BSD-3-Clause | small Python runtime dependency |
| jsonschema | runtime contract validation | MIT | inspect installed METADATA/licence file for release candidate |
| referencing | runtime schema reference registry | MIT | inspect installed METADATA/licence file for release candidate |
| Playwright for Python | optional browser/dev acceptance | Apache-2.0 | not an ordinary runtime dependency; downloaded browsers have separate notices |
| build (PyPA) | test/dev wheel+sdist frontend | MIT | build-time only; not an ordinary runtime dependency |
| Node.js | external test/helper runtime | project-specific upstream terms | not bundled by this repair |
| Chromium via Playwright | external downloaded acceptance browser | BSD/third-party notices | not bundled by this repair |
| ffmpeg/ffprobe | external reference-audit executables | build-dependent LGPL/GPL and component terms | not bundled; record exact binary/version/configuration before any redistribution |

The JSON environment report records the installed version plus
`License-Expression`/`License` metadata when distributions expose it. Absence
of a metadata field is not evidence of absence of a licence.

## Project and recovered-source status

The repository had no canonical project-level licence file when this inventory
was created. `pyproject.toml` intentionally omits a project licence assertion;
ZG-045 must resolve redistribution terms before public package publication.

The recovered v1.2.1 runtime is a separately authenticated compatibility input.
Its byte identity and source provenance remain governed by
`baseline/recovered_source/README.md`, `baseline/V1_2_1_CONTRACT.json` and the
ZG-001 recovery tests. #103/#203 do not rewrite or relicense those recovered bytes. #203 packages the authenticated materialized runtime into pre-release wheel/sdist acceptance artifacts only after its existing hash-checked materializer succeeds; this is packaging of the accepted bytes, not a provenance rewrite.

Private/reference recordings are not package dependencies and remain excluded
from tracked release material unless redistribution rights are separately
established.
