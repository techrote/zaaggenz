# Programme status reconciliation — 2026-09-15

This record closes the bootstrap-era documentation contradiction tracked by issue #88. It does not replace the machine-readable programme state. Live implementation/evidence/research/owner-gate/readiness truth is [`programme/task_state.json`](../../programme/task_state.json); the documents below serve distinct explanatory roles.

## Authority and audit result

Authority remains:

1. accepted code, tests and completion/evidence records;
2. versioned contracts/ADRs and accepted recipes;
3. `programme/task_state.json` for current stable-task state/readiness;
4. current issue scope and master atlas;
5. research/design briefs;
6. historical conversation/planning snapshots as navigation/provenance only.

The stable `ZG-001…ZG-045` atlas, `programme/tasks.json`, `programme/dependency_graph.json` and `programme/issue_map.json` were checked during this reconciliation. No planned DAG edge or stable-ID mapping was changed: the defect was stale narrative status, not a newly proven dependency-graph error.

## Core document disposition

| Document | Status after audit | Reconciliation |
|---|---|---|
| `OVERVIEW.md` | current status pointer valid | #89 made `task_state.json` the live readiness authority and converted the old ZG-001 blocker into historical context. No second status vocabulary is introduced here. |
| `CONTEXT_AND_DECISIONS.md` | **stale planning claims repaired** | Keeps the original access snapshot as explicitly historical, adds accepted ZG-001 archive/runtime identities, and points live status to `task_state.json`. |
| `RAG_INDEX.md` | current | Already points to `task_state.json` and the latest accepted serial ZG-024 handoffs (`ZG024_RESEARCH_HANDOFF_1.md` and `_2.md`). |
| `REQUIREMENTS_TRACEABILITY.md` | status-neutral | Explicitly labelled a requirements map, not a live completion report; readiness points to `task_state.json`. |
| `WORKED_WORKFLOWS.md` | status-neutral | Explicitly labelled target end-to-end workflows, not assertions that every capability is complete. |
| `programme/tasks.json` | retained | Planned task metadata/dependencies/locks remain authoritative for the planned programme. |
| `programme/dependency_graph.json` | retained | Planned parent DAG unchanged. |
| `programme/issue_map.json` | retained | Stable-ID → top-level issue mapping unchanged. |
| `programme/task_state.json` | live state authority | Orthogonal implementation/evidence/research/owner-gate/blocker/readiness state accepted in #89. |

## Current programme snapshot

This summary is descriptive for the original 2026-09-15 reconciliation; later dated sections record subsequent evidence changes. The JSON state is always authoritative.

- **ZG-001:** baseline recovery/provenance is accepted. The original owner-supplied ZIP SHA-256 is `90be319a4660a637077df935a8ebcbd1bb4c3a629e28e2f6d4bfe62d88dfe8a8`; the compact recovered runtime payload SHA-256 is `eaf5d3ab822dfa121cd3b795d62619af9e62c041fb02de19f8dbeafb0014c919`. Source recovery is **not** a current blocker.
- **ZG-002…ZG-021:** accepted implementation/evidence is currently dependency-satisfying according to `task_state.json`; corrective follow-ups may still harden individual boundaries without automatically erasing accepted prerequisite evidence.
- **ZG-022:** substantial implementation/evidence is accepted, but the owner listening/default-approval gate remains pending. It is not dependency-satisfying.
- **ZG-023:** accepted and dependency-satisfying; #94 separately hardens real immutable source binding before later workspace integration relies on it.
- **ZG-024:** serial inverse-search research remains active. PR #84 and PR #86 plus handoffs 1/2 are accepted partial evidence; #87/#92/#134 remain relevant and the parent is not dependency-satisfying.
- **ZG-025…ZG-027:** accepted and dependency-satisfying under the current state record.
- **ZG-028:** accepted implementation evidence exists, but completion/readiness is explicitly withheld by corrective blockers including #138; GitHub issue state therefore cannot be used as a proxy.
- **ZG-029:** active/partial with #91 ownership reconciliation outstanding. **ZG-030** remains blocked on ZG-029.
- **ZG-031/ZG-032:** accepted and dependency-satisfying under the current state record, with separate corrective work still tracked where applicable.
- **ZG-033…ZG-040:** formal study/research tasks remain planned rather than silently inferred complete from their prerequisites.
- **ZG-041…ZG-045:** later integration/performance/export/release work remains unsatisfied/not-started according to the state record; specific reconciliation/prerequisite blockers remain explicit where known.

## Historical source/access correction

The original planning audit correctly refused to invent production source when the v1.2.1 archive was unavailable to that run. That was a sound **historical** blocker. ZG-001 later recovered the exact owner archive and authenticated a compact source payload containing the application/runtime, 13 smoke tests, launchers, requirements and key examples. `baseline/recovered_source/README.md` is the provenance authority and materialised `app/...` paths are the concrete downstream baseline.

Accordingly, future documentation may describe source unavailability only as dated planning history. Present-tense language such as “ZG-001 must recover the source before implementation” or “production-source import is still gated” is contradictory and is rejected by the programme-document check.

## ZG-024 read-set reconciliation

The current serial inverse-search read set is:

- `docs/inverse/README.md` — laboratory/reuse boundary;
- `docs/inverse/RECOVERED_BASELINE.md` — predecessor provenance;
- `docs/inverse/ZG024_RESEARCH_HANDOFF_1.md` — deterministic laboratory calibration;
- `docs/inverse/ZG024_RESEARCH_HANDOFF_2.md` — fixed-budget strategy comparison and staged-search direction.

These are accepted partial/research handoffs, not evidence that parent ZG-024 is complete. Issue #25 remains the parent research task.

## Reproducible future audit

Run:

```sh
python tools/validate_programme_state.py --validate
python tools/check_programme_docs.py --check
python -m unittest discover -s tests/programme -p 'test_programme_*.py' -v
```

`check_programme_docs.py` verifies the core document set exists, points status-bearing prose to the accepted state authority, retains the latest ZG-024 handoff pointers, confirms key live state (ZG-001 resolved; ZG-022 owner-gated; ZG-024 active), checks the accepted baseline hashes against the recovered-source provenance document, and rejects known bootstrap-era present-tense blocker phrases.

When implementation/evidence changes, update `task_state.json` through review first. Narrative documents should consume that state rather than inventing a parallel completion vocabulary.


## Post-merge evidence rollback — 2026-09-19

Independent review of the newly merged ZG-040/PR #211 and ZG-042/PR #210 found material gaps that were not exercised by their original acceptance fixtures. This is an evidence-state correction, not a planned-DAG change and not a reopening of the earlier broad corrective campaign.

### ZG-040 / #41

The merged scaffold remained useful, but dependency acceptance was revoked pending bounded corrections for:

- authentication of statistical outcomes/item identity against trusted ZG-015 evidence;
- duplicate/relabelled physical-item prevention in crossed inference;
- single-use amendment/deviation iterable safety;
- executable planned-observation, missing-data and stopping rules;
- method/estimand/endpoint/confirmatory compatibility;
- bounded randomisation/bootstrap memory/work execution.

At the rollback point, live state was `implementation=partial`, `evidence=partial`, `research=active`, `dependency_satisfied=false`; issue #41 was reopened. This paragraph is historical and is superseded for live status by the corrective-reacceptance section below and `programme/task_state.json`.

### ZG-042 / #43

The workload policy/benchmark/BATCH-lane work remained useful, but dependency acceptance was revoked pending bounded corrections for:

- immutable admission/execution input ownership;
- conservative accounting of real long-form object lifetimes and retained products;
- cancellation before large retained allocation;
- exact continuation only at boundaries whose in-progress state is serializable;
- unfinished-glide boundary rejection or a versioned continuation-state extension;
- full-rate evidence for the documented section plan.

At the rollback point, live state was `implementation=partial`, `evidence=partial`, `dependency_satisfied=false`; issue #43 was reopened. ZG-042 was subsequently reaccepted through PR #213 and issue #43 corrective evidence; `programme/task_state.json` is authoritative.

### Workflow consequence

A previously accepted/merged parent can be downgraded when later adversarial review reproduces a material failure. The original PR and green CI remain historical evidence; readiness is changed explicitly in `task_state.json`. Agents must re-read the live state before starting dependent work and before merge. Reacceptance requires adversarial regressions for the reproduced failures and a fresh final-head/reverse-dependency gate.

## Corrective reacceptance — ZG-040 / #41 — 2026-09-19

PR #214 implements the bounded repair path recorded above without changing the planned DAG, recovered source, rendered audio, ZG-015 blinding/provenance contract or artistic defaults. The corrected public ZG-040 surface adds content-addressed prospective evidence plans tied to exact trusted ZG-015 trial/result identities, physical-item identity enforcement, one-shot-safe amendment/deviation ownership, executable planned-cell missingness/stopping, method/estimand compatibility checks, and bounded batched paired resampling with progress/cancellation.

Adversarial regressions reproduce the original failures: decorative result-hash tampering, item relabelling, single-use audit iterators, 100-participant plans completed from eight observed participants, vanished missing cells, incompatible method/estimand declarations, the 1,792-pair randomisation allocation case, and unbounded counterbalance materialisation. Synthetic calibration remains explicitly non-participant evidence.

The reviewed state for the final PR head is `implementation=accepted`, `evidence=accepted`, `research=accepted`, `dependency_satisfied=true`, with no ZG-040 blocker and evidence references to PR #211, the rollback review, PR #214 and the #41 corrective-reacceptance record. This reacceptance is valid only when the exact final head passes the required ZG-040 Ubuntu/Windows, inherited ZG-015/QC, programme-state and reverse-dependency gates. Issue #41 is closed only after those exact-head gates pass and the merge is verified on `main`.

## Authority reconciliation update — 2026-09-20

This dated section records the post-corrective state consumed by the pre-ZG-043 authority-reconciliation campaign. It supersedes the original 2026-09-15 snapshot for **current navigation only**; the earlier sections remain preserved history. Live readiness is still `programme/task_state.json`.

### Machine authority repaired first

ZG-000 child issue #217 / PR #222 repaired the machine-readable state without changing any planned DAG edge, stable-ID mapping or `dependency_satisfied` boolean. The accepted live blocker/evidence model now separates semantic blocker identity from issue/PR/document navigation.

- **ZG-024** remains implementation/evidence partial, research-active and not dependency-satisfying. Correctives #134 / PR #187 (Candidate 2.0 provenance), #87 / PR #194 (transient-v4 eligibility) and #92 / PR #195 (staged deterministic research) are complete evidence, not live blockers. The parent #25 blocker is now the narrower research condition: reliable eligible-candidate availability plus held-out improvement on fresh structural/spectral and mixed-texture cases without holdout feedback or weakened safety gates. The accepted #92 result is mixed/no-go and promoted no production optimizer.
- **ZG-029** is accepted/dependency-satisfying under ownership policy `zaaggenz.layer-ownership/1.1.0`. Final corrective #202 / PR #209 distinguishes raw SYNTHLINE/exciter audition/null stems from the exact processed `source_bus`; the old 1.0 additive-pre-master wording is historical only.
- **ZG-045** remains not started/not dependency-satisfying, but completed canonical-environment prerequisite #103 / PR #199 and hardening #203 / PR #205 are no longer represented as a live task-local blocker. Outstanding readiness comes from the planned DAG.

### Late programme reacceptance/integration

- **ZG-042 / #43** was reaccepted through PR #213 after the PR #212 rollback. Current state is accepted/dependency-satisfying; the rollback remains historical evidence.
- **ZG-040 / #41** was reaccepted through PR #214 after the same rollback. Current state is implementation/evidence/research accepted and dependency-satisfying.
- **ZG-041 / #42** is integrated through PR #215. Compose remains the default ordinary workspace; `/research` is an explicit non-destructive hub over accepted Research surfaces and does not own a second Compose session.
- **ZG-043 / #44** is not itself implemented or dependency-satisfying, but all of its declared hard parents (ZG-009, ZG-011, ZG-027, ZG-029, ZG-030 and ZG-041) currently satisfy dependency evidence. This is prerequisite readiness, not a completion claim for ZG-043.

### Current ZG-024 read set

For new inverse-search work, read the accepted chain through Candidate 2.0 provenance, transient-v4, staged protocol v2, the mixed/no-go staged result and lineage reconciliation, then read the live `task_state.json` row and parent #25 latest blocker record. Handoffs 1/2 remain important history/substrate but are not the terminal current authority.

The repository must preserve the original rollback, failed/superseded research and pre-G0 records as history while preventing them from being mistaken for live instructions.