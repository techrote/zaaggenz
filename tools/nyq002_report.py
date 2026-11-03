"""Generate real NYQ-002 numerical-domain PCM/checkpoint/audition evidence."""
from __future__ import annotations

import argparse
from dataclasses import replace
from fractions import Fraction
import hashlib
import json
import platform
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
from scipy.io import wavfile
import scipy

from zaaggenz_contracts.nyquismic import ClockSpec, VirtualRate, Point, Reset, SonicSpec
from zaaggenz_dsp.nyquismic import FrozenInput, SamplerPlan, SamplerCheckpoint


def file_record(path, root):
    payload = path.read_bytes()
    return {'path': path.relative_to(root).as_posix(), 'bytes': len(payload),
            'sha256': hashlib.sha256(payload).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    root = args.out
    (root / 'raw').mkdir(parents=True, exist_ok=True)
    (root / 'listening-matched').mkdir(exist_ok=True)
    try:
        head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        head = None
    report = {'version': 'nyq002-sampler-evidence/1.0.0', 'git_head': head,
              'environment': {'python': platform.python_version(), 'platform': platform.platform(),
                              'numpy': np.__version__, 'scipy': scipy.__version__},
              'scope': 'Fixed-grid kernel evidence; no final SRC, quality convergence, rack/UI or owner listening acceptance.',
              'fixtures': [], 'files': []}
    base = SonicSpec(clock=ClockSpec(rate=VirtualRate('11137/1')))
    specs = {
        '11137-hold': base,
        '11730-linear': replace(base, clock=ClockSpec(rate=VirtualRate('11730/1')),
                                reconstruction='linear_time_v1'),
        'capture-nearest': replace(base, capture='nearest_left_tie_v1'),
        'clock-ramp': replace(base, clock=ClockSpec(rate=VirtualRate('4000/1'),
                             points_hz=(Point('1/4', '11730/1'),), interpolation='linear')),
        'reset-and-step': replace(base, clock=ClockSpec(rate=VirtualRate('4000/1'),
                             points_hz=(Point('1/8', '8000/1'),), resets=(Reset('1/8', '1/4'),))),
    }
    for rate in (12000, 48000):
        t = np.arange(rate // 4, dtype=np.float64) / rate
        # Original synthetic source, with nonlinear structure and a transient;
        # no owner reference recording or protected factory recipe is changed.
        audio = (.35 * np.sin(2 * np.pi * (220 * t + 1800 * t * t)) +
                 .16 * np.tanh(2 * np.sin(2 * np.pi * 971 * t)) +
                 .12 * np.exp(-t * 150) * np.cos(2 * np.pi * 2800 * t)).astype(np.float32)
        source = FrozenInput.from_pcm(audio, rate)
        source_path = root / 'raw' / f'synthetic-source-{rate}.wav'
        wavfile.write(source_path, rate, source.pcm)
        report['files'].append(file_record(source_path, root))
        rms = float(np.sqrt(np.mean(source.pcm.astype(np.float64) ** 2)))
        for name, spec in specs.items():
            plan = SamplerPlan.prepare(source, spec)
            whole = plan.render()
            cut = rate // 13
            prefix = plan.render(stop_frame=cut)
            restored = SamplerCheckpoint.from_json(prefix.checkpoint.to_json())
            suffix = plan.render(checkpoint=restored)
            joined = np.concatenate((prefix.audio, suffix.audio))
            region_start, region_stop = rate // 17, rate // 7
            region = plan.render(region_start, region_stop)
            if not np.array_equal(joined, whole.audio) or not np.array_equal(region.audio, whole.audio[region_start:region_stop]):
                raise RuntimeError('whole/chunk/region PCM disagreement')
            if not np.isfinite(whole.audio).all() or np.max(np.abs(whole.audio), initial=0) > np.finfo(np.float32).max:
                raise RuntimeError('unrepresentable evidence PCM')
            raw_path = root / 'raw' / f'{name}-{rate}.wav'
            wavfile.write(raw_path, rate, whole.audio.astype(np.float32))
            current_rms = float(np.sqrt(np.mean(whole.audio ** 2)))
            gain = rms / current_rms if current_rms else 1.0
            matched_path = root / 'listening-matched' / f'{name}-{rate}.wav'
            wavfile.write(matched_path, rate, (whole.audio * gain).astype(np.float32))
            spec_path = root / f'{name}-{rate}.json'
            spec_path.write_text(json.dumps({'spec': spec.to_dict(), 'evaluation': plan.evaluation.to_dict(),
                                'source_asset': source.asset.to_dict(), 'render_identity': plan.identity.to_dict(),
                                'checkpoint': restored.to_dict()}, indent=2, sort_keys=True) + '\n', encoding='utf-8')
            report['files'].extend(file_record(path, root) for path in (raw_path, matched_path, spec_path))
            report['fixtures'].append({'name': name, 'sample_rate_hz': rate,
                'diagnostics': whole.diagnostics, 'chunk_resume_bit_exact': True, 'region_bit_exact': True,
                'listening_derivative': {'gain_linear': gain, 'method': 'one scalar RMS match to synthetic source; raw export unchanged'},
                'wav_representation': 'IEEE float32; no limiter/dither/normalization on raw output'})
    for path in ('zaaggenz_contracts/nyquismic.py', 'zaaggenz_contracts/nyquismic_clock.py',
                 'zaaggenz_dsp/nyquismic.py', 'tests/contracts/fixtures/nyquismic-v1.json',
                 'tests/dsp/nyquismic_audio_oracles.py', 'tests/dsp/test_nyquismic_sampler.py',
                 'tools/nyq002_report.py'):
        # Match the repository's text-source identity policy on Windows while
        # keeping WAV and emitted artifact/file hashes byte-exact above.
        source_bytes = (ROOT / path).read_text(encoding='utf-8').replace('\r\n', '\n').encode('utf-8')
        report.setdefault('source_sha256', {})[path] = hashlib.sha256(source_bytes).hexdigest()
    report['source_hash_policy'] = 'UTF-8 text normalized to LF; output file/WAV hashes use exact bytes'
    (root / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps({'fixtures': len(report['fixtures']), 'files': len(report['files']),
                      'report': str(root / 'report.json'), 'chunk_and_region_bit_exact': True}))


if __name__ == '__main__':
    main()
