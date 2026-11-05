"""NYQ-004 native-grid audio proof pack; synthetic source, no external rights.

This executes opt-in controlled physical-time clocks and emits float32 WAV
demonstrations. It is NOT a supported instrument/Compose export path.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import tempfile

import numpy as np
from scipy.io import wavfile

from zaaggenz_contracts.nyquismic import (
    ClockSpec, JitterSpec, ModulationRoute, Point, RateQuantizer, SonicSpec,
    VirtualRate,
)
from zaaggenz_dsp.nyquismic import FrozenInput
from zaaggenz_dsp.nyquismic_controlled_audio_proof import (
    METHOD, render_controlled_audio_proof,
)

RATE = 12000
FRAMES = RATE
PACK_VERSION = 'nyq004.native-grid-audition-pack.v1'


def _source() -> np.ndarray:
    """Entirely generated integer-periodic source, deterministic and rights-clear."""
    n = np.arange(FRAMES, dtype=np.int64)
    # Both components are exact binary fractions before float32 conversion.
    wave = ((n * 37) % 257 - 128) / 1024.0
    wave += ((n * 71) % 509 - 254) / 2048.0
    wave *= np.where(n < FRAMES // 2, 1.0, 0.75)
    return np.asarray(wave, dtype='<f4')


def _cases():
    step = ModulationRoute(
        id='step-source', mapping='add_hz', depth=120.0, initial='0/1',
        points=(Point('1/2', '1/1'),))
    ladder = RateQuantizer(policy='nearest_hz',
                           levels_hz=('360/1', '420/1', '480/1'))
    return (
        ('static_hold', 'Static 360 Hz virtual clock; sample-and-hold',
         SonicSpec(clock=ClockSpec(rate=VirtualRate('360/1')))),
        ('step_hold', '440→560 Hz virtual clock at 1/2 s, continuous phase',
         SonicSpec(clock=ClockSpec(rate=VirtualRate('440/1'), routes=(step,)))),
        ('rate_ladder', 'Explicit nearest-Hz ladder on an additive step clock',
         SonicSpec(clock=ClockSpec(rate=VirtualRate('440/1'), routes=(step,),
                                   quantizer=ladder))),
        ('seeded_jitter', '440 Hz clock with 8% fractional frequency-cell jitter',
         SonicSpec(clock=ClockSpec(rate=VirtualRate('440/1'),
             jitter=JitterSpec(model='uniform_frequency_cells_v1', amount=.08,
                               cell_s='1/20', seed='71', stream='nyq004-proof')))),
        ('time_linear', 'Physical-time linear reconstruction at 360 Hz',
         SonicSpec(clock=ClockSpec(rate=VirtualRate('360/1')),
                   reconstruction='linear_time_v1')),
    )


def generate_pack(destination: Path) -> dict:
    """Create a new complete pack atomically; refuse to overwrite evidence."""
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError('refusing to replace an existing NYQ-004 proof pack')
    destination.parent.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix='.nyq004-proof-', dir=destination.parent))
    try:
        raw = _source()
        source = FrozenInput.from_pcm(raw, RATE)
        rows = []

        def write_audio(name, data, *, description, spec=None, diagnostics=None):
            pcm = np.asarray(data, dtype='<f4')
            if pcm.shape != (FRAMES,) or not np.isfinite(pcm).all():
                raise ValueError('proof output shape or finiteness violation')
            filepath = scratch / (name + '.wav')
            wavfile.write(filepath, RATE, pcm)
            rows.append({
                'file':filepath.name, 'description':description, 'sample_rate_hz':RATE,
                'channels':1, 'frames':FRAMES, 'audio_format':'IEEE float32 WAV',
                'pcm_sha256':sha256(pcm.tobytes()).hexdigest(),
                'wav_sha256':sha256(filepath.read_bytes()).hexdigest(),
                'sonic_spec':None if spec is None else spec.to_dict(),
                'diagnostics':diagnostics,
            })

        write_audio('00_source', raw,
                    description='Rights-clear synthetic source; no virtual clock')
        for i, (name, description, spec) in enumerate(_cases(), start=1):
            result = render_controlled_audio_proof(source, spec)
            if result.diagnostics['product_rack_export_qualified']:
                raise AssertionError('proof was incorrectly promoted to product export')
            if result.diagnostics['method'] != METHOD:
                raise AssertionError('unrecognized controlled clock method')
            write_audio(f'{i:02d}_{name}', result.audio, description=description,
                        spec=spec, diagnostics=result.diagnostics)
        manifest = {
            'format':PACK_VERSION,
            'scope':'opt-in native-grid experimental PCM; NOT Compose/export qualified',
            'source_rights':'fully code-generated integer-periodic signal; no external recordings',
            'source_asset_sha256':source.asset.sha256,
            'native_rate_hz':RATE, 'duration_s':'1/1',
            'floating_point_policy':'unclipped float32 WAV; no hidden normalization',
            'method':METHOD, 'cases':rows,
        }
        (scratch / 'manifest.json').write_text(
            json.dumps(manifest, sort_keys=True, indent=2, allow_nan=False) + '\n',
            encoding='utf-8', newline='\n')
        os.rename(scratch, destination)
        return manifest
    except BaseException:
        shutil.rmtree(scratch, ignore_errors=True)
        raise


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, required=True,
                   help='new output directory (must not exist)')
    args = p.parse_args(argv)
    manifest = generate_pack(args.out)
    print(json.dumps({'output':str(args.out), 'cases':len(manifest['cases']),
                      'method':manifest['method']}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
