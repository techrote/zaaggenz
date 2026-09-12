# Recovered v1.2.1 runtime source payload

ZG-001 recovery input: owner-supplied `zaaggenz-v1.2.1.zip` on 2026-09-12.

- original ZIP SHA-256: `90be319a4660a637077df935a8ebcbd1bb4c3a629e28e2f6d4bfe62d88dfe8a8`
- original ZIP size: 9,498,941 bytes
- original top directory: `uptempo-harmonic-noise-tools-v1.2.1-earth-ui-cachefix/`
- runtime payload SHA-256: `eaf5d3ab822dfa121cd3b795d62619af9e62c041fb02de19f8dbeafb0014c919`
- runtime files: 34 regular files under archive prefix `app/`

The original archive contains many historical/generated WAV outputs. They are excluded from this compact runtime payload; their identities are retained in the ZG-001 source-archive manifest. The payload includes the Python application/runtime modules, web UI, all 13 recovered smoke tests, launchers, declared requirements and the two key JSON examples needed for baseline inspection.

The multipart `.b64.00`…`.b64.16` files are an authenticated transport representation, not the application format. To create normal repository files from a checkout, run from the repository root:

```sh
python baseline/recovered_source/materialize.py
```

The materializer concatenates exactly 17 parts, validates Base64, verifies the decoded XZ payload SHA-256 above, rejects unsafe tar members, and then creates `app/`. It refuses to overwrite existing regular files unless `--replace` is explicit.

After materialization:

```sh
python -m pip install -r app/requirements.txt
cd app
python -m py_compile webapp.py uh.py uptempo_harmony/*.py
node --check web/static/app.js
for t in tests/*_smoke.py; do python "$t"; done
```

Recorded recovery environment: Python 3.13.5, NumPy 2.3.5, SciPy 1.17.0. The application declares `numpy>=2.0` and `scipy>=1.14`.

This packaging preserves the recovered bytes without overwriting the zaaggenz programme documentation at repository root. Once materialized, downstream implementation work should use the normal `app/...` paths; do not edit the multipart payload as source code.
