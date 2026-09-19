from __future__ import annotations

from copy import deepcopy
import hashlib
import unittest

from zaaggenz_listening.trial import make_result, make_trial
from zaaggenz_studies import (
    StudyDataset,
    StudyError,
    StudyManifest,
    analyse_study,
    balanced_cyclic_orders,
    freeze_evidence_plan,
    freeze_manifest,
    make_amendment,
    make_deviation,
)
from zaaggenz_studies.corrective import _resampling_plan


def _sha(label):
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _manifest(*, participants=8, method="crossed-row-column-conservative-v1",
              estimand="mean-difference", primary=True, mode="confirmatory"):
    stimuli = []
    for item in range(4):
        for condition in ("control", "variant"):
            stimuli.append({
                "id": _sha(f"stimulus-{item}-{condition}"),
                "raw_pcm_sha256": _sha(f"raw-{item}-{condition}"),
                "playback_sha256": _sha(f"playback-{item}-{condition}"),
                "family": f"item{item}",
                "condition": condition,
            })
    randomisation = (
        "within-cell-pair-v1"
        if method == "paired-cell-randomisation-v1"
        else "balanced-cyclic-v1"
    )
    return StudyManifest({
        "format": "zaaggenz-study-manifest",
        "version": "1.0.0",
        "title": "Synthetic corrective fixture",
        "family": "chordness-tuning",
        "mode": mode,
        "questions": ["Does the variant differ from control?"],
        "hypotheses": [{
            "id": "primary-effect",
            "text": "Variant and control differ.",
            "direction": "two-sided",
        }],
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
        "endpoints": [{
            "id": "sonority-fit",
            "scale": "bounded-continuous",
            "minimum": 0.0,
            "maximum": 100.0,
        }],
        "contrasts": [{
            "id": "primary-effect",
            "endpoint": "sonority-fit",
            "condition_a": "control",
            "condition_b": "variant",
            "estimand": estimand,
            "method": method,
            "primary": primary,
        }],
        "exclusions": [{
            "id": "technical-failure",
            "rule": "Exclude only a pre-outcome playback/capture failure.",
            "timing": "pre-outcome",
        }],
        "missing_data": {
            "strategy": "available-pairs-with-threshold-v1",
            "max_fraction": 0.2,
            "min_complete_pairs": 8,
        },
        "stopping_rule": {
            "kind": "fixed-complete-cases",
            "min_participants": participants,
            "max_participants": participants,
            "target_ci_half_width": None,
            "endpoint": None,
        },
        "analysis": {
            "alpha": 0.05,
            "multiplicity": "holm-primary-v1" if mode == "confirmatory" else "none-exploratory-v1",
            "confirmatory_methods": [method] if primary else [],
        },
        "privacy": {
            "participant_id_policy": "pseudonymous-study-local-v1",
            "notes": "Synthetic corrective test fixture only.",
        },
    })


def _synthetic_document(manifest, *, participants=None, effect=5.0, omit=frozenset()):
    m = manifest.to_dict()
    count = m["stopping_rule"]["max_participants"] if participants is None else participants
    lookup = {(row["family"], row["condition"]): row["id"] for row in m["stimuli"]}
    rows = []
    for participant in range(count):
        for item in range(4):
            if (participant, item) in omit:
                continue
            for condition in ("control", "variant"):
                value = 50.0 + (effect if condition == "variant" else 0.0)
                rows.append({
                    "participant_id": f"p{participant}",
                    "item_id": f"item{item}",
                    "stimulus_id": lookup[(f"item{item}", condition)],
                    "trial_id": _sha(f"synthetic-trial-{participant}-{item}-{condition}"),
                    "result_sha256": _sha(f"synthetic-result-{participant}-{item}-{condition}"),
                    "condition": condition,
                    "endpoint": "sonority-fit",
                    "value": value,
                    "status": "completed",
                    "exclusion_id": None,
                    "familiarity": None,
                })
    return {
        "format": "zaaggenz-study-dataset",
        "version": "1.0.0",
        "manifest_sha256": manifest.sha256,
        "rows": rows,
    }


def _matched(manifest):
    return [{
        "stimulus_id": row["id"],
        "playback_sha256": row["playback_sha256"],
        "gain_db": 0.0,
        "source_rms_dbfs": -24.0,
        "source_sample_peak": 0.5,
        "target_rms_dbfs": -24.0,
        "matched_rms_dbfs": -24.0,
        "matched_sample_peak": 0.5,
        "sample_peak_headroom_db": 6.0,
        "method": "whole-file-rms-common-target-v1",
        "true_peak_measured": False,
    } for row in manifest.to_dict()["stimuli"]]


def _focused_trial(manifest, focus_stimulus, serial):
    matched = _matched(manifest)
    for seed in range(serial * 20, serial * 20 + 200):
        trial = make_trial(
            f"corrective-{serial}", "multi", matched,
            seed=str(seed), endpoints=("sonority_fit",),
        )
        if trial.to_dict()["presentation_order"][0] == focus_stimulus:
            return trial
    raise AssertionError("could not deterministically find focused trial seed")


def _trusted_fixture(manifest):
    frozen = freeze_manifest(manifest)
    m = manifest.to_dict()
    lookup = {(row["family"], row["condition"]): row["id"] for row in m["stimuli"]}
    assignments = []
    trials = []
    results = {}
    serial = 0
    for participant in range(m["stopping_rule"]["max_participants"]):
        for item in range(4):
            for condition in ("control", "variant"):
                stimulus = lookup[(f"item{item}", condition)]
                trial = _focused_trial(manifest, stimulus, serial)
                serial += 1
                trials.append(trial)
                assignments.append({
                    "participant_index": participant,
                    "participant_id": f"p{participant}",
                    "item_id": f"item{item}",
                    "condition": condition,
                    "stimulus_id": stimulus,
                    "trial_id": trial.to_dict()["id"],
                    "endpoint": "sonority-fit",
                    "extraction": "rating",
                })
                rating = 50.0 + (5.0 if condition == "variant" else 0.0)
                result = make_result(trial, ratings={"sonority_fit": rating})
                results[trial.to_dict()["id"]] = {
                    "result": result,
                    "result_sha256": result.sha256,
                }
    plan = freeze_evidence_plan(frozen, assignments, trials)
    return frozen, plan, results


class EvidenceIntegrityTests(unittest.TestCase):
    def test_trusted_dataset_derives_values_and_authenticates_zg015_result_hash(self):
        manifest = _manifest()
        frozen, plan, results = _trusted_fixture(manifest)
        dataset = StudyDataset.from_zg015(manifest, plan, results)
        report = analyse_study(frozen, manifest, dataset)
        self.assertEqual(report["evidence_authority"], "zg015-content-verified")
        self.assertEqual(report["claim_scope"], "zg015-verified-participant-evidence")
        self.assertAlmostEqual(report["confirmatory"][0]["effect"], 5.0)

        tampered = deepcopy(results)
        trial_id = next(iter(tampered))
        old = tampered[trial_id]["result"]
        changed = old.to_dict()
        changed["ratings"]["sonority_fit"] = 99.0
        # Retain the old authenticated hash deliberately: this is the reproduced
        # decorative-hash attack and must now fail before statistics.
        tampered[trial_id] = {
            "result": changed,
            "result_sha256": old.sha256,
        }
        with self.assertRaisesRegex(StudyError, "does not authenticate"):
            StudyDataset.from_zg015(manifest, plan, tampered)

    def test_frozen_item_identity_rejects_relabelling_and_physical_duplication(self):
        manifest = _manifest()
        frozen, plan, _ = _trusted_fixture(manifest)
        plan_doc = plan.to_dict()
        bad = deepcopy(plan_doc["assignments"])
        bad[0]["item_id"] = "invented-item"
        trials = [make_trial(
            row["title"], row["design"], row["matched_stimuli"],
            seed=row["seed"], endpoints=tuple(row["endpoints"]),
            instruction_template=row["instruction_template"],
            comfortable_level_prompt=row["comfortable_level_prompt"],
            rest_prompt_seconds=row["rest_prompt_seconds"],
        ) for row in plan_doc["trials"]]
        with self.assertRaisesRegex(StudyError, "frozen stimulus identity"):
            freeze_evidence_plan(frozen, bad, trials)

        duplicate = manifest.to_dict()
        duplicate["stimuli"][2]["raw_pcm_sha256"] = duplicate["stimuli"][0]["raw_pcm_sha256"]
        relabelled = StudyManifest(duplicate)
        with self.assertRaisesRegex(StudyError, "raw physical stimulus"):
            freeze_manifest(relabelled)


class OwnedIterableTests(unittest.TestCase):
    def test_after_outcome_amendment_generator_is_not_exhausted_before_demotion(self):
        original = _manifest()
        frozen = freeze_manifest(original)
        changed = original.to_dict()
        changed["analysis"]["alpha"] = 0.04
        amended = StudyManifest(changed)
        amendment = make_amendment(
            frozen, original, amended,
            phase="after-outcome-access", reason="adversarial generator fixture",
        )
        dataset = StudyDataset(_synthetic_document(amended), amended)
        report = analyse_study(
            frozen, amended, dataset,
            amendments=(row for row in (amendment,)),
        )
        self.assertEqual(report["confirmatory"], [])
        self.assertEqual(report["amendments"][0]["id"], amendment.sha256)
        self.assertEqual(report["completion"]["status"], "inconclusive")

    def test_deviation_list_tuple_and_generator_have_identical_effect(self):
        manifest = _manifest()
        frozen = freeze_manifest(manifest)
        deviation = make_deviation(
            frozen, category="analysis", phase="after-outcome-access",
            impact="confirmatory-invalidated", reason="same owned record",
        )
        dataset = StudyDataset(_synthetic_document(manifest), manifest)
        forms = [
            [deviation],
            (deviation,),
            (row for row in (deviation,)),
        ]
        reports = [analyse_study(frozen, manifest, dataset, deviations=form) for form in forms]
        self.assertEqual([r["completion"]["status"] for r in reports], ["inconclusive"] * 3)
        self.assertEqual([r["deviations"][0]["id"] for r in reports], [deviation.sha256] * 3)


class PlannedObservationAndMethodTests(unittest.TestCase):
    def test_fixed_100_participant_plan_cannot_complete_with_only_eight(self):
        manifest = _manifest(participants=100)
        frozen = freeze_manifest(manifest)
        dataset = StudyDataset(_synthetic_document(manifest, participants=8), manifest)
        report = analyse_study(frozen, manifest, dataset)
        self.assertEqual(report["completion"]["status"], "inconclusive")
        self.assertIn("requires 100", report["completion"]["reason"])

    def test_omitted_pair_is_counted_missing_instead_of_disappearing(self):
        manifest = _manifest()
        frozen = freeze_manifest(manifest)
        dataset = StudyDataset(
            _synthetic_document(manifest, omit=frozenset({(0, 0)})), manifest
        )
        report = analyse_study(frozen, manifest, dataset)
        row = report["confirmatory"][0]
        self.assertEqual(row["planned_cells"], 32)
        self.assertEqual(row["complete_pairs"], 31)
        self.assertAlmostEqual(row["missing_fraction"], 1 / 32)
        self.assertFalse(report["stopping_rule"]["met"])
        self.assertEqual(report["completion"]["status"], "inconclusive")

    def test_incompatible_estimand_and_descriptive_primary_fail_at_freeze(self):
        median_crossed = _manifest(estimand="median-difference")
        with self.assertRaisesRegex(StudyError, "computes mean-difference only"):
            freeze_manifest(median_crossed)

        descriptive = _manifest(method="descriptive-only-v1")
        with self.assertRaisesRegex(StudyError, "cannot be a confirmatory primary"):
            freeze_manifest(descriptive)


class ResourceEnvelopeTests(unittest.TestCase):
    def test_reproduced_1792_pair_case_is_batched_under_bounded_envelope(self):
        plan = _resampling_plan(1792)
        self.assertLessEqual(plan["randomisation_work_cells"], 8_000_000)
        self.assertLessEqual(plan["bootstrap_work_cells"], 8_000_000)
        self.assertLess(plan["max_batch_bytes_estimate"], 8 * 1024 * 1024)
        self.assertLess(plan["randomisation_draws"], 32768)

    def test_large_counterbalance_fails_before_materialising_million_rows(self):
        with self.assertRaisesRegex(StudyError, "bounded"):
            balanced_cyclic_orders(tuple(f"c{i}" for i in range(16)), 1_000_000, seed="1")

    def test_paired_resampling_exposes_progress_and_cancellation(self):
        manifest = _manifest(participants=8, method="paired-cell-randomisation-v1")
        frozen = freeze_manifest(manifest)
        dataset = StudyDataset(_synthetic_document(manifest), manifest)
        progress = []
        report = analyse_study(
            frozen, manifest, dataset,
            progress=lambda event: progress.append(event),
        )
        self.assertTrue(progress)
        self.assertIn("resampling", report["confirmatory"][0])
        with self.assertRaisesRegex(StudyError, "cancelled"):
            analyse_study(frozen, manifest, dataset, cancel=lambda: True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
