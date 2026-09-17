"""Run the preregistered ZG-024d staged-search development/confirmation programme."""
from __future__ import annotations

import argparse
import gzip
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
from research.zg024b.strategies import StrategySpec, run_strategy
from research.zg024d.fixtures import (
    DEV_NAMES, CONFIRM_NAMES, DEV_SEEDS, CONFIRM_SEEDS, SAFETY_NAMES,
    research_fixture, safety_fixture, normalized_parameter_error, manifold_error,
)
from research.zg024d.staged import METHOD_ID as STAGED_METHOD, run_staged, research_implementation

BASE_COMMIT = "7935accaa82f26479b1392725fe503b58611b4ab"
HALTON_METHOD = "zg024b.halton-shifted.v1"
COORD_METHOD = "zg024b.coordinate-refine.v1"
METHODS = (STAGED_METHOD, HALTON_METHOD, COORD_METHOD)
ATOL, RTOL = 1e-7, 1e-5
REQUIRED_PAIRED_RATE = 2.0 / 3.0
REQUIRED_ELIGIBLE_RATE = 0.90
MAX_HOLDOUT_MEDIAN_FACTOR = 1.10


def _candidate_by_id(result, candidate_id):
    return next(candidate for candidate in result.candidates if candidate.id == candidate_id)


def _run(fixture, plan, method):
    fit, audit = fixture.experiment()
    if method == STAGED_METHOD:
        result = run_staged(fit, plan)
    else:
        result = run_strategy(fit, StrategySpec(method))
    best = _candidate_by_id(result, result.ranked_candidate_ids[0]) if result.ranked_candidate_ids else None
    audited = audit.evaluate(best, result.audit_selection()) if best is not None else None
    row = {
        "fixture": fixture.name,
        "fixture_id": fixture.catalogue_record()["fixture_id"],
        "seed": fixture.seed,
        "method_id": method,
        "declared_budget": fixture.budget.max_evaluations,
        "consumed_evaluations": len(result.candidates),
        "eligible_candidates": sum(candidate.eligible for candidate in result.candidates),
        "pareto_candidates": len(result.pareto_candidate_ids),
        "best_candidate_id": None if best is None else best.id,
        "best_parameters": None if best is None else dict(best.to_dict()["parameters"]["values"]),
        "best_fit_score": None if best is None else best.score,
        "best_fit_components": None if best is None else best.to_dict()["fit"]["objectives"]["components"],
        "best_holdout_score": None if audited is None else audited["holdout"]["objectives"]["score"],
        "whole_signal_score": None if audited is None else audited["whole_signal"]["objectives"]["score"],
        "overfit_warning": None if audited is None else audited["overfit_warning"],
        "parameter_error": None if best is None else normalized_parameter_error(fixture, best),
        "manifold_error": None if best is None else manifold_error(fixture, best),
        "physical_render_calls": fit.render_calls,
        "verified_render_cache_hits": fit.render_hits,
        "feature_cache_hits": fit.features.hits,
        "feature_cache_misses": fit.features.calls,
    }
    return row, {
        "catalogue": fixture.catalogue_record(),
        "plan": plan.to_dict(),
        "method_id": method,
        "result": result.to_dict(),
        "selected_audit": audited,
    }


def _aggregate(rows):
    aggregate = {}
    for method in METHODS:
        selected = [row for row in rows if row["method_id"] == method]
        fits = [row["best_fit_score"] for row in selected if row["best_fit_score"] is not None]
        holds = [row["best_holdout_score"] for row in selected if row["best_holdout_score"] is not None]
        parameter = [row["parameter_error"] for row in selected if row["parameter_error"] is not None]
        manifold = [row["manifold_error"] for row in selected if row["manifold_error"] is not None]
        aggregate[method] = {
            "runs": len(selected),
            "eligible_winner_rate": sum(row["best_fit_score"] is not None for row in selected) / len(selected),
            "median_best_fit_score": statistics.median(fits) if fits else None,
            "median_best_holdout_score": statistics.median(holds) if holds else None,
            "median_identifiable_parameter_error": statistics.median(parameter) if parameter else None,
            "median_nonidentifiable_manifold_error": statistics.median(manifold) if manifold else None,
            "median_physical_render_calls": statistics.median(row["physical_render_calls"] for row in selected),
        }
    return aggregate


def _close(a, b):
    return math.isclose(a, b, abs_tol=ATOL, rel_tol=RTOL)


def _confirmation_decision(rows, safety):
    quality_names = tuple(name for name in CONFIRM_NAMES if name != "confirm-holdout")
    paired = {(STAGED_METHOD, HALTON_METHOD): [0, 0], (STAGED_METHOD, COORD_METHOD): [0, 0]}
    eligible = {method: 0 for method in METHODS}
    total = {method: 0 for method in METHODS}
    holdouts = {method: [] for method in METHODS}
    blockers = []

    for name in quality_names:
        for seed in CONFIRM_SEEDS:
            group = {row["method_id"]: row for row in rows if row["fixture"] == name and row["seed"] == seed}
            for method in METHODS:
                total[method] += 1
                if group[method]["best_fit_score"] is not None:
                    eligible[method] += 1
                if group[method]["best_holdout_score"] is not None:
                    holdouts[method].append(group[method]["best_holdout_score"])
            for key in paired:
                staged = group[key[0]]["best_fit_score"]
                comparator = group[key[1]]["best_fit_score"]
                if staged is not None and comparator is not None:
                    paired[key][1] += 1
                    if staged < comparator or _close(staged, comparator):
                        paired[key][0] += 1

    rates = {}
    for key, (wins, comparisons) in paired.items():
        rate = wins / comparisons if comparisons else 0.0
        rates[key[1]] = {"wins_or_ties": wins, "paired_runs": comparisons, "rate": rate}
        if rate + 1e-15 < REQUIRED_PAIRED_RATE:
            blockers.append(f"paired fit win/tie rate against {key[1]} is {rate:.3f}, below {REQUIRED_PAIRED_RATE:.3f}")

    eligibility_rates = {method: eligible[method] / total[method] for method in METHODS}
    staged_rate = eligibility_rates[STAGED_METHOD]
    if staged_rate + 1e-15 < REQUIRED_ELIGIBLE_RATE:
        blockers.append(f"staged eligible-winner rate {staged_rate:.3f} is below {REQUIRED_ELIGIBLE_RATE:.3f}")
    for method in (HALTON_METHOD, COORD_METHOD):
        if staged_rate + 1e-15 < eligibility_rates[method]:
            blockers.append(f"staged eligible-winner rate {staged_rate:.3f} is below comparator {method} rate {eligibility_rates[method]:.3f}")

    holdout_medians = {method: statistics.median(values) if values else None for method, values in holdouts.items()}
    comparator_holds = [holdout_medians[m] for m in (HALTON_METHOD, COORD_METHOD) if holdout_medians[m] is not None]
    if holdout_medians[STAGED_METHOD] is None or not comparator_holds:
        blockers.append("insufficient independently audited holdout results")
    else:
        limit = min(comparator_holds) * MAX_HOLDOUT_MEDIAN_FACTOR + ATOL
        if holdout_medians[STAGED_METHOD] > limit and not _close(holdout_medians[STAGED_METHOD], limit):
            blockers.append(
                f"staged median holdout {holdout_medians[STAGED_METHOD]:.9g} exceeds preregistered non-regression limit {limit:.9g}"
            )

    unsafe_eligible = [row["fixture"] for row in safety if row["unsafe_probe_eligible"]]
    if unsafe_eligible:
        blockers.append("unsafe anti-degeneracy probe remained eligible: " + ", ".join(unsafe_eligible))

    sentinel = [row for row in rows if row["fixture"] == "confirm-holdout"]
    sentinel_failures = [f"{row['method_id']}:{row['seed']}" for row in sentinel if row["overfit_warning"] is not True]
    if sentinel_failures:
        blockers.append("holdout sentinel failed to expose fit-equivalent overfit for " + ", ".join(sentinel_failures))

    return {
        "rule": {
            "paired_fit_win_or_tie_rate_minimum_against_each_comparator": REQUIRED_PAIRED_RATE,
            "eligible_winner_rate_minimum": REQUIRED_ELIGIBLE_RATE,
            "eligible_winner_rate_must_not_trail_comparator": True,
            "median_holdout_nonregression_factor_vs_best_comparator": MAX_HOLDOUT_MEDIAN_FACTOR,
            "all_unsafe_probes_must_be_ineligible": True,
            "all_confirmation_holdout_sentinels_must_warn": True,
            "truth_parameter_error": "reported only; never selection/ranking/stopping input",
        },
        "paired_fit": rates,
        "eligible_winner_rates": eligibility_rates,
        "median_holdout_scores": holdout_medians,
        "unsafe_eligible": unsafe_eligible,
        "holdout_sentinel_failures": sentinel_failures,
        "blockers": blockers,
        "outcome": "confirmation-supports-production-candidate" if not blockers else "mixed-confirmation-do-not-integrate",
    }


def build_report():
    started = time.perf_counter()
    rows, full, timing = [], [], []
    for role, names, seeds in (
        ("development", DEV_NAMES, DEV_SEEDS),
        ("sealed-confirmation", CONFIRM_NAMES, CONFIRM_SEEDS),
    ):
        for name in names:
            for seed in seeds:
                fixture, plan = research_fixture(name, seed=seed)
                for method in METHODS:
                    t0 = time.perf_counter()
                    row, evidence = _run(fixture, plan, method)
                    row["role"] = role
                    rows.append(row)
                    full.append(evidence)
                    timing.append({
                        "role": role, "fixture": name, "seed": seed, "method_id": method,
                        "seconds": time.perf_counter() - t0,
                        "physical_render_calls": row["physical_render_calls"],
                    })

    safety = []
    for name in SAFETY_NAMES:
        fixture, unsafe_state, purpose = safety_fixture(name)
        fit, _ = fixture.experiment()
        candidate = fit.evaluate(unsafe_state, 0)
        data = candidate.to_dict()
        safety.append({
            "fixture": name,
            "fixture_id": fixture.catalogue_record()["fixture_id"],
            "purpose": purpose,
            "unsafe_parameters": dict(data["parameters"]["values"]),
            "unsafe_probe_eligible": candidate.eligible,
            "validation": data["validation"],
            "fit_score": candidate.score,
        })

    dev_rows = [row for row in rows if row["role"] == "development"]
    confirm_rows = [row for row in rows if row["role"] == "sealed-confirmation"]
    report = {
        "kind": "ZG024dStagedSearchEvidence",
        "version": "1.0.0",
        "base_commit": BASE_COMMIT,
        "issue": 92,
        "scope": "preregistered staged-search research; production integration only if frozen confirmation rule passes",
        "design": {
            "methods": list(METHODS),
            "development_fixtures": list(DEV_NAMES),
            "development_seeds": list(DEV_SEEDS),
            "sealed_confirmation_fixtures": list(CONFIRM_NAMES),
            "sealed_confirmation_seeds": list(CONFIRM_SEEDS),
            "safety_probes": list(SAFETY_NAMES),
            "fairness": "same fixture/seed/logical budget per paired method; cold evaluator per method",
            "selection": "fit-only eligibility and score; holdout/truth consulted only after selection",
            "portable_tolerances": {"absolute": ATOL, "relative": RTOL},
            "confirmation_rule_frozen_before_outcomes": True,
        },
        "staged_research_implementation": research_implementation(),
        "development_runs": dev_rows,
        "development_aggregates": _aggregate(dev_rows),
        "confirmation_runs": confirm_rows,
        "confirmation_aggregates": _aggregate(confirm_rows),
        "safety_probes": safety,
    }
    report["decision"] = _confirmation_decision(confirm_rows, safety)
    report["evidence_sha256"] = digest(report)
    telemetry = {
        "kind": "ZG024dStagedTelemetry", "version": "1.0.0",
        "evidence_sha256": report["evidence_sha256"], "runs": timing,
        "total_seconds": time.perf_counter() - started,
        "note": "wall-clock telemetry is host-specific and excluded from evidence identity",
    }
    return report, full, telemetry


def portable_reference(report):
    def project(rows):
        keys = (
            "fixture", "seed", "method_id", "declared_budget", "consumed_evaluations",
            "eligible_candidates", "pareto_candidates", "best_fit_score", "best_holdout_score",
            "whole_signal_score", "overfit_warning", "parameter_error", "manifold_error",
        )
        return [{key: row[key] for key in keys} for row in rows]
    return {
        "kind": "ZG024dPortableConfirmationReference",
        "version": "1.0.0",
        "base_commit": report["base_commit"],
        "design": report["design"],
        "development_runs": project(report["development_runs"]),
        "confirmation_runs": project(report["confirmation_runs"]),
        "safety_probes": [{
            "fixture": row["fixture"], "unsafe_probe_eligible": row["unsafe_probe_eligible"],
            "fit_score": row["fit_score"], "validation": row["validation"],
        } for row in report["safety_probes"]],
        "decision": report["decision"],
        "note": "portable frozen projection; candidate lineage and decomposed evidence remain in CI artifacts",
    }


def compare_reference(actual, expected):
    failures = []

    def walk(a, e, path):
        if isinstance(e, bool) or e is None or isinstance(e, str):
            if type(a) is not type(e) or a != e:
                failures.append(path + ": discrete value changed")
        elif isinstance(e, (int, float)):
            if type(a) not in (int, float) or not math.isfinite(a) or not math.isclose(a, e, abs_tol=ATOL, rel_tol=RTOL):
                failures.append(path + f": numeric mismatch {a!r} vs {e!r}")
        elif isinstance(e, dict):
            if type(a) is not dict or a.keys() != e.keys():
                failures.append(path + ": fields changed")
                return
            for key in e:
                walk(a[key], e[key], path + "/" + key)
        elif isinstance(e, list):
            if type(a) is not list or len(a) != len(e):
                failures.append(path + ": length changed")
                return
            for index, (av, ev) in enumerate(zip(a, e)):
                walk(av, ev, path + f"/{index}")
        else:
            failures.append(path + ": unsupported evidence type")

    walk(portable_reference(actual), expected, "")
    return failures


def write_json(path, value, *, compact=False):
    payload = (json.dumps(
        value, sort_keys=True, allow_nan=False,
        separators=(",", ":") if compact else None,
        indent=None if compact else 2,
    ) + "\n").encode()
    if str(path).endswith(".gz"):
        payload = gzip.compress(payload, mtime=0)
    atomic_publish_bytes(path, payload)


def read_json(path):
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rb") as stream:
        payload = stream.read(4 * 1024 * 1024 + 1)
    if len(payload) > 4 * 1024 * 1024:
        raise ValueError("ZG-024d portable reference exceeds 4 MiB")
    return json.loads(payload.decode())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--full-out", type=Path)
    parser.add_argument("--telemetry-out", type=Path)
    parser.add_argument("--reference-out", type=Path)
    parser.add_argument("--check", type=Path)
    args = parser.parse_args()
    report, full, telemetry = build_report()
    write_json(args.out, report, compact=True)
    if args.full_out:
        write_json(args.full_out, full, compact=True)
    if args.telemetry_out:
        write_json(args.telemetry_out, telemetry)
    if args.reference_out:
        write_json(args.reference_out, portable_reference(report), compact=True)
    failures = compare_reference(report, read_json(args.check)) if args.check else []
    print(json.dumps({
        "evidence_sha256": report["evidence_sha256"],
        "development_runs": len(report["development_runs"]),
        "confirmation_runs": len(report["confirmation_runs"]),
        "decision": report["decision"],
        "seconds": telemetry["total_seconds"],
        "comparison_failures": failures,
    }, indent=2))
    if failures:
        raise SystemExit("ZG-024d portable evidence comparison failed")


if __name__ == "__main__":
    main()
