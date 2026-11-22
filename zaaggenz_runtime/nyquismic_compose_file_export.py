"""Opt-in atomic *file* handoff for the source-bound NYQ 48-kHz WAV.

This is a standalone, deliberately unregistered follow-on to #277 and #275.
The existing Compose adapter provides the immutable render and locks.
No ordinary export route, preset, graph registration or default is changed.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import tempfile

from zaaggenz_contracts.nyquismic import EvaluationPolicy, ResourceBudget, SonicSpec
from zaaggenz_dsp.nyquismic_delivery import DeliveryConversionPolicy
from zaaggenz_jobs import JobError
from zaaggenz_runtime.nyquismic_compose import ComposeControlledSource
from zaaggenz_runtime.nyquismic_compose_delivery import (
    OUTPUT_RATE_HZ, render_compose_controlled_48k_wav,
)

_CHUNK = 65536


@dataclass(frozen=True)
class SavedControlledWav48k:
    """Receipt for a single successful no-clobber on-disk publication."""
    absolute_path: str
    wav_sha256: str
    pcm_f32le_sha256: str
    source_asset_sha256: str
    source_revision_sha256: str
    recipe_sha256: str
    packet_sha256: str
    render_identity_sha256: str
    sample_rate_hz: int
    frames: int
    channels: int


def _require(ok: bool, reason: str) -> None:
    if not ok:
        raise JobError('NYQ 48-kHz file export: ' + reason)


def _cancel_check(cancelled) -> None:
    _require(cancelled is None or not cancelled(), 'caller cancelled file export')


def _staged_sha256(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open('rb') as reader:
        for chunk in iter(lambda: reader.read(_CHUNK), b''):
            sha.update(chunk)
    return sha.hexdigest()


def save_compose_controlled_48k_wav_file(
    binding: ComposeControlledSource,
    sonic: SonicSpec,
    packet,
    evaluation: EvaluationPolicy,
    destination: str | os.PathLike[str],
    *,
    policy: DeliveryConversionPolicy = DeliveryConversionPolicy(),
    budget: ResourceBudget = ResourceBudget(),
    cancelled=None,
) -> SavedControlledWav48k:
    """Render and atomically create a new, non-overwriting 48-kHz WAV file.

    A temporary file is flushed and independently hash-verified in the SAME
    directory before the final commit. Hard-link creation is the atomic
    no-clobber publication primitive on supported filesystems: a preexisting
    user's export is never overwritten, even by a concurrent external writer.
    The small commit runs while holding #275's job -> document locks, and
    repeats the exact job/generation/cancellation guard. No DSP or disk staging
    runs under those locks. If hard links are unsupported, fail closed.

    The commit is linearized only at the link creation. This does not register
    an application export action, guarantee directory fsync across crashes,
    or make a prior output permanently current after later Compose edits.
    """
    _require(type(binding) is ComposeControlledSource,
             'requires real, current Compose source binding')
    _require(type(destination) in (str, Path) or hasattr(destination, '__fspath__'),
             'destination must be a filesystem path')
    _require(cancelled is None or callable(cancelled), 'invalid cancellation hook')
    dest = Path(destination).absolute()
    _require(dest.suffix.lower() == '.wav' and dest.name not in ('.', '..'),
             'destination must name an explicit .wav file')
    _require(dest.parent.is_dir(), 'destination directory does not exist')
    if dest.exists() or dest.is_symlink():
        raise FileExistsError(str(dest))

    _cancel_check(cancelled)
    wav = render_compose_controlled_48k_wav(
        binding, sonic, packet, evaluation, policy=policy, budget=budget,
        cancelled=cancelled,
    )
    _require(wav.sample_rate_hz == OUTPUT_RATE_HZ and
             hashlib.sha256(wav.wav_bytes).hexdigest() == wav.wav_sha256,
             'source-bound WAV identity mismatch')
    result = SavedControlledWav48k(
        str(dest), wav.wav_sha256, wav.pcm_f32le_sha256,
        wav.source_asset_sha256, wav.source_revision_sha256,
        wav.recipe_sha256, wav.packet_sha256, wav.identity_sha256,
        wav.sample_rate_hz, wav.frames, wav.channels,
    )

    fd, tmp_name = tempfile.mkstemp(prefix='.nyq48-', suffix='.partial',
                                     dir=str(dest.parent))
    staged = Path(tmp_name)
    try:
        with os.fdopen(fd, 'wb') as writer:
            for start in range(0, len(wav.wav_bytes), _CHUNK):
                _cancel_check(cancelled)
                writer.write(wav.wav_bytes[start:start + _CHUNK])
            writer.flush()
            os.fsync(writer.fileno())
        _cancel_check(cancelled)
        _require(_staged_sha256(staged) == wav.wav_sha256,
                 'staged file differs from authenticated WAV')
        binding._guard()

        timeline = binding.timeline
        with timeline._jobs_lock:
            with timeline.session._lock:
                def current() -> bool:
                    job = timeline._jobs.get(binding.job_id)
                    return (job is not None and
                            timeline._current_locked(job) and
                            timeline.session.current_identity() ==
                            (binding.generation, binding.timeline_revision_id))
                _require(current(), 'Compose revision or job revoked before disk commit')
                _cancel_check(cancelled)
                _require(current(), 'session changed during cancellation check')
                # Unlike a pre-check plus os.replace(), link() is atomic
                # no-clobber even if an external process creates dest now.
                os.link(staged, dest)
        return result
    finally:
        staged.unlink(missing_ok=True)
