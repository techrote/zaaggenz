"""Generate original source-derived grammar fixtures; never load reference recordings."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import platform
from pathlib import Path
import sys
import numpy as np
from scipy.io import wavfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'app'))
from zaaggenz_contracts.legacy import adapt_parameters, freeze_legacy
from zaaggenz_grammar import (ExpansionRequest, starter_grammars, expand_grammar,
    make_grammar_recipe, save_grammar_recipe, load_grammar_recipe, submit_grammar_render)
from zaaggenz_jobs import JobScheduler
from uptempo_harmony.synth import PRESETS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--audio-dir', required=True, type=Path)
    parser.add_argument('--sample-rate', type=int, default=48000)
    args = parser.parse_args()
    params = adapt_parameters('synth', {**PRESETS['locked_bloom'].to_dict(), 'sr': args.sample_rate, 'bpm': 200., 'beats': 1})
    base = freeze_legacy(params).to_dict()
    output = args.audio_dir
    output.mkdir(parents=True, exist_ok=True)
    rows, audio = [], []
    scheduler = JobScheduler()
    try:
        for name, count, ornaments in [('step-return', 32, 0), ('skip-return', 32, 0), ('step-return', 128, 8)]:
            label = f'{name}-{count // 8}bar'
            grammar = starter_grammars()[name]
            # Ornaments and scheduled rests use distinct positions in the long example.
            request = ExpansionRequest(event_count=count, seed='20260913',
                                       ornament_every=7 if ornaments else 0, rest_every=8)
            bundle = make_grammar_recipe(grammar, request, params, base['time_map'], base['tuning'],
                                         quality='standard', tail_mode='truncate')
            path = output / f'{label}.zggrammar.json'
            save_grammar_recipe(bundle, path)
            reopened = load_grammar_recipe(path)
            assert bundle.sha256 == reopened.sha256
            job = submit_grammar_render(reopened, scheduler)
            result_state = scheduler.wait(job)
            if result_state.state != 'completed':
                raise RuntimeError(result_state.error or result_state.state)
            artifact = scheduler.result(job)
            x = np.frombuffer(artifact.audio_bytes, dtype='<f4').copy()
            assert np.isfinite(x).all() and np.max(np.abs(x)) > 0
            audio.append(x)
            expansion = expand_grammar(grammar, request, base['tuning'])
            trace_file = output / f'{label}.trace.json'
            trace_file.write_text(json.dumps(expansion.trace, indent=2) + '\n', encoding='utf-8')
            rms = float(np.sqrt(np.mean(x.astype(np.float64) ** 2)))
            peak = float(np.max(np.abs(x)))
            rows.append({'name': label, 'recipe_file': path.name, 'recipe_sha256': bundle.sha256,
                         'render_recipe_sha256': reopened.render_recipe.sha256, 'revision_id': reopened.project.head,
                         'expansion_sha256': expansion.sha256, 'trace_file': trace_file.name,
                         'samples': len(x), 'duration_seconds': len(x) / args.sample_rate,
                         'raw_rms': rms, 'raw_peak': peak, 'raw_pcm_sha256': hashlib.sha256(x.tobytes()).hexdigest(),
                         'entry_degree': expansion.trace[0]['degree'], 'return_degrees': [t['degree'] for t in expansion.trace[-3:]],
                         'rules': sorted({t['rule'] for t in expansion.trace})})
        # One documented playback-only gain per immutable example. Common RMS and
        # a global headroom bound; these gains never modify the synthesis recipe.
        target_rms = min([10**(-24 / 20)] + [r['raw_rms'] * 10**(-3 / 20) / r['raw_peak'] for r in rows])
        for row, x in zip(rows, audio):
            gain = target_rms / row['raw_rms']
            matched = (x.astype(np.float64) * gain).astype(np.float32)
            row.update(matching_gain_db=20 * math.log10(gain), matched_rms=float(np.sqrt(np.mean(matched.astype(np.float64)**2))),
                       matched_peak=float(np.max(np.abs(matched))), matched_headroom_db=-20 * math.log10(float(np.max(np.abs(matched)))))
            wav = output / (row['name'] + '-matched.wav')
            wavfile.write(wav, args.sample_rate, matched)
            row.update(wav=wav.name, wav_sha256=hashlib.sha256(wav.read_bytes()).hexdigest())
        assert rows[0]['return_degrees'] != rows[1]['return_degrees']
        assert abs(rows[0]['matched_rms'] - rows[1]['matched_rms']) < 1e-8
        assert all(row['matched_headroom_db'] >= 2.999 for row in rows)
        report = {'method': 'zg011-fixtures-v1', 'scope': 'original generated-source examples; numerical evidence, not owner listening approval',
                  'python': sys.version, 'platform': platform.platform(), 'numpy': np.__version__,
                  'sample_rate_hz': args.sample_rate, 'quality': 'standard source-derived',
                  'matching': {'method': 'whole-file RMS, one playback gain; common -3 dBFS peak ceiling',
                               'target_rms': target_rms, 'true_peak_measured': False, 'perceptual_loudness_match_claimed': False},
                  'examples': rows}
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, sort_keys=True, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({'out': str(args.out), 'examples': len(rows), 'sample_rate_hz': args.sample_rate, 'checks': 'passed'}))
    finally:
        scheduler.shutdown(cancel=True)


if __name__ == '__main__':
    main()
