"""Reproduce ZG-024d preregistered staged-search calibration and independent audits."""
from __future__ import annotations
import argparse, json, math, statistics, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from zaaggenz_contracts import digest
from zaaggenz_jobs import atomic_publish_bytes
from research.zg024b import StrategySpec, run_strategy
from research.zg024d import (METHODS, StagedSpec, run_staged, CALIBRATION_NAME,
    AUDIT_NAMES, ALL_NAMES, SEARCH_SEEDS, research_fixture, normalized_parameter_error)
from research.zg024d.staged import research_implementation

BASELINES = (
    'zg024b.uniform-splitmix.v1',
    'zg024b.halton-shifted.v1',
    'zg024b.coordinate-refine.v1',
)
ATOL, RTOL = 1e-7, 1e-5


def _best(result):
    if not result.ranked_candidate_ids:
        return None
    wanted = result.ranked_candidate_ids[0]
    return next(candidate for candidate in result.candidates if candidate.id == wanted)


def _run(fixture, method):
    fit, audit = fixture.experiment(); started = time.perf_counter()
    if method in METHODS:
        result = run_staged(fit, StagedSpec(method)); family = 'staged'
    else:
        result = run_strategy(fit, StrategySpec(method)); family = 'baseline'
    elapsed = time.perf_counter() - started; best = _best(result)
    audited = audit.evaluate(best, result.audit_selection()) if best is not None else None
    return {
        'fixture': fixture.name, 'seed': fixture.seed, 'family': family, 'method_id': method,
        'declared_budget': fixture.budget.max_evaluations,
        'consumed_evaluations': len(result.candidates),
        'eligible_candidates': sum(candidate.eligible for candidate in result.candidates),
        'best_fit_score': None if best is None else best.score,
        'best_holdout_score': None if audited is None else audited['holdout']['objectives']['score'],
        'parameter_error': None if best is None else normalized_parameter_error(fixture, best),
        'best_parameters': None if best is None else dict(best.to_dict()['parameters']['values']),
        'physical_render_calls': fit.render_calls,
        'search_seconds': elapsed,
        'result_sha256': result.sha256,
    }, {'result': result.to_dict(), 'selected_audit': audited}


def _median(rows, field):
    values = [row[field] for row in rows if row[field] is not None]
    return statistics.median(values) if values else None


def _summaries(rows):
    output = {}
    for name in ALL_NAMES:
        output[name] = {}
        for method in BASELINES + METHODS:
            selected = [row for row in rows if row['fixture'] == name and row['method_id'] == method]
            output[name][method] = {
                'runs': len(selected),
                'eligible_runs': sum(row['best_fit_score'] is not None for row in selected),
                'median_best_fit_score': _median(selected, 'best_fit_score'),
                'median_best_holdout_score': _median(selected, 'best_holdout_score'),
                'median_parameter_error': _median(selected, 'parameter_error'),
            }
    return output


def _select_from_calibration(summaries):
    table = summaries[CALIBRATION_NAME]
    staged = [(table[m]['median_best_fit_score'], m) for m in METHODS
              if table[m]['eligible_runs'] == len(SEARCH_SEEDS) and table[m]['median_best_fit_score'] is not None]
    if not staged:
        return None
    return min(staged, key=lambda item: (item[0], item[1]))[1]


def _decision(summaries, selected):
    calibration = summaries[CALIBRATION_NAME]
    baseline_scores = [calibration[m]['median_best_fit_score'] for m in BASELINES
                       if calibration[m]['median_best_fit_score'] is not None]
    baseline_best = min(baseline_scores) if baseline_scores else None
    selected_score = None if selected is None else calibration[selected]['median_best_fit_score']
    calibration_improved = (selected_score is not None and baseline_best is not None and
                            selected_score < baseline_best and
                            not math.isclose(selected_score, baseline_best, abs_tol=ATOL, rel_tol=RTOL))
    audits = {}
    for name in AUDIT_NAMES:
        table = summaries[name]
        baseline = min((table[m]['median_best_fit_score'] for m in BASELINES
                        if table[m]['median_best_fit_score'] is not None), default=None)
        score = None if selected is None else table[selected]['median_best_fit_score']
        ratio = None if score is None or baseline in (None, 0) else score / baseline
        audits[name] = {'selected_median_fit': score, 'best_baseline_median_fit': baseline, 'ratio': ratio,
                        'beats_or_ties': score is not None and baseline is not None and
                            (score < baseline or math.isclose(score, baseline, abs_tol=ATOL, rel_tol=RTOL))}
    beats = sum(v['beats_or_ties'] for v in audits.values())
    non_regressions = sum(v['ratio'] is not None and v['ratio'] <= 1.05 for v in audits.values())
    return {
        'selected_method_from_calibration_only': selected,
        'calibration_best_baseline_median_fit': baseline_best,
        'calibration_selected_median_fit': selected_score,
        'calibration_strict_improvement': calibration_improved,
        'audit_results': audits,
        'confirmatory_policy_pass': calibration_improved and beats >= 1 and non_regressions >= 2,
        'policy': ('Calibration selects the eligible staged method with lowest median fit across three seeds. It must '
                   'strictly beat the best baseline median. The frozen selection then must beat/tie the best baseline '
                   'on >=1 independent audit and stay within 5% on both audits. Holdout never selects or reranks.'),
    }


def build_report():
    started = time.perf_counter(); rows = []; full = []
    for name in ALL_NAMES:
        for seed in SEARCH_SEEDS:
            for method in BASELINES + METHODS:
                fixture = research_fixture(name, seed=seed)
                row, detail = _run(fixture, method); rows.append(row)
                full.append({'catalogue': fixture.catalogue_record(), 'row': row, **detail})
    summaries = _summaries(rows); selected = _select_from_calibration(summaries); decision = _decision(summaries, selected)
    report = {
        'kind': 'ZG024dStagedStrategyEvidence', 'version': '1.0.0',
        'scope': 'preregistered research only; no production optimizer or product-default selection',
        'design': {
            'calibration_fixture': CALIBRATION_NAME, 'independent_audit_fixtures': list(AUDIT_NAMES),
            'search_seeds': list(SEARCH_SEEDS), 'baseline_methods': list(BASELINES), 'staged_methods': list(METHODS),
            'fairness': 'same fixture/seed/logical budget; cold evaluator per method; all logical candidates retained',
            'selection': 'fit-only; target truth and holdout excluded until after fit selection',
            'failure_policy': 'record no-go if the frozen calibration-selected method fails confirmatory_policy_pass',
        },
        'research_implementation': research_implementation(),
        'runs': rows, 'summaries': summaries, 'decision': decision,
    }
    report['evidence_sha256'] = digest(report)
    telemetry = {'kind':'ZG024dTelemetry','version':'1.0.0','evidence_sha256':report['evidence_sha256'],
                 'total_seconds': time.perf_counter()-started,
                 'note':'wall-clock measurements are host-specific and excluded from evidence identity'}
    return report, full, telemetry


def write(path, value):
    atomic_publish_bytes(path, (json.dumps(value, sort_keys=True, allow_nan=False, separators=(',', ':'))+'\n').encode())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True); parser.add_argument('--full-out', type=Path)
    parser.add_argument('--telemetry-out', type=Path); parser.add_argument('--require-pass', action='store_true')
    args = parser.parse_args(); report, full, telemetry = build_report(); write(args.out, report)
    if args.full_out: write(args.full_out, full)
    if args.telemetry_out: write(args.telemetry_out, telemetry)
    print(json.dumps({'evidence_sha256': report['evidence_sha256'], 'decision': report['decision'],
                      'seconds': telemetry['total_seconds']}, indent=2))
    if args.require_pass and not report['decision']['confirmatory_policy_pass']:
        raise SystemExit('ZG-024d preregistered confirmatory policy did not pass; retain evidence as no-go')

if __name__ == '__main__':
    main()
