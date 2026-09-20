"""Run the sealed ZG-024e confirmation programme after the committed selection freeze."""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from zaaggenz_contracts import digest
from zaaggenz_jobs import atomic_publish_bytes
from research.zg024e import CONTROL_METHOD, SEARCH_SEEDS, DiagnosticSpec
from research.zg024e.confirmation import (
    CONFIRMATION_NAMES,
    DESIGN_FREEZE_COMMIT,
    MATCHED_NULL_METHOD,
    SELECTED_METHOD,
    SELECTION_DECISION_SHA256,
    SELECTION_FREEZE_COMMIT,
    confirmation_fixture,
)
from tools.inverse_feasibility_report import (
    ATOL,
    RTOL,
    BASELINES,
    _audit_pending,
    _budget_accounting_ok,
    _portable_compare,
    _portable_row,
    _report_identity_row,
    _run_fit,
    _sentinels,
    _median,
)

SELECTION_RECORD = ROOT / "examples" / "zg024e-development-selection.json"


def _ratio(value, baseline):
    if value is None or baseline is None:
        return None
    if math.isclose(value, baseline, abs_tol=ATOL, rel_tol=RTOL):
        return 1.0
    if baseline == 0.0:
        return math.inf if value > 0.0 else 1.0
    return value / baseline


def _load_frozen_selection():
    value = json.loads(SELECTION_RECORD.read_text(encoding="utf-8"))
    required = {
        "kind": "ZG024eDevelopmentSelection",
        "version": "1.0.0",
        "child_issue": 227,
        "parent_issue": 25,
        "design_freeze_commit": DESIGN_FREEZE_COMMIT,
        "selection_decision_sha256": SELECTION_DECISION_SHA256,
        "selected_intervention_method": SELECTED_METHOD,
        "selected_matched_null_method": MATCHED_NULL_METHOD,
        "primary_mechanism": "cross-family-coupling",
        "primary_diagnosis": "cross-family-coupling",
    }
    for key, expected in required.items():
        if value.get(key) != expected:
            raise ValueError(
                f"committed ZG-024e development selection mismatch for {key}: "
                f"{value.get(key)!r} != {expected!r}"
            )
    if value.get("search_seeds") != list(SEARCH_SEEDS):
        raise ValueError("committed ZG-024e search seed set changed")
    return value


def _holdout_comparison(rows):
    output = {}
    for fixture in CONFIRMATION_NAMES:
        selected_median = _median([
            row["best_holdout_score"] for row in rows
            if row["fixture"] == fixture and row["method_id"] == SELECTED_METHOD
        ])
        baseline_medians = {
            method: _median([
                row["best_holdout_score"] for row in rows
                if row["fixture"] == fixture and row["method_id"] == method
                and row["declared_budget"] == 36
            ])
            for method in BASELINES
        }
        finite = [
            (method, value) for method, value in baseline_medians.items()
            if value is not None and math.isfinite(value)
        ]
        best_method, best_value = min(finite, key=lambda pair: pair[1]) if finite else (None, None)
        ratio = _ratio(selected_median, best_value)
        comparable = (
            selected_median is not None and math.isfinite(selected_median)
            and best_value is not None and math.isfinite(best_value)
        )
        output[fixture] = {
            "selected_median_holdout": selected_median,
            "flat_control_median_holdouts": baseline_medians,
            "best_flat_control_method": best_method,
            "best_flat_control_median_holdout": best_value,
            "ratio": ratio,
            "comparable": comparable,
            "passes_1p10_if_comparable": (not comparable) or ratio <= 1.10,
        }
    return output


def _confirmation_portable_row(row):
    """Portable confirmation projection excludes environment-exact PCM equivalence.

    Exact-output equivalence groups are retained in the full per-platform evidence.
    They are derived from bit-identical f32 PCM asset hashes and therefore belong to
    same-environment evidence identity, not the tolerance-based Windows/Ubuntu
    portability surface. Promotion/selection never consumes those groups.
    """
    value = _portable_row(row)
    stages = value.get("promotion_stages")
    if stages is not None:
        value["promotion_stages"] = [
            {
                key: item[key]
                for key in (
                    "stage", "eligible_count", "pareto_count",
                    "retained_count", "retained_cap",
                )
            }
            for item in stages
        ]
    value["exact_output_equivalence"] = "full-evidence-only-environment-exact"
    return value


def _availability(rows, method):
    return sum(
        row["final_available"] for row in rows
        if row["family"] == "diagnostic" and row["method_id"] == method
    )


def _structure_availability(rows, method):
    target = "confirm2-structure-spectral-starvation"
    return sum(
        row["final_available"] for row in rows
        if row["fixture"] == target and row["family"] == "diagnostic"
        and row["method_id"] == method
    )


def build_confirmation_report():
    started = time.perf_counter()
    selection = _load_frozen_selection()
    rows, full, pending = [], [], []

    for name in CONFIRMATION_NAMES:
        for seed in SEARCH_SEEDS:
            for method in (SELECTED_METHOD, MATCHED_NULL_METHOD):
                fixture = confirmation_fixture(name, seed=seed, budget_evaluations=36)
                row, detail, result, best, audit = _run_fit(
                    fixture, method, diagnostic=True
                )
                rows.append(row)
                full.append(detail)
                pending.append((fixture, row, detail, result, best, audit))

            for method in BASELINES:
                fixture = confirmation_fixture(name, seed=seed, budget_evaluations=36)
                row, detail, result, best, audit = _run_fit(
                    fixture, method, diagnostic=False
                )
                rows.append(row)
                full.append(detail)
                pending.append((fixture, row, detail, result, best, audit))

            fixture = confirmation_fixture(name, seed=seed, budget_evaluations=24)
            row, detail, result, best, audit = _run_fit(
                fixture, CONTROL_METHOD, diagnostic=True
            )
            rows.append(row)
            full.append(detail)
            pending.append((fixture, row, detail, result, best, audit))

    # Method selection and diagnosis are already frozen in repository history. Truth
    # distance and holdout are disclosed only after every fit-side confirmation search
    # above has completed; neither can alter proposals, promotion, stopping or ranking.
    _audit_pending(pending)

    sentinel_rows, sentinel_details = _sentinels(SELECTED_METHOD)
    full.extend(sentinel_details)

    selected_available = _availability(rows, SELECTED_METHOD)
    null_available = _availability(rows, MATCHED_NULL_METHOD)
    structure_available = _structure_availability(rows, SELECTED_METHOD)
    availability_gain = selected_available - null_available
    promotion_integrity = all(
        row["promotion_ineligible_violations"] == 0 for row in rows + sentinel_rows
    )
    exact_budget_integrity = all(_budget_accounting_ok(row) for row in rows)

    expected = {
        "sentinel2-transient": {"transient_loss", "silence_collapse"},
        "sentinel2-silence": {"silence_collapse", "energy_collapse", "transient_loss"},
        "sentinel2-clipping": {"pathological_clipping", "destructive_output_clipping"},
    }
    sentinel_integrity = True
    for row in sentinel_rows:
        sentinel_integrity = sentinel_integrity and (
            not row["final_available"]
            and row["promotion_ineligible_violations"] == 0
            and bool(set(row["gate_rejections"]) & expected[row["fixture"]])
        )

    holdout = _holdout_comparison(rows)
    holdout_supported = all(
        item["passes_1p10_if_comparable"] for item in holdout.values()
    )
    data_rule_positive = (
        structure_available >= 2
        and selected_available >= 7
        and availability_gain >= 2
        and promotion_integrity
        and sentinel_integrity
        and holdout_supported
        and exact_budget_integrity
    )

    decision = {
        "selected_intervention_method": SELECTED_METHOD,
        "matched_null_method": MATCHED_NULL_METHOD,
        "primary_diagnosis": selection["primary_diagnosis"],
        "structure_spectral_eligible_seeds": structure_available,
        "structure_spectral_required": 2,
        "overall_eligible_cases": selected_available,
        "overall_required": 7,
        "matched_null_eligible_cases": null_available,
        "eligible_case_gain_over_matched_null": availability_gain,
        "eligible_case_gain_required": 2,
        "promotion_integrity": promotion_integrity,
        "sentinel_integrity": sentinel_integrity,
        "holdout_supported": holdout_supported,
        "exact_budget_integrity": exact_budget_integrity,
        "data_rule_positive": data_rule_positive,
        "deterministic_replay_checkpoint_cancellation_cache_contract":
            "required from inherited and ZG-024e focused CI regressions",
        "cross_platform_portability_contract":
            "required from exact-head Ubuntu/Windows portable-evidence comparison",
        "outcome": (
            "positive-subject-to-exact-head-ci-and-parent-contract"
            if data_rule_positive
            else "mixed-or-no-go-no-production-promotion"
        ),
        "production_promotion_authorized": False,
        "parent_dependency_satisfied_by_this_report": False,
        "policy": (
            "frozen by ZG024E_DIAGNOSTIC_PROTOCOL_V1.md; confirmation cannot select "
            "another intervention or weaken objective/gate tolerances"
        ),
    }

    portable = {
        "kind": "ZG024eConfirmationPortableEvidence",
        "version": "1.0.0",
        "design_freeze_commit": DESIGN_FREEZE_COMMIT,
        "selection_freeze_commit": SELECTION_FREEZE_COMMIT,
        "selection_decision_sha256": SELECTION_DECISION_SHA256,
        "confirmation_names": list(CONFIRMATION_NAMES),
        "search_seeds": list(SEARCH_SEEDS),
        "confirmation": [_confirmation_portable_row(row) for row in rows],
        "sentinels": [_confirmation_portable_row(row) for row in sentinel_rows],
        "holdout": holdout,
        "decision": decision,
    }
    portable_identity = {
        "kind": "ZG024eConfirmationPortableEvidenceIdentity",
        "version": "1.0.0",
        "selection_decision_sha256": SELECTION_DECISION_SHA256,
        "confirmation_row_sha256s": [digest(row) for row in portable["confirmation"]],
        "sentinel_row_sha256s": [digest(row) for row in portable["sentinels"]],
        "holdout_sha256": digest(holdout),
        "decision": decision,
    }
    report = {
        "kind": "ZG024eConfirmationEvidence",
        "version": "1.0.0",
        "scope": (
            "untouched post-selection confirmation of eligible-candidate availability "
            "and held-out generalisation; no production promotion implied"
        ),
        "frozen_selection": selection,
        "design_freeze_commit": DESIGN_FREEZE_COMMIT,
        "selection_freeze_commit": SELECTION_FREEZE_COMMIT,
        "confirmation_rows": rows,
        "sentinel_rows": sentinel_rows,
        "holdout": holdout,
        "decision": decision,
        "portable": portable,
    }
    report["portable_sha256"] = digest(portable_identity)
    evidence_identity = {
        "kind": "ZG024eConfirmationEvidenceIdentity",
        "version": "1.0.0",
        "selection_decision_sha256": SELECTION_DECISION_SHA256,
        "confirmation_row_sha256s": [
            digest(_report_identity_row(row)) for row in rows
        ],
        "sentinel_row_sha256s": [
            digest(_report_identity_row(row)) for row in sentinel_rows
        ],
        "holdout_sha256": digest(holdout),
        "decision": decision,
        "portable_sha256": report["portable_sha256"],
    }
    report["evidence_sha256"] = digest(evidence_identity)
    telemetry = {
        "kind": "ZG024eConfirmationTelemetry",
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--full-out", required=True)
    parser.add_argument("--portable-out", required=True)
    parser.add_argument("--telemetry-out", required=True)
    parser.add_argument("--compare-portable")
    parser.add_argument("--require-integrity", action="store_true")
    args = parser.parse_args()

    report, full, telemetry = build_confirmation_report()
    write(args.out, report)
    write(args.full_out, full)
    write(args.portable_out, report["portable"])
    write(args.telemetry_out, telemetry)

    if args.compare_portable:
        expected = json.loads(Path(args.compare_portable).read_text(encoding="utf-8"))
        _portable_compare(report["portable"], expected)

    print(json.dumps({
        "evidence_sha256": report["evidence_sha256"],
        "portable_sha256": report["portable_sha256"],
        "decision": report["decision"],
        "seconds": telemetry["total_seconds"],
    }, indent=2, sort_keys=True))

    if args.require_integrity:
        decision = report["decision"]
        if not (
            decision["promotion_integrity"]
            and decision["sentinel_integrity"]
            and decision["exact_budget_integrity"]
        ):
            raise SystemExit(
                "ZG-024e confirmation integrity failed; retain evidence and do not promote"
            )


if __name__ == "__main__":
    main()
