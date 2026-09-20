"""Run the preregistered ZG-024e development-side diagnostic programme.

Confirmation material is intentionally absent from this module. The development
selection record is constructed (and, via CLI, atomically published) before any
post-selection holdout audit is performed.
"""
from __future__ import annotations

import argparse
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
from research.zg024e import (
    BALANCED_36_METHOD,
    CONTROL_METHOD,
    DEVELOPMENT_NAMES,
    DESIGN_MANIFEST,
    METHODS,
    SEARCH_SEEDS,
    SENTINEL_NAMES,
    DiagnosticSpec,
    design_sha256,
    development_fixture,
    normalized_parameter_error,
    run_diagnostic,
    sentinel_renderer,
)
from research.zg024e.diagnostic import research_implementation

BASELINES = (
    "zg024b.uniform-splitmix.v1",
    "zg024b.halton-shifted.v1",
    "zg024b.coordinate-refine.v1",
)
DIAGNOSTIC_36 = tuple(method for method in METHODS if method != CONTROL_METHOD)
ATOL, RTOL = 1e-7, 1e-5
DESIGN_FREEZE_COMMIT = "a7156aa6cb148582a943b8c0f211e5f603b1670b"
MECHANISMS = {
    "more-total-budget": (BALANCED_36_METHOD, CONTROL_METHOD),
    "a-budget-reallocation": ("zg024e.factorized-36-a-heavy.v1", BALANCED_36_METHOD),
    "b-budget-reallocation": ("zg024e.factorized-36-b-heavy.v1", BALANCED_36_METHOD),
    "eligible-parent-breadth": ("zg024e.factorized-36-wide-parents.v1", BALANCED_36_METHOD),
    "cross-family-coupling": ("zg024e.coupled-ab-36.v1", BALANCED_36_METHOD),
}
METHOD_TO_MECHANISM = {intervention: name for name, (intervention, _) in MECHANISMS.items()}


def _close(a, b):
    return a is not None and b is not None and math.isclose(a, b, abs_tol=ATOL, rel_tol=RTOL)


def _median(values):
    finite = [value for value in values if value is not None and math.isfinite(value)]
    return statistics.median(finite) if finite else None


def _best(result, diagnostic):
    ids = result.final_retained_candidate_ids if diagnostic else result.ranked_candidate_ids
    if not ids:
        return None
    by_id = {candidate.id: candidate for candidate in result.candidates}
    choices = [by_id[value] for value in ids if value in by_id]
    choices = [candidate for candidate in choices if candidate.eligible]
    if not choices:
        return None
    return min(
        choices,
        key=lambda candidate: (
            candidate.score if candidate.score is not None else math.inf,
            tuple(value for _, value in candidate.to_dict()["parameters"]["values"]),
            candidate.id,
        ),
    )


def _rejection_counts(result):
    counts = {}
    for candidate in result.candidates:
        for window in candidate.to_dict()["fit"]["windows"]:
            for reason in window["validation"]["rejected_reasons"]:
                counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items()))


def _promotion_violations(result):
    if not hasattr(result, "promotions"):
        return 0
    eligible = {candidate.id for candidate in result.candidates if candidate.eligible}
    return sum(
        candidate_id not in eligible
        for record in result.promotions
        for candidate_id in record["retained_candidate_ids"]
    )


def _promotion_summary(result):
    if not hasattr(result, "promotions"):
        return None
    return [
        {
            "stage": record["stage"],
            "eligible_count": len(record["eligible_candidate_ids"]),
            "pareto_count": len(record["pareto_candidate_ids"]),
            "retained_count": len(record["retained_candidate_ids"]),
            "retained_cap": record.get("retained_cap"),
            "equivalence_group_sizes": sorted(
                len(group) for group in record["exact_output_equivalence_groups"]
            ),
        }
        for record in result.promotions
    ]


def _run_fit(fixture, method, *, diagnostic):
    fit, audit = fixture.experiment()
    started = time.perf_counter()
    if diagnostic:
        result = run_diagnostic(fit, DiagnosticSpec(method))
    else:
        result = run_strategy(fit, StrategySpec(method))
    elapsed = time.perf_counter() - started
    best = _best(result, diagnostic)
    row = {
        "fixture": fixture.name,
        "seed": fixture.seed,
        "family": "diagnostic" if diagnostic else "baseline",
        "method_id": method,
        "method_key": f"{method}@{fixture.budget.max_evaluations}",
        "declared_budget": fixture.budget.max_evaluations,
        "consumed_evaluations": len(result.candidates),
        "eligible_candidates": sum(candidate.eligible for candidate in result.candidates),
        "final_available": best is not None,
        "best_fit_score": None if best is None else best.score,
        "best_holdout_score": None,
        "parameter_error": None if best is None else normalized_parameter_error(fixture, best),
        "best_candidate_id": None if best is None else best.id,
        "best_parameters": None if best is None else dict(best.to_dict()["parameters"]["values"]),
        "stage_consumption": dict(result.stage_consumption) if diagnostic else None,
        "promotion_stages": _promotion_summary(result),
        "final_retained_count": len(result.final_retained_candidate_ids) if diagnostic else None,
        "pareto_count": len(result.pareto_candidate_ids),
        "promotion_ineligible_violations": _promotion_violations(result),
        "gate_rejections": _rejection_counts(result),
        "stop_reason": result.stop_reason if diagnostic else None,
        "physical_render_calls": fit.render_calls,
        "render_cache_hits": fit.render_hits,
        "search_seconds": elapsed,
        "result_sha256": result.sha256,
        "environment_sha256": fit.environment_sha256,
    }
    detail = {
        "catalogue": fixture.catalogue_record(),
        "row": row,
        "result": result.to_dict(),
        "selected_audit": None,
    }
    return row, detail, result, best, audit


def _rows_for(rows, method):
    return [
        row for row in rows
        if row["family"] == "diagnostic" and row["method_id"] == method
    ]


def _fit_regression_count(intervention_rows, null_rows):
    null = {(row["fixture"], row["seed"]): row for row in null_rows}
    count = 0
    finite_pairs = 0
    for row in intervention_rows:
        other = null[(row["fixture"], row["seed"])]
        left, right = row["best_fit_score"], other["best_fit_score"]
        if left is None or right is None or not math.isfinite(left) or not math.isfinite(right):
            continue
        finite_pairs += 1
        if _close(left, right):
            continue
        if right == 0.0:
            if left > 0.0:
                count += 1
        elif left / right > 1.10:
            count += 1
    return count, finite_pairs


def _mechanism_record(rows, name, intervention, null):
    irows = _rows_for(rows, intervention)
    nrows = _rows_for(rows, null)
    if len(irows) != 15 or len(nrows) != 15:
        raise ValueError("incomplete ZG-024e development matrix for mechanism " + name)
    i_available = sum(row["final_available"] for row in irows)
    n_available = sum(row["final_available"] for row in nrows)
    fit_regressions, finite_pairs = _fit_regression_count(irows, nrows)
    violations = sum(row["promotion_ineligible_violations"] for row in irows)
    gain = i_available - n_available
    return {
        "mechanism": name,
        "intervention_method": intervention,
        "matched_null_method": null,
        "intervention_eligible_cases": i_available,
        "matched_null_eligible_cases": n_available,
        "eligible_case_gain": gain,
        "fit_pairs_both_finite": finite_pairs,
        "additional_fit_regressions_over_10_percent": fit_regressions,
        "promotion_ineligible_violations": violations,
        "development_supported": (
            gain >= 3 and violations == 0 and fit_regressions <= 3
        ),
        "policy": (
            "supported iff eligible-final gain >=3/15, zero ineligible promotions, "
            "and <=3 >10% fit regressions where both methods have finite eligible fits"
        ),
    }


def _freeze_selection(rows):
    summaries = {}
    for method in DIAGNOSTIC_36:
        method_rows = _rows_for(rows, method)
        if len(method_rows) != 15:
            raise ValueError("incomplete 36-evaluation diagnostic matrix: " + method)
        summaries[method] = {
            "eligible_final_cases": sum(row["final_available"] for row in method_rows),
            "starvation_stop_cases": sum(row["stop_reason"] is not None for row in method_rows),
            "median_eligible_best_fit": _median([row["best_fit_score"] for row in method_rows]),
            "promotion_ineligible_violations": sum(
                row["promotion_ineligible_violations"] for row in method_rows
            ),
        }

    def select_key(method):
        summary = summaries[method]
        median = summary["median_eligible_best_fit"]
        return (
            -summary["eligible_final_cases"],
            summary["starvation_stop_cases"],
            math.inf if median is None else median,
            method,
        )

    selected = min(DIAGNOSTIC_36, key=select_key)
    mechanisms = {
        name: _mechanism_record(rows, name, intervention, null)
        for name, (intervention, null) in MECHANISMS.items()
    }
    primary_mechanism = METHOD_TO_MECHANISM[selected]
    primary = mechanisms[primary_mechanism]
    diagnosis = (
        primary_mechanism
        if primary["development_supported"]
        else "no-single-tested-mechanism-supported"
    )
    record = {
        "kind": "ZG024eDevelopmentSelection",
        "version": "1.0.0",
        "child_issue": 227,
        "parent_issue": 25,
        "design_freeze_commit": DESIGN_FREEZE_COMMIT,
        "design_sha256": design_sha256(),
        "development_fixtures": list(DEVELOPMENT_NAMES),
        "search_seeds": list(SEARCH_SEEDS),
        "selected_intervention_method": selected,
        "selected_matched_null_method": primary["matched_null_method"],
        "primary_mechanism": primary_mechanism,
        "primary_diagnosis": diagnosis,
        "method_summaries": summaries,
        "mechanisms": mechanisms,
        "selection_policy": (
            "development fit/eligibility only: maximize eligible-final cases; then minimize "
            "starvation stops; then minimize median finite eligible fit; then method id"
        ),
        "disclosure_boundary": (
            "constructed before any post-selection development holdout audit and before "
            "the ZG-024e confirmation module exists"
        ),
    }
    record["selection_sha256"] = digest(record)
    return record


def _audit_pending(pending):
    for row, detail, result, best, audit in pending:
        if best is None:
            continue
        audited = audit.evaluate(best, result.audit_selection())
        row["best_holdout_score"] = audited["holdout"]["objectives"]["score"]
        detail["selected_audit"] = audited


def _sentinels(selected_method):
    spec = DiagnosticSpec(selected_method)
    rows, details = [], []
    expected = {
        "sentinel2-transient": {"transient_loss", "silence_collapse"},
        "sentinel2-silence": {"silence_collapse", "energy_collapse", "transient_loss"},
        "sentinel2-clipping": {"pathological_clipping", "destructive_output_clipping"},
    }
    for name in SENTINEL_NAMES:
        fixture = development_fixture(
            name, seed=SEARCH_SEEDS[0], budget_evaluations=spec.budget
        )
        renderer, renderer_id = sentinel_renderer(name)
        fit, _ = fixture.experiment(renderer=renderer, renderer_id=renderer_id)
        started = time.perf_counter()
        result = run_diagnostic(fit, spec)
        elapsed = time.perf_counter() - started
        row = {
            "fixture": name,
            "seed": fixture.seed,
            "family": "sentinel",
            "method_id": selected_method,
            "method_key": f"{selected_method}@{spec.budget}",
            "declared_budget": spec.budget,
            "consumed_evaluations": len(result.candidates),
            "eligible_candidates": sum(candidate.eligible for candidate in result.candidates),
            "final_available": bool(result.final_retained_candidate_ids),
            "best_fit_score": None,
            "best_holdout_score": None,
            "parameter_error": None,
            "best_candidate_id": None,
            "best_parameters": None,
            "stage_consumption": dict(result.stage_consumption),
            "promotion_stages": _promotion_summary(result),
            "final_retained_count": len(result.final_retained_candidate_ids),
            "pareto_count": len(result.pareto_candidate_ids),
            "promotion_ineligible_violations": _promotion_violations(result),
            "gate_rejections": _rejection_counts(result),
            "stop_reason": result.stop_reason,
            "physical_render_calls": fit.render_calls,
            "render_cache_hits": fit.render_hits,
            "search_seconds": elapsed,
            "result_sha256": result.sha256,
            "environment_sha256": fit.environment_sha256,
            "expected_gate_any": sorted(expected[name]),
        }
        details.append({
            "catalogue": fixture.catalogue_record(),
            "row": row,
            "result": result.to_dict(),
            "selected_audit": None,
        })
        rows.append(row)
    return rows, details


def _budget_accounting_ok(row):
    declared = row["declared_budget"]
    consumed = row["consumed_evaluations"]
    if type(declared) is not int or type(consumed) is not int:
        return False
    if row["family"] == "baseline":
        return (
            row["method_id"] in BASELINES
            and declared in (24, 36)
            and consumed == declared
            and row["stage_consumption"] is None
            and row["stop_reason"] is None
        )
    if row["family"] not in ("diagnostic", "sentinel") or row["method_id"] not in METHODS:
        return False

    spec = DiagnosticSpec(row["method_id"])
    if declared != spec.budget:
        return False
    allocation = spec.allocation
    stage = row["stage_consumption"]
    if not isinstance(stage, dict) or set(stage) != set(allocation):
        return False
    if any(type(value) is not int or value < 0 for value in stage.values()):
        return False
    if sum(stage.values()) != consumed:
        return False

    stop = row["stop_reason"]
    if spec.mode == "factorized":
        if stop is None or stop == "stage-C-no-eligible-final-alternative":
            expected = allocation
        elif stop == "stage-A-no-eligible-parent":
            expected = {"A": allocation["A"], "B": 0, "C": 0}
        elif stop == "stage-B-no-eligible-parent":
            expected = {"A": allocation["A"], "B": allocation["B"], "C": 0}
        else:
            return False
    else:
        if stop is None or stop == "stage-C-no-eligible-final-alternative":
            expected = allocation
        elif stop == "stage-AB-no-eligible-parent":
            expected = {"AB": allocation["AB"], "C": 0}
        else:
            return False

    if stage != expected or consumed != sum(expected.values()):
        return False
    if stop is None:
        return row["final_retained_count"] is not None and row["final_retained_count"] > 0
    return row["final_retained_count"] == 0


def _portable_row(row):
    return {
        key: row[key]
        for key in (
            "fixture", "seed", "family", "method_id", "method_key",
            "declared_budget", "consumed_evaluations", "eligible_candidates",
            "final_available", "best_fit_score", "best_holdout_score",
            "parameter_error", "stage_consumption", "promotion_stages",
            "final_retained_count", "pareto_count",
            "promotion_ineligible_violations", "gate_rejections",
            "stop_reason", "physical_render_calls", "render_cache_hits",
        )
    }


def build_development_report(*, on_selection=None):
    started = time.perf_counter()
    rows, full, pending = [], [], []

    for name in DEVELOPMENT_NAMES:
        for seed in SEARCH_SEEDS:
            for method in METHODS:
                spec = DiagnosticSpec(method)
                fixture = development_fixture(
                    name, seed=seed, budget_evaluations=spec.budget
                )
                row, detail, result, best, audit = _run_fit(
                    fixture, method, diagnostic=True
                )
                rows.append(row)
                full.append(detail)
                pending.append((row, detail, result, best, audit))

            for budget in (24, 36):
                for method in BASELINES:
                    fixture = development_fixture(
                        name, seed=seed, budget_evaluations=budget
                    )
                    row, detail, result, best, audit = _run_fit(
                        fixture, method, diagnostic=False
                    )
                    rows.append(row)
                    full.append(detail)
                    pending.append((row, detail, result, best, audit))

    # This is the preregistered disclosure boundary. Nothing below this point may
    # alter the selected intervention or primary diagnosis.
    selection = _freeze_selection(rows)
    if on_selection is not None:
        on_selection(selection)

    # Development holdouts are diagnostic only and are deliberately evaluated after
    # the immutable selection object above has been constructed/published.
    _audit_pending(pending)

    sentinel_rows, sentinel_details = _sentinels(
        selection["selected_intervention_method"]
    )
    full.extend(sentinel_details)

    budget_integrity = all(_budget_accounting_ok(row) for row in rows)
    promotion_integrity = all(
        row["promotion_ineligible_violations"] == 0 for row in rows + sentinel_rows
    )
    sentinel_integrity = True
    for row in sentinel_rows:
        expected = set(row["expected_gate_any"])
        observed = set(row["gate_rejections"])
        sentinel_integrity = sentinel_integrity and (
            not row["final_available"]
            and row["promotion_ineligible_violations"] == 0
            and bool(expected & observed)
        )

    integrity = {
        "exact_budget_integrity": budget_integrity,
        "promotion_integrity": promotion_integrity,
        "sentinel_integrity": sentinel_integrity,
    }
    portable = {
        "kind": "ZG024eDevelopmentPortableEvidence",
        "version": "1.0.0",
        "design_sha256": design_sha256(),
        "selection": selection,
        "development": [_portable_row(row) for row in rows],
        "sentinels": [_portable_row(row) for row in sentinel_rows],
        "integrity": integrity,
    }
    report = {
        "kind": "ZG024eDevelopmentEvidence",
        "version": "1.0.0",
        "scope": (
            "preregistered development diagnosis; selection frozen before holdout audit; "
            "confirmation material absent"
        ),
        "design_manifest": DESIGN_MANIFEST,
        "design_sha256": design_sha256(),
        "design_freeze_commit": DESIGN_FREEZE_COMMIT,
        "research_implementation": research_implementation(),
        "baseline_methods": list(BASELINES),
        "diagnostic_methods": list(METHODS),
        "selection": selection,
        "development_rows": rows,
        "sentinel_rows": sentinel_rows,
        "integrity": integrity,
        "portable": portable,
    }
    report["portable_sha256"] = digest(portable)
    report["evidence_sha256"] = digest(report)
    telemetry = {
        "kind": "ZG024eDevelopmentTelemetry",
        "version": "1.0.0",
        "evidence_sha256": report["evidence_sha256"],
        "total_seconds": time.perf_counter() - started,
        "note": "host wall-clock is excluded from portable evidence identity",
    }
    return report, full, telemetry


def write(path, value):
    atomic_publish_bytes(
        path,
        (json.dumps(value, sort_keys=True, allow_nan=False, separators=(",", ":")) + "\n").encode(),
    )


def _portable_compare(actual, expected, path="root"):
    if type(actual) is not type(expected):
        raise ValueError(f"{path}: type mismatch")
    if isinstance(actual, dict):
        if set(actual) != set(expected):
            raise ValueError(f"{path}: key mismatch")
        for key in sorted(actual):
            _portable_compare(actual[key], expected[key], path + "." + key)
    elif isinstance(actual, list):
        if len(actual) != len(expected):
            raise ValueError(f"{path}: list length mismatch")
        for index, (left, right) in enumerate(zip(actual, expected)):
            _portable_compare(left, right, f"{path}[{index}]")
    elif isinstance(actual, float):
        if not math.isclose(actual, expected, abs_tol=ATOL, rel_tol=RTOL):
            raise ValueError(f"{path}: {actual!r} != {expected!r}")
    elif actual != expected:
        raise ValueError(f"{path}: {actual!r} != {expected!r}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--full-out", required=True)
    parser.add_argument("--portable-out", required=True)
    parser.add_argument("--selection-out", required=True)
    parser.add_argument("--telemetry-out", required=True)
    parser.add_argument("--compare-portable")
    parser.add_argument("--require-integrity", action="store_true")
    args = parser.parse_args()

    def publish_selection(selection):
        write(args.selection_out, selection)

    report, full, telemetry = build_development_report(
        on_selection=publish_selection
    )
    write(args.out, report)
    write(args.full_out, full)
    write(args.portable_out, report["portable"])
    write(args.telemetry_out, telemetry)

    if args.compare_portable:
        expected = json.loads(Path(args.compare_portable).read_text(encoding="utf-8"))
        _portable_compare(report["portable"], expected)

    summary = {
        "evidence_sha256": report["evidence_sha256"],
        "portable_sha256": report["portable_sha256"],
        "selection": report["selection"],
        "integrity": report["integrity"],
        "seconds": telemetry["total_seconds"],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))

    if args.require_integrity and not all(report["integrity"].values()):
        raise SystemExit(
            "ZG-024e development integrity failed; retain evidence and do not disclose confirmation"
        )


if __name__ == "__main__":
    main()
