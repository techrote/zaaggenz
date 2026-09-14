"""Reproduce ZG-024b fixed-budget strategy comparisons and post-selection audits."""
from __future__ import annotations

import argparse
import gzip
import json
import math
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from zaaggenz_contracts import digest
from zaaggenz_jobs import atomic_publish_bytes
from research.zg024b.fixtures import (CORE_NAMES, SEARCH_SEEDS, SENTINEL_NAME,
    research_fixture, normalized_parameter_error, nonidentifiable_manifold_error)
from research.zg024b.strategies import METHODS, StrategySpec, run_strategy, research_implementation

BASE_COMMIT = '7316a6ceeeeac11a48264c925b639d6dfad07f53'
ATOL = 1e-7
RTOL = 1e-5


def _candidate_by_id(result, candidate_id):
    return next(c for c in result.candidates if c.id == candidate_id)


def _losses(candidate):
    return candidate.to_dict()['fit']['objectives']['components']


def _summary_run(fixture, strategy, fit, audit, result):
    best = _candidate_by_id(result, result.ranked_candidate_ids[0]) if result.ranked_candidate_ids else None
    audit_report = None
    if best is not None:
        audit_report = audit.evaluate(best, result.audit_selection())
    return {
        'fixture': fixture.name,
        'fixture_id': fixture.catalogue_record()['fixture_id'],
        'seed': fixture.seed,
        'method_id': strategy.method_id,
        'declared_budget': fixture.budget.max_evaluations,
        'consumed_evaluations': len(result.candidates),
        'proposal_attempts': result.proposal_attempts,
        'eligible_candidates': sum(c.eligible for c in result.candidates),
        'pareto_candidates': len(result.pareto_candidate_ids),
        'best_ordinal': None if best is None else best.to_dict()['ordinal'],
        'best_parameters': None if best is None else dict(best.to_dict()['parameters']['values']),
        'best_fit_score': None if best is None else best.score,
        'best_fit_components': None if best is None else _losses(best),
        'best_holdout_score': None if audit_report is None else audit_report['holdout']['objectives']['score'],
        'best_holdout_components': None if audit_report is None else audit_report['holdout']['objectives']['components'],
        'whole_signal_score': None if audit_report is None else audit_report['whole_signal']['objectives']['score'],
        'overfit_warning': None if audit_report is None else audit_report['overfit_warning'],
        'parameter_error': None if best is None else normalized_parameter_error(fixture, best),
        'nonidentifiable_manifold_error': None if best is None else nonidentifiable_manifold_error(fixture, best),
        'physical_render_calls': fit.render_calls,
        'verified_render_cache_hits': fit.render_hits,
        'feature_cache_hits': fit.features.hits,
        'feature_cache_misses': fit.features.calls,
    }, audit_report


def _aggregate(core_rows):
    out = {}
    for method in METHODS:
        rows = [r for r in core_rows if r['method_id'] == method]
        identifiable = [r for r in rows if r['parameter_error'] is not None]
        nonid = [r for r in rows if r['nonidentifiable_manifold_error'] is not None]
        fits = [r['best_fit_score'] for r in rows if r['best_fit_score'] is not None]
        holds = [r['best_holdout_score'] for r in rows if r['best_holdout_score'] is not None]
        out[method] = {
            'runs': len(rows),
            'top_candidate_available_rate': sum(r['best_fit_score'] is not None for r in rows)/len(rows),
            'median_best_fit_score': statistics.median(fits) if fits else None,
            'mean_best_fit_score': sum(fits)/len(fits) if fits else None,
            'median_best_holdout_score': statistics.median(holds) if holds else None,
            'median_identifiable_parameter_error': statistics.median(r['parameter_error'] for r in identifiable) if identifiable else None,
            'median_nonidentifiable_manifold_error': statistics.median(r['nonidentifiable_manifold_error'] for r in nonid) if nonid else None,
            'median_physical_render_calls': statistics.median(r['physical_render_calls'] for r in rows),
            'mean_pareto_candidates': sum(r['pareto_candidates'] for r in rows)/len(rows),
        }
    wins = {m: 0 for m in METHODS}
    for name in CORE_NAMES:
        for seed in SEARCH_SEEDS:
            group = [r for r in core_rows if r['fixture'] == name and r['seed'] == seed and r['best_fit_score'] is not None]
            if not group:
                continue
            best = min(r['best_fit_score'] for r in group)
            for row in group:
                if math.isclose(row['best_fit_score'], best, abs_tol=ATOL, rel_tol=RTOL):
                    wins[row['method_id']] += 1
    for method in METHODS:
        out[method]['paired_fit_wins_or_ties'] = wins[method]
    return out


def build_report():
    started = time.perf_counter()
    core_rows, full_runs, timing = [], [], []
    for name in CORE_NAMES:
        for seed in SEARCH_SEEDS:
            for method in METHODS:
                fixture = research_fixture(name, seed=seed)
                fit, audit = fixture.experiment()
                strategy = StrategySpec(method)
                t0 = time.perf_counter()
                result = run_strategy(fit, strategy)
                search_seconds = time.perf_counter()-t0
                row, audit_report = _summary_run(fixture, strategy, fit, audit, result)
                core_rows.append(row)
                full_runs.append({'catalogue': fixture.catalogue_record(), 'strategy': strategy.to_dict(),
                                  'result': result.to_dict(), 'selected_audit': audit_report})
                timing.append({'fixture': name, 'seed': seed, 'method_id': method,
                               'search_seconds': search_seconds,
                               'total_seconds': time.perf_counter()-t0,
                               'physical_render_calls': fit.render_calls,
                               'feature_cache_hits': fit.features.hits,
                               'feature_cache_misses': fit.features.calls})

    sentinel_rows = []
    for method in METHODS:
        fixture = research_fixture(SENTINEL_NAME, seed='24')
        fit, audit = fixture.experiment()
        strategy = StrategySpec(method)
        result = run_strategy(fit, strategy)
        row, audit_report = _summary_run(fixture, strategy, fit, audit, result)
        sentinel_rows.append(row)
        full_runs.append({'catalogue': fixture.catalogue_record(), 'strategy': strategy.to_dict(),
                          'result': result.to_dict(), 'selected_audit': audit_report})

    report = {
        'kind': 'ZG024bStrategyResearchEvidence', 'version': '1.0.0',
        'base_commit': BASE_COMMIT,
        'scope': 'search-strategy research only; no production optimizer selection',
        'design': {
            'methods': list(METHODS), 'core_fixtures': list(CORE_NAMES), 'search_seeds': list(SEARCH_SEEDS),
            'sentinel': SENTINEL_NAME,
            'fairness': 'same fixture/search seed/logical budget per paired method; each method starts with cold evaluator caches',
            'selection': 'fit-only eligibility and aggregate score; holdout/truth diagnostics computed only after fit selection',
            'portable_tolerances': {'absolute': ATOL, 'relative': RTOL},
        },
        'research_implementation': research_implementation(),
        'core_runs': core_rows,
        'strategy_aggregates': _aggregate(core_rows),
        'holdout_sentinel_runs': sentinel_rows,
    }
    report['evidence_sha256'] = digest(report)
    telemetry = {'kind': 'ZG024bStrategyTelemetry', 'version': '1.0.0',
                 'evidence_sha256': report['evidence_sha256'], 'runs': timing,
                 'total_seconds': time.perf_counter()-started,
                 'note': 'wall-clock telemetry is host-specific and excluded from evidence identity'}
    return report, full_runs, telemetry


_CAL_FIELDS = ('fixture', 'seed', 'method_id', 'declared_budget', 'consumed_evaluations',
               'proposal_attempts', 'eligible_candidates', 'pareto_candidates', 'best_ordinal',
               'best_parameters', 'best_fit_score', 'best_holdout_score', 'whole_signal_score',
               'overfit_warning', 'parameter_error', 'nonidentifiable_manifold_error',
               'physical_render_calls')


def calibration_reference(report):
    """Compact portable freeze; complete components/lineage remain in CI evidence artifacts."""
    return {
        'kind': 'ZG024bStrategyCalibration', 'version': '1.0.0',
        'base_commit': report['base_commit'], 'design': report['design'],
        'strategy_aggregates': report['strategy_aggregates'],
        'core_runs': [{k: row[k] for k in _CAL_FIELDS} for row in report['core_runs']],
        'holdout_sentinel_runs': [{k: row[k] for k in _CAL_FIELDS} for row in report['holdout_sentinel_runs']],
        'note': 'portable frozen outcomes; full per-component candidate evidence remains in CI artifacts',
    }


def compare_reports(actual, expected):
    failures = []
    def walk(a, e, path):
        if isinstance(e, bool) or e is None or isinstance(e, str):
            if type(a) is not type(e) or a != e:
                failures.append(path + ': discrete value changed')
        elif isinstance(e, (int, float)):
            if type(a) not in (int, float) or not math.isfinite(a) or not math.isclose(a, e, abs_tol=ATOL, rel_tol=RTOL):
                failures.append(path + f': numeric mismatch {a!r} vs {e!r}')
        elif isinstance(e, dict):
            if type(a) is not dict or a.keys() != e.keys():
                failures.append(path + ': fields changed'); return
            for key in e:
                walk(a[key], e[key], path+'/'+key)
        elif isinstance(e, list):
            if type(a) is not list or len(a) != len(e):
                failures.append(path + ': length changed'); return
            for i, (av, ev) in enumerate(zip(a, e)):
                walk(av, ev, path+f'/{i}')
        else:
            failures.append(path + ': unsupported evidence type')
    walk(calibration_reference(actual), expected, '')
    return failures


def write_json(path, value, *, compact=False):
    text = json.dumps(value, sort_keys=True, allow_nan=False,
                      separators=(',', ':') if compact else None,
                      indent=None if compact else 2) + '\n'
    payload = text.encode('utf-8')
    if str(path).endswith('.gz'):
        payload = gzip.compress(payload, mtime=0)
    atomic_publish_bytes(path, payload)


def read_json(path):
    opener = gzip.open if str(path).endswith('.gz') else open
    with opener(path, 'rb') as stream:
        payload = stream.read(2*1024*1024+1)
    if len(payload) > 2*1024*1024:
        raise ValueError('ZG-024b reference exceeds 2 MiB')
    return json.loads(payload.decode('utf-8'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--full-out', type=Path)
    parser.add_argument('--telemetry-out', type=Path)
    parser.add_argument('--reference-out', type=Path)
    parser.add_argument('--check', type=Path)
    args = parser.parse_args()
    report, full, telemetry = build_report()
    write_json(args.out, report, compact=True)
    if args.full_out:
        write_json(args.full_out, full, compact=True)
    if args.telemetry_out:
        write_json(args.telemetry_out, telemetry)
    reference = calibration_reference(report)
    if args.reference_out:
        write_json(args.reference_out, reference, compact=True)
    failures = compare_reports(report, read_json(args.check)) if args.check else []
    print(json.dumps({'evidence_sha256': report['evidence_sha256'], 'core_runs': len(report['core_runs']),
                      'sentinel_runs': len(report['holdout_sentinel_runs']),
                      'seconds': telemetry['total_seconds'], 'comparison_failures': failures}, indent=2))
    if failures:
        raise SystemExit('ZG-024b evidence comparison failed')


if __name__ == '__main__':
    main()
