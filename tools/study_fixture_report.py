"""Generate deterministic ZG-040 scaffold evidence; contains no participant data."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from zaaggenz_studies import (
    FAMILIES,
    SimulationAssumptions,
    StudyDataset,
    StudyManifest,
    analyse_study,
    balanced_cyclic_orders,
    freeze_manifest,
    plan_precision,
    simulate_crossed_design,
)


def _sha(label):
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _manifest(family, endpoint, scale, method):
    lo, hi = (0.0, 100.0) if scale == "bounded-continuous" else ((1.0, 7.0) if scale == "ordinal" else (None, None))
    stimuli = []
    for item in range(4):
        for condition in ("control", "variant"):
            stimuli.append(
                {
                    "id": _sha(f"{family}-stimulus-{item}-{condition}"),
                    "raw_pcm_sha256": _sha(f"{family}-raw-{item}-{condition}"),
                    "playback_sha256": _sha(f"{family}-playback-{item}-{condition}"),
                    "family": f"item{item}",
                    "condition": condition,
                }
            )
    return StudyManifest(
        {
            "format": "zaaggenz-study-manifest",
            "version": "1.0.0",
            "title": f"ZG-040 synthetic {family} scaffold",
            "family": family,
            "mode": "confirmatory",
            "questions": ["Synthetic scaffold question; no participant claim."],
            "hypotheses": [
                {
                    "id": "primary-effect",
                    "text": "Synthetic primary contrast used only to verify the scaffold.",
                    "direction": "two-sided",
                }
            ],
            "stimuli": stimuli,
            "matching": {
                "method": "whole-file-rms-common-target-v1",
                "target_rms_dbfs": -24.0,
                "peak_ceiling_dbfs": -3.0,
                "true_peak_measured": False,
            },
            "randomisation": {
                "method": "within-cell-pair-v1" if method == "paired-cell-randomisation-v1" else "balanced-cyclic-v1",
                "seed": "41",
                "counterbalanced": True,
            },
            "endpoints": [{"id": endpoint, "scale": scale, "minimum": lo, "maximum": hi}],
            "contrasts": [
                {
                    "id": "primary-effect",
                    "endpoint": endpoint,
                    "condition_a": "control",
                    "condition_b": "variant",
                    "estimand": "mean-difference",
                    "method": method,
                    "primary": True,
                }
            ],
            "exclusions": [
                {
                    "id": "technical-failure",
                    "rule": "Exclude only pre-outcome playback/capture failure.",
                    "timing": "pre-outcome",
                }
            ],
            "missing_data": {
                "strategy": "available-pairs-with-threshold-v1",
                "max_fraction": 0.2,
                "min_complete_pairs": 8,
            },
            "stopping_rule": {
                "kind": "fixed-complete-cases",
                "min_participants": 8,
                "max_participants": 8,
                "target_ci_half_width": None,
                "endpoint": None,
            },
            "analysis": {
                "alpha": 0.05,
                "multiplicity": "holm-primary-v1",
                "confirmatory_methods": [method],
            },
            "privacy": {
                "participant_id_policy": "pseudonymous-study-local-v1",
                "notes": "Synthetic fixture only; no participant identifiers or responses.",
            },
        }
    )


def _null_dataset(manifest):
    doc = manifest.to_dict()
    endpoint = doc["endpoints"][0]["id"]
    if doc["endpoints"][0]["scale"] != "bounded-continuous":
        raise ValueError("null fixture uses bounded-continuous endpoint")
    lookup = {(row["family"], row["condition"]): row["id"] for row in doc["stimuli"]}
    rows = []
    for participant in range(8):
        p_offset = (participant - 3.5) * 0.1
        for item in range(4):
            i_offset = (item - 1.5) * 0.2
            for condition in ("control", "variant"):
                value = 50.0 + (p_offset + i_offset if condition == "variant" else 0.0)
                rows.append(
                    {
                        "participant_id": f"p{participant}",
                        "item_id": f"item{item}",
                        "stimulus_id": lookup[(f"item{item}", condition)],
                        "trial_id": _sha(f"null-trial-{participant}-{item}"),
                        "result_sha256": _sha(f"null-result-{participant}-{item}-{condition}"),
                        "condition": condition,
                        "endpoint": endpoint,
                        "value": value,
                        "status": "completed",
                        "exclusion_id": None,
                        "familiarity": 50.0,
                    }
                )
    return StudyDataset(
        {
            "format": "zaaggenz-study-dataset",
            "version": "1.0.0",
            "manifest_sha256": manifest.sha256,
            "rows": rows,
        },
        manifest,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    definitions = {
        "reference-ablation": ("sound-quality", "bounded-continuous", "crossed-row-column-conservative-v1"),
        "chordness-tuning": ("sonority-fit", "bounded-continuous", "crossed-row-column-conservative-v1"),
        "linked-return": ("recognition", "ordinal", "crossed-row-column-conservative-v1"),
        "variation-meter-gesture": ("groove", "bounded-continuous", "crossed-row-column-conservative-v1"),
        "vocal-participation": ("imitation-success", "binary", "paired-cell-randomisation-v1"),
        "grammar-learning": ("return-choice", "choice", "paired-cell-randomisation-v1"),
    }
    if set(definitions) != set(FAMILIES):
        raise RuntimeError("planned study family coverage drift")

    manifests = []
    for family, (endpoint, scale, method) in definitions.items():
        manifest = _manifest(family, endpoint, scale, method)
        frozen = freeze_manifest(manifest)
        manifests.append(
            {
                "family": family,
                "endpoint": endpoint,
                "scale": scale,
                "method": method,
                "manifest_sha256": manifest.sha256,
                "freeze_id": frozen.sha256,
            }
        )

    null_manifest = _manifest(
        "chordness-tuning", "sonority-fit", "bounded-continuous",
        "crossed-row-column-conservative-v1",
    )
    null_frozen = freeze_manifest(null_manifest)
    null_report = analyse_study(
        null_frozen, null_manifest, _null_dataset(null_manifest)
    )

    assumptions = SimulationAssumptions(
        effect=0.0, listener_sd=0.35, item_sd=0.45, residual_sd=1.0
    )
    calibration = simulate_crossed_design(
        96, 4, assumptions, replicates=256, seed=23
    )
    precision = plan_precision(
        (24, 48), (4, 12),
        SimulationAssumptions(effect=0.2, missing_fraction=0.05),
        target_half_width=0.5, replicates=64, seed=91,
    )
    counterbalance = balanced_cyclic_orders(("a", "b", "c", "d"), 12, seed="17")

    report = {
        "kind": "ZG040StudyScaffoldEvidence",
        "version": "1.0.0",
        "scope": "synthetic fixtures and assumed-variance simulation only; no participant data",
        "planned_family_manifests": manifests,
        "null_completion": {
            "status": null_report["completion"]["status"],
            "report_sha256": null_report["report_sha256"],
        },
        "four_item_calibration": calibration,
        "precision_projection": precision,
        "counterbalance": counterbalance,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
