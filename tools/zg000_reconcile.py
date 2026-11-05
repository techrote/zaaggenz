#!/usr/bin/env python3
"""Fail-closed, exact-head ZG-000 downstream reconciliation."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode

SHA = re.compile(r"^[0-9a-f]{40}$")
WORKFLOW = re.compile(r"^zg[0-9]{3}[a-z]?(?:-[a-z0-9-]+)?\.yml$")
TERMINAL = {"completed"}
ACTIVE = {"requested", "waiting", "pending", "queued", "in_progress"}


class ReconcileError(RuntimeError):
    """Blocked qualification; fail closed."""


class Superseded(ReconcileError):
    """PR head replaced or source identity changed."""


class QualificationFailed(ReconcileError):
    """A required downstream test failed at this exact head."""


class ExecutionCancelled(ReconcileError):
    """An indispensable watcher was intentionally cancelled."""


class QualificationPending(ReconcileError):
    """A required exact-head test has not completed."""


class GitHubAPI:
    """Injectable CLI API. Bounded GET retries; never retry ambiguous POST."""

    def __init__(self, sleep: Callable[[float], None] = time.sleep):
        self.sleep = sleep

    def request(self, method: str, path: str, payload: dict | None = None) -> dict:
        args = ["gh", "api", "--method", method,
                "-H", "Accept: application/vnd.github+json",
                "-H", "X-GitHub-Api-Version: 2026-03-10", path]
        if payload is not None:
            args.extend(["--input", "-"])
        delays = (0, 1, 3) if method == "GET" else (0,)
        for index, delay in enumerate(delays):
            if delay:
                self.sleep(delay)
            try:
                cp = subprocess.run(args, input=json.dumps(payload) if payload is not None else None,
                                    capture_output=True, text=True, timeout=45, check=False)
            except (OSError, subprocess.TimeoutExpired) as exc:
                if index + 1 < len(delays):
                    continue
                raise ReconcileError(f"{method} {path}: transport failure (outcome unknown): {exc}") from exc
            if cp.returncode == 0:
                try:
                    response = json.loads(cp.stdout) if cp.stdout.strip() else {}
                    if not isinstance(response, dict):
                        raise ValueError("expected JSON object")
                    return response
                except ValueError as exc:
                    raise ReconcileError(f"{method} {path}: unparseable response") from exc
            if index + 1 >= len(delays):
                raise ReconcileError(f"{method} {path}: API failure (no mutation retried): "
                                     + cp.stderr.strip()[:700])
        raise AssertionError("unreachable")


class Reconciler:
    def __init__(self, api: Any, repo: str, pr: int, sha: str, ref: str,
                 rows: list[dict], run_id: int, sleep: Callable[[float], None] = time.sleep):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
            raise ValueError("invalid repository")
        if pr < 1 or not SHA.fullmatch(sha) or not ref or ref.startswith("refs/"):
            raise ValueError("invalid PR, exact SHA, or source branch")
        if not isinstance(rows, list) or any(
            not isinstance(x, dict) or not isinstance(x.get("workflow"), str)
            or not WORKFLOW.fullmatch(x["workflow"])
            or not re.fullmatch(r"ZG-[0-9]{3}[a-z]?", x.get("stable_id", ""))
            for x in rows
        ):
            raise ValueError("invalid selected workflow matrix")
        names = [x["workflow"] for x in rows]
        if len(set(names)) != len(names):
            raise ValueError("duplicate workflow in selection")
        self.api, self.repo, self.pr, self.sha, self.ref = api, repo, pr, sha, ref
        self.rows, self.run_id, self.sleep = rows, run_id, sleep
        self.workflow_ids: dict[str, int] = {}
        # Inventory IDs before every POST, including cancelled runs. A run seen
        # before an ambiguous POST cannot be presented as its new evidence.
        self.prior_run_ids: dict[str, set[int]] = {}
        self.reconciled_workflows: set[str] = set()
        self.manifest: dict[str, Any] = {
            "schema": "zg000-dispatch-v1", "repo": repo, "pr": pr,
            "requested_sha": sha, "current_pr_sha": None, "source_ref": ref,
            "orchestrator_run_id": run_id, "selected": rows,
            "runs": [], "rejected": [], "decisions": [], "state": "pending",
            "reused": 0, "dispatched": 0, "reconciled": 0, "avoided_dispatches": 0,
            "policy": "no child cancellation; no ambiguous dispatch retry",
        }

    def api_path(self, suffix: str) -> str:
        return f"repos/{self.repo}/{suffix}"

    def check_head(self) -> str:
        data = self.api.request("GET", self.api_path(f"pulls/{self.pr}"))
        current = data.get("head", {}) or {}
        actual = current.get("sha")
        self.manifest["current_pr_sha"] = actual
        if (data.get("state") != "open" or current.get("ref") != self.ref
                or (current.get("repo") or {}).get("full_name") != self.repo):
            raise Superseded(f"PR #{self.pr} is closed or its source identity changed")
        if actual != self.sha:
            raise Superseded(f"PR #{self.pr} moved from {self.sha} to {actual}")
        return actual

    def workflow_id(self, workflow: str) -> int:
        if workflow not in self.workflow_ids:
            data = self.api.request("GET", self.api_path(f"actions/workflows/{workflow}"))
            if (data.get("path") != f".github/workflows/{workflow}"
                    or data.get("state") != "active" or not isinstance(data.get("id"), int)):
                raise ReconcileError(f"unaccepted or inactive workflow definition: {workflow}")
            self.workflow_ids[workflow] = data["id"]
        return self.workflow_ids[workflow]

    def verify(self, row: dict, run: dict, *, require_completed: bool = False) -> None:
        workflow = row["workflow"]
        expected_id = self.workflow_id(workflow)
        expected_path = f".github/workflows/{workflow}"
        expected = {
            "workflow_id": expected_id, "path": expected_path,
            "event": "workflow_dispatch", "head_sha": self.sha,
            "head_branch": self.ref,
        }
        for key, value in expected.items():
            if run.get(key) != value:
                raise ReconcileError(f"{workflow} run {run.get('id')}: {key}="
                                     f"{run.get(key)!r}, required {value!r}")
        if (type(run.get("id")) is not int or run["id"] < 1
                or type(run.get("run_attempt")) is not int or run["run_attempt"] < 1):
            raise ReconcileError(f"{workflow}: missing run ID/attempt")
        status = run.get("status")
        if status not in TERMINAL | ACTIVE:
            raise ReconcileError(f"{workflow}: unknown run status {status!r}")
        if require_completed and not (status == "completed" and run.get("conclusion") == "success"):
            reason = f"{workflow}: required run {run['id']} is {status}/{run.get('conclusion')}"
            if status in ACTIVE:
                raise QualificationPending(reason)
            if run.get("conclusion") == "cancelled":
                raise ExecutionCancelled(reason)
            if run.get("conclusion") in ("failure", "timed_out", "action_required"):
                raise QualificationFailed(reason)
            raise ReconcileError(reason)

    def get_run(self, run_id: int) -> dict:
        data = self.api.request("GET", self.api_path(f"actions/runs/{run_id}"))
        if data.get("id") != run_id:
            raise ReconcileError("run-ID lookup returned different run")
        return data

    def existing(self, row: dict) -> tuple[str, dict | None]:
        workflow = row["workflow"]
        query = urlencode({"event": "workflow_dispatch", "head_sha": self.sha, "per_page": 100})
        data = self.api.request("GET", self.api_path(f"actions/workflows/{workflow}/runs?{query}"))
        runs = data.get("workflow_runs")
        if not isinstance(runs, list):
            raise ReconcileError(f"{workflow}: malformed workflow run list")
        # A short or uncounted inventory cannot prove that dispatch is needed.
        # The query requests a complete 100-run page for this exact head. If
        # GitHub reports more entries than it returned, an existing queued or
        # failed child may be hidden, making a second POST unsafe.
        total = data.get("total_count")
        if (type(total) is not int or total < 0 or total > 100
                or len(runs) != total):
            raise ReconcileError(f"{workflow}: incomplete or uncounted pre-dispatch inventory")
        # Validate rows BEFORE reading their fields: a malformed API entry
        # must produce a recorded blocked manifest, not an uncaught
        # AttributeError that loses the normal evidence handover.
        if any(not isinstance(run, dict) or type(run.get("id")) is not int
               or run["id"] < 1 for run in runs):
            raise ReconcileError(f"{workflow}: invalid pre-dispatch run inventory")
        candidates = []
        for run in runs:
            if (run.get("head_sha") != self.sha or run.get("event") != "workflow_dispatch"
                    or run.get("head_branch") != self.ref):
                continue
            self.verify(row, run)
            candidates.append(run)

        # Record every listed ID, not just accepted candidates. The next POST
        # must not adopt an older cancelled or mismatched run after ambiguity.
        self.prior_run_ids[workflow] = {run["id"] for run in runs}
        if not candidates:
            return "missing_or_cancelled", None
        # Latest run/attempt is authoritative: old green may not hide new red.
        latest = max(candidates, key=lambda x: (x["id"], x["run_attempt"]))
        detail = self.get_run(latest["id"])
        self.verify(row, detail)
        if detail["run_attempt"] != latest["run_attempt"]:
            raise ReconcileError(f"{workflow}: run attempt changed during discovery")
        if detail["status"] in ACTIVE:
            return "reuse_active", detail
        if detail["status"] == "completed" and detail.get("conclusion") == "success":
            return "reuse_success", detail
        if detail["status"] == "completed" and detail.get("conclusion") == "cancelled":
            return "missing_or_cancelled", None
        raise QualificationFailed(f"{workflow}: latest exact-head run {detail['id']} is "
                                  f"{detail['status']}/{detail.get('conclusion')}; explicit repair required")

    def recover_ambiguous_post(self, row: dict, cause: ReconcileError) -> dict:
        """Read-only, bounded reconciliation after an uncertain POST outcome.

        A second POST is forbidden. Only ONE newly visible, independently
        verified exact-head run (absent from the pre-POST inventory) can be
        adopted. Missing, wrong-source or multiple new runs leave the gate
        blocked rather than guessing which mutation took place.
        """
        workflow = row["workflow"]
        before = self.prior_run_ids.get(workflow)
        if before is None:
            raise ReconcileError(f"{workflow}: missing pre-POST inventory") from cause
        self.manifest["decisions"].append({
            "workflow": workflow, "decision": "ambiguous_post",
            "reason": str(cause),
            "policy": "read-only reconciliation; never retry POST",
        })
        query = urlencode({"event": "workflow_dispatch", "head_sha": self.sha, "per_page": 100})
        # A newly visible run might not be the only new run: workflow listings
        # are eventually consistent. Require two separately verified complete
        # inventories before accepting uniqueness. This is bounded evidence,
        # not proof of POST attribution or globally atomic discovery.
        observed: tuple[int, int] | None = None
        for delay in (0, 2, 5, 10, 20):
            if delay:
                self.sleep(delay)
            self.check_head()
            try:
                data = self.api.request(
                    "GET", self.api_path(f"actions/workflows/{workflow}/runs?{query}"))
            except ReconcileError:
                continue  # Bounded read-only API recovery. No second POST.
            runs = data.get("workflow_runs")
            if not isinstance(runs, list) or not isinstance(data.get("total_count"), int):
                raise ReconcileError(f"{workflow}: malformed post-dispatch inventory") from cause
            if (type(data["total_count"]) is not int or data["total_count"] < 0
                    or data["total_count"] > 100 or len(runs) != data["total_count"]):
                raise ReconcileError(f"{workflow}: incomplete or uncounted post-dispatch inventory") from cause
            if any(not isinstance(run, dict) or type(run.get("id")) is not int
                   or run["id"] < 1 for run in runs):
                raise ReconcileError(f"{workflow}: invalid post-dispatch run inventory") from cause
            newly_visible = [run for run in runs if run["id"] not in before]
            if len(newly_visible) > 1:
                raise ReconcileError(
                    f"{workflow}: ambiguous POST followed by multiple new runs; no attribution") from cause
            if not newly_visible:
                if observed is not None:
                    raise ReconcileError(
                        f"{workflow}: new run disappeared during ambiguous POST confirmation") from cause
                continue
            candidate = newly_visible[0]
            # Verify the list result and authoritative run detail independently.
            self.verify(row, candidate)
            try:
                detail = self.get_run(candidate["id"])
            except ReconcileError:
                observed = None  # A missing detail is not a validated observation.
                continue
            self.verify(row, detail)
            if detail["run_attempt"] != candidate["run_attempt"]:
                raise ReconcileError(
                    f"{workflow}: attempt changed while reconciling ambiguous POST") from cause
            identity = (detail["id"], detail["run_attempt"])
            if observed is None:
                observed = identity
                continue  # A second complete inventory must corroborate it.
            if observed != identity:
                raise ReconcileError(
                    f"{workflow}: candidate identity changed during ambiguous POST confirmation") from cause
            self.check_head()
            self.manifest["decisions"].append({
                "workflow": workflow, "decision": "ambiguous_post_reconciled",
                "run_id": detail["id"], "run_attempt": detail["run_attempt"],
            })
            # This is an observed run, not proof the uncertain POST created it.
            self.reconciled_workflows.add(workflow)
            self.manifest["reconciled"] += 1
            return detail
        raise ReconcileError(
            f"{workflow}: ambiguous POST not reconciled to one newly visible exact-head run; "
            "no mutation retried") from cause

    def dispatch_one(self, row: dict) -> dict:
        workflow = row["workflow"]
        try:
            response = self.api.request(
                "POST", self.api_path(f"actions/workflows/{workflow}/dispatches"),
                {"ref": self.ref})
        except ReconcileError as exc:
            # A transport/CLI failure cannot prove whether GitHub dispatched.
            # Reconcile only pre/post IDs at this exact source, without POSTing.
            return self.recover_ambiguous_post(row, exc)
        run_id = response.get("workflow_run_id")
        if type(run_id) is not int or run_id < 1:
            raise ReconcileError(f"{workflow}: dispatch returned no authoritative run ID; do not retry")
        self.manifest["dispatched"] += 1
        self.manifest["decisions"].append({"workflow": workflow, "decision": "dispatch_issued", "run_id": run_id})
        for delay in (0, 2, 5, 10, 20):
            if delay:
                self.sleep(delay)
            self.check_head()
            try:
                detail = self.get_run(run_id)
            except ReconcileError:
                continue  # Bounded eventual-consistency lookup; never POST again.
            try:
                self.verify(row, detail)
            except ReconcileError as exc:
                self.manifest["rejected"].append({"workflow": workflow, "run_id": run_id,
                                                   "reason": str(exc), "actual_sha": detail.get("head_sha")})
                self.check_head()
                raise
            return detail
        raise ReconcileError(f"{workflow}: dispatched run {run_id} could not be verified after bounded lookup")

    def dispatch(self) -> list[dict]:
        watch = []
        self.check_head()
        for row in self.rows:
            self.check_head()
            decision, detail = self.existing(row)
            self.check_head()
            if detail is None:
                detail = self.dispatch_one(row)
                decision = ("reconciled_ambiguous_post" if row["workflow"] in self.reconciled_workflows
                            else "dispatched")
            else:
                self.manifest["reused"] += 1
                self.manifest["avoided_dispatches"] += 1
            selected = {
                "workflow": row["workflow"], "stable_id": row["stable_id"],
                "run_id": detail["id"], "run_attempt": detail["run_attempt"],
                "sha": self.sha, "ref": self.ref, "decision": decision,
                "workflow_id": detail["workflow_id"], "path": detail["path"],
                "event": detail["event"], "head_sha": detail["head_sha"],
                "head_branch": detail["head_branch"],
            }
            self.manifest["runs"].append(selected)
            self.manifest["decisions"].append({"workflow": row["workflow"], "decision": decision,
                                               "run_id": detail["id"], "run_attempt": detail["run_attempt"]})
            watch.append(selected)
            self.check_head()
        self.check_head()
        self.manifest["state"] = "pending" if watch else "qualified"
        return watch

    def verify_selected(self, selected: dict, completed: bool) -> dict:
        self.check_head()
        row = {"workflow": selected["workflow"], "stable_id": selected["stable_id"]}
        if selected.get("sha") != self.sha or selected.get("ref") != self.ref:
            raise ReconcileError("watch matrix source differs from requested source")
        run = self.get_run(selected["run_id"])
        self.verify(row, run, require_completed=completed)
        if run["run_attempt"] != selected["run_attempt"]:
            raise ReconcileError(f"{row['workflow']}: run attempt changed: "
                                 f"{selected['run_attempt']} -> {run['run_attempt']}")
        self.check_head()
        return run

    def finalize(self, watcher_result: str) -> None:
        self.check_head()
        if watcher_result != "success":
            if watcher_result == "failure":
                raise QualificationFailed("downstream watcher matrix failed")
            if watcher_result == "cancelled":
                raise ExecutionCancelled("downstream watcher matrix cancelled")
            raise ReconcileError(f"watch matrix unavailable: {watcher_result}")
        selected = self.manifest.get("runs", [])
        if len(selected) != len(self.rows) or {r["workflow"] for r in selected} != {r["workflow"] for r in self.rows}:
            raise ReconcileError("watch matrix did not cover every selected downstream workflow")
        self.manifest["terminal_runs"] = []
        for row in selected:
            actual = self.verify_selected(row, completed=True)
            self.manifest["terminal_runs"].append({
                "workflow": row["workflow"], "run_id": actual["id"],
                "run_attempt": actual["run_attempt"], "head_sha": actual["head_sha"],
                "workflow_id": actual["workflow_id"], "event": actual["event"],
                "status": actual["status"], "conclusion": actual["conclusion"],
            })
        self.check_head()
        self.manifest["state"] = "qualified"

    def record_error(self, exc: BaseException) -> None:
        self.manifest["state"] = (
            "superseded" if isinstance(exc, Superseded) else
            "failed" if isinstance(exc, QualificationFailed) else
            "cancelled" if isinstance(exc, ExecutionCancelled) else
            "pending" if isinstance(exc, QualificationPending) else "blocked"
        )
        self.manifest["error"] = str(exc)
        self.manifest["decisions"].append({"decision": self.manifest["state"], "reason": str(exc)})

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(self.manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("dispatch", "verify-run", "finalize"))
    parser.add_argument("--repo", default=os.getenv("GITHUB_REPOSITORY", ""))
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--run-id", type=int, default=int(os.getenv("GITHUB_RUN_ID", "0")))
    parser.add_argument("--manifest", type=Path, default=Path("zg000-dispatch-manifest.json"))
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--watcher-result", default="")
    parser.add_argument("--row-json")
    args = parser.parse_args()
    manifest = {}
    if args.mode == "finalize" and not args.manifest.exists():
        raise SystemExit("missing authoritative dispatch manifest; cannot finalize")
    if args.mode == "finalize" and args.manifest.exists():
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        if (manifest.get("repo"), manifest.get("pr"), manifest.get("requested_sha"), manifest.get("source_ref")) != (
                args.repo, args.pr, args.sha, args.ref):
            raise SystemExit("refusing to finalize a manifest for another source")
        rows = manifest["selected"]
    elif args.mode == "dispatch":
        rows = json.loads(os.getenv("ZG000_MATRIX_JSON", "[]"))
    else:
        rows = [json.loads(args.row_json)] if args.row_json else []
    engine = Reconciler(GitHubAPI(), args.repo, args.pr, args.sha, args.ref, rows, args.run_id)
    if manifest:
        engine.manifest = manifest
    try:
        if args.mode == "dispatch":
            watch = engine.dispatch()
            if args.github_output:
                with args.github_output.open("a", encoding="utf-8") as output:
                    output.write("watch_matrix=" + json.dumps(watch, separators=(",", ":")) + "\n")
                    output.write("has_runs=" + ("true" if watch else "false") + "\n")
        elif args.mode == "verify-run":
            engine.verify_selected(rows[0], completed="true" == os.getenv("ZG000_REQUIRE_COMPLETE", "false"))
        else:
            engine.finalize(args.watcher_result)
    except (ReconcileError, ValueError, KeyError) as exc:
        engine.record_error(exc)
        print(f"ZG-000 {engine.manifest['state']}: {exc}", file=sys.stderr)
        return_code = 1
    else:
        return_code = 0
    finally:
        if args.mode != "verify-run":
            engine.save(args.manifest)
            print("ZG-000 manifest: " + str(args.manifest))
            print("ZG-000 state: " + engine.manifest["state"])
            print("ZG-000 reused: " + str(engine.manifest["reused"]))
            print("ZG-000 dispatched: " + str(engine.manifest["dispatched"]))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
