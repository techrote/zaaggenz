#!/usr/bin/env python3
"""Reproducible actual Compose WAV/context evidence; no preference or UI claim."""
from __future__ import annotations
import argparse
import hashlib
import io
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'app')]
import numpy as np
from scipy.io import wavfile
from zaaggenz_contracts.music import beat_to_sample
from zaaggenz_dsp import CompressionSpec, BitcrushSpec
from zaaggenz_project import Project
from zaaggenz_spectral.band_selective import BandSlotSpec, BandSelectiveRequest
from zaaggenz_spectral.model import SpectralRetuneRequest, LatticeVoice
from zaaggenz_spectral.rack_adapter import request_to_rack
from zaaggenz_timeline.model import TimelineDocument, default_document, compile_recipe
from zaaggenz_timeline.service import TimelineService


def report(out: Path) -> None:
    if out.exists() and any(out.iterdir()):
        raise ValueError('evidence output directory must be empty')
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for rate in (12000, 48000):
        data = default_document(rate).to_dict()
        data['end_beat'] = '2/1'
        data['notes'] = [{'id': 'n0', 'beat': '0/1', 'duration_beats': '2/1',
                          'degree': 0, 'detune_cents': 0., 'gain_db': -8.,
                          'muted': False, 'roll_density': 4}]
        data['next_id'] = 1
        project = Project.from_document(data['project'])
        base = project.head_recipe
        spectral = SpectralRetuneRequest(base.to_dict()['tuning'],
            (LatticeVoice(0, (1., 2., 3.)),), amount=.65, min_confidence=.4,
            max_hz=4000., max_displacement_cents=180.)
        slot = BandSlotSpec(gain_db=2., spectral=spectral,
            compression=CompressionSpec(threshold_db=-24., ratio=3., attack_ms=2., release_ms=80.),
            bitcrush=BitcrushSpec(bit_depth=10, hold_samples=3),
            stage_order=('gain', 'compression', 'spectral', 'bitcrush'))
        project.set_rack(request_to_rack(BandSelectiveRequest(slots=(None, slot, None, None)), base))
        data['project'] = project.to_document()
        document = TimelineDocument.from_json(json.dumps(data))
        service = TimelineService(debounce_seconds=0)
        outputs = {}
        try:
            for name, region in [('full', None), ('region', {'start_beat': '1/4', 'end_beat': '5/4'})]:
                job = service.submit(document.to_dict(), region, name='locked_bloom-mbr002-' + name)
                terminal = service.scheduler.wait(job['job_id'], 60)
                if terminal.state != 'completed':
                    raise RuntimeError(str(terminal))
                status = service.status(job['job_id'])
                if not status['accepted']:
                    raise AssertionError('current artifact was not accepted')
                artifact = service.artifact(job['job_id'])
                raw, revision = service.wave(job['job_id'])
                sr, pcm = wavfile.read(io.BytesIO(raw))
                if sr != rate or revision != document.revision_id or not np.isfinite(pcm).all():
                    raise AssertionError('invalid delivered WAV identity/audio')
                np.testing.assert_array_equal(pcm, np.frombuffer(artifact.audio_bytes, dtype='<f4'))
                filename = f'locked_bloom-mbr002-{rate}hz-{name}.wav'
                (out / filename).write_bytes(raw)
                outputs[name] = artifact.audio_bytes
                rows.append({'file': filename, 'wav_sha256': hashlib.sha256(raw).hexdigest(),
                             'request': job, 'artifact': artifact.metadata()})
            recipe = compile_recipe(document)
            tm = recipe.to_dict()['time_map']
            lo, hi = beat_to_sample(tm, '1/4'), beat_to_sample(tm, '5/4')
            if outputs['region'] != outputs['full'][lo*4:hi*4]:
                raise AssertionError('full-context crop differs')
            cached = service.submit(document.to_dict())
            if service.scheduler.wait(cached['job_id'], 60).state != 'completed':
                raise AssertionError('identical rerender failed')
            if not service.status(cached['job_id'])['cache_hit']:
                raise AssertionError('identical rerender did not use bounded cache')
            (out / f'locked_bloom-mbr002-{rate}hz.project.json').write_text(json.dumps(document.to_dict(), sort_keys=True, indent=2, allow_nan=False), encoding='utf-8')
        finally:
            service.close()
    evidence = {'scope': 'MBR-002 actual Compose service/export; not UI or preference acceptance',
                'context_policy': 'whole-phrase-then-crop', 'rows': rows}
    (out / 'mbr002-evidence.json').write_text(json.dumps(evidence, sort_keys=True, indent=2, allow_nan=False), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    report(parser.parse_args().out)
