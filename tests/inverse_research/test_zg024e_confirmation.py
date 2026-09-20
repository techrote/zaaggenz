import json
import unittest
from pathlib import Path

from research.zg024d.confirmation import CONFIRMATION_NAMES as ZG024D_CONFIRMATION_NAMES
from research.zg024e import DEVELOPMENT_NAMES, SEARCH_SEEDS
from research.zg024e.confirmation import (
    CONFIRMATION_NAMES,
    DESIGN_FREEZE_COMMIT,
    MATCHED_NULL_METHOD,
    SELECTED_METHOD,
    SELECTION_DECISION_SHA256,
    SELECTION_FREEZE_COMMIT,
    confirmation_fixture,
)
from tools.inverse_feasibility_confirmation import _confirmation_portable_row

ROOT = Path(__file__).resolve().parents[2]


class ZG024eConfirmationFreezeTests(unittest.TestCase):
    def test_confirmation_is_distinct_and_post_selection_frozen(self):
        self.assertEqual(
            "a7156aa6cb148582a943b8c0f211e5f603b1670b",
            DESIGN_FREEZE_COMMIT,
        )
        self.assertEqual(
            "3364e563aa8094bc39655570d7197542fba2e6b5",
            SELECTION_FREEZE_COMMIT,
        )
        self.assertEqual(
            "d673e22602aee773005e242910a0a54b60f2e9cedfff26c5d6898b3cf3ba6629",
            SELECTION_DECISION_SHA256,
        )
        self.assertTrue(set(CONFIRMATION_NAMES).isdisjoint(DEVELOPMENT_NAMES))
        self.assertTrue(set(CONFIRMATION_NAMES).isdisjoint(ZG024D_CONFIRMATION_NAMES))

    def test_committed_selection_exactly_binds_confirmation_methods(self):
        value = json.loads(
            (ROOT / "examples" / "zg024e-development-selection.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(SELECTION_DECISION_SHA256, value["selection_decision_sha256"])
        self.assertEqual(SELECTED_METHOD, value["selected_intervention_method"])
        self.assertEqual(MATCHED_NULL_METHOD, value["selected_matched_null_method"])
        self.assertEqual("cross-family-coupling", value["primary_diagnosis"])
        self.assertEqual(list(SEARCH_SEEDS), value["search_seeds"])

    def test_confirmation_budget_variants_share_target_but_not_request_budget(self):
        for name in CONFIRMATION_NAMES:
            with self.subTest(name=name):
                small = confirmation_fixture(name, seed=SEARCH_SEEDS[0], budget_evaluations=24)
                large = confirmation_fixture(name, seed=SEARCH_SEEDS[0], budget_evaluations=36)
                self.assertEqual(small.target.tobytes(), large.target.tobytes())
                self.assertEqual(24, small.budget.max_evaluations)
                self.assertEqual(36, large.budget.max_evaluations)
                self.assertEqual(small.plan.to_dict(), large.plan.to_dict())
                self.assertEqual(small.objective.to_dict(), large.objective.to_dict())

    def test_portable_projection_keeps_exact_pcm_equivalence_platform_local(self):
        row = {
            "fixture": "portable-test",
            "seed": "53",
            "family": "diagnostic",
            "method_id": SELECTED_METHOD,
            "method_key": SELECTED_METHOD + "@36",
            "declared_budget": 36,
            "consumed_evaluations": 36,
            "eligible_candidates": 2,
            "final_available": True,
            "best_fit_score": 0.25,
            "best_holdout_score": 0.30,
            "parameter_error": 0.1,
            "stage_consumption": {"AB": 24, "C": 12},
            "promotion_stages": [{
                "stage": "C-final",
                "eligible_count": 2,
                "pareto_count": 2,
                "retained_count": 2,
                "retained_cap": 4,
                "equivalence_group_sizes": [2],
            }],
            "final_retained_count": 2,
            "pareto_count": 2,
            "promotion_ineligible_violations": 0,
            "gate_rejections": {},
            "stop_reason": None,
            "physical_render_calls": 72,
            "render_cache_hits": 0,
        }
        portable = _confirmation_portable_row(row)
        self.assertEqual(
            "full-evidence-only-environment-exact",
            portable["exact_output_equivalence"],
        )
        self.assertNotIn(
            "equivalence_group_sizes",
            portable["promotion_stages"][0],
        )
        self.assertEqual(2, portable["promotion_stages"][0]["retained_count"])

    def test_unknown_fixture_seed_and_budget_fail_closed(self):
        with self.assertRaises(ValueError):
            confirmation_fixture("not-a-confirmation")
        with self.assertRaises(ValueError):
            confirmation_fixture(CONFIRMATION_NAMES[0], seed="999")
        with self.assertRaises(ValueError):
            confirmation_fixture(CONFIRMATION_NAMES[0], budget_evaluations=25)


if __name__ == "__main__":
    unittest.main()
