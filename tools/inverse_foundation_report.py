"""Reproduce ZG-024a evidence; portable numeric comparison never asserts byte equality."""
from __future__ import annotations
import argparse
from contextlib import nullcontext
import json
import gzip
import math
import re
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from zaaggenz_contracts import digest
from zaaggenz_jobs import atomic_publish_bytes
from zaaggenz_jobs.model import numeric_thread_limit
from zaaggenz_inverse import run_grid
from zaaggenz_inverse.fixtures import NAMES, synthetic_fixture
from zaaggenz_inverse.legacy import provenance, run_recovered_benchmark
from zaaggenz_inverse.recipes import environment_manifest, implementation_manifest
from tools.inverse_validation_transition import apply_validation_transition, validate_validation_transitions

BASE_COMMIT = '6e0153d824608d6a9899c5ea8e8c0b9a29688c98'
# Frozen before cross-platform CI. These are engineering tolerances, not permission
# to substitute hashes or claim resumability across numerical environments.
ATOL, RTOL = 1e-7, 1e-5
SHA256_RE = re.compile(r'^[0-9a-f]{64}$')

def summarize_evaluation(evaluation):
    windows = []
    for record in evaluation['windows']:
        m, v = record['measurements'], record['validation']
        i = m['intermediate']
        windows.append({'window': record['window'],
            'components': {c['name']: c['value'] for c in m['components']},
            'levels': {key: i.get(key) for key in ('raw_rmse', 'reference_rms', 'candidate_rms', 'signed_level_delta_db')},
            'feature_pair_sha256': m['feature_pair_sha256'],
            'validation': {'state': v['state'], 'triggered_gates': [f['gate'] for f in v['findings'] if f['triggered']],
                           'allowed_gates': [f['gate'] for f in v['findings'] if f['triggered'] and f['allowed']]}})
    return {'objectives': evaluation['objectives'], 'windows': windows}


def build_report(*, include_legacy=True):
    """Return compact evidence, full replay/audit records, and non-identity telemetry."""
    start = time.perf_counter()
    fixtures, full, timing = [], [], []
    for name in NAMES:
        t = time.perf_counter()
        fixture = synthetic_fixture(name)
        fit, auditor = fixture.experiment()
        result = run_grid(fit)
        search_seconds = time.perf_counter()-t
        selection = result.audit_selection(all_candidates=True)
        audits = [auditor.evaluate(c, selection) for c in result.candidates]
        id_to_ordinal = {c.id: c.to_dict()['ordinal'] for c in result.candidates}
        candidates = []
        for c, audit in zip(result.candidates, audits):
            d = c.to_dict()
            candidates.append({'candidate_id': c.id, 'evaluation_sha256': c.sha256, 'ordinal': d['ordinal'],
                'parameters': dict(d['parameters']['values']), 'recipe_sha256': c.recipe.sha256,
                'render_sha256': d['provenance']['render_sha256'], 'feature_sha256': d['provenance']['feature_sha256'],
                'render_cache_key': d['provenance']['render_cache_key'],
                'render_signal_assets': {k: v['asset'] for k, v in d['render']['signals'].items()},
                'master_gain_linear': d['render']['master_gain_linear'], 'output_policy': d['render']['output_policy'],
                'source_internal_gain_factors': None,
                'source_internal_normalisation': d['render']['source_internal_normalisation'],
                'eligible': c.eligible, 'reproducibility': d['reproducibility'],
                'validation_state': d['validation_state'], 'structural_rejections': d['structural_rejections'],
                'fit': summarize_evaluation(d['fit']), 'holdout': summarize_evaluation(audit['holdout']),
                'whole_signal': summarize_evaluation(audit['whole_signal']),
                'audit_reproducibility': audit['reproducibility'], 'generalisation_gap': audit['generalisation_gap'],
                'overfit_warning': audit['overfit_warning']})
        fixtures.append({'catalogue': fixture.catalogue_record(), 'source_revision_id': fit.request.source_revision_id,
            'search_id': result.search_id, 'search_result_sha256': result.sha256,
            'selection_sha256': selection.sha256, 'checkpoint': result.checkpoint.to_dict(),
            'budget': result.to_dict()['budget'],
            'ranked_ordinals': [id_to_ordinal[i] for i in result.ranked_candidate_ids],
            'pareto_ordinals': [id_to_ordinal[i] for i in result.pareto_candidate_ids], 'candidates': candidates})
        full.append({'fixture': fixture.catalogue_record(), 'request': fit.request.to_dict(),
                     'search': result.to_dict(), 'audits': audits})
        timing.append({'fixture': name, 'search_and_generation_seconds': search_seconds,
            'audit_seconds': time.perf_counter()-t-search_seconds, 'physical_search_renders': fit.render_calls,
            'verified_render_cache_hits': fit.render_hits, 'audit_renders': len(audits),
            'feature_cache': {'hits': fit.features.hits, 'misses': fit.features.calls}})
    legacy_start = time.perf_counter()
    legacy = {'provenance': provenance(), 'benchmark': run_recovered_benchmark() if include_legacy else None}
    report = {'kind': 'InverseFoundationEvidence', 'version': '1.0.0', 'base_commit': BASE_COMMIT,
        'scope': 'ZG-024a first serial pass; engineering laboratory, not final optimizer or original-chain recovery',
        'environment': environment_manifest(), 'implementation': implementation_manifest(),
        'portable_metric_policy': {'absolute_tolerance': ATOL, 'relative_tolerance': RTOL,
            'identity_policy': 'exact within declared environment; cross-platform comparisons use recipe definitions and numeric metrics, not PCM/measurement hash substitution'},
        'legacy': legacy, 'fixtures': fixtures}
    report['evidence_sha256'] = digest(report)
    telemetry = {'kind': 'InverseFoundationTelemetry', 'version': '1.0.0', 'evidence_sha256': report['evidence_sha256'],
        'environment': report['environment'], 'fixtures': timing,
        'legacy_seconds': time.perf_counter()-legacy_start, 'total_seconds': time.perf_counter()-start,
        'note': 'Observed local wall time, not portable performance guarantees; excluded from evidence identity.'}
    return report, full, telemetry


def calibration_reference(report):
    """Compact checked-in evidence; full editable recipes/measurements remain in CI archives."""
    from zaaggenz_inverse.contracts import LOSS_UNITS
    names = tuple(sorted(LOSS_UNITS))
    legacy = report['legacy']['benchmark']
    out = {'kind': 'InverseFoundationCalibration', 'version': '1.0.0', 'base_commit': report['base_commit'],
        'source_report_sha256': report['evidence_sha256'], 'environment': report['environment'],
        'implementation_sha256': digest(report['implementation']), 'portable_metric_policy': report['portable_metric_policy'],
        'loss_component_order': list(names), 'loss_units': LOSS_UNITS,
        'legacy_provenance': report['legacy']['provenance'],
        'legacy_benchmark': None if legacy is None else {k: legacy[k] for k in ('profile','maxiter','popsize','seed',
            'initial_score','initial_components','best_score','best_components','evaluations','cancelled','bounds')}, 'fixtures': []}
    for fixture in report['fixtures']:
        cat = fixture['catalogue']; definition = cat['definition']
        row = {k: cat[k] for k in ('fixture_id','definition_sha256','target_asset')}
        row.update({k: definition[k] for k in ('name','generation','ground_truth_parameters','domain','windows','objective','seed')})
        row.update({k: fixture[k] for k in ('search_id','search_result_sha256','budget','ranked_ordinals','pareto_ordinals')})
        row.update(base_recipe_sha256=digest(definition['base_recipe']), ground_truth_recipe_sha256=digest(definition['ground_truth_recipe']))
        row['candidates'] = []
        for candidate in fixture['candidates']:
            c = {k: candidate[k] for k in ('ordinal','parameters','candidate_id','evaluation_sha256','recipe_sha256',
                 'eligible','reproducibility','validation_state','audit_reproducibility','generalisation_gap','overfit_warning')}
            for split in ('fit','holdout','whole_signal'):
                e = candidate[split]
                c[split] = {'losses': [e['objectives']['components'][n] for n in names], 'score': e['objectives']['score'],
                    'validation': [w['validation'] for w in e['windows']]}
            row['candidates'].append(c)
        out['fixtures'].append(row)
    out['evidence_sha256'] = digest(out)
    return out


def portable_projection(reference):
    """Explicit allowlist; exact identities remain recorded, never replaced by tolerant hashes."""
    out = {k: reference[k] for k in ('kind','version','base_commit','implementation_sha256','portable_metric_policy',
        'loss_component_order','loss_units','legacy_provenance','legacy_benchmark')}
    out['fixtures'] = []
    for fixture in reference['fixtures']:
        f = {k: fixture[k] for k in ('name','definition_sha256','generation','ground_truth_parameters','domain','windows',
            'objective','seed','base_recipe_sha256','ground_truth_recipe_sha256','budget','ranked_ordinals','pareto_ordinals')}
        f['candidates'] = [{k:c[k] for k in ('ordinal','parameters','recipe_sha256','eligible','reproducibility','validation_state',
            'audit_reproducibility','generalisation_gap','overfit_warning','fit','holdout','whole_signal')}
            for c in fixture['candidates']]
        out['fixtures'].append(f)
    return out


def validate_implementation_transitions(document):
    """Return reviewed exact identity transitions; reject wildcards/ambiguous records."""
    if document is None:return []
    if type(document) is not dict or document.get('kind')!='InverseFoundationImplementationTransitions' or document.get('version')!='1.0.0':
        raise ValueError('invalid inverse implementation-transition document')
    rows=document.get('transitions')
    if type(rows) is not list:raise ValueError('implementation transitions must be a list')
    seen=set();out=[]
    for i,row in enumerate(rows):
        if type(row) is not dict:raise ValueError(f'implementation transition {i} must be an object')
        old=row.get('from_implementation_sha256');new=row.get('to_implementation_sha256')
        if not isinstance(old,str) or not SHA256_RE.fullmatch(old) or not isinstance(new,str) or not SHA256_RE.fullmatch(new) or old==new:
            raise ValueError(f'implementation transition {i} requires distinct lowercase SHA-256 identities')
        if (old,new) in seen:raise ValueError(f'duplicate implementation transition {old}->{new}')
        seen.add((old,new))
        if type(row.get('issue')) is not int or row['issue']<=0:raise ValueError(f'implementation transition {i} requires issue number')
        if not isinstance(row.get('stable_id'),str) or not re.fullmatch(r'ZG-\d{3}',row['stable_id']):raise ValueError(f'implementation transition {i} requires stable_id')
        if not isinstance(row.get('reason'),str) or not row['reason'].strip():raise ValueError(f'implementation transition {i} requires reason')
        paths=row.get('changed_paths')
        if type(paths) is not list or not paths or any(not isinstance(p,str) or not p or '*' in p for p in paths):
            raise ValueError(f'implementation transition {i} requires explicit changed_paths without wildcards')
        out.append(row)
    return out


def compare_reports(actual, expected, *, implementation_transitions=(), validation_transitions=()):
    """Return path-specific differences; every reviewed transition is exact and fail-closed."""
    failures = []
    def walk(a, e, path):
        if isinstance(e, bool) or e is None or isinstance(e, str):
            if type(a) is not type(e) or a != e: failures.append(path + ': discrete value changed')
        elif isinstance(e, (int, float)):
            if type(a) not in (int, float) or not math.isfinite(a) or not math.isclose(a,e,abs_tol=ATOL,rel_tol=RTOL):
                failures.append(path + f': numeric mismatch {a!r} vs {e!r}')
        elif isinstance(e, dict):
            if type(a) is not dict or a.keys() != e.keys(): failures.append(path + ': fields changed'); return
            for key in e: walk(a[key],e[key],path+'/'+key)
        elif isinstance(e, list):
            if type(a) is not list or len(a) != len(e): failures.append(path + ': length changed'); return
            for i,(av,ev) in enumerate(zip(a,e)): walk(av,ev,path+f'/{i}')
        else: failures.append(path + ': unsupported evidence type')
    for label, report in (('actual',actual),('expected',expected)):
        payload = {k:v for k,v in report.items() if k != 'evidence_sha256'}
        if digest(payload) != report.get('evidence_sha256'): failures.append(label+': evidence identity mismatch')
    actual_projection=portable_projection(actual);expected_projection=portable_projection(expected)
    actual_impl=actual_projection['implementation_sha256'];expected_impl=expected_projection['implementation_sha256']
    implementation_transition=None
    if actual_impl!=expected_impl:
        implementation_transition=next((row for row in implementation_transitions
            if row['from_implementation_sha256']==expected_impl and row['to_implementation_sha256']==actual_impl),None)
        if implementation_transition is not None:
            # Preserve both exact identities in their evidence envelopes; align only
            # the comparison copy so every other undeclared field must reproduce.
            actual_projection=dict(actual_projection);actual_projection['implementation_sha256']=expected_impl
        else:
            failures.append(f'/implementation_sha256: unreviewed transition {expected_impl}->{actual_impl}')
            actual_projection=dict(actual_projection);actual_projection['implementation_sha256']=expected_impl
    actual_projection, transition_failures, _ = apply_validation_transition(
        actual_projection, expected_projection, expected_impl=expected_impl, actual_impl=actual_impl,
        transitions=validation_transitions, implementation_transition_reviewed=implementation_transition is not None)
    failures.extend(transition_failures)
    walk(actual_projection,expected_projection,'')
    return failures


def write_json(path, value, *, compact=False):
    text = json.dumps(value, sort_keys=True, allow_nan=False, separators=(',',':') if compact else None,
                      indent=None if compact else 2)+'\n'
    payload = text.encode('utf-8')
    if str(path).endswith('.gz'): payload = gzip.compress(payload, mtime=0)
    atomic_publish_bytes(path,payload)


def read_json(path):
    opener = gzip.open if str(path).endswith('.gz') else open
    with opener(path, 'rb') as stream:
        payload = stream.read(1024*1024+1)
    if len(payload) > 1024*1024: raise ValueError('calibration exceeds 1 MiB limit')
    return json.loads(payload.decode('utf-8'))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--full-out', type=Path)
    p.add_argument('--telemetry-out', type=Path)
    p.add_argument('--check', type=Path, help='compare against checked-in compact calibration')
    p.add_argument('--implementation-transitions', type=Path, help='reviewed exact implementation-identity transitions; never wildcarded or automatic')
    p.add_argument('--validation-transitions', type=Path, help='reviewed exact portable validation migrations tied to implementation identities')
    p.add_argument('--reference-out', type=Path, help='explicitly write a new compact calibration; never update automatically in CI')
    args = p.parse_args()
    controller = numeric_thread_limit(1)
    with controller if controller is not None else nullcontext():
        report, full, telemetry = build_report()
    write_json(args.out, report, compact=True)
    if args.full_out: write_json(args.full_out, full, compact=True)
    if args.telemetry_out: write_json(args.telemetry_out, telemetry)
    reference = calibration_reference(report)
    expected = read_json(args.check) if args.check else None
    transition_document=read_json(args.implementation_transitions) if args.implementation_transitions else None
    transitions=validate_implementation_transitions(transition_document)
    validation_document=read_json(args.validation_transitions) if args.validation_transitions else None
    validation_transitions=validate_validation_transitions(validation_document)
    failures = compare_reports(reference, expected, implementation_transitions=transitions,
                               validation_transitions=validation_transitions) if expected is not None else []
    expected_impl=None if expected is None else expected.get('implementation_sha256')
    implementation_transition_accepted=bool(expected is not None and reference['implementation_sha256']!=expected_impl and
        any(row['from_implementation_sha256']==expected_impl and row['to_implementation_sha256']==reference['implementation_sha256'] for row in transitions))
    validation_transition=next((row for row in validation_transitions if expected is not None and
        row['from_implementation_sha256']==expected_impl and row['to_implementation_sha256']==reference['implementation_sha256']),None)
    print(json.dumps({'evidence_sha256': report['evidence_sha256'], 'fixtures': len(report['fixtures']),
        'candidates': sum(len(f['candidates']) for f in report['fixtures']),
        'seconds': telemetry['total_seconds'],
        'implementation_sha256': reference['implementation_sha256'],
        'expected_implementation_sha256': expected_impl,
        'implementation_transition_accepted': implementation_transition_accepted,
        'reviewed_validation_changes': 0 if validation_transition is None else len(validation_transition['changes']),
        'comparison_failures': failures}, indent=2))
    if failures: raise SystemExit('ZG-024a evidence comparison failed')


if __name__ == '__main__': main()
