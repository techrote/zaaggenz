# ZG-000 — Superseded-Run and Exact-Head Dispatch Policy

## Authority and scope

ZG-000 retains the existing `tools/ci_reverse_dependencies.py` selector, source ownership configuration and programme dependency DAG. Direct/native feature workflows remain authoritative. This change does **not** alter musical behaviour, DSP, ZG-024a transitions, task-state evidence, owner gates or repository protections.

## Concurrency and ownership

Automatic `pull_request` generations are serialised using GitHub Actions concurrency grouped by repository, workflow identity and **PR number**, with `cancel-in-progress: true`. Newer PR updates supersede the previous orchestration generation. Different PRs and unrelated workflows remain independent.

Manual `workflow_dispatch` of ZG-000 is **audit-only** and uses a unique run-scoped concurrency group. It never dispatches children and does not interrupt automatic generations.

ZG-000 **never cancels independently triggered child workflows**, including direct PR tests, shared/manual tests and another orchestrator's work. Cancelled parent runs remain cancelled; the newest head is responsible for its own validation.

## Dispatch and idempotency

The original event's immutable `pull_request.head.sha` is compared with the live authoritative PR head before inventory, before dispatch, after each child is identified, between selected workflows and before final acceptance.

For every required downstream workflow, list `workflow_dispatch` runs at the exact SHA. Require a matching source branch, event, workflow ID, workflow definition path, actual run SHA and attempt. A newer run/attempt supersedes an older run at the same SHA:

- Latest completed success: reuse and verify.
- Latest queued/running: watch without relaunching.
- Latest failure: fail and require explicit repair/rerun; do not mask a recent red with an older green.
- Latest cancelled: cannot certify; one new dispatch may be started **only if the complete exact-source inventory contains no earlier queued/running child**. If an older child remains active, block for reconciliation rather than launching a duplicate or treating an older run as qualified. Even when the complete workflow listing labels an earlier child completed, read and verify each earlier same-source child's authoritative run details and exact run attempt before permitting replacement: a stale list can conceal a still-active child or a newer rerun attempt. Any disagreement, unavailable detail or active execution blocks without a new POST.
- Missing: dispatch one run.

GitHub REST API version `2026-03-10` removed the `return_run_details` request parameter and always returns `200` with `workflow_run_id`. Dispatch sends only the moving source `ref` (and no removed parameter). The returned run ID is verified against GitHub's authoritative actual run source; no timestamp/run-ID inference is used. An ambiguous POST is **never retried**. If the GitHub CLI fails without an authoritative response, the orchestrator may perform bounded **read-only** recovery: compare the pre-POST exact-head workflow inventory with new workflow-dispatch runs, require exactly one previously unseen run, independently verify its workflow ID/path, source branch, exact commit SHA and attempt from the authoritative run endpoint, and recheck the live PR head. A unique verified run is recorded as `reconciled_ambiguous_post`, **not** counted as a confirmed new dispatch; attribution to the failed POST is not claimed. A candidate must also survive **two complete, independently checked post-POST inventories**, with matching authoritative ID and attempt on each. A second run emerging at confirmation, partial follow-up inventory, disappearing candidate or a candidate first observed only on the final bounded poll blocks qualification; one early listing is insufficient under eventual consistency. This reduces but cannot eliminate races with yet-unpublished workflow runs. A pre-POST inventory and every post-POST inventory must each include an integer `total_count` matching the returned list length (the request is capped at 100) **and distinct positive integer run IDs**; otherwise the response is uncounted or truncated and the gate blocks without assuming that another run is absent. This prevents a partial list from concealing an active/failed child or making one of several new runs appear unique. No new or multiple new runs, malformed/excess inventory, mismatched source or unavailable run details leave qualification blocked. A response with missing run ID also remains blocked. GET and run-visibility checks have bounded retries.

GitHub `workflow_dispatch` still targets a potentially moving branch, not an immutable SHA. If its actual `head_sha` changes between the head check and GitHub's scheduling, the obsolete parent rejects that child, stops further dispatch and **never certifies it for the old SHA**. There remains a narrow check-to-POST window in which some work may be wasted; it is explicitly not claimed to be eliminated.

### Cross-parent no-child guard (9 November 2026)

A complete-looking empty child list is no longer sufficient to start a POST. When a child is absent or its latest run is cancelled, the dispatcher corroborates its *current parent* through two counted ZG-000 pull-request orchestration inventories on the source branch, each with exact workflow, PR number, source SHA and attempt. A prior same-SHA parent can have created a child not yet indexed by the child workflow listing: any observed earlier same-head parent now blocks, as do orchestration reruns, an invisible current parent, missing provenance, changed inventory, differing authoritative older-parent detail, or a newer parent. An older, verifiably different-SHA parent does not block a new commit; a first verified parent still has a path to one dispatch. There is no extra POST after ambiguity and no cancellation of independently owned children.

**Limit:** This is a read-only observation guard, not a durable atomic dispatch claim. Even both parent listings can be stale and omit an older run. Mutable/incomplete PR metadata also causes conservative refusal. The deterministic regression proves the visible-older-parent plus stale-empty-child case; it cannot prove globally exactly-once behavior. Full idempotency requires owner-approved durable source/child-scoped arbitration (or a genuinely equivalent external contract) and potentially shared GitHub Actions workflow permissions/wiring outside this three-file lease. Integration must independently review that residual risk before admission; neither green tools-only CI nor a mocked test authorizes fully race-free dispatch. A real disposable same-repo rapid-retry experiment remains NOT RUN without explicit permission.

## Exact-head completion states

- **qualified:** every selected reverse-dependency run completed successfully, with matching immutable SHA, source branch, workflow identity, event, run ID and unchanged attempt; the original PR head is still current; watcher matrix passed.
- **superseded:** PR head or PR source identity changed.
- **failed:** an authoritative required downstream run or watcher failed.
- **cancelled:** indispensable execution was cancelled.
- **pending:** required exact-head tests remain active.
- **blocked:** API/dispatch identity, workflow definition, coverage or evidence could not be established.

Final acceptance re-reads a complete, counted exact-head workflow inventory for each watched child and refuses to qualify an older selected run if any newer same-branch run or attempt exists, even when the older run is green. A new run must have its own watcher and accepted evidence; a truncated, duplicate-ID or malformed final inventory blocks. Workflow definition IDs must be positive JSON integers (a JSON boolean is never an authoritative ID). This prevents a same-head manual rerun or concurrent dispatch from hiding a later red behind previously selected success. The finalizer performs a **second complete matrix-wide inventory audit** after checking every child's authoritative terminal status: a newer run on an early workflow can emerge while a later workflow is being verified. If the late run supersedes the previously watched result, final acceptance blocks without dispatch or cancellation. The second sweep also re-reads each selected run's authoritative details: a counted yet stale workflow list cannot conceal a changed attempt, renewed activity or a new failure already visible at the run endpoint. Unavailable details block acceptance. GitHub run listings and run details remain eventually consistent, so two finite sweeps are additional final audits rather than a claim of globally atomic scheduler observation.

Only `qualified` is acceptable reverse-dependency evidence; none of these statuses substitutes for required native/direct checks. Non-qualified states exit nonzero when the parent is not already cancelled.

## Audit and recovery

Seven-day bounded Actions artifacts `zg000-dispatch-manifest` and `zg000-reconciliation-final` contain schema `zg000-dispatch-v1`, source PR/head, live head, required workflows, reused and dispatched run IDs/attempts, rejected identities, reasons, counts of dispatches avoided, and final state. A hard runner cancellation can prevent the final artifact; GitHub's cancelled-run conclusion remains authoritative.

Interrupted/ambiguous dispatches require inspection of existing exact-head run records before any manual retry. Never cancel child runs without independently proving exclusive obsolete ownership.

## Acceptance outstanding

The deterministic tests mock API responses and inspect actual dispatch counts and identity; **they do not prove GitHub's live scheduler convergence**. Before merging, run an isolated rapid-push test on a disposable same-repo PR, inspect parent cancellation, child run IDs, attempt/source identities, manifests and absence of growing obsolete fan-out. Require exact-head Ubuntu/Windows tests and **independent read-only review**. Keep this PR draft if any requirement remains unverified.
