# Authority reconciliation campaign RAG

**Parent programme:** ZG-000  
**Repository:** `techrote/zaaggenz`  
**Planning/audit base:** `main` at `4a7ffbaee17d88dd2ff8a59efc3cda14e2663629` on 2026-09-19  
**Purpose:** reconcile the repository's machine-readable programme authority, human-facing authority surfaces and automated drift guards before ZG-043 long-form implementation begins.

This document is the canonical retrieval/read-set for the authority-reconciliation campaign. It is a plan and execution handoff, not a replacement for `programme/task_state.json`, `programme/tasks.json` or the accepted implementation/contracts.

## 1. Why this campaign exists

The 2026-09-19 deep repository audit found that the accepted runtime and corrective campaign are substantially healthier than several repository authority surfaces imply. No current accepted runtime feature was shown to violate its latest semantic contract, but a fresh engineer or autonomous agent can still receive contradictory instructions from official entry points.

The material contradictions are:

- root `README.md`, `programme/DEPLOYMENT_STATUS.md`, root `RESEARCH_SCRATCHPAD.md`, root `PRELIMINARY_RESEARCH_RESULTS.md`, and ZG-000 issue #1 still contain source-recovery / ZG-001 live-gate wording that has been superseded by accepted recovery evidence;
- `docs/zaaggenz/OVERVIEW.md` retains a present-tense paragraph saying ZG-040 and ZG-042 currently block downstream work even though both were subsequently reaccepted;
- `programme/task_state.json` correctly keeps ZG-024 incomplete but names closed child issues #87/#92/#134 as its blockers instead of the surviving research condition recorded on parent #25;
- `programme/task_state.json` still names closed #103 as a ZG-045 blocker even though #103 and corrective #203 are complete;
- the ZG-029 state row does not directly point to final PR #209 / policy 1.1.0 even though that reopened corrective materially changed the authoritative source-stem/source-bus semantics;
- `docs/zaaggenz/RAG_INDEX.md` still presents the ZG-024 handoff 1/2 pair as the effective latest serial read set, omitting Candidate 2.0 provenance, transient-v4 evidence migration, staged protocol v2, the mixed/no-go staged result and lineage reconciliation;
- several subsystem docs retain pre-integration future tense after #94/#95/#201/#214/#215 have completed;
- `tools/check_programme_docs.py` checks only a narrow selected set of documents and a handful of literal stale phrases, while `tools/validate_programme_state.py` validates state combinations but cannot prevent a completed child issue number from remaining indefinitely as a live blocker identity.

This is therefore an **authority correctness** problem rather than a new product/DSP design problem.

## 2. Authority hierarchy to preserve

After the campaign, the repository must still have exactly one authority for each question:

| Question | Authority |
|---|---|
| What code currently does | accepted `main` implementation plus executable tests |
| What a contract/interface means | versioned contracts, ADRs and compatibility policies |
| Whether a stable task's accepted evidence may satisfy downstream dependencies | `programme/task_state.json` |
| Planned hard prerequisites, topological levels and shared locks | `programme/tasks.json` + `programme/dependency_graph.json` |
| Stable ID to GitHub issue mapping | `programme/issue_map.json` |
| Agent retrieval/read set | `docs/zaaggenz/RAG_INDEX.md`, derived from the authorities above |
| Historical decisions, rollbacks and superseded evidence | dated docs, issue/PR completion records and research artefacts |
| GitHub issue open/closed state | informational mirror only; never dependency authority |

Do **not** create a second status vocabulary or derive readiness from GitHub issue closure.

## 3. Protected invariants and non-goals

Every issue in this campaign must preserve:

- stable programme IDs ZG-000…ZG-045;
- the 45-task planned programme and its current 158 hard-prerequisite edges unless a separately reproduced factual graph defect is found;
- `programme/issue_map.json`;
- recovered v1.2.1 source/provenance and protected `locked_bloom` semantics;
- source PCM, DSP topology/order, tuning, phase/reset/tail, final-master and project/artifact identity semantics;
- accepted research/calibration history, including rollbacks, mixed/no-go results and superseded protocol records;
- ZG-022's still-pending owner listening/default gate;
- ZG-024's still-incomplete parent research state;
- Compose as the ordinary music-making authority and Research as optional/non-destructive;
- GitHub issue/PR history: correct current authority by appending/updating current surfaces, not by deleting historical completion or rollback evidence.

Non-goals:

- no new top-level stable IDs;
- no broad re-planning of the programme;
- no default sound promotion;
- no new optimizer selection;
- no product/DSP implementation in the authority issues;
- no attempt to mark ZG-024 complete;
- no attempt to satisfy ZG-022 owner review automatically;
- no silent DAG rewrite merely because issue states changed.

## 4. Campaign structure

The authority repair is deliberately serialized into three ZG-000 child issues. A separate ZG-042 technical hardening issue follows the authority campaign and should preferably complete before substantial ZG-043 long-form implementation.

### A. Machine-readable live authority

**Issue:** #217 — `[ZG-000 authority reconciliation] Repair machine-readable live programme authority`

Owns:

- `programme/task_state.json`;
- `tools/validate_programme_state.py`;
- programme-state regression tests;
- only the smallest documentation required to explain a state-format/validation rule change.

Required outcomes:

1. ZG-024 remains:
   - implementation `partial`;
   - evidence `partial`;
   - research `active`;
   - `dependency_satisfied=false`;
   - issue #25 open;
   but its closed child issues #87/#92/#134 are removed as live blocker identities.
2. ZG-024 receives a semantic blocker describing the actual surviving condition recorded by the final #25 update: reliable eligible-candidate availability plus held-out improvement on fresh structural/spectral and mixed-texture cases without holdout feedback or weakened safety gates.
3. ZG-024 evidence references are advanced through the accepted Candidate 2.0 provenance repair, transient-v4 repair, staged deterministic research mixed/no-go result and lineage reconciliation.
4. ZG-029 remains accepted/dependency-satisfying and directly references final #202/PR #209 policy-1.1 authority, while retaining useful earlier #206/#208 evidence.
5. ZG-045 remains not-started/not-satisfying, but closed #103 is removed as a task-local blocker. ZG-043/ZG-044 readiness continues to come from the DAG and is not duplicated as blocker objects.
6. The validator distinguishes semantic blocker identity from evidence/navigation refs so the same “closed child issue remains the blocker” drift is harder to reintroduce.
7. Existing `dependency_satisfied` decisions do not change unless exact evidence in the issue proves a contradiction.

This issue must land before the human-facing authority issue.

### B. Human-facing authority and RAG reconciliation

**Issue:** #218 — `[ZG-000 authority reconciliation] Reconcile front-door docs and RAG with accepted main`

Depends on A.

Owns the current authority/read-set prose, including:

- root `README.md`;
- `programme/DEPLOYMENT_STATUS.md`;
- root `RESEARCH_SCRATCHPAD.md`;
- root `PRELIMINARY_RESEARCH_RESULTS.md`;
- `docs/zaaggenz/OVERVIEW.md`;
- `docs/zaaggenz/RAG_INDEX.md`;
- `docs/zaaggenz/PROGRAMME_STATUS_RECONCILIATION.md`;
- `docs/runtime/README.md`;
- `docs/zaaggenz/briefs/ARCHITECTURE.md`;
- `docs/analysis/ZG023_INSPECTOR.md`;
- `docs/inverse/CANDIDATE_PROVENANCE.md`;
- `docs/studies/README.md`;
- `docs/zaaggenz/CI_REVERSE_DEPENDENCIES.md`;
- other directly adjacent status-bearing text only when needed for consistency.

Required outcomes:

- no current authority surface says ZG-001/source recovery is still a live implementation gate;
- pre-G0 root research files remain preserved but are visibly labelled historical/superseded as live status sources;
- `OVERVIEW.md` preserves the ZG-040/ZG-042 rollback as dated history while making their later reacceptance unambiguous;
- the ZG-024 RAG sequence reaches Candidate 2.0, transient-v4, staged protocol v2/result, lineage reconciliation and the live parent blocker;
- current RAG explicitly warns not to restart #87/#92/#134;
- runtime/architecture docs include the accepted `/research` hub without making it a second state owner;
- ZG-023 docs describe #95 as established current architecture, not future work;
- Candidate provenance docs stop using completed #94/#92 as future trackers and instead state the current boundary honestly;
- ZG-040 docs say corrective reacceptance is complete;
- CI explanatory prose matches the current machine inventory, while the JSON remains authority.

This issue is documentation/read-set reconciliation only. It must not edit `task_state.json` except to repair an integration conflict from A, in which case the branch must first reconcile onto current `main` and preserve A's semantics.

### C. Authority drift guardrails and final dispatch certification

**Issue:** #219 — `[ZG-000 authority reconciliation] Harden authority drift checks and certify ZG-043 dispatch readiness`

Depends on A and B.

Owns:

- `tools/check_programme_docs.py`;
- `tools/validate_programme_state.py` only if a guardrail not safely expressible in A is still required;
- programme documentation/state tests;
- final read-only reconciliation of the authority surfaces;
- post-merge update of ZG-000 issue #1 body to remove the obsolete “Immediate gate” and point readers at the accepted live authority.

Required outcomes:

1. The programme-doc checker covers all designated status-bearing front doors, not only six selected docs.
2. Root pre-G0 research docs are required to carry a historical/superseded marker.
3. If live state says ZG-040 or ZG-042 is dependency-satisfying, current prose declaring it a current blocker is rejected.
4. If live state says ZG-001 is accepted/dependency-satisfying, current source-recovery blocker language is rejected outside explicitly historical sections.
5. RAG validation requires the current ZG-024 terminal evidence/read set rather than handoff 1/2 alone.
6. Runtime docs are checked for the accepted Research-hub/current-authority contract at an appropriate stable invariant level.
7. Offline validation remains reproducible; ordinary CI does not query GitHub issue state.
8. The issue updates ZG-000/#1 only after its PR merges: preserve historical comments, but replace the stale body gate with a pointer to `programme/task_state.json`.
9. A fresh readiness report demonstrates:
   - ZG-033 and ZG-034 are blocked only by ZG-022;
   - ZG-039 is blocked by ZG-024;
   - ZG-043 has all declared hard prerequisites satisfied;
   - ZG-044 is blocked by ZG-022, ZG-024 and ZG-043;
   - ZG-045 is blocked by ZG-043 and ZG-044 through the DAG, not by #103.
10. The final completion record states that authority reconciliation is complete and ZG-043 may be dispatched from the then-current `main`.

### D. Adjacent technical hardening before substantial ZG-043 work

**Issue:** #220 — `[ZG-042 follow-up] Enforce process/native memory evidence against long-form reservations`

This is **not** an authority-reconciliation issue and must not be described as one. It is included here because the audit found one remaining acceptance-strength gap directly relevant to ZG-043.

Current accepted ZG-042 evidence is not revoked: PR #213 actually executed the full-rate 64-bar plan with a 267,321,344-byte reservation and measured both Python `tracemalloc` peak and process RSS evidence below that reservation.

The gap is that `tools/benchmark_zg042.py` only fails the acceptance run on `tracemalloc_peak_bytes > reserved_memory_bytes`; Linux RSS is sampled and recorded but not executable acceptance evidence. A future native NumPy/SciPy/backend allocation regression could therefore exceed the intended job memory envelope while Python traced memory still passes.

The follow-up should add an explicitly defined process/native-memory acceptance rule that compares a defensible job-attributable RSS delta/peak measure against the authoritative reservation, retains existing `tracemalloc` evidence, does not compare total interpreter baseline RSS naively to a job-only reservation, and changes no audio/quality/chunking semantics.

Prefer completing D after C and before substantial ZG-043 long-form work. ZG-043's existing planned DAG does not need to be rewritten merely to represent this recommendation.

## 5. Required read sets

Every issue body must contain its own focused read set and must also reference this document plus the universal agent rules.

### Universal for A–C

Read:

- this file;
- `docs/zaaggenz/OVERVIEW.md`;
- `docs/zaaggenz/RAG_INDEX.md`;
- `docs/zaaggenz/CONTEXT_AND_DECISIONS.md`;
- `docs/zaaggenz/PROGRAMME_STATUS_RECONCILIATION.md`;
- `docs/zaaggenz/briefs/AGENT_OPERATING_RULES.md`;
- `docs/zaaggenz/briefs/VALIDATION_GATES.md`;
- `programme/tasks.json`;
- `programme/dependency_graph.json`;
- `programme/task_state.json`;
- `programme/issue_map.json`;
- `programme/ci_reverse_dependencies.json`;
- `tools/validate_programme_state.py`;
- `tools/check_programme_docs.py`;
- relevant `tests/programme/**`.

### ZG-024 evidence required for A/B/C

Read:

- issue #25 final/current history;
- issues #87, #92, #134 and their completion records;
- PRs #84, #86, #187, #194, #195;
- `docs/inverse/README.md`;
- `docs/inverse/ZG024_RESEARCH_HANDOFF_1.md`;
- `docs/inverse/ZG024_RESEARCH_HANDOFF_2.md`;
- `docs/inverse/CANDIDATE_PROVENANCE.md`;
- `docs/inverse/TRANSIENT_PRESERVATION_GATE.md`;
- `docs/inverse/TRANSIENT_V4_EVIDENCE_MIGRATION.md`;
- `docs/inverse/ZG024_STAGED_PROTOCOL_V2.md`;
- `docs/inverse/ZG024_STAGED_RESULT.md`;
- `docs/inverse/ZG024_LINEAGE_RECONCILIATION.md`.

Do not interpret the mixed/no-go result as failure to complete #92; it is the frozen accepted outcome. Do not promote a production optimizer.

### ZG-029 evidence required for A/B/C

Read:

- issues #30, #91, #202;
- PRs #181, #206, #207, #208, #209;
- `docs/zaaggenz/ZG029_LAYER_OWNERSHIP_ADR.md`;
- `docs/zaaggenz/ZG029_RUNTIME.md`;
- `docs/zaaggenz/ZG029_CORRECTIVE_RUNTIME_EVIDENCE.md`;
- `docs/zaaggenz/ZG030_POCKETS.md`.

Policy 1.1.0 / PR #209 is current authority. Do not regress to the old claim that raw SYNTHLINE/exciter arrays are independent post-topology pre-master contributions.

### ZG-040/041/042 evidence required for B/C

Read:

- PR #212 rollback;
- PR #213 ZG-042 corrective reacceptance;
- PR #214 ZG-040 corrective reacceptance;
- PR #215 ZG-041 integration;
- `docs/studies/README.md`;
- `docs/performance/ZG042_LONGFORM.md`;
- `docs/runtime/README.md`;
- `docs/runtime/ZG041_COMPOSE_RESEARCH.md`;
- `docs/zaaggenz/briefs/ARCHITECTURE.md`.

### D additional read set

Read:

- issue #43 / ZG-042;
- PR #210 and rollback PR #212;
- PR #213 and its exact final-head benchmark evidence;
- `zaaggenz_performance/policy.py`;
- `zaaggenz_performance/sections.py`;
- `tools/benchmark_zg042.py`;
- `tests/performance/**`;
- `.github/workflows/zg042-performance.yml`;
- `docs/performance/ZG042_LONGFORM.md`;
- ZG-004 scheduler/memory contract and ZG-029 persistent-layer contract.

## 6. Autonomous execution contract for every issue

Each issue in this campaign must be executable end-to-end by one implementation agent.

The issue prompt must require the agent to:

1. fetch/re-read current authoritative `main` and record its exact SHA before branch creation;
2. re-read the issue's entire required read set and all newer comments before editing;
3. verify prerequisites and ensure a concurrent/superseding PR has not already completed the work;
4. create one dedicated branch from the exact current `main`; do not reuse an unrelated branch;
5. make the smallest complete change within the issue's owned surfaces;
6. add adversarial/boundary regression tests for every reproduced authority or validation failure;
7. run focused tests first, then the repository's normal programme/reverse-dependency checks;
8. inspect the final diff for accidental product/DSP/DAG changes outside scope;
9. open a PR with the exact scope, evidence, non-goals and validation results;
10. continue autonomously through CI; repair legitimate failures on the same branch rather than starting over;
11. before merge, verify all required workflows are successful on the **exact current PR head**, no required check is pending/failed, and no unresolved review thread materially blocks acceptance;
12. merge only that exact reviewed head, using the repository's normal merge method and an expected-head guard where available;
13. re-read `main` after merge and verify the accepted commit landed;
14. perform any explicitly required post-merge GitHub metadata step (notably ZG-000 issue #1 body in C);
15. add a precise issue completion record containing branch, reviewed head, merge SHA, changed authority/contract, commands/workflow runs, and any intentionally unresolved item;
16. close the issue only when every acceptance criterion is satisfied.

If current `main` or a newer accepted issue comment contradicts an older instruction, preserve the newer accepted authority and document the reconciliation. Do not weaken tests, delete historical evidence, force-update branches, or declare completion based only on a local pass.

## 7. Minimum automated checks

A–C should at minimum run:

```text
python tools/validate_programme_state.py --validate
python tools/validate_programme_state.py --report
python tools/check_programme_docs.py --check
python tools/ci_reverse_dependencies.py --audit
python -m unittest discover -s tests/programme -v
```

A may legitimately run a subset before the documentation branch exists, but its final PR must run every check applicable to its changed files and the repository's programme workflows.

D must run the complete ZG-042 focused performance suite, its full-rate benchmark/acceptance path, ZG-004 scheduler regressions, ZG-029 persistent-layer regressions and reverse-dependency selection required by its changed paths.

Do not manually trigger broad expensive suites merely because prose changed; let the accepted reverse-dependency machinery select implementation workflows. Conversely, do not suppress a workflow that the ownership/impact system selects.

## 8. Concurrency

Required serial order:

```text
#217 machine authority
    ↓
#218 human/RAG authority
    ↓
#219 guardrails + ZG-000 body + final readiness certification
    ↓
authority reconciled
    ↓
#220 ZG-042 native/process-memory hardening (prefer before substantial ZG-043)
    ↓
ZG-043 implementation
```

Do not run A and B concurrently: B must consume A's accepted machine representation.

C must start from the merged result of both A and B.

D is technically independent of the machine/prose repair, but for a clean pre-ZG-043 checkpoint it should begin after C unless urgent profiling requires otherwise.

## 9. Final authority-reconciliation definition of done

Authority reconciliation is complete only when:

- ZG-024 remains incomplete for the actual surviving research condition, not closed child ticket numbers;
- ZG-029's live evidence reaches policy 1.1.0 / PR #209 directly;
- #103 is no longer represented as a live ZG-045 blocker;
- no current authority/front-door surface says ZG-001 remains a source-recovery gate;
- pre-G0 research docs are unmistakably historical as status sources;
- no current authority prose says ZG-040 or ZG-042 is blocked while live state says accepted;
- the current ZG-024 RAG read set reaches the staged mixed/no-go result and present parent blocker;
- runtime architecture includes the accepted Research hub and correct single-session ownership;
- ZG-040 top-level status says reacceptance is complete;
- CI reverse-dependency explanatory prose matches the machine inventory;
- the programme checker catches the contradiction classes found by the audit;
- GitHub issue #1 body points to current programme authority instead of the obsolete recovery gate;
- a fresh readiness report shows ZG-043's declared hard prerequisites all satisfied;
- no product/DSP/default/DAG semantics changed as a side effect.

At that point ZG-043 can be dispatched without an authority-hygiene qualification.

## 10. Audit provenance

This campaign was produced from a read-only deep audit of `main` at `4a7ffbaee17d88dd2ff8a59efc3cda14e2663629`. The audit reviewed the 45-task/158-edge programme state, implementation/test surfaces, 103 substantive documentation files, open programme issues, the corrective campaign #87–#140, and the critical late PR/reacceptance history through PR #215.

The audit did **not** prove a present accepted runtime semantic failure. The only additional technical acceptance-strength gap carried into this plan is ZG-042's current use of `tracemalloc` rather than sampled process/native memory as the executable full-rate memory criterion; that is intentionally isolated in issue D rather than being mislabeled as authority reconciliation.
