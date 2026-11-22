"""One-command saved-Compose -> original 48-kHz multi-rate DAW WAV archive.

Opt-in offline post-Compose full-mix export. Reuses source-authenticated sweep
and DAW WAV packaging; no registered graph node, GUI export, or new renderer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

from zaaggenz_runtime import nyquismic_audition_sweep as sweep
from zaaggenz_runtime import nyquismic_daw_stems as stems

FORMAT = 'nyq.saved-compose-direct-daw.v1'
_CHUNK = 1024 * 1024


def _check(cancelled):
    if cancelled is not None and cancelled():
        raise RuntimeError('NYQ direct DAW export cancelled')


def _sha_file(path: Path, cancelled=None, *, max_bytes=None) -> str:
    digest = hashlib.sha256()
    size = 0
    with path.open('rb') as handle:
        for part in iter(lambda: handle.read(_CHUNK), b''):
            _check(cancelled)
            size += len(part)
            if max_bytes is not None and size > max_bytes:
                raise ValueError('saved Compose project exceeds 2 MB')
            digest.update(part)
    return digest.hexdigest()


def export_saved_compose_daw(
    project_path: str | Path,
    output_path: str | Path,
    *,
    virtual_rates_hz: tuple[str, ...] | list[str],
    evaluation_rate_hz: int = 192000,
    wait_seconds: float = 120.,
    cancelled=None,
) -> dict:
    """Render each virtual clock and atomically publish one verified WAV ZIP.

    Intermediate rate-sweep artifacts remain temporary. Each underlying stage
    checks the original saved-project identity, PCM and packet receipts. This
    final stage repeats project and archive checks before no-clobber commit.
    """
    if cancelled is not None and not callable(cancelled):
        raise ValueError('cancelled must be callable or None')
    rates = sweep._rates(virtual_rates_hz)
    if type(evaluation_rate_hz) is not int or evaluation_rate_hz not in sweep.EVALUATION_RATES_HZ:
        raise ValueError('unsupported evaluation rate')
    if type(wait_seconds) not in (int, float) or not 0 < wait_seconds <= 3600:
        raise ValueError('invalid per-variant render timeout')
    dest = Path(output_path).absolute()
    if dest.suffix.lower() != '.zip' or not dest.parent.is_dir():
        raise ValueError('output must be a .zip in an existing directory')
    if dest.exists() or dest.is_symlink():
        raise FileExistsError(str(dest))
    project = Path(project_path)
    if not project.name.endswith('.zgtimeline.json') or not project.is_file():
        raise ValueError('project must be an existing saved Compose .zgtimeline.json')
    source_sha = _sha_file(project, cancelled, max_bytes=sweep.MAX_PROJECT_BYTES)
    _check(cancelled)

    with tempfile.TemporaryDirectory(prefix='.nyq-direct-daw-', dir=str(dest.parent)) as folder:
        stage = Path(folder)
        sweep_path = stage / 'rates.zip'
        stems_path = stage / 'original-and-nyq.zip'
        sweep_receipt = sweep.export_saved_compose_rate_sweep(
            project, sweep_path, virtual_rates_hz=list(rates),
            evaluation_rate_hz=evaluation_rate_hz,
            wait_seconds=wait_seconds, cancelled=cancelled)
        _check(cancelled)
        if (sweep_receipt.get('project_file_sha256') != source_sha or
                sweep_receipt.get('rates_hz') != list(rates) or
                sweep_receipt.get('archive_sha256') != _sha_file(sweep_path, cancelled)):
            raise RuntimeError('saved Compose sweep receipt/source mismatch')
        stem_receipt = stems.export_daw_stems(sweep_path, stems_path, cancelled=cancelled)
        _check(cancelled)
        if (stem_receipt.get('source_sweep_sha256') != sweep_receipt['archive_sha256'] or
                stem_receipt.get('delivery_hz') != 48000 or
                stem_receipt.get('zip_sha256') != _sha_file(stems_path, cancelled) or
                len(stem_receipt.get('stems', [])) != len(rates) + 1):
            raise RuntimeError('NYQ WAV stems receipt/source mismatch')
        if _sha_file(project, cancelled, max_bytes=sweep.MAX_PROJECT_BYTES) != source_sha:
            raise RuntimeError('saved Compose project changed before DAW publication')
        _check(cancelled)
        # The hard link is the no-overwrite commit. Revalidate immediately AFTER
        # it too: cancellation or an external project edit can arrive between
        # the final preflight check and the filesystem operation.
        staged_stat = stems_path.stat()
        os.link(stems_path, dest)  # atomic create-if-absent, same filesystem
        try:
            _check(cancelled)
            if _sha_file(project, cancelled, max_bytes=sweep.MAX_PROJECT_BYTES) != source_sha:
                raise RuntimeError('saved Compose project changed during DAW publication')
            _check(cancelled)
        except BaseException:
            # Attempt rollback only while the path still identifies our staged
            # inode with unchanged metadata. Another writer's replacement is
            # preserved when observable; an uncooperative replacement racing
            # the stat/unlink itself cannot be excluded portably.
            try:
                output_stat = dest.stat(follow_symlinks=False)
                if (output_stat.st_dev == staged_stat.st_dev and
                        output_stat.st_ino == staged_stat.st_ino and
                        output_stat.st_size == staged_stat.st_size and
                        output_stat.st_mtime_ns == staged_stat.st_mtime_ns):
                    dest.unlink()
            except FileNotFoundError:
                pass
            raise
    return {
        'format': FORMAT, 'absolute_path': str(dest),
        'project_file_sha256': source_sha,
        'source_asset_sha256': sweep_receipt['source_asset_sha256'],
        'dry_pcm_f32le_sha256': sweep_receipt['dry_pcm_f32le_sha256'],
        'virtual_rates_hz': list(rates), 'delivery_hz': 48000,
        'source_sweep_sha256': sweep_receipt['archive_sha256'],
        'zip_sha256': stem_receipt['zip_sha256'],
        'stems': stem_receipt['stems'],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Saved Compose to source-verified Nyquismic DAW WAVs')
    parser.add_argument('--project', required=True, help='Existing .zgtimeline.json')
    parser.add_argument('--output', required=True, help='New DAW .zip; never overwritten')
    parser.add_argument('--virtual-hz', action='append', required=True,
                        help='Repeat for 2–6 positive rational virtual sampling rates, Hz')
    parser.add_argument('--evaluation-hz', type=int, default=192000,
                        choices=sweep.EVALUATION_RATES_HZ)
    args = parser.parse_args(argv)
    try:
        receipt = export_saved_compose_daw(
            args.project, args.output, virtual_rates_hz=args.virtual_hz,
            evaluation_rate_hz=args.evaluation_hz)
    except (Exception, KeyboardInterrupt) as exc:
        print('NYQ direct DAW export failed: ' + str(exc), file=sys.stderr)
        return 130 if isinstance(exc, KeyboardInterrupt) else 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
