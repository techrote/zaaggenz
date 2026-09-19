from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
import itertools
import json
import math

import numpy as np
from scipy import stats

from zaaggenz_contracts import digest
from zaaggenz_contracts.model import check_json, loads

from .model import (
    VERSION,
    FrozenStudy,
    StudyAmendment,
    StudyDeviation,
    StudyError,
    StudyManifest,
    verify_amendment_chain,
)


@dataclass(frozen=True, init=False)
class StudyDataset:
    _json: str

    def __init__(self, document, manifest):
        if not isinstance(manifest, StudyManifest):
            raise StudyError("StudyManifest required")
        try:
            check_json(document)
        except (TypeError, ValueError) as exc:
            raise StudyError(f"dataset must be strict JSON: {exc}") from exc
        if (
            type(document) is not dict
            or set(document) != {"format", "version", "manifest_sha256", "rows"}
            or document["format"] != "zaaggenz-study-dataset"
            or document["version"] != VERSION
        ):
            raise StudyError("invalid study dataset envelope")
        if document["manifest_sha256"] != manifest.sha256:
            raise StudyError("dataset manifest binding mismatch")

        m = manifest.to_dict()
        endpoints = {row["id"]: row for row in m["endpoints"]}
        stimuli = {row["id"]: row for row in m["stimuli"]}
        exclusion_ids = {row["id"] for row in m["exclusions"]}
        rows = document["rows"]
        if type(rows) is not list or not 1 <= len(rows) <= 1_000_000:
            raise StudyError("dataset rows must contain 1..1,000,000 observations")
        normalised = []
        seen = set()
        for raw in rows:
            if type(raw) is not dict or set(raw) != {
                "participant_id",
                "item_id",
                "stimulus_id",
                "trial_id",
                "result_sha256",
                "condition",
                "endpoint",
                "value",
                "status",
                "exclusion_id",
                "familiarity",
            }:
                raise StudyError("dataset row has missing or unknown fields")
            participant = _id(raw["participant_id"], "participant_id")
            item = _id(raw["item_id"], "item_id")
            stimulus = _sha(raw["stimulus_id"], "stimulus_id")
            trial = _sha(raw["trial_id"], "trial_id")
            result = _sha(raw["result_sha256"], "result_sha256")
            endpoint_id = _id(raw["endpoint"], "endpoint")
            condition = _id(raw["condition"], "condition")
            if stimulus not in stimuli:
                raise StudyError("dataset row references stimulus outside manifest")
            if stimuli[stimulus]["condition"] != condition:
                raise StudyError("dataset row condition disagrees with frozen stimulus binding")
            if endpoint_id not in endpoints:
                raise StudyError("dataset row references endpoint outside manifest")
            if raw["status"] not in ("completed", "missing", "excluded"):
                raise StudyError("invalid dataset observation status")

            value = raw["value"]
            exclusion_id = raw["exclusion_id"]
            if raw["status"] == "completed":
                if exclusion_id is not None:
                    raise StudyError("completed observation cannot carry exclusion_id")
                value = _endpoint_value(value, endpoints[endpoint_id])
            else:
                if value is not None:
                    raise StudyError("missing/excluded observation must have null value")
                if raw["status"] == "excluded":
                    if exclusion_id not in exclusion_ids:
                        raise StudyError("excluded observation requires predeclared exclusion_id")
                elif exclusion_id is not None:
                    raise StudyError("missing observation cannot carry exclusion_id")

            familiarity = raw["familiarity"]
            if familiarity is not None:
                familiarity = _finite(familiarity, 0, 100, "familiarity")

            key = (participant, item, endpoint_id, condition)
            if key in seen:
                raise StudyError("duplicate participant/item/endpoint/condition observation")
            seen.add(key)
            normalised.append(
                {
                    **deepcopy(raw),
                    "participant_id": participant,
                    "item_id": item,
                    "stimulus_id": stimulus,
                    "trial_id": trial,
                    "result_sha256": result,
                    "condition": condition,
                    "endpoint": endpoint_id,
                    "value": value,
                    "exclusion_id": exclusion_id,
                    "familiarity": familiarity,
                }
            )
        payload = {
            "format": document["format"],
            "version": VERSION,
            "manifest_sha256": manifest.sha256,
            "rows": normalised,
        }
        object.__setattr__(
            self,
            "_json",
            json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False),
        )

    def to_dict(self):
        return loads(self._json)

    @property
    def sha256(self):
        return digest({"domain": "zaaggenz-study-dataset-v1", "dataset": self.to_dict()})


def _id(value, name):
    from .model import IDENTIFIER

    if type(value) is not str or not IDENTIFIER.fullmatch(value):
        raise StudyError(f"{name}: canonical lowercase identifier required")
    return value


def _sha(value, name):
    from .model import HEX64

    if type(value) is not str or not HEX64.fullmatch(value):
        raise StudyError(f"{name}: lowercase SHA-256 required")
    return value


def _finite(value, lo, hi, name):
    if (
        type(value) not in (int, float)
        or type(value) is bool
        or not math.isfinite(float(value))
        or not lo <= float(value) <= hi
    ):
        raise StudyError(f"{name}: finite value in {lo}..{hi} required")
    return float(value)


def _endpoint_value(value, endpoint):
    scale = endpoint["scale"]
    if scale in ("bounded-continuous", "ordinal"):
        return _finite(value, endpoint["minimum"], endpoint["maximum"], "endpoint value")
    if scale == "binary":
        if type(value) is bool:
            return 1.0 if value else 0.0
        if value in (0, 1):
            return float(value)
        raise StudyError("binary endpoint value must be boolean/0/1")
    if scale == "choice":
        if value not in (0, 1):
            raise StudyError("choice endpoint value must be 0/1 for the predeclared target choice")
        return float(value)
    raise StudyError("unsupported endpoint scale")


def _contrast_pairs(manifest, dataset, contrast):
    rows = dataset.to_dict()["rows"]
    endpoint = contrast["endpoint"]
    a = contrast["condition_a"]
    b = contrast["condition_b"]
    cells = {}
    for row in rows:
        if row["endpoint"] != endpoint or row["condition"] not in (a, b):
            continue
        key = (row["participant_id"], row["item_id"])
        cells.setdefault(key, {})[row["condition"]] = row
    diffs = []
    all_cells = len(cells)
    missing_cells = 0
    for key, conditions in sorted(cells.items()):
        left = conditions.get(a)
        right = conditions.get(b)
        if (
            left is None
            or right is None
            or left["status"] != "completed"
            or right["status"] != "completed"
        ):
            missing_cells += 1
            continue
        diffs.append((key[0], key[1], float(right["value"]) - float(left["value"])))
    missing_fraction = 1.0 if all_cells == 0 else missing_cells / all_cells
    return diffs, all_cells, missing_fraction


def _directional_p(t_stat, df, direction):
    if direction == "greater":
        return float(stats.t.sf(t_stat, df))
    if direction == "less":
        return float(stats.t.cdf(t_stat, df))
    return float(2.0 * stats.t.sf(abs(t_stat), df))


def _contrast_direction(manifest, contrast_id):
    # Hypotheses are independent prose/evidence records. A matching hypothesis ID
    # may predeclare direction for one contrast; otherwise inference is two-sided.
    for row in manifest["hypotheses"]:
        if row["id"] == contrast_id:
            return row["direction"]
    return "two-sided"


def _crossed_conservative(diffs, alpha, direction):
    participants = sorted({p for p, _, _ in diffs})
    items = sorted({i for _, i, _ in diffs})
    if len(participants) < 4 or len(items) < 4:
        return {
            "state": "inconclusive",
            "reason": "crossed method requires at least four represented participants and four represented items",
        }
    values = np.asarray([v for _, _, v in diffs], dtype=np.float64)
    effect = float(np.mean(values))
    row_means = np.asarray(
        [np.mean([v for p, _, v in diffs if p == participant]) for participant in participants],
        dtype=np.float64,
    )
    column_means = np.asarray(
        [np.mean([v for _, i, v in diffs if i == item]) for item in items],
        dtype=np.float64,
    )
    se = math.sqrt(
        float(np.var(row_means, ddof=1)) / len(row_means)
        + float(np.var(column_means, ddof=1)) / len(column_means)
    )
    df = min(len(row_means) - 1, len(column_means) - 1)
    if not math.isfinite(se) or se <= 0:
        return {
            "state": "inconclusive",
            "reason": "crossed uncertainty is undefined/zero for the observed design",
            "effect": effect,
            "complete_pairs": len(diffs),
        }
    critical = float(stats.t.ppf(1.0 - alpha / 2.0, df))
    t_stat = effect / se
    return {
        "state": "analysed",
        "effect": effect,
        "standard_error": se,
        "ci_low": effect - critical * se,
        "ci_high": effect + critical * se,
        "confidence_level": 1.0 - alpha,
        "p_value": _directional_p(t_stat, df, direction),
        "df": int(df),
        "participants": len(participants),
        "items": len(items),
        "complete_pairs": len(diffs),
        "uncertainty_method": "row-plus-column-conservative-min-df-v1",
    }


def _statistic(values, estimand):
    array = np.asarray(values, dtype=np.float64)
    if estimand in ("mean-difference", "choice-proportion"):
        return float(np.mean(array))
    if estimand == "median-difference":
        return float(np.median(array))
    raise StudyError("unsupported estimand")


def _paired_randomisation(diffs, alpha, direction, estimand, seed):
    values = np.asarray([v for _, _, v in diffs], dtype=np.float64)
    n = len(values)
    if n < 2:
        return {"state": "inconclusive", "reason": "paired method requires at least two complete pairs"}
    observed = _statistic(values, estimand)
    rng = np.random.default_rng(seed)
    if n <= 16:
        signs = np.asarray(list(itertools.product((-1.0, 1.0), repeat=n)), dtype=np.float64)
    else:
        signs = rng.choice(np.asarray((-1.0, 1.0)), size=(32768, n))
    permuted = np.asarray([_statistic(values * row, estimand) for row in signs], dtype=np.float64)
    if direction == "greater":
        extreme = np.count_nonzero(permuted >= observed - 1e-15)
    elif direction == "less":
        extreme = np.count_nonzero(permuted <= observed + 1e-15)
    else:
        extreme = np.count_nonzero(np.abs(permuted) >= abs(observed) - 1e-15)
    p_value = float((extreme + 1) / (len(permuted) + 1))

    # Effect uncertainty is an explicitly separate paired-cell bootstrap; the
    # randomisation p-value remains tied to the assignment exchangeability rule.
    draws = 4096
    indices = rng.integers(0, n, size=(draws, n))
    boot = np.asarray([_statistic(values[idx], estimand) for idx in indices], dtype=np.float64)
    lo, hi = np.quantile(boot, [alpha / 2.0, 1.0 - alpha / 2.0])
    return {
        "state": "analysed",
        "effect": observed,
        "standard_error": float(np.std(boot, ddof=1)),
        "ci_low": float(lo),
        "ci_high": float(hi),
        "confidence_level": 1.0 - alpha,
        "p_value": p_value,
        "df": None,
        "participants": len({p for p, _, _ in diffs}),
        "items": len({i for _, i, _ in diffs}),
        "complete_pairs": n,
        "uncertainty_method": "paired-cell-bootstrap-4096-v1",
        "test_method": "paired-cell-sign-randomisation-v1",
    }


def _descriptive(diffs, alpha, estimand, seed):
    values = np.asarray([v for _, _, v in diffs], dtype=np.float64)
    if not len(values):
        return {"state": "inconclusive", "reason": "no complete pairs"}
    effect = _statistic(values, estimand)
    if len(values) == 1:
        return {
            "state": "analysed",
            "effect": effect,
            "standard_error": None,
            "ci_low": None,
            "ci_high": None,
            "confidence_level": None,
            "p_value": None,
            "df": None,
            "participants": 1,
            "items": 1,
            "complete_pairs": 1,
            "uncertainty_method": "descriptive-only-v1",
        }
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, len(values), size=(4096, len(values)))
    boot = np.asarray([_statistic(values[idx], estimand) for idx in indices])
    lo, hi = np.quantile(boot, [alpha / 2.0, 1.0 - alpha / 2.0])
    return {
        "state": "analysed",
        "effect": effect,
        "standard_error": float(np.std(boot, ddof=1)),
        "ci_low": float(lo),
        "ci_high": float(hi),
        "confidence_level": 1.0 - alpha,
        "p_value": None,
        "df": None,
        "participants": len({p for p, _, _ in diffs}),
        "items": len({i for _, i, _ in diffs}),
        "complete_pairs": len(values),
        "uncertainty_method": "descriptive-paired-bootstrap-4096-v1",
    }


def _holm(rows):
    indexed = [
        (index, float(row["p_value"]))
        for index, row in enumerate(rows)
        if row.get("state") == "analysed" and row.get("p_value") is not None
    ]
    if not indexed:
        return rows
    ordered = sorted(indexed, key=lambda pair: pair[1])
    adjusted = {}
    running = 0.0
    m = len(ordered)
    for rank, (index, p_value) in enumerate(ordered):
        candidate = min(1.0, (m - rank) * p_value)
        running = max(running, candidate)
        adjusted[index] = running
    out = deepcopy(rows)
    for index, value in adjusted.items():
        out[index]["p_adjusted"] = float(value)
        out[index]["multiplicity"] = "holm-primary-v1"
    return out


def analyse_study(frozen, current_manifest, dataset, *, amendments=(), deviations=()):
    if not isinstance(frozen, FrozenStudy) or not isinstance(current_manifest, StudyManifest):
        raise StudyError("FrozenStudy and StudyManifest required")
    if not isinstance(dataset, StudyDataset):
        raise StudyError("StudyDataset required")
    verify_amendment_chain(frozen, tuple(amendments), current_manifest)
    if dataset.to_dict()["manifest_sha256"] != current_manifest.sha256:
        raise StudyError("dataset is not bound to current authorised study manifest")
    for deviation in deviations:
        if not isinstance(deviation, StudyDeviation) or deviation.to_dict()["freeze_id"] != frozen.sha256:
            raise StudyError("deviation does not belong to frozen study")

    manifest = current_manifest.to_dict()
    alpha = float(manifest["analysis"]["alpha"])
    seed_base = int(manifest["randomisation"]["seed"])
    after_outcome_amendment = any(
        amendment.to_dict()["phase"] == "after-outcome-access" for amendment in amendments
    )
    confirmatory_invalid = after_outcome_amendment or any(
        deviation.to_dict()["impact"] == "confirmatory-invalidated" for deviation in deviations
    )
    rows = []
    for index, contrast in enumerate(manifest["contrasts"]):
        diffs, all_cells, missing_fraction = _contrast_pairs(manifest, dataset, contrast)
        result = {
            "contrast_id": contrast["id"],
            "endpoint": contrast["endpoint"],
            "condition_a": contrast["condition_a"],
            "condition_b": contrast["condition_b"],
            "estimand": contrast["estimand"],
            "method": contrast["method"],
            "primary": contrast["primary"],
            "all_observed_cells": all_cells,
            "missing_fraction": missing_fraction,
        }
        if missing_fraction > manifest["missing_data"]["max_fraction"]:
            result.update(
                state="inconclusive",
                reason="predeclared missing-data threshold exceeded",
                complete_pairs=len(diffs),
            )
        elif len(diffs) < manifest["missing_data"]["min_complete_pairs"]:
            result.update(
                state="inconclusive",
                reason="predeclared minimum complete pairs not reached",
                complete_pairs=len(diffs),
            )
        else:
            direction = _contrast_direction(manifest, contrast["id"])
            method = contrast["method"]
            if method == "crossed-row-column-conservative-v1":
                result.update(_crossed_conservative(diffs, alpha, direction))
            elif method == "paired-cell-randomisation-v1":
                if manifest["randomisation"]["method"] != "within-cell-pair-v1":
                    raise StudyError("paired randomisation analysis requires within-cell-pair-v1 assignment")
                result.update(
                    _paired_randomisation(
                        diffs,
                        alpha,
                        direction,
                        contrast["estimand"],
                        seed_base + index * 104729,
                    )
                )
            elif method == "descriptive-only-v1":
                result.update(
                    _descriptive(diffs, alpha, contrast["estimand"], seed_base + index * 104729)
                )
            else:
                raise StudyError("unsupported contrast method")
        rows.append(result)

    confirmatory = [row for row in rows if row["primary"]]
    exploratory = [row for row in rows if not row["primary"]]
    if manifest["mode"] == "confirmatory" and not confirmatory_invalid:
        confirmatory = _holm(confirmatory)
    else:
        exploratory = deepcopy(confirmatory) + exploratory
        for row in exploratory:
            row["analysis_status"] = "exploratory"
        confirmatory = []

    if manifest["mode"] == "exploratory":
        completion = {
            "status": "complete-exploratory",
            "reason": "study was explicitly exploratory; no confirmatory claim is produced",
        }
    elif confirmatory_invalid:
        completion = {
            "status": "inconclusive",
            "reason": "confirmatory interpretation invalidated by post-outcome amendment/deviation; results retained as exploratory",
        }
    elif any(row.get("state") != "analysed" for row in confirmatory):
        completion = {
            "status": "inconclusive",
            "reason": "at least one primary contrast could not satisfy the frozen analysis/missing-data contract",
        }
    else:
        threshold = alpha
        detected = any((row.get("p_adjusted", row.get("p_value", 1.0)) <= threshold) for row in confirmatory)
        completion = {
            "status": "complete-difference-detected" if detected else "complete-null-compatible",
            "reason": (
                "at least one primary contrast crossed the frozen multiplicity-adjusted alpha"
                if detected
                else "planned primary evidence is compatible with zero at the frozen alpha; this does not prove equality"
            ),
        }

    report = {
        "format": "zaaggenz-study-report",
        "version": VERSION,
        "freeze_id": frozen.sha256,
        "manifest_sha256": current_manifest.sha256,
        "dataset_sha256": dataset.sha256,
        "confirmatory": confirmatory,
        "exploratory": exploratory,
        "amendments": [amendment.to_dict() for amendment in amendments],
        "deviations": [deviation.to_dict() for deviation in deviations],
        "completion": completion,
    }
    try:
        check_json(report)
    except (TypeError, ValueError) as exc:
        raise StudyError(f"analysis report is not strict JSON: {exc}") from exc
    report["report_sha256"] = digest({"domain": "zaaggenz-study-report-v1", "report": report})
    return report
