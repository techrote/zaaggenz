"""Export original, unmodified 48-kHz float32 Nyquismic sweep WAVs as DAW stems.

This opt-in, offline postprocessor does not render, normalize, resample, mix, or
register a Compose graph node. It depends on the source-authenticating sweep
reader in nyquismic_rate_compare; it is not a general session exporter.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import zipfile

from zaaggenz_runtime import nyquismic_rate_compare as compare

FORMAT = 'nyq.original-daw-stems.v1'
_CHUNK = 1024 * 1024


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _check(cancelled) -> None:
    if cancelled is not None and cancelled():
        raise RuntimeError('NYQ DAW stem export cancelled')


def _file_sha(path: Path, cancelled=None) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(_CHUNK), b''):
            _check(cancelled)
            h.update(block)
    return h.hexdigest()


def _entry(archive: zipfile.ZipFile, name: str, data: bytes) -> None:
    # A fixed, safe ZIP envelope gives reproducible cold-reopen bytes.
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    archive.writestr(info, data)


def export_daw_stems(sweep_zip: str | Path, output: str | Path, *, cancelled=None) -> dict:
    """Stage then atomically publish original sweep WAVs; no destination clobber."""
    if cancelled is not None and not callable(cancelled):
        raise ValueError('cancelled must be callable')
    dest = Path(output).absolute()
    source = Path(sweep_zip)
    if dest.suffix.lower() != '.zip' or not dest.parent.is_dir():
        raise ValueError('output must be a .zip in an existing directory')
    if dest.exists() or dest.is_symlink():
        raise FileExistsError(str(dest))
    record = compare._verified_sweep(source, cancelled)
    _check(cancelled)
    stems = [('original.wav', record['dry'], record['source']['dry_pcm_f32le_sha256'], None, None)]
    stems += [(f'nyq-rate-{i:02d}.wav', v['wet'], v['wet_pcm_sha256'], v['rate'], v['packet_sha256'])
              for i, v in enumerate(record['variants'], 1)]
    # Each WAV was independently checked by the exact #292 verified-sweep reader.
    entries = [{'file': name, 'wav_sha256': _sha(wav), 'pcm_f32le_sha256': pcm,
                'virtual_rate_hz': rate, 'packet_sha256': packet}
               for name, wav, pcm, rate, packet in stems]
    manifest = {'format': FORMAT, 'source_sweep_sha256': record['archive_sha256'],
                'source': record['source'], 'sample_rate_hz': 48000,
                'frames': record['frames'], 'channels': record['channels'],
                'stems': entries,
                'scope': 'Original 48-kHz saved-Compose post-rack mix, not graph/rack final delivery'}
    body = (json.dumps(manifest, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8')
    fd, tmp_path = tempfile.mkstemp(prefix='.nyq-stems-', suffix='.partial', dir=str(dest.parent))
    tmp = Path(tmp_path)
    try:
        with os.fdopen(fd, 'w+b') as f:
            with zipfile.ZipFile(f, 'w', compression=zipfile.ZIP_STORED, allowZip64=False) as archive:
                _entry(archive, 'manifest.json', body)
                for name, wav, _, _, _ in stems:
                    _check(cancelled)
                    _entry(archive, name, wav)
            f.flush()
            os.fsync(f.fileno())
        _check(cancelled)
        archive_hash = _file_sha(tmp, cancelled)
        # A changed input cannot silently masquerade as the current sweep.
        if _file_sha(source, cancelled) != record['archive_sha256']:
            raise RuntimeError('source sweep changed before DAW stem publication')
        _check(cancelled)
        os.link(tmp, dest)  # create-if-absent even when another writer races
    finally:
        tmp.unlink(missing_ok=True)
    return {'format': FORMAT, 'absolute_path': str(dest), 'zip_sha256': archive_hash,
            'source_sweep_sha256': record['archive_sha256'], 'frames': record['frames'],
            'channels': record['channels'], 'delivery_hz': 48000, 'stems': entries}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Export original, unmodified Nyquismic sweep WAVs for DAW import')
    parser.add_argument('--sweep', required=True, help='Verified saved-Compose rate-sweep .zip')
    parser.add_argument('--output', required=True, help='New output ZIP (never overwritten)')
    args = parser.parse_args(argv)
    try:
        result = export_daw_stems(args.sweep, args.output)
    except (Exception, KeyboardInterrupt) as exc:
        print('NYQ DAW stems failed: ' + str(exc), file=sys.stderr)
        return 130 if isinstance(exc, KeyboardInterrupt) else 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
