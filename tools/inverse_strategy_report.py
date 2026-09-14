"""Reproduce ZG-024b fixed-budget strategy comparisons and post-selection audits."""
from __future__ import annotations
import argparse, gzip, json, math, statistics, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from zaaggenz_contracts import digest
from zaaggenz_jobs import atomic_publish_bytes
from research.zg024b.fixtures import (CORE_NAMES, SEARCH_SEEDS, SENTINEL_NAME,
    research_fixture, normalized_parameter_error, nonidentifiable_manifold_error)
from research.zg024b.strategies import METHODS, StrategySpec, run_strategy, research_implementation

BASE_COMMIT = '7316a6ceeeeac11a48264c925b639d6dfad07f53'
ATOL, RTOL = 1e-7, 1e-5


def _candidate_by_id(result, candidate_id):
    return next(c for c in result.candidates if c.id == candidate_id)


def _summary_run(fixture, strategy, fit, audit, result):
    best = _candidate_by_id(result, result.ranked_candidate_ids[0]) if result.ranked_candidate_ids else None
    audited = audit.evaluate(best, result.audit_selection()) if best is not None else None
    return {
        'fixture': fixture.name, 'fixture_id': fixture.catalogue_record()['fixture_id'],
        'seed': fixture.seed, 'method_id': strategy.method_id,
        'declared_budget': fixture.budget.max_evaluations,
        'consumed_evaluations': len(result.candidates), 'proposal_attempts': result.proposal_attempts,
        'eligible_candidates': sum(c.eligible for c in result.candidates),
        'pareto_candidates': len(result.pareto_candidate_ids),
        'best_ordinal': None if best is None else best.to_dict()['ordinal'],
        'best_parameters': None if best is None else dict(best.to_dict()['parameters']['values']),
        'best_fit_score': None if best is None else best.score,
        'best_fit_components': None if best is None else best.to_dict()['fit']['objectives']['components'],
        'best_holdout_score': None if audited is None else audited['holdout']['objectives']['score'],
        'best_holdout_components': None if audited is None else audited['holdout']['objectives']['components'],
        'whole_signal_score': None if audited is None else audited['whole_signal']['objectives']['score'],
        'overfit_warning': None if audited is None else audited['overfit_warning'],
        'parameter_error': None if best is None else normalized_parameter_error(fixture, best),
        'nonidentifiable_manifold_error': None if best is None else nonidentifiable_manifold_error(fixture, best),
        'physical_render_calls': fit.render_calls, 'verified_render_cache_hits': fit.render_hits,
        'feature_cache_hits': fit.features.hits, 'feature_cache_misses': fit.features.calls,
    }, audited


def _aggregate(rows):
    out = {}
    for method in METHODS:
        r = [x for x in rows if x['method_id'] == method]
        ident = [x for x in r if x['parameter_error'] is not None]
        nonid = [x for x in r if x['nonidentifiable_manifold_error'] is not None]
        fits = [x['best_fit_score'] for x in r if x['best_fit_score'] is not None]
        holds = [x['best_holdout_score'] for x in r if x['best_holdout_score'] is not None]
        out[method] = {
            'runs': len(r), 'top_candidate_available_rate': sum(x['best_fit_score'] is not None for x in r)/len(r),
            'median_best_fit_score': statistics.median(fits) if fits else None,
            'mean_best_fit_score': sum(fits)/len(fits) if fits else None,
            'median_best_holdout_score': statistics.median(holds) if holds else None,
            'median_identifiable_parameter_error': statistics.median(x['parameter_error'] for x in ident) if ident else None,
            'median_nonidentifiable_manifold_error': statistics.median(x['nonidentifiable_manifold_error'] for x in nonid) if nonid else None,
            'median_physical_render_calls': statistics.median(x['physical_render_calls'] for x in r),
            'mean_pareto_candidates': sum(x['pareto_candidates'] for x in r)/len(r), 'paired_fit_wins_or_ties': 0,
        }
    for name in CORE_NAMES:
        for seed in SEARCH_SEEDS:
            group = [x for x in rows if x['fixture'] == name and x['seed'] == seed and x['best_fit_score'] is not None]
            if not group: continue
            best = min(x['best_fit_score'] for x in group)
            for row in group:
                if math.isclose(row['best_fit_score'], best, abs_tol=ATOL, rel_tol=RTOL):
                    out[row['method_id']]['paired_fit_wins_or_ties'] += 1
    return out


def build_report():
    started = time.perf_counter(); core, full, timing = [], [], []
    for name in CORE_NAMES:
        for seed in SEARCH_SEEDS:
            for method in METHODS:
                fixture = research_fixture(name, seed=seed); fit, audit = fixture.experiment(); strategy = StrategySpec(method)
                t0 = time.perf_counter(); result = run_strategy(fit, strategy); search_seconds = time.perf_counter()-t0
                row, audited = _summary_run(fixture, strategy, fit, audit, result); core.append(row)
                full.append({'catalogue': fixture.catalogue_record(), 'strategy': strategy.to_dict(),
                             'result': result.to_dict(), 'selected_audit': audited})
                timing.append({'fixture': name, 'seed': seed, 'method_id': method, 'search_seconds': search_seconds,
                               'total_seconds': time.perf_counter()-t0, 'physical_render_calls': fit.render_calls,
                               'feature_cache_hits': fit.features.hits, 'feature_cache_misses': fit.features.calls})
    sentinel = []
    for method in METHODS:
        fixture = research_fixture(SENTINEL_NAME, seed='24'); fit, audit = fixture.experiment(); strategy = StrategySpec(method)
        result = run_strategy(fit, strategy); row, audited = _summary_run(fixture, strategy, fit, audit, result); sentinel.append(row)
        full.append({'catalogue': fixture.catalogue_record(), 'strategy': strategy.to_dict(),
                     'result': result.to_dict(), 'selected_audit': audited})
    report = {'kind':'ZG024bStrategyResearchEvidence','version':'1.0.0','base_commit':BASE_COMMIT,
        'scope':'search-strategy research only; no production optimizer selection',
        'design':{'methods':list(METHODS),'core_fixtures':list(CORE_NAMES),'search_seeds':list(SEARCH_SEEDS),
                  'sentinel':SENTINEL_NAME,
                  'fairness':'same fixture/search seed/logical budget per paired method; each method starts with cold evaluator caches',
                  'selection':'fit-only eligibility and aggregate score; holdout/truth diagnostics computed only after fit selection',
                  'portable_tolerances':{'absolute':ATOL,'relative':RTOL}},
        'research_implementation':research_implementation(),'core_runs':core,
        'strategy_aggregates':_aggregate(core),'holdout_sentinel_runs':sentinel}
    report['evidence_sha256'] = digest(report)
    telemetry = {'kind':'ZG024bStrategyTelemetry','version':'1.0.0','evidence_sha256':report['evidence_sha256'],
                 'runs':timing,'total_seconds':time.perf_counter()-started,
                 'note':'wall-clock telemetry is host-specific and excluded from evidence identity'}
    return report, full, telemetry


def calibration_reference(report):
    fixtures = []
    for name in CORE_NAMES:
        for method in METHODS:
            rows = sorted((x for x in report['core_runs'] if x['fixture']==name and x['method_id']==method),
                          key=lambda x: SEARCH_SEEDS.index(x['seed']))
            fixtures.append({'fixture':name,'method_id':method,
                'best_fit_by_seed':[x['best_fit_score'] for x in rows],
                'best_holdout_by_seed':[x['best_holdout_score'] for x in rows],
                'eligible_by_seed':[x['eligible_candidates'] for x in rows],
                'pareto_by_seed':[x['pareto_candidates'] for x in rows],
                'parameter_error_by_seed':[x['parameter_error'] for x in rows],
                'manifold_error_by_seed':[x['nonidentifiable_manifold_error'] for x in rows]})
    sentinel = [{'method_id':x['method_id'],'best_fit_score':x['best_fit_score'],
                 'best_holdout_score':x['best_holdout_score'],'overfit_warning':x['overfit_warning'],
                 'pareto_candidates':x['pareto_candidates'],'best_parameters':x['best_parameters']}
                for x in report['holdout_sentinel_runs']]
    return {'kind':'ZG024bStrategyCalibration','version':'1.0.0','base_commit':report['base_commit'],
            'design':report['design'],'strategy_aggregates':report['strategy_aggregates'],
            'fixture_results':fixtures,'holdout_sentinel':sentinel,
            'note':'portable frozen outcomes; full per-component candidate/lineage evidence remains in CI artifacts'}


def compare_reports(actual, expected):
    failures = []
    def walk(a,e,path):
        if isinstance(e,bool) or e is None or isinstance(e,str):
            if type(a) is not type(e) or a != e: failures.append(path+': discrete value changed')
        elif isinstance(e,(int,float)):
            if type(a) not in (int,float) or not math.isfinite(a) or not math.isclose(a,e,abs_tol=ATOL,rel_tol=RTOL):
                failures.append(path+f': numeric mismatch {a!r} vs {e!r}')
        elif isinstance(e,dict):
            if type(a) is not dict or a.keys()!=e.keys(): failures.append(path+': fields changed'); return
            for key in e: walk(a[key],e[key],path+'/'+key)
        elif isinstance(e,list):
            if type(a) is not list or len(a)!=len(e): failures.append(path+': length changed'); return
            for i,(av,ev) in enumerate(zip(a,e)): walk(av,ev,path+f'/{i}')
        else: failures.append(path+': unsupported evidence type')
    walk(calibration_reference(actual), expected, '')
    return failures


def write_json(path,value,*,compact=False):
    text=json.dumps(value,sort_keys=True,allow_nan=False,separators=(',',':') if compact else None,
                    indent=None if compact else 2)+'\n'; payload=text.encode()
    if str(path).endswith('.gz'): payload=gzip.compress(payload,mtime=0)
    atomic_publish_bytes(path,payload)


def read_json(path):
    opener=gzip.open if str(path).endswith('.gz') else open
    with opener(path,'rb') as stream: payload=stream.read(2*1024*1024+1)
    if len(payload)>2*1024*1024: raise ValueError('ZG-024b reference exceeds 2 MiB')
    return json.loads(payload.decode())


def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--out',type=Path,required=True)
    p.add_argument('--full-out',type=Path); p.add_argument('--telemetry-out',type=Path)
    p.add_argument('--reference-out',type=Path); p.add_argument('--check',type=Path); args=p.parse_args()
    report,full,telemetry=build_report(); write_json(args.out,report,compact=True)
    if args.full_out: write_json(args.full_out,full,compact=True)
    if args.telemetry_out: write_json(args.telemetry_out,telemetry)
    if args.reference_out: write_json(args.reference_out,calibration_reference(report),compact=True)
    failures=compare_reports(report,read_json(args.check)) if args.check else []
    print(json.dumps({'evidence_sha256':report['evidence_sha256'],'core_runs':len(report['core_runs']),
                      'sentinel_runs':len(report['holdout_sentinel_runs']),'seconds':telemetry['total_seconds'],
                      'comparison_failures':failures},indent=2))
    if failures: raise SystemExit('ZG-024b evidence comparison failed')

if __name__=='__main__': main()
