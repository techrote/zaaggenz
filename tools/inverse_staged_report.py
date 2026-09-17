"""Reproduce the frozen ZG-024d v2 staged-search development and confirmation programme."""
from __future__ import annotations

import argparse
from functools import cmp_to_key
import json
import math
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from zaaggenz_contracts import digest
from zaaggenz_jobs import atomic_publish_bytes
from research.zg024b import StrategySpec, run_strategy
from research.zg024d import (
    DESIGN_MANIFEST, DEVELOPMENT_NAMES, METHODS, SEARCH_SEEDS, SENTINEL_NAMES,
    StagedSpec, design_sha256, development_fixture, normalized_parameter_error,
    run_staged, sentinel_renderer,
)
from research.zg024d.staged import research_implementation

BASELINES = (
    'zg024b.uniform-splitmix.v1',
    'zg024b.halton-shifted.v1',
    'zg024b.coordinate-refine.v1',
)
ATOL, RTOL = 1e-7, 1e-5


def _close(a, b):
    return a is not None and b is not None and math.isclose(a, b, abs_tol=ATOL, rel_tol=RTOL)


def _score_cmp(left, right):
    a, b = left[1], right[1]
    if a is None and b is None:
        return (left[0] > right[0])-(left[0] < right[0])
    if a is None:
        return 1
    if b is None:
        return -1
    if _close(a, b):
        return (left[0] > right[0])-(left[0] < right[0])
    return -1 if a < b else 1


def _best(result, staged):
    ids = result.final_retained_candidate_ids if staged else result.ranked_candidate_ids
    if not ids:
        return None
    by_id = {candidate.id: candidate for candidate in result.candidates}
    choices = [by_id[value] for value in ids]
    choices = [candidate for candidate in choices if candidate.eligible]
    return min(choices, key=lambda candidate: (candidate.score if candidate.score is not None else math.inf,
                                                tuple(value for _, value in candidate.to_dict()['parameters']['values']),
                                                candidate.id)) if choices else None


def _rejection_counts(result):
    counts = {}
    for candidate in result.candidates:
        for window in candidate.to_dict()['fit']['windows']:
            for reason in window['validation']['rejected_reasons']:
                counts[reason] = counts.get(reason, 0)+1
    return dict(sorted(counts.items()))


def _promotion_violations(result):
    if not hasattr(result, 'promotions'):
        return 0
    eligible = {candidate.id for candidate in result.candidates if candidate.eligible}
    return sum(candidate_id not in eligible for record in result.promotions
               for candidate_id in record['retained_candidate_ids'])


def _run(fixture, method, *, fit_kwargs=None):
    fit_kwargs = fit_kwargs or {}
    fit, audit = fixture.experiment(**fit_kwargs)
    started = time.perf_counter()
    staged = method in METHODS
    result = run_staged(fit, StagedSpec(method)) if staged else run_strategy(fit, StrategySpec(method))
    elapsed = time.perf_counter()-started
    best = _best(result, staged)
    audited = None
    if best is not None:
        selection = result.audit_selection()
        audited = audit.evaluate(best, selection)
    row = {
        'fixture': fixture.name, 'seed': fixture.seed,
        'family': 'staged' if staged else 'baseline', 'method_id': method,
        'declared_budget': fixture.budget.max_evaluations,
        'consumed_evaluations': len(result.candidates),
        'eligible_candidates': sum(candidate.eligible for candidate in result.candidates),
        'best_fit_score': None if best is None else best.score,
        'best_holdout_score': None if audited is None else audited['holdout']['objectives']['score'],
        'parameter_error': None if best is None else normalized_parameter_error(fixture, best),
        'best_parameters': None if best is None else dict(best.to_dict()['parameters']['values']),
        'stage_consumption': dict(result.stage_consumption) if staged else None,
        'final_retained_count': len(result.final_retained_candidate_ids) if staged else None,
        'promotion_ineligible_violations': _promotion_violations(result),
        'gate_rejections': _rejection_counts(result),
        'stop_reason': result.stop_reason if staged else None,
        'physical_render_calls': fit.render_calls, 'render_cache_hits': fit.render_hits,
        'search_seconds': elapsed, 'result_sha256': result.sha256,
        'environment_sha256': fit.environment_sha256,
    }
    detail = {'catalogue': fixture.catalogue_record(), 'row': row, 'result': result.to_dict(),
              'selected_audit': audited}
    return row, detail


def _method_ranks(rows, methods):
    ranks = {method: [] for method in methods}
    for fixture in DEVELOPMENT_NAMES:
        for seed in SEARCH_SEEDS:
            case = [(method, next((row['best_fit_score'] for row in rows
                                   if row['fixture'] == fixture and row['seed'] == seed and row['method_id'] == method), None))
                    for method in methods]
            ordered = sorted(case, key=cmp_to_key(_score_cmp))
            rank = 1
            previous = None
            for index, (method, score) in enumerate(ordered):
                if index and not _close(previous, score):
                    rank = index+1
                ranks[method].append(rank)
                previous = score
    return ranks


def _median(values):
    finite = [value for value in values if value is not None and math.isfinite(value)]
    return statistics.median(finite) if finite else None


def _select_staged(development_rows):
    ranks = _method_ranks(development_rows, METHODS)
    summary = {}
    for method in METHODS:
        method_rows = [row for row in development_rows if row['method_id'] == method]
        summary[method] = {
            'median_rank': statistics.median(ranks[method]),
            'median_best_fit_score': _median([row['best_fit_score'] for row in method_rows]),
            'eligible_cases': sum(row['best_fit_score'] is not None for row in method_rows),
            'promotion_ineligible_violations': sum(row['promotion_ineligible_violations'] for row in method_rows),
        }
    selected = min(METHODS, key=lambda method: (summary[method]['median_rank'],
                    math.inf if summary[method]['median_best_fit_score'] is None else summary[method]['median_best_fit_score'],
                    method))
    return selected, summary


def _best_baseline(rows, fixture, seed, field='best_fit_score'):
    values = [(method, next((row[field] for row in rows if row['fixture'] == fixture and row['seed'] == seed
                             and row['method_id'] == method), None)) for method in BASELINES]
    ordered = sorted(values, key=cmp_to_key(_score_cmp))
    return ordered[0]


def _ratio(value, baseline):
    if value is None or baseline is None:
        return None
    if _close(value, baseline):
        return 1.0
    if baseline == 0:
        return math.inf if value > 0 else 1.0
    return value/baseline


def _paired_support(rows, selected, fixture_names):
    cases = []
    for fixture in fixture_names:
        for seed in SEARCH_SEEDS:
            selected_row = next(row for row in rows if row['fixture'] == fixture and row['seed'] == seed
                                and row['method_id'] == selected)
            baseline_method, baseline_score = _best_baseline(rows, fixture, seed)
            score = selected_row['best_fit_score']; ratio = _ratio(score, baseline_score)
            tie_or_better = (score is not None and baseline_score is not None and
                             (score < baseline_score or _close(score, baseline_score)))
            cases.append({'fixture': fixture, 'seed': seed, 'selected_score': score,
                          'best_baseline_method': baseline_method, 'best_baseline_score': baseline_score,
                          'ratio': ratio, 'beats_or_ties': tie_or_better,
                          'worse_by_over_10_percent': ratio is None or ratio > 1.10})
    return cases


def _holdout_confirmation(rows, selected, confirmation_names):
    output = {}
    for fixture in confirmation_names:
        selected_values = [row['best_holdout_score'] for row in rows
                           if row['fixture'] == fixture and row['method_id'] == selected]
        selected_median = _median(selected_values)
        baseline_medians = {}
        for method in BASELINES:
            baseline_medians[method] = _median([row['best_holdout_score'] for row in rows
                if row['fixture'] == fixture and row['method_id'] == method])
        finite = [(method, value) for method, value in baseline_medians.items() if value is not None]
        best_method, best_value = min(finite, key=lambda pair: pair[1]) if finite else (None, None)
        ratio = _ratio(selected_median, best_value)
        output[fixture] = {'selected_median_holdout': selected_median,
                           'best_baseline_method': best_method,
                           'best_baseline_median_holdout': best_value,
                           'ratio': ratio, 'regresses_over_10_percent': ratio is None or ratio > 1.10}
    return output


def _sentinels(selected):
    rows, details = [], []
    for name in SENTINEL_NAMES:
        fixture = development_fixture(name, seed='41')
        renderer, renderer_id = sentinel_renderer(name)
        row, detail = _run(fixture, selected, fit_kwargs={'renderer': renderer, 'renderer_id': renderer_id})
        rows.append(row); details.append(detail)
    return rows, details


def _portable_row(row):
    return {key: row[key] for key in (
        'fixture', 'seed', 'family', 'method_id', 'declared_budget', 'consumed_evaluations',
        'eligible_candidates', 'best_fit_score', 'best_holdout_score', 'parameter_error',
        'stage_consumption', 'final_retained_count', 'promotion_ineligible_violations',
        'gate_rejections', 'stop_reason')}


def _budget_accounting_ok(row):
    """Validate exact logical-budget accounting without defeating fail-closed gates.

    Flat comparators must consume their entire declared budget. A staged run must
    either consume its complete frozen allocation or stop at the first stage whose
    eligible-parent set is empty, with every downstream evaluation left explicitly
    unspent. Those early stops are the protocol-v2 safety semantics and rank as no
    eligible candidate; they are not an integrity failure and must never be filled by
    promoting a rejected parent merely to reach 24 evaluations.
    """
    declared = row['declared_budget']
    consumed = row['consumed_evaluations']
    if type(declared) is not int or type(consumed) is not int or declared != 24:
        return False
    if row['family'] == 'baseline':
        return (row['method_id'] in BASELINES and consumed == declared and
                row['stage_consumption'] is None and row['stop_reason'] is None)
    if row['family'] != 'staged' or row['method_id'] not in METHODS:
        return False

    allocation = dict(zip(('A', 'B', 'C'), StagedSpec(row['method_id']).allocation))
    stage = row['stage_consumption']
    if not isinstance(stage, dict) or set(stage) != {'A', 'B', 'C'}:
        return False
    if any(type(value) is not int or value < 0 for value in stage.values()):
        return False
    if sum(stage.values()) != consumed or sum(allocation.values()) != declared:
        return False

    stop = row['stop_reason']
    if stop is None:
        expected = allocation
        if row['final_retained_count'] is None or row['final_retained_count'] <= 0:
            return False
    elif stop == 'stage-A-no-eligible-parent':
        expected = {'A': allocation['A'], 'B': 0, 'C': 0}
    elif stop == 'stage-B-no-eligible-parent':
        expected = {'A': allocation['A'], 'B': allocation['B'], 'C': 0}
    elif stop == 'stage-C-no-eligible-final-alternative':
        expected = allocation
    else:
        return False

    if stage != expected or consumed != sum(expected.values()):
        return False
    if stop is not None and (row['best_fit_score'] is not None or row['final_retained_count'] != 0):
        return False
    return True


def build_report():
    started = time.perf_counter(); development_rows = []; full = []
    all_methods = BASELINES + METHODS
    for name in DEVELOPMENT_NAMES:
        for seed in SEARCH_SEEDS:
            for method in all_methods:
                row, detail = _run(development_fixture(name, seed=seed), method)
                development_rows.append(row); full.append(detail)

    # Frozen method choice is made exclusively from development fit evidence. Only now
    # is the post-design-freeze confirmation catalogue imported/built.
    selected, staged_summary = _select_staged(development_rows)
    dev_cases = _paired_support(development_rows, selected, DEVELOPMENT_NAMES)
    selected_dev_rows = [row for row in development_rows if row['method_id'] == selected]
    development_supported = (
        sum(case['beats_or_ties'] for case in dev_cases) >= 9 and
        sum(case['worse_by_over_10_percent'] for case in dev_cases) <= 2 and
        sum(row['promotion_ineligible_violations'] for row in selected_dev_rows) == 0
    )

    from research.zg024d.confirmation import CONFIRMATION_NAMES, DESIGN_FREEZE_COMMIT, confirmation_fixture
    confirmation_rows = []
    for name in CONFIRMATION_NAMES:
        for seed in SEARCH_SEEDS:
            for method in BASELINES + (selected,):
                row, detail = _run(confirmation_fixture(name, seed=seed), method)
                confirmation_rows.append(row); full.append(detail)
    confirm_cases = _paired_support(confirmation_rows, selected, CONFIRMATION_NAMES)
    holdout = _holdout_confirmation(confirmation_rows, selected, CONFIRMATION_NAMES)

    sentinel_rows, sentinel_details = _sentinels(selected); full.extend(sentinel_details)
    sentinel_integrity = all(row['promotion_ineligible_violations'] == 0 and row['gate_rejections']
                             for row in sentinel_rows)
    exact_budget_integrity = all(_budget_accounting_ok(row)
                                 for row in development_rows+confirmation_rows)
    promotion_integrity = all(row['promotion_ineligible_violations'] == 0
                              for row in development_rows+confirmation_rows+sentinel_rows)
    confirmation_supported = (sum(case['beats_or_ties'] for case in confirm_cases) >= 6 and
                              not any(case['worse_by_over_10_percent'] for case in confirm_cases))
    holdout_supported = not any(item['regresses_over_10_percent'] for item in holdout.values())
    production_candidate_supported = (development_supported and confirmation_supported and holdout_supported and
                                      sentinel_integrity and exact_budget_integrity and promotion_integrity)

    rejected = {}
    for method in METHODS:
        if method == selected:
            continue
        rejected[method] = {'reason': 'not selected by frozen development median-rank policy',
                            **staged_summary[method]}

    decision = {
        'selected_method_from_development_only': selected,
        'development_supported': development_supported,
        'development_cases_beating_or_tying_best_flat': sum(case['beats_or_ties'] for case in dev_cases),
        'development_cases_worse_over_10_percent': sum(case['worse_by_over_10_percent'] for case in dev_cases),
        'confirmation_cases_beating_or_tying_best_flat': sum(case['beats_or_ties'] for case in confirm_cases),
        'confirmation_cases_worse_over_10_percent': sum(case['worse_by_over_10_percent'] for case in confirm_cases),
        'confirmation_supported': confirmation_supported,
        'holdout_supported': holdout_supported,
        'sentinel_integrity': sentinel_integrity,
        'exact_budget_integrity': exact_budget_integrity,
        'promotion_integrity': promotion_integrity,
        'production_candidate_supported': production_candidate_supported,
        'outcome': ('production-candidate-supported' if production_candidate_supported else
                    'mixed-or-no-go-no-production-promotion'),
        'policy': ('frozen by ZG024_STAGED_PROTOCOL_V2.md; confirmation cannot select another staged method; '
                   'exact budget integrity includes explicitly accounted fail-closed safety stops'),
    }

    portable = {
        'kind': 'ZG024dPortableEvidence', 'version': '2.0.0', 'design_sha256': design_sha256(),
        'selected_method': selected,
        'development': [_portable_row(row) for row in development_rows],
        'confirmation': [_portable_row(row) for row in confirmation_rows],
        'sentinels': [_portable_row(row) for row in sentinel_rows],
        'staged_summary': staged_summary, 'development_cases': dev_cases,
        'confirmation_cases': confirm_cases, 'holdout_confirmation': holdout,
        'decision': decision,
    }
    report = {
        'kind': 'ZG024dStagedStrategyEvidence', 'version': '2.0.0',
        'scope': 'fresh development + post-freeze confirmation research; production promotion only if frozen bar passes',
        'invalidated_prior_draft': ('PR #195 v1 evidence was not inspected and is excluded because acceptance review '
                                    'found the v1 design incomplete before v2 confirmation disclosure'),
        'design_manifest': DESIGN_MANIFEST, 'design_sha256': design_sha256(),
        'design_freeze_commit': DESIGN_FREEZE_COMMIT,
        'research_implementation': research_implementation(),
        'baseline_methods': list(BASELINES), 'staged_methods': list(METHODS),
        'development_rows': development_rows, 'confirmation_rows': confirmation_rows,
        'sentinel_rows': sentinel_rows, 'staged_summary': staged_summary,
        'development_cases': dev_cases, 'confirmation_cases': confirm_cases,
        'holdout_confirmation': holdout, 'rejected_staged_alternatives': rejected,
        'decision': decision, 'portable': portable,
    }
    report['portable_sha256'] = digest(portable)
    report['evidence_sha256'] = digest(report)
    telemetry = {'kind': 'ZG024dTelemetry', 'version': '2.0.0',
                 'evidence_sha256': report['evidence_sha256'],
                 'total_seconds': time.perf_counter()-started,
                 'note': 'wall-clock measurements are host-specific and excluded from portable evidence identity'}
    return report, full, telemetry


def write(path, value):
    atomic_publish_bytes(path, (json.dumps(value, sort_keys=True, allow_nan=False,
                                           separators=(',', ':'))+'\n').encode())


def _portable_compare(actual, expected, path='root'):
    if type(actual) is not type(expected):
        raise ValueError(f'{path}: type mismatch')
    if isinstance(actual, dict):
        if set(actual) != set(expected):
            raise ValueError(f'{path}: key mismatch')
        for key in actual:
            _portable_compare(actual[key], expected[key], path+'.'+key)
    elif isinstance(actual, list):
        if len(actual) != len(expected):
            raise ValueError(f'{path}: list length mismatch')
        for index, (a, b) in enumerate(zip(actual, expected)):
            _portable_compare(a, b, f'{path}[{index}]')
    elif isinstance(actual, float):
        if not math.isclose(actual, expected, abs_tol=ATOL, rel_tol=RTOL):
            raise ValueError(f'{path}: {actual!r} != {expected!r}')
    elif actual != expected:
        raise ValueError(f'{path}: {actual!r} != {expected!r}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--full-out', type=Path)
    parser.add_argument('--telemetry-out', type=Path)
    parser.add_argument('--portable-out', type=Path)
    parser.add_argument('--check-portable', type=Path)
    parser.add_argument('--require-integrity', action='store_true')
    args = parser.parse_args()
    report, full, telemetry = build_report()
    write(args.out, report)
    if args.full_out: write(args.full_out, full)
    if args.telemetry_out: write(args.telemetry_out, telemetry)
    if args.portable_out: write(args.portable_out, report['portable'])
    if args.check_portable:
        expected = json.loads(args.check_portable.read_text(encoding='utf-8'))
        _portable_compare(report['portable'], expected)
    print(json.dumps({'evidence_sha256': report['evidence_sha256'],
                      'portable_sha256': report['portable_sha256'],
                      'decision': report['decision'], 'seconds': telemetry['total_seconds']}, indent=2))
    if args.require_integrity:
        decision = report['decision']
        if not (decision['exact_budget_integrity'] and decision['promotion_integrity'] and
                decision['sentinel_integrity']):
            raise SystemExit('ZG-024d integrity policy failed; retain evidence and do not promote')


if __name__ == '__main__':
    main()
