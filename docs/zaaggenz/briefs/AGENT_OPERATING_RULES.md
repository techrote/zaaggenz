# Agent operating rules and universal implementation prompt

These instructions accompany every issue and are part of its acceptance contract. Read the issue's named brief sections and the relevant source-register entries; the index is a navigation aid, not authority over those documents.

## Before coding

Resolve the repository/branch and confirm the issue's actual hard dependencies from `programme/tasks.json` / `programme/dependency_graph.json`, then consult `programme/task_state.json` for the current evidence/gate decision on those stable IDs. `programme/issue_map.json` maps stable IDs to deployed GitHub issue numbers; GitHub open/closed state is an informational mirror only and never establishes or revokes dependency satisfaction. A dependency counts only when `task_state.json` records its accepted evidence as dependency-satisfying, or an explicitly approved equivalent is recorded and the state file is updated through review. Check current code and tests; historical conversation file paths are discovery clues. Do not manufacture missing source from screenshots. If baseline is absent, stop implementation at ZG-001's documented blocked state.

When programme evidence changes, update the orthogonal state dimensions rather than overloading one status word: implementation, evidence, research, owner gate, blockers and `dependency_satisfied`. Add accepted evidence references where practical. Validate with `python tools/validate_programme_state.py --validate` and the programme-state tests. A GitHub close/reopen operation alone must never change dependency readiness.

Work in a dedicated branch/worktree named for the stable ID. Obtain the listed shared integration locks before editing the relevant shared file/contract. Disjoint module prototypes may run concurrently under frozen interfaces, but no agent owns another issue's central file implicitly. Use small commits; no forced updates, destructive branch resets or silent format migrations.

## Implement

Preserve legacy baseline outputs and UI access unless the issue explicitly specifies an opt-in alternative. Implement the minimum complete vertical slice, not a superficial placeholder or a new disconnected demo. Every parameter needs units, bounds, defaults, serialisation and bypass semantics. Changes to audio order, phase, state, latency, headroom or normalisation must be visible in the recipe and release notes.

Keep compose mode usable without scientific prerequisites. Expensive work runs through bounded async jobs; previews and cancellation remain responsive. Do not add mandatory ML/GPU/cloud dependencies or silently upload source audio. Respect seed and channel policies; support empty/silent/short/invalid input and cancellation without corrupting session state.

Use existing tested modules through an adapter before adopting new libraries. Record licences and citations; prefer author implementations when compatible, but never assume availability or an acceptable licence from a citation alone. Cache expensive shared features by content and method hash; never reuse analysis after its input or method has changed.

## Post-merge review and evidence revocation

A merged PR or previously green final-head CI is **not irrevocable dependency evidence**. If later adversarial review reproduces a material contract, provenance, numerical-bound, concurrency or research-integrity failure in an accepted task:

1. preserve the original merged PR/completion record as historical evidence;
2. reopen the parent issue (or create a tightly scoped successor only when lineage genuinely belongs elsewhere);
3. immediately update `programme/task_state.json` so implementation/evidence/research/blocker fields describe the new reality and set `dependency_satisfied: false` when downstream reliance is unsafe;
4. update task-specific contracts/docs and this programme workflow as needed before starting newly unblocked downstream work;
5. add the reproduction as an adversarial regression and require the repaired final head to re-pass direct and reverse-dependency gates;
6. reclose/reaccept only after the stronger acceptance claim is executable, not merely documented.

Do not erase useful prior evidence merely because a narrower guarantee failed. Conversely, do not leave a task dependency-satisfying just because most of its implementation remains useful. Readiness is an explicit evidence decision.

When consuming a recently accepted parent, inspect `task_state.json` immediately before coding and again before merge. If a parent has been downgraded or reopened for a material corrective, stop work that depends on the disputed guarantee rather than relying on an earlier green run.

## Verify and report

Run the recovered baseline tests and the issue-specific fixtures. Add positive, identity, adversarial and boundary cases. Include actual commands, environment, result hashes and known limitations in the PR. Numerical metrics do not certify a musical improvement: provide reproducible level-matched audition recipes where sound changes. Owner approval is required before replacing a default sound.

For experiments, freeze design and stimuli before looking at confirmatory outcomes. Never erase null data or silently redefine an endpoint. No claims of dopamine/adrenaline measurement, universal pleasure or authentic cultural reproduction without appropriate evidence.

Update the issue's evidence links, new contract/ADR versions and any revised dependency. Update `programme/task_state.json` when accepted evidence, research state, an owner gate or a true readiness blocker changes. Do not mark downstream tasks ready just because an upstream issue was closed as abandoned. Hand back one clear completion record or one precise blocker; avoid large speculative parallel rewrites.

## Definition of done

An implementation issue closes only when its concrete deliverables are integrated, tests and relevant listening evidence are attached, documentation/contracts are updated, and no listed guardrail is broken. A research issue closes when its preregistered evidence product and honest conclusion are complete, including a null or inconclusive result. A documentation-only plan is not feature completion.
