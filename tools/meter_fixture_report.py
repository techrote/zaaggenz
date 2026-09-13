"""Generate matched metrical click fixtures and multi-hypothesis overlay evidence."""
from __future__ import annotations
import argparse
from fractions import Fraction
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

from zaaggenz_contracts import Contract
from zaaggenz_contracts.legacy import envelope
from zaaggenz_contracts.model import fraction
from zaaggenz_contracts.music import beat_to_sample
from zaaggenz_meter import nested_124_cross32, generate_ticks, clock_relation, periodicity_overlay


def rat(value):
    return f'{value.numerator}/{value.denominator}'


def make_time_map(sample_rate):
    return Contract(envelope('TimeMap', sample_rate_hz=sample_rate, origin_sample=0,
                             beat_unit='quarter_note', rounding='nearest_ties_even',
                             tempo_segments=[
                                 {'beat':'0/1','bpm':'200/1'}, {'beat':'16/1','bpm':'160/1'},
                                 {'beat':'40/1','bpm':'240/1'}, {'beat':'56/1','bpm':'137/1'}],
                             meter_segments=[{'beat':'0/1','numerator':4,'denominator':4}]))


def shift_nonanchors(fast, anchors, offset):
    anchor_set = set(anchors)
    return [beat if beat in anchor_set else beat + offset for beat in fast]


def click_audio(time_map, end_beat, left_beats, right_beats):
    sr = int(time_map.to_dict()['sample_rate_hz'])
    frames = beat_to_sample(time_map.to_dict(), rat(end_beat))
    audio = np.zeros((frames, 2), dtype=np.float32)
    length = 64
    window = (np.sin(np.linspace(0, math.pi, length, endpoint=False)) ** 2 * .2).astype(np.float32)
    for channel, positions in enumerate((left_beats, right_beats)):
        for beat in positions:
            at = beat_to_sample(time_map.to_dict(), rat(beat))
            stop = min(frames, at + length)
            if at < 0 or at >= frames:
                raise RuntimeError('click outside fixture span')
            audio[at:stop, channel] += window[:stop-at]
    if np.max(np.abs(audio), initial=0) >= 1:
        raise RuntimeError('click fixture clipped')
    return audio


def channel_rms(audio):
    return [float(np.sqrt(np.mean(audio[:, i].astype(np.float64) ** 2))) for i in range(audio.shape[1])]


def overlay(plan, beats):
    return periodicity_overlay(plan, measured_beats=[rat(x) for x in beats],
                               tolerance_fraction='1/16', support_threshold=.95)


def candidate(report, clock_id):
    return next(row for row in report['candidates'] if row['clock_id'] == clock_id)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--audio-dir', type=Path, required=True)
    parser.add_argument('--sample-rate', type=int, default=48000)
    args = parser.parse_args(); args.audio_dir.mkdir(parents=True, exist_ok=True)

    plan = nested_124_cross32()
    tm = make_time_map(args.sample_rate)
    fast = [fraction(r['beat']) for r in generate_ticks(plan, 'articulation')]
    bounce = [fraction(r['beat']) for r in generate_ticks(plan, 'bounce')]
    sway = [fraction(r['beat']) for r in generate_ticks(plan, 'sway')]
    cross = [fraction(r['beat']) for r in generate_ticks(plan, 'cross-3-2')]
    disturb_fast = shift_nonanchors(fast, sway, Fraction(1, 8))
    disturb_sway = [beat + Fraction(1, 8) for beat in sway]
    conditions = [
        ('nested-baseline', fast, sway, 'nested hierarchy intact'),
        ('disturb-fast-keep-sway', disturb_fast, sway, 'fast articulation displaced; sway anchor unchanged'),
        ('keep-fast-disturb-sway', fast, disturb_sway, 'fast articulation unchanged; sway anchor displaced'),
        ('true-cross-3-2', fast, cross, 'articulation plus explicitly independent 3:2 clock'),
    ]
    rows = []
    for name, left, right, description in conditions:
        audio = click_audio(tm, fraction(plan.to_dict()['end_beat']), left, right)
        path = args.audio_dir / f'{name}.wav'
        wavfile.write(path, args.sample_rate, audio)
        left_overlay, right_overlay = overlay(plan, left), overlay(plan, right)
        rows.append({'name': name, 'description': description, 'left_event_count': len(left),
                     'right_event_count': len(right), 'left_rms': channel_rms(audio)[0],
                     'right_rms': channel_rms(audio)[1], 'peak': float(np.max(np.abs(audio))),
                     'wav': path.name, 'wav_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                     'left_overlay': left_overlay, 'right_overlay': right_overlay})
    base, fast_changed, slow_changed, cross_row = rows
    if (base['left_event_count'], base['right_event_count']) != (fast_changed['left_event_count'], fast_changed['right_event_count']):
        raise RuntimeError('fast-disturbance matched inventory changed')
    if (base['left_event_count'], base['right_event_count']) != (slow_changed['left_event_count'], slow_changed['right_event_count']):
        raise RuntimeError('slow-disturbance matched inventory changed')
    for key in ('left_rms','right_rms','peak'):
        if abs(base[key] - fast_changed[key]) > 1e-12 or abs(base[key] - slow_changed[key]) > 1e-12:
            raise RuntimeError(f'matched click energy changed: {key}')
    if candidate(base['left_overlay'],'articulation')['tick_coverage'] != 1.0:
        raise RuntimeError('baseline articulation not recovered')
    if candidate(base['right_overlay'],'sway')['tick_coverage'] != 1.0:
        raise RuntimeError('baseline sway not recovered')
    if candidate(fast_changed['right_overlay'],'sway')['tick_coverage'] != 1.0:
        raise RuntimeError('stable sway lost when only fast layer changed')
    if candidate(fast_changed['left_overlay'],'articulation')['tick_coverage'] >= .95:
        raise RuntimeError('fast disturbance failed to disturb articulation clock')
    if candidate(slow_changed['left_overlay'],'articulation')['tick_coverage'] != 1.0:
        raise RuntimeError('fast layer changed when only sway was disturbed')
    if candidate(slow_changed['right_overlay'],'sway')['tick_coverage'] >= .95:
        raise RuntimeError('sway disturbance failed to disturb sway clock')
    if candidate(cross_row['right_overlay'],'cross-3-2')['tick_coverage'] != 1.0:
        raise RuntimeError('3:2 cross clock not recovered')

    sample_rows = generate_ticks(plan, 'articulation', tm)
    rounding = [abs(float(fraction(row['rounding_error_samples']))) for row in sample_rows]
    sample_intervals = [b['sample'] - a['sample'] for a,b in zip(sample_rows,sample_rows[1:])
                        if a['phase_segment_index'] == b['phase_segment_index']]
    report = {
        'method': 'zg026-meter-fixtures-v1', 'plan_sha256': plan.sha256,
        'sample_rate_hz': args.sample_rate, 'python': sys.version, 'platform': platform.platform(),
        'scope': 'original stereo click/control evidence; not a zaag sound-quality or listener-preference test',
        'time_map': tm.to_dict(), 'nested_counts': {'articulation':len(fast),'bounce':len(bounce),'sway':len(sway)},
        'cross_relation': clock_relation(plan,'cross-3-2'),
        'sample_rounding': {'maximum_absolute_error_samples': max(rounding),
                            'interval_min_samples': min(sample_intervals), 'interval_max_samples': max(sample_intervals),
                            'policy': 'frozen TimeMap nearest_ties_even; round once after exact beat-to-seconds mapping'},
        'matching': {'method':'identical 64-sample click kernel and identical event inventory per stereo layer for the three nested matched conditions',
                     'perceptual_loudness_match_claimed':False, 'audio_role':'measurement/control fixture'},
        'conditions': rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    (args.audio_dir / 'meter-plan.json').write_text(json.dumps(plan.to_dict(), indent=2, sort_keys=True)+'\n', encoding='utf-8')
    print(json.dumps({'checks':'passed','conditions':len(rows),'sample_rate_hz':args.sample_rate,
                      'max_rounding_error_samples':max(rounding)}))


if __name__ == '__main__': main()
