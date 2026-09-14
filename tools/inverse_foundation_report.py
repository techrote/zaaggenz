#!/usr/bin/env python3
"""Reproduce ZG-024a fixtures + boring baseline; no target data is sent online.

The deterministic core excludes timings/cache counters. Full records remain
available as per-fixture JSON sidecars; the checked-in report is compact.
"""
from __future__ import annotations
import argparse
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'app'))
import numpy as np
from zaaggenz_contracts import digest
from zaaggenz_inverse import run_baseline, audit_result, Checkpoint, ParameterState
from zaaggenz_inverse.fixtures import CATALOGUE, make_fixture
from zaaggenz_inverse.objectives import AXES
from zaaggenz_inverse.render import execution_identity

BASE_MAIN = '6e0153d824608d6a9899c5ea8e8c0b9a29688c98'


def split_summary(split):
    if split is None:
        return None
    aggregate = split['aggregate']
    return {'vector': aggregate['vector'], 'applicable': aggregate['applicable'],
            'search_score': aggregate['search_score'], 'complete': aggregate['complete'],
            'windows': [{'id': w['window']['id'],
                         'vector': [w['objective']['losses'][k]['scaled'] for k in AXES],
                         'target_feature_id': w['objective']['target_feature_id'],
                         'candidate_feature_id': w['objective']['candidate_feature_id'],
                         'validation_codes': w['validation']['codes'],
                         'level_delta_db': w['validation']['level_delta_db'],
                         'transient_flux_ratio': w['validation']['transient']['flux_ratio'],
                         'before_gain_rms': w['validation']['gain_provenance']['before_gain_qc']['rms'],
                         'after_gain_rms': w['validation']['gain_provenance']['actual_output_qc']['rms'],
                         'output_clip_fraction': w['validation']['gain_provenance']['output_clip_fraction']}
                        for w in split['windows']]}


def recovered_benchmark():
    """Unmodified historical quick-DE smoke; scores are NOT new-harness scores."""
    from uptempo_harmony.inverse import (extract_candidate_features, extract_reference_features,
        feature_distance, inverse_optimize, BASE_BOUNDS, INVERSE_PROFILES, DEFAULT_WEIGHTS, bounds_for)
    from uptempo_harmony.synth import PRESETS, synthesize_one
    target_params = replace(PRESETS['swept_mixed'], sr=16000, beats=1)
    target_audio, _ = synthesize_one(target_params)
    beat_n = round(target_params.sr * 60 / target_params.bpm)
    target_audio = np.pad(target_audio, (0, max(0, beat_n-len(target_audio))))[:beat_n]
    target = extract_reference_features(target_audio, target_params.sr, target_params.bpm, f0_hint=target_params.f0_hz)
    base = replace(PRESETS['neutral'], sr=16000, bpm=target_params.bpm, beats=1)
    audio, debug = synthesize_one(base)
    baseline_score, baseline_components = feature_distance(extract_candidate_features(audio, debug, base, target), target)
    result = inverse_optimize(target, base, profile='quick', maxiter=3, popsize=3, seed=7)
    if not np.isfinite(result.score) or not result.score < baseline_score:
        raise AssertionError('recovered baseline failed its inherited improvement smoke')
    keys, bounds = bounds_for('quick', target.terminal_f0_hz)
    return {'method': 'unmodified recovered scipy differential_evolution quick profile',
            'source': 'app/uptempo_harmony/inverse.py',
            'source_sha256': hashlib.sha256((ROOT/'app/uptempo_harmony/inverse.py').read_bytes()).hexdigest(),
            'seed': 7, 'maxiter': 3, 'popsize': 3, 'evaluations': result.evaluations,
            'target_parameters': target_params.to_dict(), 'initial_parameters': base.to_dict(),
            'best_parameters': result.params.to_dict(), 'active_bounds': {k: list(v) for k, v in zip(keys, bounds)},
            'all_bounds': {k: list(v) for k, v in BASE_BOUNDS.items()}, 'profiles': INVERSE_PROFILES, 'weights': DEFAULT_WEIGHTS,
            'before_score': baseline_score, 'after_score': result.score,
            'before_components': baseline_components, 'after_components': result.components,
            'warning': 'historical peak-normalised feature objective; no holdouts, absolute-level guarantee, or before-normalisation tap; not comparable to new score'}


def build_report(full_dir=None):
    if full_dir is not None:
        full_dir.mkdir(parents=True, exist_ok=True)
    fixtures, observations = [], {}
    for name in CATALOGUE:
        f = make_fixture(name)
        problem, vault = f.problem()
        start = time.perf_counter()
        result = run_baseline(problem)
        search_seconds = time.perf_counter()-start
        # Fresh feature cache: verify measurement as well as render reproducibility.
        fresh, _ = f.problem()
        repeated = run_baseline(fresh)
        if repeated.sha256 != result.sha256:
            raise AssertionError(name + ': repeated deterministic run diverged')
        audit = audit_result(result, vault, f.renderer, store=problem._store)
        data = result.to_dict(); audited = {c['candidate_id']: c for c in audit.to_dict()['candidates']}
        records = []
        for c in data['retained']:
            a = audited[c['id']]
            records.append({'id': c['id'], 'grid_index': c['grid_index'], 'parameters': c['parameters'],
                'render_id': c['render_id'], 'render': c['render'],
                'validation': c['validation'], 'fit': split_summary(c['fit']),
                'held_out': split_summary(a['held_out']), 'whole_signal': split_summary(a['whole_signal'])})
        # Render recipes are reconstructable from the request and state; retain the
        # tap hashes and policy once per candidate rather than repeat entire graphs.
        for row in records:
            r = row.pop('render')
            row['render_taps'] = None if r is None else {k: r[k] for k in ('before_gain','output','output_policy')}
        resume_check = None
        if name == 'fit-only-tail':
            paused = run_baseline(problem, pause_after=1)
            checkpoint = Checkpoint.from_dict(paused.to_dict()['checkpoint'])
            resumed = run_baseline(problem, resume=checkpoint)
            if resumed.to_dict()['ledger'] != data['ledger']:
                raise AssertionError('resume ledger differs from uninterrupted search')
            resume_check = {'checkpoint_sha256': checkpoint.sha256, 'replayed': 1,
                            'trace_sha256': resumed.to_dict()['checkpoint']['trace_sha256']}
        fixtures.append({'name': name, 'fixture_id': f.fixture_id, 'request': f.request.to_dict(),
            'witness_sha256': f.witness.sha256, 'ground_truth_parameters': f.witness.to_dict()['parameters'],
            'generation': {k: f.witness.to_dict()[k] for k in ('source_seed','render_seed','generation','note')},
            'result_sha256': result.sha256, 'repeat_result_sha256': repeated.sha256,
            'candidate_set_sha256': data['candidate_set_sha256'], 'trace_sha256': data['checkpoint']['trace_sha256'],
            'evaluations': data['evaluations'], 'render_calls': data['render_calls'],
            'best_candidate_id': data['best_candidate_id'], 'frontier_candidate_ids': data['frontier_candidate_ids'],
            'ledger': data['ledger'], 'retained': records, 'resume_check': resume_check})
        observations[name] = {'cold_search_seconds': search_seconds,
            'search_repeat_audit_seconds': time.perf_counter()-start,
            'feature_cache_hits_including_audit': problem._store.hits,
            'feature_cache_misses_including_audit': problem._store.misses}
        if full_dir:
            (full_dir/(name+'-search.json')).write_text(result.to_json()+'\n', encoding='utf-8')
            (full_dir/(name+'-audit.json')).write_text(audit.to_json()+'\n', encoding='utf-8')
            (full_dir/(name+'-witness.json')).write_text(f.witness.to_json()+'\n', encoding='utf-8')
        print(f'{name}: {data["evaluations"]} evaluations, {len(data["retained"])} retained, repeated identity verified', flush=True)
    legacy_start = time.perf_counter()
    legacy = recovered_benchmark()
    observations['recovered_quick_de_seconds'] = time.perf_counter()-legacy_start
    core = {'kind': 'ZG024FoundationEvidence', 'version': '1.0.0', 'accepted_main': BASE_MAIN,
            'execution': execution_identity(), 'axes': list(AXES), 'fixtures': fixtures, 'recovered_baseline': legacy,
            'interpretation': 'synthetic calibration; no production-chain identification or listening-quality claim',
            'vector_semantics': 'fixed-order scaled nonnegative losses; raw loss = vector entry * request objective scale; null means target-inapplicable or explicitly incomplete',
            'holdout_policy': 'frozen retained candidates only; no selection from holdout/whole-signal scores',
            'numerical_policy': 'same-execution exact repeat; cross-platform metric comparison rtol=1e-5 atol=1e-6, never substitute hash equality'}
    return {'core': core, 'core_sha256': digest(core), 'observations_not_hashed': observations}


def compare_reports(actual, expected):
    """Portable regression check, intentionally not a false cross-OS hash promise."""
    a, e = actual['core'], expected['core']
    if a['axes'] != e['axes']:
        raise AssertionError('objective axes changed')
    for new, old in zip(a['fixtures'], e['fixtures'], strict=True):
        if new['name'] != old['name'] or new['evaluations'] != old['evaluations']:
            raise AssertionError('fixture inventory/budget changed')
        for key in ('budget', 'domain', 'grid', 'windows', 'seed', 'stage', 'method', 'objectives', 'validation'):
            if new['request'][key] != old['request'][key]:
                raise AssertionError(f"{new['name']}: request {key} changed")
        if new['generation'] != old['generation'] or new['ground_truth_parameters'] != old['ground_truth_parameters']:
            raise AssertionError(f"{new['name']}: fixture generation changed")
        nr = {r['grid_index']: r for r in new['retained']}; er = {r['grid_index']: r for r in old['retained']}
        if nr.keys() != er.keys(): raise AssertionError('retained candidate set changed')
        for index, row in nr.items():
            other = er[index]
            if row['parameters'] != other['parameters'] or row['validation'] != other['validation']:
                raise AssertionError('candidate parameters or validation changed')
            for split in ('fit','held_out','whole_signal'):
                x, y = row[split], other[split]
                if x['applicable'] != y['applicable'] or x['complete'] != y['complete']:
                    raise AssertionError('objective applicability changed')
                np.testing.assert_allclose([v if v is not None else np.nan for v in x['vector']],
                                           [v if v is not None else np.nan for v in y['vector']], rtol=1e-5, atol=1e-6, equal_nan=True,
                                           err_msg=f"{new['name']} grid={index} {split} axes={AXES}")
                if [w['validation_codes'] for w in x['windows']] != [w['validation_codes'] for w in y['windows']]:
                    raise AssertionError('window gate outcomes changed')
    if a['recovered_baseline']['source_sha256'] != e['recovered_baseline']['source_sha256']:
        raise AssertionError('recovered baseline source changed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--full-dir', type=Path)
    parser.add_argument('--compare', type=Path)
    args = parser.parse_args()
    report = build_report(args.full_dir)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, sort_keys=True, separators=(',', ':'), allow_nan=False)+'\n', encoding='utf-8')
    if args.compare:
        compare_reports(report, json.loads(args.compare.read_text(encoding='utf-8')))
    print('evidence core SHA256:', report['core_sha256'])


if __name__ == '__main__': main()
