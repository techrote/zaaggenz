from __future__ import annotations

from copy import deepcopy
import hashlib
import unittest

from zaaggenz_studies import (
    FAMILIES,
    SimulationAssumptions,
    StudyDataset,
    StudyError,
    StudyManifest,
    analyse_study,
    balanced_cyclic_orders,
    freeze_manifest,
    make_amendment,
    make_deviation,
    plan_precision,
    simulate_crossed_design,
    verify_amendment_chain,
    verify_frozen_manifest,
)


def _sha(label):
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _manifest(
    *,
    family="chordness-tuning",
    method="crossed-row-column-conservative-v1",
    endpoint_id="fit",
    scale="bounded-continuous",
    minimum=0.0,
    maximum=100.0,
    mode="confirmatory",
):
    stimuli = []
    for item in range(4):
        for condition in ("control", "variant"):
            stimuli.append(
                {
                    "id": _sha(f"stimulus-{item}-{condition}"),
                    "raw_pcm_sha256": _sha(f"raw-{item}-{condition}"),
                    "playback_sha256": _sha(f"playback-{item}-{condition}"),
                    "family": f"item{item}",
                    "condition": condition,
                }
            )
    randomisation = (
        "within-cell-pair-v1"
        if method == "paired-cell-randomisation-v1"
        else "balanced-cyclic-v1"
    )
    return StudyManifest(
        {
            "format": "zaaggenz-study-manifest",
            "version": "1.0.0",
            "title": "Synthetic preregistered fixture",
            "family": family,
            "mode": mode,
            "questions": ["Does the frozen variant differ from the frozen control on the declared endpoint?"],
            "hypotheses": [
                {
                    "id": "primary-effect",
                    "text": "The variant and control differ on the primary endpoint.",
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
                "method": randomisation,
                "seed": "7",
                "counterbalanced": True,
            },
            "endpoints": [
                {
                    "id": endpoint_id,
                    "scale": scale,
                    "minimum": minimum,
                    "maximum": maximum,
                }
            ],
            "contrasts": [
                {
                    "id": "primary-effect",
                    "endpoint": endpoint_id,
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
                    "rule": "Exclude only a pre-outcome trial with a recorded playback or capture failure.",
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
                "multiplicity": "holm-primary-v1" if mode == "confirmatory" else "none-exploratory-v1",
                "confirmatory_methods": [method],
            },
            "privacy": {
                "participant_id_policy": "pseudonymous-study-local-v1",
                "notes": "Fixture identifiers are synthetic and contain no participant identity.",
            },
        }
    )


def _dataset(manifest, effect=5.0, *, missing_cells=0):
    m = manifest.to_dict()
    endpoint = m["endpoints"][0]["id"]
    by_item_condition = {
        (row["family"], row["condition"]): row["id"] for row in m["stimuli"]
    }
    rows = []
    missing = set()
    for serial in range(missing_cells):
        missing.add((serial // 4, serial % 4))
    for participant in range(8):
        participant_offset = (participant - 3.5) * 0.1
        for item in range(4):
            item_offset = (item - 1.5) * 0.2
            for condition in ("control", "variant"):
                status = "completed"
                value = 50.0
                if condition == "variant":
                    value += effect + participant_offset + item_offset
                    if (participant, item) in missing:
                        status = "missing"
                        value = None
                rows.append(
                    {
                        "participant_id": f"p{participant}",
                        "item_id": f"item{item}",
                        "stimulus_id": by_item_condition[(f"item{item}", condition)],
                        "trial_id": _sha(f"trial-{participant}-{item}"),
                        "result_sha256": _sha(f"result-{participant}-{item}-{condition}"),
                        "condition": condition,
                        "endpoint": endpoint,
                        "value": value,
                        "status": status,
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


class StudyManifestTests(unittest.TestCase):
    def test_freeze_detects_post_freeze_stimulus_and_analysis_changes(self):
        manifest = _manifest()
        frozen = freeze_manifest(manifest)
        self.assertTrue(verify_frozen_manifest(frozen, manifest))

        changed = manifest.to_dict()
        changed["stimuli"][0]["playback_sha256"] = _sha("different-playback")
        with self.assertRaises(StudyError):
            verify_frozen_manifest(frozen, StudyManifest(changed))

        changed = manifest.to_dict()
        changed["randomisation"]["method"] = "within-cell-pair-v1"
        changed["contrasts"][0]["method"] = "paired-cell-randomisation-v1"
        changed["analysis"]["confirmatory_methods"] = ["paired-cell-randomisation-v1"]
        with self.assertRaises(StudyError):
            verify_frozen_manifest(frozen, StudyManifest(changed))

    def test_prospective_amendment_is_content_addressed_and_lineage_checked(self):
        original = _manifest()
        frozen = freeze_manifest(original)
        changed = original.to_dict()
        changed["analysis"]["alpha"] = 0.04
        amended = StudyManifest(changed)
        amendment = make_amendment(
            frozen,
            original,
            amended,
            phase="prospective-before-outcome",
            reason="Tighten alpha before any outcome access.",
        )
        self.assertIn("/analysis/alpha", amendment.to_dict()["changed_paths"])
        self.assertTrue(
            verify_amendment_chain(frozen, (amendment,), amended)
        )
        with self.assertRaises(StudyError):
            verify_amendment_chain(frozen, (), amended)

    def test_after_outcome_amendment_demotes_confirmatory_output(self):
        original = _manifest()
        frozen = freeze_manifest(original)
        changed = original.to_dict()
        changed["analysis"]["alpha"] = 0.04
        amended = StudyManifest(changed)
        amendment = make_amendment(
            frozen,
            original,
            amended,
            phase="after-outcome-access",
            reason="Example of a post-outcome analytical change that must not remain confirmatory.",
        )
        report = analyse_study(
            frozen,
            amended,
            _dataset(amended, effect=5.0),
            amendments=(amendment,),
        )
        self.assertEqual(report["confirmatory"], [])
        self.assertTrue(report["exploratory"])
        self.assertEqual(report["completion"]["status"], "inconclusive")

    def test_confirmatory_invalidating_deviation_is_machine_readable(self):
        manifest = _manifest()
        frozen = freeze_manifest(manifest)
        deviation = make_deviation(
            frozen,
            category="analysis",
            phase="after-outcome-access",
            impact="confirmatory-invalidated",
            reason="Synthetic fixture demonstrating explicit invalidation rather than silent reinterpretation.",
        )
        report = analyse_study(
            frozen,
            manifest,
            _dataset(manifest),
            deviations=(deviation,),
        )
        self.assertEqual(report["completion"]["status"], "inconclusive")
        self.assertEqual(report["deviations"][0]["id"], deviation.sha256)

    def test_every_planned_family_accepts_an_endpoint_specific_manifest(self):
        definitions = {
            "reference-ablation": ("sound-quality", "bounded-continuous", 0.0, 100.0),
            "chordness-tuning": ("sonority-fit", "bounded-continuous", 0.0, 100.0),
            "linked-return": ("recognition", "ordinal", 1.0, 7.0),
            "variation-meter-gesture": ("groove", "bounded-continuous", 0.0, 100.0),
            "vocal-participation": ("imitation-success", "binary", None, None),
            "grammar-learning": ("return-choice", "choice", None, None),
        }
        self.assertEqual(set(definitions), set(FAMILIES))
        hashes = set()
        for family, (endpoint, scale, lo, hi) in definitions.items():
            with self.subTest(family=family):
                method = (
                    "paired-cell-randomisation-v1"
                    if scale in ("binary", "choice")
                    else "crossed-row-column-conservative-v1"
                )
                manifest = _manifest(
                    family=family,
                    method=method,
                    endpoint_id=endpoint,
                    scale=scale,
                    minimum=lo,
                    maximum=hi,
                )
                hashes.add(manifest.sha256)
                self.assertEqual(manifest.to_dict()["family"], family)
        self.assertEqual(len(hashes), len(FAMILIES))


class StudyAnalysisTests(unittest.TestCase):
    def test_crossed_analysis_recovers_declared_estimand_and_reports_uncertainty(self):
        manifest = _manifest()
        frozen = freeze_manifest(manifest)
        report = analyse_study(frozen, manifest, _dataset(manifest, effect=5.0))
        row = report["confirmatory"][0]
        self.assertAlmostEqual(row["effect"], 5.0, places=12)
        self.assertLess(row["ci_low"], row["effect"])
        self.assertGreater(row["ci_high"], row["effect"])
        self.assertEqual(row["uncertainty_method"], "row-plus-column-conservative-min-df-v1")
        self.assertEqual(report["completion"]["status"], "complete-difference-detected")

    def test_null_compatible_is_a_valid_completion_not_claimed_equality(self):
        manifest = _manifest()
        frozen = freeze_manifest(manifest)
        report = analyse_study(frozen, manifest, _dataset(manifest, effect=0.0))
        self.assertEqual(report["completion"]["status"], "complete-null-compatible")
        self.assertIn("does not prove equality", report["completion"]["reason"])

    def test_missingness_above_frozen_threshold_is_inconclusive(self):
        manifest = _manifest()
        frozen = freeze_manifest(manifest)
        report = analyse_study(
            frozen,
            manifest,
            _dataset(manifest, effect=5.0, missing_cells=10),
        )
        self.assertEqual(report["confirmatory"][0]["state"], "inconclusive")
        self.assertGreater(report["confirmatory"][0]["missing_fraction"], 0.2)
        self.assertEqual(report["completion"]["status"], "inconclusive")

    def test_holm_multiplicity_is_applied_only_to_frozen_primary_contrasts(self):
        base = _manifest().to_dict()
        second = deepcopy(base["contrasts"][0])
        second["id"] = "second-effect"
        base["contrasts"].append(second)
        base["hypotheses"].append(
            {
                "id": "second-effect",
                "text": "A second frozen primary contrast uses the same synthetic endpoint for multiplicity coverage.",
                "direction": "two-sided",
            }
        )
        manifest = StudyManifest(base)
        frozen = freeze_manifest(manifest)
        report = analyse_study(frozen, manifest, _dataset(manifest, effect=5.0))
        self.assertEqual(len(report["confirmatory"]), 2)
        for row in report["confirmatory"]:
            self.assertIn("p_adjusted", row)
            self.assertGreaterEqual(row["p_adjusted"], row["p_value"])
            self.assertEqual(row["multiplicity"], "holm-primary-v1")

    def test_paired_randomisation_requires_the_frozen_assignment_model(self):
        manifest = _manifest(method="paired-cell-randomisation-v1")
        frozen = freeze_manifest(manifest)
        report = analyse_study(frozen, manifest, _dataset(manifest, effect=3.0))
        row = report["confirmatory"][0]
        self.assertEqual(row["test_method"], "paired-cell-sign-randomisation-v1")
        self.assertLess(row["p_value"], 0.05)


class StudyDesignTests(unittest.TestCase):
    def test_balanced_cyclic_counterbalance_is_deterministic_and_position_balanced(self):
        conditions = ("a", "b", "c", "d")
        rows = balanced_cyclic_orders(conditions, 12, seed="17")
        self.assertEqual(rows, balanced_cyclic_orders(conditions, 12, seed="17"))
        for position in range(4):
            counts = {condition: 0 for condition in conditions}
            for row in rows:
                counts[row["order"][position]] += 1
            self.assertEqual(set(counts.values()), {3})

    def test_simulation_retains_known_bad_listener_only_analysis_as_adversarial_fixture(self):
        report = simulate_crossed_design(
            96,
            4,
            SimulationAssumptions(
                effect=0.0,
                listener_sd=0.35,
                item_sd=0.45,
                residual_sd=1.0,
            ),
            replicates=256,
            seed=23,
        )
        production = report["production_candidate"]["null_rejection"]
        naive = report["adversarial_comparison"]["null_rejection"]
        self.assertLess(production, 0.15)
        self.assertGreater(naive, 0.30)
        self.assertGreater(naive, production + 0.20)
        self.assertEqual(report["assumptions"]["status"], "assumed-not-estimated")

    def test_precision_plan_is_reproducible_and_not_a_sample_size_recommendation(self):
        assumptions = SimulationAssumptions(effect=0.2, missing_fraction=0.05)
        a = plan_precision(
            (24, 48),
            (4, 12),
            assumptions,
            target_half_width=0.5,
            replicates=64,
            seed=91,
        )
        b = plan_precision(
            (24, 48),
            (4, 12),
            assumptions,
            target_half_width=0.5,
            replicates=64,
            seed=91,
        )
        self.assertEqual(a, b)
        self.assertEqual(len(a["rows"]), 4)
        self.assertIn("not a participant-derived sample-size recommendation", a["interpretation"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
