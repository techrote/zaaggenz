"""Opt-in source-matched dry/NYQ audition ZIP from one ordinary Compose render.

Only a new offline entrypoint. No new graph node, UI, rack default or shared
session/registry mutation. Not a replacement for accepted #252/#253 evidence.
"""
from __future__ import annotations

import argparse
from fractions import Fraction
from math import gcd
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import zipfile

import numpy as np
from scipy.io import wavfile
from scipy.signal import firwin, resample_poly

from zaaggenz_contracts.nyquismic import ClockSpec, ResourceBudget, SonicSpec, VirtualRate
from zaaggenz_contracts.nyquismic_clock_packet import compile_controlled_sampler_clock_v1
from zaaggenz_dsp.nyquismic import sampler_evaluation
from zaaggenz_jobs import JobError
from zaaggenz_runtime import RuntimeSession
from zaaggenz_runtime.nyquismic_compose import bind_completed_compose
from zaaggenz_runtime.nyquismic_compose_delivery import render_compose_controlled_48k_wav
from zaaggenz_runtime.nyquismic_offline_export import (
    DEFAULT_VIRTUAL_HZ, EVALUATION_RATES_HZ, MAX_PROJECT_BYTES,
)
from zaaggenz_timeline.model import TimelineDocument
from zaaggenz_timeline.service import TimelineService

RATE = 48000
FORMAT = 'nyq.saved-compose-ab48-zip.v1'
DRY_METHOD = 'nyq.compose-dry-fir-kaiser10-24lobes.v1'
_CHUNK = 1024 * 1024


def _require(yes: bool, reason: str) -> None:
    if not yes:
        raise JobError('NYQ A/B export: ' + reason)


def _check_cancel(cancelled) -> None:
    _require(cancelled is None or not cancelled(), 'caller cancelled A/B export')


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _dry_48k_wav(binding, budget: ResourceBudget, cancelled):
    """Independent neutral-rate reference from SAME authenticated post-rack PCM.

    It is dry of the added Nyquismic virtual sampler, not a rack-bypass export.
    The source rate conversion is intentionally not allowed to normalize/clip.
    """
    binding._guard()
    _check_cancel(cancelled)
    rate = binding.source.sample_rate_hz
    source = np.array(binding.source.pcm, dtype=np.float64, copy=True, order='C')
    _require(source.ndim in (1, 2) and
             (source.ndim == 1 or source.shape[1] in (1, 2)),
             'unsupported Compose PCM channel layout')
    channels = 1 if source.ndim == 1 else source.shape[1]
    _require(source.size <= budget.max_frames and np.isfinite(source).all(),
             'dry reference input outside admitted PCM budget')
    exact_frames = Fraction(source.shape[0] * RATE, rate)
    _require(exact_frames.denominator == 1 and exact_frames.numerator > 0,
             'dry source physical duration is not integral on the 48-kHz grid')
    _require(exact_frames.numerator * channels <= budget.max_frames,
             'dry reference output outside admitted frame budget')
    up, down = RATE // gcd(RATE, rate), rate // gcd(RATE, rate)
    taps = 1 if up == down else 24 * max(up, down) + 1
    _require(taps <= budget.max_filter_taps,
             'dry-reference FIR exceeds admitted kernel-tap budget')
    if up == down:
        kernel = np.array([1.], dtype='<f8')
        converted = source
    else:
        kernel = firwin(taps, 1. / max(up, down),
                        window=('kaiser', 10.), pass_zero='lowpass')
        converted = resample_poly(source, up, down, axis=0, window=kernel,
                                  padtype='constant')
    _check_cancel(cancelled)
    _require(converted.shape[0] == exact_frames.numerator and
             np.isfinite(converted).all(), 'dry conversion changed physical extent')
    with np.errstate(over='ignore', invalid='ignore'):
        pcm = np.asarray(converted, dtype='<f4')
    _require(np.isfinite(pcm).all(), 'dry float32 reference would overflow')
    output = io.BytesIO()
    wavfile.write(output, RATE, pcm)
    data = output.getvalue()
    decoded_rate, decoded = wavfile.read(io.BytesIO(data))
    _require(decoded_rate == RATE and decoded.dtype == np.float32 and
             decoded.shape == pcm.shape and
             decoded.tobytes(order='C') == pcm.tobytes(order='C'),
             'dry WAV header or PCM decoding mismatch')
    return data, {
        'source_rate_hz': rate,
        'frames': decoded.shape[0],
        'channels': channels,
        'method': DRY_METHOD,
        'ratio_up': up,
        'ratio_down': down,
        'fir_taps': taps,
        'fir_sha256': _sha(np.asarray(kernel, dtype='<f8').tobytes()),
        'pcm_f32le_sha256': _sha(pcm.tobytes(order='C')),
        'wav_sha256': _sha(data),
    }


def _bundle_bytes(dry: bytes, wet: bytes, manifest: dict) -> bytes:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, mode='w', compression=zipfile.ZIP_STORED,
                         allowZip64=False) as archive:
        # Stable metadata: a cold reopen must reproduce identical bundle bytes.
        for name, data in (
            ('compose-dry.wav', dry),
            ('compose-nyquismic.wav', wet),
            ('manifest.json', (json.dumps(manifest, sort_keys=True,
                                          separators=(',', ':'), allow_nan=False) +
                               '\n').encode('utf-8')),
        ):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3
            info.external_attr = 0o600 << 16
            archive.writestr(info, data)
    return payload.getvalue()


def _publish_zip(binding, destination: Path, payload: bytes, cancelled) -> None:
    """One atomic no-clobber ZIP commit, serialized with Compose job/document edits."""
    fd, temporary = tempfile.mkstemp(prefix='.nyq-ab48-', suffix='.partial',
                                     dir=str(destination.parent))
    staged = Path(temporary)
    try:
        with os.fdopen(fd, 'wb') as output:
            for start in range(0, len(payload), _CHUNK):
                _check_cancel(cancelled)
                output.write(payload[start:start + _CHUNK])
            output.flush()
            os.fsync(output.fileno())
        _check_cancel(cancelled)
        sha = hashlib.sha256()
        with staged.open('rb') as reader:
            for chunk in iter(lambda: reader.read(_CHUNK), b''):
                sha.update(chunk)
        _require(sha.hexdigest() == _sha(payload), 'staged archive identity changed')
        binding._guard()
        timeline = binding.timeline
        with timeline._jobs_lock:
            with timeline.session._lock:
                def current():
                    job = timeline._jobs.get(binding.job_id)
                    return (job is not None and timeline._current_locked(job) and
                            timeline.session.current_identity() ==
                            (binding.generation, binding.timeline_revision_id))
                _require(current(), 'Compose job or revision revoked before publication')
                _check_cancel(cancelled)
                _require(current(), 'Compose changed during cancellation check')
                # Hardlink, not replace: an existing user archive is never clobbered.
                os.link(staged, destination)
    finally:
        staged.unlink(missing_ok=True)


def export_saved_compose_ab48(
    project_path: str | Path,
    output_path: str | Path,
    *,
    virtual_rate_hz: str = DEFAULT_VIRTUAL_HZ,
    evaluation_rate_hz: int = 192000,
    wait_seconds: float = 120.,
    cancelled=None,
) -> dict:
    """Save one source-bound dry/NYQ pair as a no-overwrite deterministic ZIP."""
    if type(virtual_rate_hz) is not str:
        raise ValueError('virtual rate must be a rational Hz string')
    if type(evaluation_rate_hz) is not int or evaluation_rate_hz not in EVALUATION_RATES_HZ:
        raise ValueError('evaluation rate must be 192000, 384000 or 768000 Hz')
    if type(wait_seconds) not in (int, float) or not 0 < wait_seconds <= 3600:
        raise ValueError('wait seconds must be within (0, 3600]')
    if cancelled is not None and not callable(cancelled):
        raise ValueError('cancelled must be a callable or None')
    dest = Path(output_path).absolute()
    if dest.suffix.lower() != '.zip' or not dest.parent.is_dir():
        raise ValueError('output must be a .zip file in an existing directory')
    if dest.exists() or dest.is_symlink():
        raise FileExistsError(str(dest))
    project = Path(project_path)
    if project.suffix.lower() != '.json' or not project.name.endswith('.zgtimeline.json'):
        raise ValueError('project must be a saved Compose .zgtimeline.json')
    if project.stat().st_size > MAX_PROJECT_BYTES:
        raise ValueError('Compose project exceeds 2 MB')
    raw_project = project.read_bytes()
    if len(raw_project) > MAX_PROJECT_BYTES:
        raise ValueError('Compose project exceeds 2 MB')
    document = TimelineDocument.from_json(raw_project.decode('utf-8'))
    clock = ClockSpec(rate=VirtualRate(value=virtual_rate_hz))
    budget = ResourceBudget()
    service = TimelineService(session=RuntimeSession(document), debounce_seconds=0)
    try:
        _check_cancel(cancelled)
        request = service.submit(document.to_dict(), name='NYQ opt-in A/B audition')
        job_id = request['job_id']
        state = service.scheduler.wait(job_id, wait_seconds)
        if state.state != 'completed':
            service.cancel(job_id)
            raise JobError('ordinary Compose did not finish: ' + state.state)
        binding = bind_completed_compose(service, job_id)
        asset = binding.source.asset.to_dict()
        sonic = SonicSpec(clock=clock, channels=asset['channels'])
        duration = Fraction(asset['frame_count'], binding.source.sample_rate_hz)
        end = Fraction(clock.origin_s) + duration
        claims = binding.packet_claims
        packet = compile_controlled_sampler_clock_v1(
            sonic, full_end_s=f'{end.numerator}/{end.denominator}',
            input_asset_sha256=claims['input_asset_sha256'],
            source_revision_sha256=claims['source_revision_sha256'],
            graph_revision_sha256=claims['graph_revision_sha256'],
            expected_live_graph_sha256=claims['expected_live_graph_sha256'],
            upstream_route_receipts=(), budget=budget, cancelled=cancelled,
        )
        evaluation = sampler_evaluation(evaluation_rate_hz)
        dry, dry_info = _dry_48k_wav(binding, budget, cancelled)
        wet = render_compose_controlled_48k_wav(
            binding, sonic, packet, evaluation, budget=budget, cancelled=cancelled)
        _require(wet.frames == dry_info['frames'] and
                 wet.channels == dry_info['channels'], 'dry/wet frame alignment failed')
        manifest = {
            'format': FORMAT,
            'reference': 'post-Compose-full-mix-without-added-Nyquismic',
            'project_file_sha256': _sha(raw_project),
            'source_asset_sha256': binding.source.asset.sha256,
            'source_revision_sha256': binding.timeline_revision_id,
            'compose_recipe_sha256': binding.recipe_sha256,
            'packet_sha256': packet.sha256,
            'sonic_sha256': sonic.sha256,
            'evaluation_policy_sha256': evaluation.sha256,
            'virtual_rate_hz': virtual_rate_hz,
            'evaluation_rate_hz': evaluation_rate_hz,
            'sample_rate_hz': RATE,
            'channels': wet.channels,
            'frames': wet.frames,
            'dry': dry_info,
            'wet': {
                'wav_sha256': wet.wav_sha256,
                'pcm_f32le_sha256': wet.pcm_f32le_sha256,
                'render_identity_sha256': wet.identity_sha256,
                'conversion_kernel_sha256': wet.conversion_kernel_sha256,
            },
        }
        payload = _bundle_bytes(dry, wet.wav_bytes, manifest)
        _publish_zip(binding, dest, payload, cancelled)
        return {
            'format': FORMAT,
            'absolute_path': str(dest),
            'archive_sha256': _sha(payload),
            'manifest': manifest,
        }
    finally:
        service.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=(
        'Opt-in A/B ZIP: identical Compose source, original post-rack 48-kHz '
        'reference and controlled Nyquismic 48-kHz WAV. No default changes.'))
    parser.add_argument('--project', required=True, help='Saved .zgtimeline.json')
    parser.add_argument('--output', required=True, help='New .zip, never overwritten')
    parser.add_argument('--virtual-hz', default=DEFAULT_VIRTUAL_HZ)
    parser.add_argument('--evaluation-hz', type=int, choices=EVALUATION_RATES_HZ,
                        default=192000)
    args = parser.parse_args(argv)
    try:
        receipt = export_saved_compose_ab48(
            args.project, args.output, virtual_rate_hz=args.virtual_hz,
            evaluation_rate_hz=args.evaluation_hz)
    except (Exception, KeyboardInterrupt) as exc:
        print(f'NYQ A/B export failed: {exc}', file=sys.stderr)
        return 130 if isinstance(exc, KeyboardInterrupt) else 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
