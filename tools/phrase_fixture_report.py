"""Generate original 48 kHz phrase-role comparisons with playback-only level matching."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import sys
import numpy as np
from scipy.io import wavfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'app'))
from zaaggenz_melody import render_phrase
from zaaggenz_phrase import PhraseRolePlan, template_1234_5555, expand_role_plan, compile_role_recipe


def changed(plan, field, selector, want=None):
    base = selector(expand_role_plan(plan, 'fixture-tuning'))
    for seed in range(1, 10000):
        data = plan.to_dict(); data[field] = str(seed); candidate = PhraseRolePlan(data)
        got = selector(expand_role_plan(candidate, 'fixture-tuning'))
        if (want is not None and got == want) or (want is None and got != base):
            return candidate
    raise RuntimeError(f'no bounded alternative found for {field}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--audio-dir', type=Path, required=True)
    parser.add_argument('--sample-rate', type=int, default=48000)
    args = parser.parse_args(); args.audio_dir.mkdir(parents=True, exist_ok=True)
    base = template_1234_5555(placement_seed='0', content_seed='0')
    different_content = changed(base, 'content_seed', lambda x: x.trace[3]['variant_id'])
    different_placement = changed(base, 'placement_seed', lambda x: x.trace[3]['placement_offset'])
    no_fill = changed(base, 'content_seed', lambda x: x.trace[3]['variant_id'], want='no-fill')
    plans = [('baseline', base), ('different-content', different_content),
             ('different-placement', different_placement), ('no-fill', no_fill)]
    rows, raw = [], []
    for name, plan in plans:
        bundle = compile_role_recipe(plan, sample_rate=args.sample_rate)
        result = render_phrase(bundle.recipe)
        x = result.mix.astype(np.float32, copy=True)
        if not np.isfinite(x).all() or np.max(np.abs(x), initial=0) <= 0:
            raise RuntimeError(f'{name}: invalid generated audio')
        role = bundle.expansion.trace[3]
        rows.append({'name': name, 'plan_sha256': plan.sha256, 'expansion_sha256': bundle.expansion.sha256,
                     'timeline_revision_id': bundle.timeline.revision_id, 'recipe_sha256': bundle.recipe.sha256,
                     'placement_seed': plan.to_dict()['placement_seed'], 'content_seed': plan.to_dict()['content_seed'],
                     'variant_id': role['variant_id'], 'source_family': role['source_family'],
                     'placement_offset': role['placement_offset'], 'window': [role['window_start_beat'], role['window_end_beat']],
                     'destination_beat': role['destination_beat'], 'declared_content_probability': role['declared_content_probability'],
                     'declared_placement_probability': role['declared_placement_probability'],
                     'event_count': len(bundle.expansion.phrase.to_dict()['events']), 'samples': len(x),
                     'duration_seconds': len(x) / args.sample_rate, 'raw_rms': float(np.sqrt(np.mean(x.astype(np.float64)**2))),
                     'raw_peak': float(np.max(np.abs(x))), 'raw_pcm_sha256': hashlib.sha256(x.tobytes()).hexdigest(),
                     'notes': result.diagnostics['notes'], 'rests': result.diagnostics['rests'],
                     'roll_retriggers': result.diagnostics['roll_retriggers']})
        raw.append(x)
        (args.audio_dir / f'{name}.plan.json').write_text(json.dumps(plan.to_dict(), indent=2, sort_keys=True)+'\n', encoding='utf-8')
        (args.audio_dir / f'{name}.trace.json').write_text(json.dumps(bundle.expansion.trace, indent=2, sort_keys=True)+'\n', encoding='utf-8')
        (args.audio_dir / f'{name}.timeline.json').write_text(json.dumps(bundle.timeline.to_dict(), indent=2, sort_keys=True)+'\n', encoding='utf-8')
    if rows[0]['variant_id'] == rows[1]['variant_id'] or rows[0]['placement_offset'] != rows[1]['placement_offset']:
        raise RuntimeError('content comparison failed to isolate content choice')
    if rows[0]['variant_id'] != rows[2]['variant_id'] or rows[0]['placement_offset'] == rows[2]['placement_offset']:
        raise RuntimeError('placement comparison failed to isolate placement choice')
    if rows[3]['variant_id'] != 'no-fill' or rows[3]['destination_beat'] != '15/1':
        raise RuntimeError('no-fill fixture lost the return anchor')
    target_rms = min([10**(-24/20)] + [row['raw_rms'] * (10**(-3/20)) / row['raw_peak'] for row in rows])
    for row, x in zip(rows, raw):
        gain = target_rms / row['raw_rms']
        matched = (x.astype(np.float64) * gain).astype(np.float32)
        path = args.audio_dir / f'{row["name"]}-matched.wav'
        wavfile.write(path, args.sample_rate, matched)
        row.update(matching_gain_db=20*math.log10(gain), matched_rms=float(np.sqrt(np.mean(matched.astype(np.float64)**2))),
                   matched_peak=float(np.max(np.abs(matched))), matched_headroom_db=-20*math.log10(float(np.max(np.abs(matched)))),
                   wav=path.name, wav_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    report = {'method': 'zg025-phrase-role-fixtures-v1', 'sample_rate_hz': args.sample_rate,
              'python': sys.version, 'platform': platform.platform(), 'numpy': np.__version__,
              'scope': 'original generated-source examples; generator probabilities are not listener probabilities; no owner listening approval implied',
              'matching': {'method': 'whole-file RMS, one playback-only gain per immutable render; common sample-peak ceiling',
                           'target_rms': target_rms, 'true_peak_measured': False, 'perceptual_loudness_match_claimed': False},
              'examples': rows}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True)+'\n', encoding='utf-8')
    print(json.dumps({'checks': 'passed', 'examples': len(rows), 'sample_rate_hz': args.sample_rate}))


if __name__ == '__main__': main()
