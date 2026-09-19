from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
from scipy import stats

from .model import StudyError


@dataclass(frozen=True)
class SimulationAssumptions:
    effect: float = 0.0
    listener_sd: float = 0.35
    item_sd: float = 0.45
    residual_sd: float = 1.0
    missing_fraction: float = 0.0
    outcome_domain: str = "continuous-contrast"

    def __post_init__(self):
        for name in ("effect", "listener_sd", "item_sd", "residual_sd", "missing_fraction"):
            value = getattr(self, name)
            if type(value) not in (int, float) or type(value) is bool or not math.isfinite(float(value)):
                raise StudyError(f"{name} must be finite numeric")
        if min(self.listener_sd, self.item_sd, self.residual_sd) < 0:
            raise StudyError("simulation SD assumptions must be non-negative")
        if not 0 <= self.missing_fraction < 0.8:
            raise StudyError("simulation missing_fraction must be in [0,0.8)")
        if self.outcome_domain not in (
            "continuous-contrast",
            "bounded-100-contrast",
            "ordinal-7-contrast",
        ):
            raise StudyError("unsupported simulation outcome domain")

    def metadata(self):
        return {
            "effect": float(self.effect),
            "listener_sd": float(self.listener_sd),
            "item_sd": float(self.item_sd),
            "residual_sd": float(self.residual_sd),
            "missing_fraction": float(self.missing_fraction),
            "outcome_domain": self.outcome_domain,
            "status": "assumed-not-estimated",
        }


def balanced_cyclic_orders(conditions, participant_count, *, seed="0"):
    conditions = tuple(conditions)
    if not 2 <= len(conditions) <= 16 or len(set(conditions)) != len(conditions):
        raise StudyError("counterbalance requires 2..16 unique conditions")
    if any(type(value) is not str or not value for value in conditions):
        raise StudyError("counterbalance conditions must be non-empty strings")
    if type(participant_count) is not int or type(participant_count) is bool or not 1 <= participant_count <= 1000000:
        raise StudyError("participant_count must be in 1..1,000,000")
    try:
        numeric_seed = int(seed)
    except (TypeError, ValueError) as exc:
        raise StudyError("counterbalance seed must be a decimal integer string") from exc
    if str(numeric_seed) != str(seed) or not 0 <= numeric_seed <= 2**64 - 1:
        raise StudyError("counterbalance seed outside canonical uint64 decimal domain")
    rng = np.random.default_rng(numeric_seed)
    base = list(conditions)
    rng.shuffle(base)
    rows = []
    n = len(base)
    for participant_index in range(participant_count):
        shift = participant_index % n
        order = base[shift:] + base[:shift]
        rows.append(
            {
                "participant_index": participant_index,
                "cycle": participant_index // n,
                "order": list(order),
            }
        )
    return rows


def _transform_domain(matrix, domain):
    if domain == "continuous-contrast":
        return matrix
    if domain == "bounded-100-contrast":
        return np.clip(matrix, -100.0, 100.0)
    if domain == "ordinal-7-contrast":
        return np.clip(np.rint(matrix), -6.0, 6.0)
    raise StudyError("unsupported simulation outcome domain")


def _simulate_matrix(listeners, items, assumptions, rng):
    listener = rng.normal(0.0, assumptions.listener_sd, size=(listeners, 1))
    item = rng.normal(0.0, assumptions.item_sd, size=(1, items))
    residual = rng.normal(0.0, assumptions.residual_sd, size=(listeners, items))
    matrix = assumptions.effect + listener + item + residual
    matrix = _transform_domain(matrix, assumptions.outcome_domain)
    if assumptions.missing_fraction:
        mask = rng.random(size=matrix.shape) < assumptions.missing_fraction
        matrix = np.where(mask, np.nan, matrix)
    return matrix


def _crossed_conservative_matrix(matrix, alpha):
    values = np.asarray(matrix, dtype=np.float64)
    if values.ndim != 2:
        raise StudyError("crossed simulation matrix must be 2-D")
    observed = values[np.isfinite(values)]
    row_means = np.nanmean(values, axis=1)
    col_means = np.nanmean(values, axis=0)
    row_means = row_means[np.isfinite(row_means)]
    col_means = col_means[np.isfinite(col_means)]
    if len(observed) < 2 or len(row_means) < 4 or len(col_means) < 4:
        return None
    effect = float(np.mean(observed))
    se = math.sqrt(
        float(np.var(row_means, ddof=1)) / len(row_means)
        + float(np.var(col_means, ddof=1)) / len(col_means)
    )
    df = min(len(row_means) - 1, len(col_means) - 1)
    if not math.isfinite(se) or se <= 0:
        return None
    critical = float(stats.t.ppf(1.0 - alpha / 2.0, df))
    return effect, se, effect - critical * se, effect + critical * se, float(2 * stats.t.sf(abs(effect / se), df))


def _listener_only_matrix(matrix, alpha):
    row_means = np.nanmean(np.asarray(matrix, dtype=np.float64), axis=1)
    row_means = row_means[np.isfinite(row_means)]
    if len(row_means) < 4:
        return None
    effect = float(np.mean(row_means))
    se = float(np.std(row_means, ddof=1) / math.sqrt(len(row_means)))
    if not math.isfinite(se) or se <= 0:
        return None
    df = len(row_means) - 1
    critical = float(stats.t.ppf(1.0 - alpha / 2.0, df))
    return effect, se, effect - critical * se, effect + critical * se, float(2 * stats.t.sf(abs(effect / se), df))


def simulate_crossed_design(listeners, items, assumptions=SimulationAssumptions(), *, replicates=512, seed=0, alpha=0.05):
    if type(listeners) is not int or type(listeners) is bool or not 4 <= listeners <= 4096:
        raise StudyError("listeners must be in 4..4096")
    if type(items) is not int or type(items) is bool or not 4 <= items <= 4096:
        raise StudyError("items must be in 4..4096")
    if not isinstance(assumptions, SimulationAssumptions):
        raise StudyError("SimulationAssumptions required")
    if type(replicates) is not int or type(replicates) is bool or not 32 <= replicates <= 4096:
        raise StudyError("replicates must be in 32..4096")
    if type(seed) is not int or type(seed) is bool or not 0 <= seed <= 2**64 - 1:
        raise StudyError("simulation seed must be uint64")
    if type(alpha) not in (int, float) or type(alpha) is bool or not 1e-6 <= float(alpha) <= 0.5:
        raise StudyError("alpha outside supported range")
    alpha = float(alpha)
    rng = np.random.default_rng(seed)
    crossed = []
    naive = []
    for _ in range(replicates):
        matrix = _simulate_matrix(listeners, items, assumptions, rng)
        a = _crossed_conservative_matrix(matrix, alpha)
        b = _listener_only_matrix(matrix, alpha)
        if a is not None:
            crossed.append(a)
        if b is not None:
            naive.append(b)

    def summarise(rows, method):
        if not rows:
            return {
                "method": method,
                "usable_replicates": 0,
                "mean_estimate": None,
                "mean_ci_half_width": None,
                "coverage": None,
                "null_rejection": None,
            }
        array = np.asarray(rows, dtype=np.float64)
        target = float(assumptions.effect)
        return {
            "method": method,
            "usable_replicates": len(rows),
            "mean_estimate": float(np.mean(array[:, 0])),
            "mean_ci_half_width": float(np.mean((array[:, 3] - array[:, 2]) / 2.0)),
            "coverage": float(np.mean((array[:, 2] <= target) & (target <= array[:, 3]))),
            "null_rejection": float(np.mean(array[:, 4] <= alpha)) if abs(target) <= 1e-15 else None,
        }

    return {
        "kind": "ZG040CrossedDesignSimulation",
        "version": "1.0.0",
        "listeners": listeners,
        "items": items,
        "replicates": replicates,
        "seed": seed,
        "alpha": alpha,
        "assumptions": assumptions.metadata(),
        "production_candidate": summarise(crossed, "crossed-row-column-conservative-v1"),
        "adversarial_comparison": summarise(naive, "listener-only-naive-not-for-confirmatory-use"),
        "interpretation": "simulation under declared assumptions only; not participant evidence or a universal sample-size rule",
    }


def plan_precision(listener_grid, item_grid, assumptions=SimulationAssumptions(), *,
                   target_half_width, replicates=256, seed=0, alpha=0.05):
    listeners = tuple(listener_grid)
    items = tuple(item_grid)
    if not listeners or not items or len(listeners) * len(items) > 64:
        raise StudyError("precision grid must contain 1..64 listener/item combinations")
    if (
        type(target_half_width) not in (int, float)
        or type(target_half_width) is bool
        or not math.isfinite(float(target_half_width))
        or target_half_width <= 0
    ):
        raise StudyError("target_half_width must be positive finite")
    rows = []
    serial = 0
    for listener_count in listeners:
        for item_count in items:
            report = simulate_crossed_design(
                listener_count,
                item_count,
                assumptions,
                replicates=replicates,
                seed=seed + serial * 104729,
                alpha=alpha,
            )
            candidate = report["production_candidate"]
            width = candidate["mean_ci_half_width"]
            rows.append(
                {
                    "listeners": listener_count,
                    "items": item_count,
                    "mean_ci_half_width": width,
                    "meets_target": width is not None and width <= float(target_half_width),
                    "coverage": candidate["coverage"],
                    "usable_replicates": candidate["usable_replicates"],
                }
            )
            serial += 1
    return {
        "kind": "ZG040PrecisionPlan",
        "version": "1.0.0",
        "target_half_width": float(target_half_width),
        "alpha": float(alpha),
        "replicates_per_cell": replicates,
        "assumptions": assumptions.metadata(),
        "rows": rows,
        "interpretation": "precision projection under assumed variance/distribution only; not a participant-derived sample-size recommendation",
    }
