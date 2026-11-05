"""Deterministic source-race, dispatch-count and qualification tests."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from urllib.parse import parse_qs

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from zg000_reconcile import Reconciler, ReconcileError, Superseded  # noqa: E402

A, B, C = "a"*40, "b"*40, "c"*40
REPO = "techrote/zaaggenz"
REF = "nyq-004/rate-controls-253"
R1 = {"workflow":"zg008-melody.yml","stable_id":"ZG-008"}
R2 = {"workflow":"zg009-timeline.yml","stable_id":"ZG-009"}


class FakeAPI:
    def __init__(self, sha=A, pr=267, ref=REF):
        self.sha, self.pr, self.ref = sha, pr, ref
        self.repo = REPO
        self.calls, self.posts, self.runs = [], [], {}
        self.next_id, self.on_call = 1000, None
        self.wrong_sha, self.no_id, self.post_error = None, False, False
        self.delayed, self.fail_get, self.total_count = 0, False, None
        self.list_limit, self.omit_total_count = None, False
        self.invalid_inventory_row = False
        self.boolean_run_id = False

    def put(self, workflow=R1["workflow"], sha=None, status="completed",
            conclusion="success", attempt=1, run_id=None, ref=None, event="workflow_dispatch"):
        run_id = run_id or self.next_id
        self.next_id = max(run_id + 1, self.next_id)
        run = dict(id=run_id, workflow_id=42, path=".github/workflows/" + workflow,
                   head_sha=sha or self.sha, head_branch=ref or self.ref, event=event,
                   status=status, conclusion=conclusion, run_attempt=attempt)
        self.runs[run_id] = run
        return run

    def request(self, method, path, payload=None):
        self.calls.append((method,path,payload))
        if self.on_call:
            self.on_call(method,path,payload)
        if method == "GET" and self.fail_get:
            raise ReconcileError("HTTP 429 or stale API")
        if path.endswith(f"pulls/{self.pr}"):
            return {"state":"open","head":{"sha":self.sha,"ref":self.ref,
                                              "repo":{"full_name":self.repo}}}
        if path.endswith("/dispatches"):
            if payload != {"ref": self.ref}:
                raise ReconcileError("2026-03-10 workflow dispatch request contains unsupported fields")
            self.posts.append(payload)
            if self.post_error:
                if self.post_error in ("after", "multiple", "wrong_source"):
                    workflow = path.split("/actions/workflows/")[1].split("/")[0]
                    self.put(workflow, sha=B if self.post_error == "wrong_source" else self.sha,
                             status="queued", conclusion=None)
                    if self.post_error == "multiple":
                        self.put(workflow, status="queued", conclusion=None)
                raise ReconcileError("POST timed out; ambiguous mutation")
            if self.no_id:
                return {}
            if self.boolean_run_id:
                return {"workflow_run_id": True}
            workflow = path.split("/actions/workflows/")[1].split("/")[0]
            run = self.put(workflow, sha=self.wrong_sha or self.sha, status="queued", conclusion=None)
            return {"workflow_run_id":run["id"]}
        if "/runs?" in path:
            wf, query = path.split("/actions/workflows/")[1].split("/runs?")
            params = parse_qs(query)
            runs = [x for x in self.runs.values() if x["path"] == ".github/workflows/"+wf
                    and x["event"] == params["event"][0] and x["head_sha"] == params["head_sha"][0]]
            total = self.total_count if self.total_count is not None else len(runs)
            visible = runs[:self.list_limit] if self.list_limit is not None else runs
            if self.invalid_inventory_row and visible:
                visible = [None, *visible[1:]]
            return ({"workflow_runs":visible} if self.omit_total_count else
                    {"workflow_runs":visible, "total_count":total})
        if "/actions/workflows/" in path:
            wf = path.split("/actions/workflows/")[1]
            return {"id":42, "path":".github/workflows/"+wf,"state":"active"}
        if "/actions/runs/" in path:
            if self.delayed:
                self.delayed -= 1
                raise ReconcileError("eventually consistent")
            return dict(self.runs[int(path.rsplit("/",1)[1])])
        raise AssertionError((method,path))


def make(api, sha=A, rows=None, pr=267, ref=REF):
    return Reconciler(api, REPO, pr, sha, ref, rows or [R1], 41691032400, sleep=lambda _:None)


class ZG000RegressionTests(unittest.TestCase):
    def test_01_rapid_three_head_commits_only_latest_dispatches(self):
        for old in (A,B):
            api = FakeAPI(C)
            with self.assertRaises(Superseded): make(api,old).dispatch()
            self.assertEqual(0,len(api.posts))
        api = FakeAPI(C)
        self.assertEqual(C,make(api,C).dispatch()[0]["sha"])
        self.assertEqual(1,len(api.posts))

    def test_02_multiple_generations_cannot_reuse_older_sha(self):
        api = FakeAPI(B); api.put(sha=A)
        make(api,B).dispatch()
        self.assertEqual(1,len(api.posts))

    def test_03_superseded_before_dispatch_never_posts(self):
        api = FakeAPI(B)
        with self.assertRaises(Superseded): make(api).dispatch()
        self.assertFalse(api.posts)

    def test_04_superseded_mid_serial_dispatch(self):
        api = FakeAPI()
        def mutate(method,path,payload):
            if len(api.posts)==1 and path.endswith("pulls/267"): api.sha=B
        api.on_call=mutate
        with self.assertRaises(Superseded): make(api,rows=[R1,R2]).dispatch()
        self.assertEqual(1,len(api.posts))

    def test_05_movement_during_post(self):
        api = FakeAPI()
        api.on_call=lambda m,p,body: setattr(api,"sha",B) if m=="POST" else None
        with self.assertRaises(Superseded): make(api).dispatch()
        self.assertEqual(1,len(api.posts))

    def test_06_real_nyq004_race_fixture(self):
        old="be50352426fea81d123811bce4ebbf4ffa824e8a"
        new="b38d8c9d10186f61647e02246ded401a52d271a9"
        api=FakeAPI(old)
        api.on_call=lambda m,p,body: setattr(api,"sha",new) if m=="POST" else None
        rec=make(api,old)
        with self.assertRaises(Superseded): rec.dispatch()
        self.assertEqual(new,api.runs[1000]["head_sha"])
        self.assertEqual(old,rec.manifest["requested_sha"])
        self.assertEqual(new,rec.manifest["current_pr_sha"])

    def test_07_mismatched_actual_child_sha_is_rejected(self):
        api=FakeAPI(); api.wrong_sha=B; rec=make(api)
        with self.assertRaises(ReconcileError): rec.dispatch()
        self.assertEqual(B,rec.manifest["rejected"][0]["actual_sha"])

    def test_08_existing_success_exact_head_reused(self):
        api=FakeAPI(); original=api.put()
        rec=make(api); selected=rec.dispatch()
        self.assertEqual(original["id"],selected[0]["run_id"])
        self.assertEqual(1,rec.manifest["avoided_dispatches"])
        self.assertFalse(api.posts)

    def test_09_existing_queued_or_running_watched(self):
        for state in ("queued","in_progress"):
            api=FakeAPI(); api.put(status=state,conclusion=None)
            self.assertEqual("reuse_active",make(api).dispatch()[0]["decision"])
            self.assertFalse(api.posts)

    def test_10_existing_failure_requires_explicit_repair(self):
        api=FakeAPI(); api.put(conclusion="failure")
        with self.assertRaises(ReconcileError): make(api).dispatch()
        self.assertFalse(api.posts)

    def test_11_new_red_run_takes_precedence_over_old_green(self):
        api=FakeAPI(); api.put(run_id=90); api.put(run_id=91,conclusion="failure")
        with self.assertRaises(ReconcileError): make(api).dispatch()
        self.assertFalse(api.posts)

    def test_12_second_same_head_generation_reuses_first(self):
        api=FakeAPI(); make(api).dispatch(); make(api).dispatch()
        self.assertEqual(1,len(api.posts))

    def test_13_dispatched_without_run_id_not_retried(self):
        api=FakeAPI(); api.no_id=True
        with self.assertRaises(ReconcileError): make(api).dispatch()
        self.assertEqual(1,len(api.posts))

    def test_14_ambiguous_post_failure_not_retried(self):
        api=FakeAPI(); api.post_error=True
        with self.assertRaises(ReconcileError): make(api).dispatch()
        self.assertEqual(1,len(api.posts))

    def test_15_rate_limit_or_bad_api_blocks_before_post(self):
        api=FakeAPI(); api.fail_get=True
        with self.assertRaises(ReconcileError): make(api).dispatch()
        self.assertFalse(api.posts)

    def test_16_bounded_eventual_consistency_lookup(self):
        api=FakeAPI(); api.delayed=2
        self.assertEqual(1,len(make(api).dispatch()))
        self.assertEqual(1,len(api.posts))
        api2=FakeAPI(); api2.delayed=100
        with self.assertRaises(ReconcileError): make(api2).dispatch()
        self.assertEqual(1,len(api2.posts))

    def test_17_attempt_changed_after_reuse_cannot_qualify(self):
        api=FakeAPI(); run=api.put(); rec=make(api); selected=rec.dispatch()[0]
        run["run_attempt"]=2
        with self.assertRaises(ReconcileError): rec.verify_selected(selected,True)

    def test_18_distinct_pr_branches_remain_independent(self):
        api1=FakeAPI(pr=266,ref="nyq-003/nonuniform-reconstruction-252")
        api2=FakeAPI(pr=267,ref=REF)
        make(api1,pr=266,ref=api1.ref).dispatch()
        make(api2).dispatch()
        self.assertEqual(1,len(api1.posts))
        self.assertEqual(1,len(api2.posts))

    def test_19_manual_same_branch_exact_head_can_be_reused(self):
        api=FakeAPI(); api.put(event="workflow_dispatch")
        self.assertEqual("reuse_success",make(api).dispatch()[0]["decision"])
        self.assertFalse(api.posts)

    def test_20_fork_source_denied(self):
        api=FakeAPI(); api.repo="untrusted/zaaggenz"
        with self.assertRaises(Superseded): make(api).dispatch()
        self.assertFalse(api.posts)

    def test_21_superseded_children_not_cancelled(self):
        api=FakeAPI()
        api.on_call=lambda m,p,b: setattr(api,"sha",B) if m=="POST" else None
        with self.assertRaises(Superseded): make(api).dispatch()
        self.assertEqual(1,len(api.posts))
        self.assertFalse(any("cancel" in path for _,path,_ in api.calls))

    def test_22_cancelled_child_not_accepted(self):
        api=FakeAPI(); api.put(conclusion="cancelled")
        self.assertEqual("dispatched",make(api).dispatch()[0]["decision"])
        self.assertEqual(1,len(api.posts))

    def test_23_pending_missing_or_failed_cannot_be_final(self):
        api=FakeAPI(); rec=make(api); selected=rec.dispatch()[0]
        with self.assertRaises(ReconcileError): rec.finalize("success")
        api.runs[selected["run_id"]].update(status="completed",conclusion="success")
        with self.assertRaises(ReconcileError): rec.finalize("failure")
        rec.manifest["runs"]=[]
        with self.assertRaises(ReconcileError): rec.finalize("success")

    def test_24_qualified_only_exact_current_head(self):
        api=FakeAPI(); rec=make(api); selected=rec.dispatch()[0]
        api.runs[selected["run_id"]].update(status="completed",conclusion="success")
        rec.finalize("success")
        self.assertEqual("qualified",rec.manifest["state"])
        api.sha=B
        with self.assertRaises(Superseded): rec.finalize("success")

    def test_25_excess_inventory_fails_closed(self):
        api=FakeAPI(); api.total_count=101
        with self.assertRaises(ReconcileError): make(api).dispatch()
        self.assertFalse(api.posts)

    def test_26_unrelated_workflow_definition_not_accepted(self):
        api=FakeAPI(); run=api.put()
        run["workflow_id"]=999
        with self.assertRaises(ReconcileError): make(api).dispatch()
        self.assertFalse(api.posts)

    def test_27_no_dispatch_event_path_is_reused(self):
        api=FakeAPI(); api.put(event="pull_request")
        self.assertEqual("dispatched",make(api).dispatch()[0]["decision"])

    def test_28_final_attempt_changed_is_rejected(self):
        api=FakeAPI(); rec=make(api); selected=rec.dispatch()[0]
        api.runs[selected["run_id"]].update(status="completed",conclusion="success",run_attempt=3)
        with self.assertRaises(ReconcileError): rec.finalize("success")

    def test_29_current_api_dispatch_returns_run_id_without_removed_parameter(self):
        api = FakeAPI()
        selected = make(api).dispatch()
        self.assertEqual([{"ref": REF}], api.posts)
        self.assertEqual(1000, selected[0]["run_id"])
        self.assertEqual("dispatched", selected[0]["decision"])

    def test_30_ambiguous_post_with_unique_new_run_is_reconciled_without_retry(self):
        api = FakeAPI(); api.post_error = "after"
        rec = make(api); selected = rec.dispatch()
        self.assertEqual(1, len(api.posts))
        self.assertEqual("reconciled_ambiguous_post", selected[0]["decision"])
        self.assertEqual(1000, selected[0]["run_id"])
        self.assertEqual(1, rec.manifest["reconciled"])
        self.assertEqual(0, rec.manifest["dispatched"])
        self.assertIn("ambiguous_post_reconciled",
                      [row["decision"] for row in rec.manifest["decisions"]])
        api.runs[1000].update(status="completed", conclusion="success")
        rec.finalize("success")
        self.assertEqual("qualified", rec.manifest["state"])

    def test_31_ambiguous_post_without_evidence_remains_blocked(self):
        api = FakeAPI(); api.post_error = True
        rec = make(api)
        with self.assertRaisesRegex(ReconcileError, "no mutation retried"):
            rec.dispatch()
        self.assertEqual(1, len(api.posts))
        self.assertEqual(0, rec.manifest["reconciled"])

    def test_32_ambiguous_post_multiple_new_runs_fail_closed(self):
        api = FakeAPI(); api.post_error = "multiple"
        with self.assertRaisesRegex(ReconcileError, "multiple new runs"):
            make(api).dispatch()
        self.assertEqual(1, len(api.posts))

    def test_33_ambiguous_post_wrong_source_cannot_qualify(self):
        api = FakeAPI(); api.post_error = "wrong_source"
        with self.assertRaises(ReconcileError):
            make(api).dispatch()
        self.assertEqual(1, len(api.posts))
        self.assertEqual(B, api.runs[1000]["head_sha"])

    def test_34_ambiguous_post_does_not_adopt_prior_cancelled_run(self):
        api = FakeAPI(); old = api.put(conclusion="cancelled")
        api.post_error = True
        with self.assertRaises(ReconcileError):
            make(api).dispatch()
        self.assertEqual(1, len(api.posts))
        self.assertEqual(old["id"], 1000)

    def test_35_ambiguous_post_recovery_requires_authoritative_run_detail(self):
        api = FakeAPI(); api.post_error = "after"; api.delayed = 100
        with self.assertRaises(ReconcileError):
            make(api).dispatch()
        self.assertEqual(1, len(api.posts))

    def test_36_initial_truncated_inventory_must_not_dispatch(self):
        api = FakeAPI()
        api.put(status="queued", conclusion=None)
        api.list_limit = 0  # API reports one existing run but returns none.
        with self.assertRaisesRegex(ReconcileError, "incomplete or uncounted pre-dispatch"):
            make(api).dispatch()
        self.assertFalse(api.posts)

    def test_37_initial_missing_count_must_not_dispatch(self):
        api = FakeAPI()
        api.omit_total_count = True
        with self.assertRaisesRegex(ReconcileError, "incomplete or uncounted pre-dispatch"):
            make(api).dispatch()
        self.assertFalse(api.posts)

    def test_38_ambiguous_post_truncated_inventory_cannot_adopt_partial_evidence(self):
        api = FakeAPI()
        api.post_error = "multiple"
        api.list_limit = 1  # Complete pre-POST empty; post-POST omits second run.
        with self.assertRaisesRegex(ReconcileError, "incomplete or uncounted post-dispatch"):
            make(api).dispatch()
        self.assertEqual(1, len(api.posts))

    def test_39_ambiguous_post_missing_count_cannot_be_reconciled(self):
        api = FakeAPI()
        api.post_error = "after"
        api.on_call = lambda method, path, payload: (
            setattr(api, "omit_total_count", True)
            if method == "POST" else None
        )
        with self.assertRaisesRegex(ReconcileError, "malformed post-dispatch inventory"):
            make(api).dispatch()
        self.assertEqual(1, len(api.posts))
    def test_40_invalid_pre_dispatch_row_is_recorded_blocker_not_crash(self):
        api = FakeAPI()
        api.put(status="queued", conclusion=None)
        api.invalid_inventory_row = True
        rec = make(api)
        with self.assertRaisesRegex(ReconcileError, "invalid pre-dispatch run inventory") as caught:
            rec.dispatch()
        rec.record_error(caught.exception)
        self.assertEqual("blocked", rec.manifest["state"])
        self.assertFalse(api.posts)

    def test_41_invalid_post_dispatch_row_never_triggers_second_post(self):
        api = FakeAPI()
        api.post_error = "after"
        api.on_call = lambda method, path, payload: (
            setattr(api, "invalid_inventory_row", True)
            if method == "POST" else None
        )
        with self.assertRaisesRegex(ReconcileError, "invalid post-dispatch run inventory"):
            make(api).dispatch()
        self.assertEqual(1, len(api.posts))


    def test_42_second_new_run_visible_on_confirmation_must_block(self):
        api = FakeAPI()
        api.post_error = "after"
        observations = [0]

        def add_late_run(method, path, payload):
            if method == "GET" and "/runs?" in path and api.posts:
                observations[0] += 1
                if observations[0] == 2:
                    api.put(status="queued", conclusion=None)

        api.on_call = add_late_run
        with self.assertRaisesRegex(ReconcileError, "multiple new runs"):
            make(api).dispatch()
        self.assertEqual(2, observations[0])
        self.assertEqual(1, len(api.posts))

    def test_43_candidate_only_visible_at_last_poll_must_block(self):
        api = FakeAPI()
        api.post_error = True
        observations = [0]

        def add_at_final_poll(method, path, payload):
            if method == "GET" and "/runs?" in path and api.posts:
                observations[0] += 1
                if observations[0] == 5:
                    api.put(status="queued", conclusion=None)

        api.on_call = add_at_final_poll
        with self.assertRaisesRegex(ReconcileError, "not reconciled"):
            make(api).dispatch()
        self.assertEqual(5, observations[0])
        self.assertEqual(1, len(api.posts))

    def test_44_second_inventory_becomes_partial_must_block(self):
        api = FakeAPI()
        api.post_error = "after"
        observations = [0]

        def truncate_second_poll(method, path, payload):
            if method == "GET" and "/runs?" in path and api.posts:
                observations[0] += 1
                if observations[0] == 2:
                    api.list_limit = 0

        api.on_call = truncate_second_poll
        with self.assertRaisesRegex(ReconcileError, "incomplete or uncounted post-dispatch"):
            make(api).dispatch()
        self.assertEqual(1, len(api.posts))

    def test_45_boolean_dispatch_id_cannot_pass_positive_integer_check(self):
        api = FakeAPI()
        api.boolean_run_id = True
        with self.assertRaisesRegex(ReconcileError, "no authoritative run ID"):
            make(api).dispatch()
        self.assertEqual(1, len(api.posts))

    def test_46_boolean_run_attempt_cannot_qualify(self):
        api = FakeAPI()
        api.put(attempt=True)
        with self.assertRaisesRegex(ReconcileError, "missing run ID/attempt"):
            make(api).dispatch()
        self.assertFalse(api.posts)


if __name__ == "__main__":
    unittest.main()
