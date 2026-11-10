"""Opt-in saved Compose timeline to an actual NYQ 48-kHz WAV file.

Standalone command, not a shared graph/session, registered exporter or UI change.
Depends on independently reviewed but not yet main-integrated NYQ adapters.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import sys

from zaaggenz_contracts.nyquismic import (
    ClockSpec, ResourceBudget, SonicSpec, VirtualRate,
)
from zaaggenz_contracts.nyquismic_clock_packet import compile_controlled_sampler_clock_v1
from zaaggenz_dsp.nyquismic import sampler_evaluation
from zaaggenz_jobs import JobError
from zaaggenz_runtime import RuntimeSession
from zaaggenz_runtime.nyquismic_compose import bind_completed_compose
from zaaggenz_runtime.nyquismic_compose_file_export import save_compose_controlled_48k_wav_file
from zaaggenz_timeline.model import TimelineDocument
from zaaggenz_timeline.service import TimelineService

MAX_PROJECT_BYTES = 2_000_000  # Ordinary Compose file-open limit.
EVALUATION_RATES_HZ = (192000, 384000, 768000)
DEFAULT_VIRTUAL_HZ = '11730/1'


def export_saved_compose_nyq48(
    project_path: str | Path,
    output_path: str | Path,
    *,
    virtual_rate_hz: str = DEFAULT_VIRTUAL_HZ,
    evaluation_rate_hz: int = 192000,
    wait_seconds: float = 120.,
    cancelled=None,
) -> dict:
    """Cold-reopen, render and atomically export a saved Compose project.

    Source authority derives only from the completed current TimelineService
    artifact. The exact full PCM asset extent (including tail) defines the
    controlled-clock packet. The no-clobber file commit remains owned by #278.
    """
    if type(virtual_rate_hz) is not str:
        raise ValueError('virtual rate must be a rational Hz string')
    if type(evaluation_rate_hz) is not int or evaluation_rate_hz not in EVALUATION_RATES_HZ:
        raise ValueError('evaluation rate must be 192000, 384000 or 768000 Hz')
    if type(wait_seconds) not in (int, float) or not 0 < wait_seconds <= 3600:
        raise ValueError('wait seconds must be within (0, 3600]')
    if cancelled is not None and not callable(cancelled):
        raise ValueError('cancelled must be a callable or None')
    destination = Path(output_path).absolute()
    if destination.suffix.lower() != '.wav':
        raise ValueError('output must be a .wav file')
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(str(destination))
    project = Path(project_path)
    if project.suffix.lower() != '.json' or not project.name.endswith('.zgtimeline.json'):
        raise ValueError('project must be a saved Compose .zgtimeline.json')
    if project.stat().st_size > MAX_PROJECT_BYTES:
        raise ValueError('Compose project exceeds the 2 MB authoring limit')
    raw_project = project.read_bytes()
    if len(raw_project) > MAX_PROJECT_BYTES:
        raise ValueError('Compose project exceeds the 2 MB authoring limit')
    document = TimelineDocument.from_json(raw_project.decode('utf-8'))

    clock = ClockSpec(rate=VirtualRate(value=virtual_rate_hz))
    budget = ResourceBudget()
    service = TimelineService(session=RuntimeSession(document), debounce_seconds=0)
    try:
        if cancelled is not None and cancelled():
            raise JobError('NYQ export cancelled before Compose rendering')
        request = service.submit(document.to_dict(), name='NYQ opt-in offline export')
        job_id = request['job_id']
        state = service.scheduler.wait(job_id, wait_seconds)
        if state.state != 'completed':
            service.cancel(job_id)
            raise JobError('ordinary Compose did not finish: ' + state.state)
        binding = bind_completed_compose(service, job_id)
        asset = binding.source.asset.to_dict()
        spec = SonicSpec(clock=clock, channels=asset['channels'])
        extent = Fraction(asset['frame_count'], binding.source.sample_rate_hz)
        end = Fraction(clock.origin_s) + extent
        full_end_s = f'{end.numerator}/{end.denominator}'
        claims = binding.packet_claims
        packet = compile_controlled_sampler_clock_v1(
            spec, full_end_s=full_end_s,
            input_asset_sha256=claims['input_asset_sha256'],
            source_revision_sha256=claims['source_revision_sha256'],
            graph_revision_sha256=claims['graph_revision_sha256'],
            expected_live_graph_sha256=claims['expected_live_graph_sha256'],
            upstream_route_receipts=(), budget=budget, cancelled=cancelled,
        )
        evaluation = sampler_evaluation(evaluation_rate_hz)
        saved = save_compose_controlled_48k_wav_file(
            binding, spec, packet, evaluation, destination,
            budget=budget, cancelled=cancelled,
        )
        # This local input-file hash is a receipt, not authoritative graph ID.
        return {
            'format': 'nyq.saved-compose-wav48-receipt.v1',
            'saved_project_file_sha256': hashlib.sha256(raw_project).hexdigest(),
            'sonic_sha256': spec.sha256,
            'evaluation_policy_sha256': evaluation.sha256,
            'virtual_rate_hz': virtual_rate_hz,
            'evaluation_rate_hz': evaluation_rate_hz,
            **asdict(saved),
        }
    finally:
        service.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=(
        'Opt-in saved Compose -> controlled NYQ -> 48-kHz float WAV; '
        'no UI/graph registration or default change.'))
    parser.add_argument('--project', required=True,
                        help='Saved Compose .zgtimeline.json, not a rack preset')
    parser.add_argument('--output', required=True,
                        help='New .wav file; existing outputs are never overwritten')
    parser.add_argument('--virtual-hz', default=DEFAULT_VIRTUAL_HZ,
                        help='Positive exact virtual sampler Hz, e.g. 11730/1')
    parser.add_argument('--evaluation-hz', type=int, choices=EVALUATION_RATES_HZ,
                        default=192000, help='Numerical evaluation clock, not delivery rate')
    args = parser.parse_args(argv)
    try:
        receipt = export_saved_compose_nyq48(
            args.project, args.output, virtual_rate_hz=args.virtual_hz,
            evaluation_rate_hz=args.evaluation_hz,
        )
    except (Exception, KeyboardInterrupt) as exc:
        print(f'NYQ offline export failed: {exc}', file=sys.stderr)
        return 130 if isinstance(exc, KeyboardInterrupt) else 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
