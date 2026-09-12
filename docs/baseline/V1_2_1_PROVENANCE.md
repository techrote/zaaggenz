# v1.2.1 baseline provenance — ZG-001

## Recovered input

The owner supplied `zaaggenz-v1.2.1.zip` directly in the project conversation on 2026-09-12. It is the previously missing source input requested by ZG-001.

- SHA-256: `90be319a4660a637077df935a8ebcbd1bb4c3a629e28e2f6d4bfe62d88dfe8a8`
- size: 9,498,941 bytes
- ZIP integrity test: PASS
- regular files in archive: 77
- top-level directory: `uptempo-harmonic-noise-tools-v1.2.1-earth-ui-cachefix/`
- traversal/symlink audit: no absolute paths, `..` traversal entries or archive symlinks found
- recovered server version: `1.2.1-earth-ui`

The archive SHA-256 exactly matches the checksum recorded when the v1.2.1 Earth-UI cache-fix package was previously delivered in this project. This is the identity link used for baseline recovery; historical screenshots or partial code snippets were not used to reconstruct missing source.

## Repository import

To avoid colliding with zaaggenz programme documentation at repository root, the recovered runtime is stored as a compact, authenticated source payload under `baseline/recovered_source/`. `materialize.py` verifies the payload SHA-256 and creates ordinary runnable files beneath repository path `app/`.

Runtime payload:

- SHA-256: `eaf5d3ab822dfa121cd3b795d62619af9e62c041fb02de19f8dbeafb0014c919`
- regular files: 34
- multipart transport: `runtime_source.tar.xz.b64.00` … `.16`

The payload includes the Python runtime modules, HTTP server, CLI, browser UI, all 13 recovered smoke tests, launchers, requirements, and key JSON examples. Historical/generated WAV outputs are not imported as production source. This keeps the Git baseline small while preserving the actual runnable code and tests.

Materialize from repository root:

```sh
python baseline/recovered_source/materialize.py
```

Then run the application from `app/`.

## Recorded recovery environment

- Python 3.13.5
- NumPy 2.3.5
- SciPy 1.17.0
- Node available for `node --check web/static/app.js`

The recovered requirements declare `numpy>=2.0` and `scipy>=1.14`. Strict raw-array hashes in `baseline/V1_2_1_CONTRACT.json` are acceptance goldens for the recorded environment; cross-environment compatibility must additionally use sample count, structural invariants and declared numerical tolerances rather than assuming bit-identical floating point.

## Provenance boundary

This recovery establishes the owner-supplied application bytes and their project identity. It does not make new claims about third-party authorship, licences beyond the application's declared dependencies, or the provenance of historical rendered WAV outputs. Later dependency changes still require their own licence review.
