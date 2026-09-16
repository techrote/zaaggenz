from __future__ import annotations

import math
import unittest

from zaaggenz_jobs import JobScheduler, JobState
from zaaggenz_tuning import (
    AdaptiveState,
    AdaptiveTuningRequest,
    AdaptiveVoice,
    AdaptiveWeights,
    ab_recipe,
    candidate_tuning_set,
    commit_proposal,
    harmonic_spectrum,
    propose_adaptive_tuning,
    reject_proposal,
    submit_adaptive_tuning_job,
)


def voice(id, root_hz, nominal, *, role="voice", locked=False, confidence=1.0):
    return AdaptiveVoice(
        id,
        nominal,
        harmonic_spectrum(id + "spec", root_hz, partials=8, confidence=confidence),
        role,
        locked,
    )


def request(
    *,
    desired=0.0,
    second_cents=705.0,
    second_confidence=1.0,
    max_total=30.0,
    max_step=12.0,
    min_sep=20.0,
    pedal=False,
    root_lock=True,
):
    root = voice("root", 220.0, 0.0, role="root")
    second = voice(
        "upper",
        220.0 * 2 ** (second_cents / 1200.0),
        second_cents,
        role="pedal" if pedal else "voice",
        confidence=second_confidence,
    )
    return AdaptiveTuningRequest(
        (root, second),
        (0.0, 498.0, 702.0, 1200.0),
        "root",
        desired_tension=desired,
        root_lock=root_lock,
        max_total_drift_cents=max_total,
        max_step_cents=max_step,
        search_step_cents=1.0,
        min_separation_cents=min_sep,
        weights=AdaptiveWeights(
            tension=12.0,
            voice_leading=0.02,
            drift=0.02,
            candidate_proximity=0.1,
        ),
    )


class AdaptiveTuningTests(unittest.TestCase):
    def _committed_unlocked_root_state(self, *, max_step=5.0):
        # Seed a valid historical unlocked state, then pass it through the real
        # proposal/commit boundary so the lock-transition tests begin from a
        # committed state rather than mutating a proposal in place.
        seed = AdaptiveState((("root", 18.0), ("upper", 0.0)), 3)
        unlocked = propose_adaptive_tuning(
            request(root_lock=False, max_total=30.0, max_step=max_step), seed
        )
        self.assertEqual(unlocked.status, "proposed")
        state = commit_proposal(unlocked)
        self.assertGreater(abs(state.mapping()["root"]), max_step)
        return state

    def test_low_tension_moves_detuned_fifth_toward_candidate_and_locks_root(self):
        proposal = propose_adaptive_tuning(request(desired=0.0))
        self.assertEqual(proposal.status, "proposed")
        offsets = proposal.offset_mapping()
        self.assertEqual(offsets["root"], 0.0)
        self.assertLess(offsets["upper"], 0.0)
        self.assertLess(
            abs((705.0 + offsets["upper"]) - 702.0), abs(705.0 - 702.0)
        )
        self.assertLessEqual(abs(offsets["upper"]), 12.0)
        self.assertTrue(proposal.to_dict()["manual_review_required"])

    def test_unlocked_root_can_move_within_same_hard_bounds(self):
        proposal = propose_adaptive_tuning(request(desired=0.0, root_lock=False))
        self.assertEqual(proposal.status, "proposed")
        offsets = proposal.offset_mapping()
        self.assertNotEqual(offsets["root"], 0.0)
        self.assertLessEqual(abs(offsets["root"]), 12.0)
        adjusted = dict(proposal.adjusted_cents)
        self.assertGreaterEqual(abs(adjusted["upper"] - adjusted["root"]), 20.0 - 1e-9)
        self.assertFalse(proposal.request.root_lock)

    def test_desired_tension_changes_proposal_without_muting_any_voice(self):
        low = propose_adaptive_tuning(request(desired=0.0))
        high = propose_adaptive_tuning(request(desired=0.2))
        self.assertNotEqual(low.offset_mapping()["upper"], high.offset_mapping()["upper"])
        self.assertLessEqual(
            abs(high.objective["predicted_tension"] - 0.2),
            abs(low.objective["predicted_tension"] - 0.2) + 1e-12,
        )
        before = [v.spectrum.amplitudes for v in high.request.voices]
        after = [v.spectrum.amplitudes for v in low.request.voices]
        self.assertEqual(before, after)
        self.assertEqual(
            high.request.to_dict()["amplitude_policy"],
            "immutable; adaptive tuning changes pitch only",
        )

    def test_repeated_manual_commits_cannot_drift_beyond_absolute_bound(self):
        req = request(desired=0.3, max_total=20.0, max_step=5.0)
        state = AdaptiveState()
        for _ in range(20):
            proposal = propose_adaptive_tuning(req, state)
            self.assertEqual(proposal.status, "proposed")
            state = commit_proposal(proposal)
            self.assertTrue(all(abs(v) <= 20.0 + 1e-9 for v in state.mapping().values()))
        self.assertEqual(state.mapping()["root"], 0.0)
        self.assertEqual(state.step_index, 20)

    def test_reject_is_exact_state_noop(self):
        state = AdaptiveState((("upper", -2.0),), 4)
        proposal = propose_adaptive_tuning(request(), state)
        self.assertEqual(reject_proposal(proposal), state)

    def test_low_confidence_source_abstains(self):
        proposal = propose_adaptive_tuning(request(second_confidence=0.2))
        self.assertEqual(proposal.status, "abstained")
        self.assertEqual(proposal.reason, "low-source-confidence")
        self.assertEqual(proposal.offset_mapping()["upper"], 0.0)

    def test_pedal_choice_is_explicitly_locked(self):
        proposal = propose_adaptive_tuning(
            request(pedal=True), AdaptiveState((("upper", 4.0),), 1)
        )
        self.assertEqual(proposal.offset_mapping()["upper"], 4.0)
        self.assertEqual(proposal.request.voices[1].role, "pedal")

    def test_minimum_separation_is_hard_constraint(self):
        req = request(
            second_cents=24.0,
            desired=0.4,
            max_total=10.0,
            max_step=10.0,
            min_sep=20.0,
        )
        proposal = propose_adaptive_tuning(req)
        self.assertEqual(proposal.status, "proposed")
        adjusted = dict(proposal.adjusted_cents)
        self.assertGreaterEqual(abs(adjusted["upper"] - adjusted["root"]), 20.0 - 1e-9)

    def test_ab_export_is_hashable_reproducible_and_manual(self):
        proposal = propose_adaptive_tuning(request())
        a = ab_recipe(proposal)
        b = ab_recipe(proposal)
        self.assertEqual(a, b)
        self.assertEqual(len(a["recipe_sha256"]), 64)
        self.assertTrue(a["controls"]["manual_accept_reject"])
        self.assertTrue(candidate_tuning_set(proposal)["manual_review_required"])

    def test_analysis_job_returns_proposal(self):
        scheduler = JobScheduler()
        try:
            jid = submit_adaptive_tuning_job(scheduler, "d" * 64, request())
            snap = scheduler.wait(jid, timeout=10.0)
            self.assertEqual(snap.state, JobState.COMPLETED.value)
            self.assertEqual(scheduler.result(jid).status, "proposed")
        finally:
            scheduler.shutdown(cancel=True)

    def test_enabling_root_lock_stages_nonzero_committed_root_within_step(self):
        state = self._committed_unlocked_root_state(max_step=5.0)
        prior = state.mapping()["root"]
        proposal = propose_adaptive_tuning(
            request(root_lock=True, max_total=30.0, max_step=5.0), state
        )
        self.assertEqual(proposal.status, "proposed")
        realised = proposal.offset_mapping()["root"]
        self.assertLessEqual(abs(realised - prior), 5.0 + 1e-9)
        self.assertLess(abs(realised), abs(prior))
        expected = prior - math.copysign(min(abs(prior), 5.0), prior)
        if abs(expected) <= 1e-9:
            expected = 0.0
        self.assertAlmostEqual(realised, expected, places=9)
        transition = proposal.search["root_lock_transition"]
        self.assertTrue(transition["active"])
        self.assertEqual(transition["policy"], "staged-zero-convergence-v1")
        self.assertAlmostEqual(transition["previous_offset_cents"], prior)
        self.assertAlmostEqual(transition["realised_offset_cents"], realised)
        self.assertAlmostEqual(transition["remaining_distance_cents"], abs(realised))

    def test_root_lock_exact_step_boundary_reaches_zero(self):
        state = AdaptiveState((("root", -5.0), ("upper", 0.0)), 9)
        proposal = propose_adaptive_tuning(
            request(root_lock=True, max_total=30.0, max_step=5.0), state
        )
        self.assertEqual(proposal.status, "proposed")
        self.assertEqual(proposal.offset_mapping()["root"], 0.0)
        transition = proposal.search["root_lock_transition"]
        self.assertEqual(transition["planned_step_cents"], 5.0)
        self.assertEqual(transition["remaining_distance_cents"], 0.0)
        self.assertTrue(transition["complete"])

    def test_already_zero_root_lock_is_identity_for_root(self):
        state = AdaptiveState((("root", 0.0), ("upper", 0.0)), 2)
        proposal = propose_adaptive_tuning(request(root_lock=True), state)
        self.assertEqual(proposal.status, "proposed")
        self.assertEqual(proposal.offset_mapping()["root"], 0.0)
        transition = proposal.search["root_lock_transition"]
        self.assertFalse(transition["active"])
        self.assertEqual(transition["realised_step_cents"], 0.0)
        self.assertTrue(transition["complete"])

    def test_disabling_root_lock_has_no_hidden_transition(self):
        state = AdaptiveState((("root", 4.0), ("upper", 0.0)), 5)
        proposal = propose_adaptive_tuning(
            request(root_lock=False, max_total=30.0, max_step=5.0), state
        )
        self.assertEqual(proposal.status, "proposed")
        transition = proposal.search["root_lock_transition"]
        self.assertFalse(transition["root_lock_enabled"])
        self.assertFalse(transition["active"])
        self.assertIsNone(transition["staged_target_cents"])
        self.assertEqual(proposal.previous_state, state)
        self.assertLessEqual(
            abs(proposal.offset_mapping()["root"] - state.mapping()["root"]), 5.0 + 1e-9
        )

    def test_repeated_root_lock_commits_converge_without_slew_or_drift_violation(self):
        state = self._committed_unlocked_root_state(max_step=5.0)
        req = request(root_lock=True, max_total=30.0, max_step=5.0)
        prior_abs = abs(state.mapping()["root"])
        for _ in range(8):
            before = state.mapping()["root"]
            proposal = propose_adaptive_tuning(req, state)
            self.assertEqual(proposal.status, "proposed")
            after = proposal.offset_mapping()["root"]
            self.assertLessEqual(abs(after - before), 5.0 + 1e-9)
            self.assertLessEqual(abs(after), abs(before) + 1e-9)
            self.assertTrue(
                all(abs(v) <= req.max_total_drift_cents + 1e-9 for v in proposal.offset_mapping().values())
            )
            state = commit_proposal(proposal)
            if abs(after) <= 1e-9:
                break
        self.assertGreater(prior_abs, 5.0)
        self.assertEqual(state.mapping()["root"], 0.0)
        settled = propose_adaptive_tuning(req, state)
        self.assertEqual(settled.offset_mapping()["root"], 0.0)
        self.assertTrue(settled.search["root_lock_transition"]["complete"])

    def test_root_transition_does_not_move_pedal(self):
        state = AdaptiveState((("root", 18.0), ("upper", 4.0)), 4)
        proposal = propose_adaptive_tuning(
            request(root_lock=True, pedal=True, max_total=30.0, max_step=5.0), state
        )
        self.assertEqual(proposal.status, "proposed")
        self.assertEqual(proposal.offset_mapping()["upper"], 4.0)
        self.assertEqual(proposal.offset_mapping()["root"], 13.0)

    def test_low_confidence_root_transition_abstains_without_state_mutation(self):
        state = AdaptiveState((("root", 18.0), ("upper", 4.0)), 6)
        proposal = propose_adaptive_tuning(
            request(
                root_lock=True,
                second_confidence=0.2,
                max_total=30.0,
                max_step=5.0,
            ),
            state,
        )
        self.assertEqual(proposal.status, "abstained")
        self.assertEqual(proposal.reason, "low-source-confidence")
        self.assertEqual(proposal.offset_mapping(), state.mapping())
        transition = proposal.search["root_lock_transition"]
        self.assertTrue(transition["active"])
        self.assertEqual(transition["realised_step_cents"], 0.0)
        self.assertEqual(transition["blocked_reason"], "low-source-confidence")

    def test_zero_step_root_transition_fails_explicitly_without_teleport(self):
        root = voice("root", 220.0, 0.0, role="root")
        upper = voice("upper", 330.0, 702.0)
        req = AdaptiveTuningRequest(
            (root, upper),
            (0.0, 498.0, 702.0, 1200.0),
            "root",
            root_lock=True,
            max_total_drift_cents=30.0,
            max_step_cents=0.0,
            search_step_cents=0.1,
        )
        state = AdaptiveState((("root", 5.0), ("upper", 0.0)), 2)
        proposal = propose_adaptive_tuning(req, state)
        self.assertEqual(proposal.status, "abstained")
        self.assertEqual(proposal.reason, "root-lock-transition-zero-step")
        self.assertEqual(proposal.offset_mapping(), state.mapping())
        transition = proposal.search["root_lock_transition"]
        self.assertEqual(transition["blocked_reason"], "zero-step-budget")
        self.assertEqual(transition["remaining_distance_cents"], 5.0)

    def test_candidate_and_ab_exports_report_realised_root_transition(self):
        state = AdaptiveState((("root", 18.0), ("upper", 0.0)), 8)
        proposal = propose_adaptive_tuning(
            request(root_lock=True, max_total=30.0, max_step=5.0), state
        )
        self.assertEqual(proposal.status, "proposed")
        candidate = candidate_tuning_set(proposal)
        recipe_a = ab_recipe(proposal)
        recipe_b = ab_recipe(proposal)
        self.assertEqual(recipe_a, recipe_b)
        transition = candidate["root_lock_transition"]
        self.assertEqual(transition, recipe_a["root_lock_transition"])
        self.assertEqual(transition, recipe_a["candidate"]["root_lock_transition"])
        self.assertEqual(transition["previous_offset_cents"], 18.0)
        self.assertEqual(transition["realised_offset_cents"], 13.0)
        baseline_root = next(v for v in recipe_a["baseline"]["voices"] if v["id"] == "root")
        candidate_root = next(v for v in candidate["voices"] if v["id"] == "root")
        self.assertEqual(baseline_root["offset_cents"], 18.0)
        self.assertEqual(candidate_root["offset_cents"], 13.0)
        self.assertTrue(candidate_root["lock_transition_active"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
